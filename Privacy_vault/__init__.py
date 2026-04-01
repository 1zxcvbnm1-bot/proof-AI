"""
╔══════════════════════════════════════════════════════════════════════╗
║  PRIVACY VAULT — Unified Orchestrator                               ║
║  Connects PII scrubber · Encryption · RBAC · GDPR erasure          ║
║  Every request from any system passes through here                  ║
╚══════════════════════════════════════════════════════════════════════╝

Usage:
    vault = PrivacyVault()

    # Wrap a RAG or fact-check request
    ctx = vault.access.create_default_user("user-123")
    result = vault.process_inbound("Tell me about OpenAI", ctx.session_id, ctx.user_id)
    # → result.scrubbed_text is safe to send to LLM/RAG/fact-check

    # Restore PII in outbound response
    clean_output = vault.process_outbound(llm_response, ctx.session_id)
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Optional

from pii_scrubber  import PIIScrubber, ScrubResult
from vault         import EncryptionVault, EncryptedPayload
from access_control import AccessController, UserContext, Role, DataRegion, ConsentStatus, AccessDecision
from erasure       import ErasurePipeline, purge_rag_corpus, purge_fact_check_corpus, purge_session_store, anonymize_audit_logs


@dataclass
class VaultResult:
    """Result of passing a request through the privacy vault."""
    allowed:        bool
    scrubbed_text:  str           # safe to send to LLM
    original_text:  str           # never logged
    pii_detected:   bool
    pii_count:      int
    session_id:     str
    user_id:        str
    access_decision: Optional[AccessDecision] = None
    encrypted_log:  Optional[str] = None    # encrypted audit entry
    latency_ms:     float = 0.0

    def deny_reason(self) -> str:
        if self.access_decision and not self.access_decision.allowed:
            return self.access_decision.reason
        return ""


class PrivacyVault:
    """
    The single privacy entry point for the entire agent accelerator.

    ALL requests — RAG queries, fact-check inputs, corpus ingestion —
    must pass through process_inbound() before reaching any engine.
    ALL responses must pass through process_outbound() before reaching the user.

    Integrations:
        RAGEngine           → vault.wrap_rag_engine(engine)
        FactCheckPipeline   → vault.wrap_fact_pipeline(pipeline)
        Gateway             → vault is injected into gateway middleware
    """

    def __init__(self, master_secret: Optional[str] = None):
        self.scrubber  = PIIScrubber()
        self.encryptor = EncryptionVault(master_secret)
        self.access    = AccessController()
        self.erasure   = ErasurePipeline()

        # Register erasure handlers for all systems
        self.erasure.register_handler(purge_rag_corpus)
        self.erasure.register_handler(purge_fact_check_corpus)
        self.erasure.register_handler(purge_session_store)
        self.erasure.register_handler(anonymize_audit_logs)

        # Create a default system user for internal calls
        self.access.create_default_user("system", Role.SYSTEM)

    def process_inbound(
        self,
        text:       str,
        session_id: str,
        user_id:    str = "default",
        action:     str = "query",
        tenant_id:  str = "default",
    ) -> VaultResult:
        """
        Gate every inbound request through privacy vault.
        1. Access control check
        2. PII scrubbing
        3. Encrypt audit entry
        Returns VaultResult — use .scrubbed_text for downstream engines.
        """
        t_start = time.time()

        # Step 1: Access control
        decision = self.access.check_access(user_id, action)
        if not decision.allowed:
            return VaultResult(
                allowed=False,
                scrubbed_text="",
                original_text=text,
                pii_detected=False,
                pii_count=0,
                session_id=session_id,
                user_id=user_id,
                access_decision=decision,
                latency_ms=(time.time() - t_start) * 1000,
            )

        # Step 2: PII scrubbing
        scrub_result = self.scrubber.scrub(text, session_id)

        # Step 3: Encrypt audit entry (no raw PII stored anywhere)
        audit_data = {
            "session_id":    session_id,
            "user_id_hash":  self._hash(user_id),
            "action":        action,
            "pii_detected":  scrub_result.pii_detected,
            "entity_counts": self.scrubber.audit_summary(scrub_result)["entity_counts"],
            "timestamp":     time.time(),
        }
        encrypted_log = self.encryptor.encrypt_dict(audit_data, tenant_id)

        return VaultResult(
            allowed=True,
            scrubbed_text=scrub_result.scrubbed_text,
            original_text=text,
            pii_detected=scrub_result.pii_detected,
            pii_count=len(scrub_result.matches),
            session_id=session_id,
            user_id=user_id,
            access_decision=decision,
            encrypted_log=encrypted_log,
            latency_ms=(time.time() - t_start) * 1000,
        )

    def process_outbound(self, text: str, session_id: str) -> str:
        """
        Restore PII tokens in outbound response.
        Only happens in the user's local session — token map never sent externally.
        """
        return self.scrubber.restore(text, session_id)

    async def request_erasure(self, user_id: str, tenant_id: str = "default") -> dict:
        """Submit and execute a GDPR Article 17 erasure request."""
        req = self.erasure.submit_request(user_id, tenant_id)
        completed = await self.erasure.execute(req.request_id)
        # Clear session store immediately
        self.scrubber.clear_session(user_id)
        return self.erasure.get_receipt(req.request_id)

    def register_user(
        self,
        user_id:   str,
        role:      Role = Role.API_USER,
        region:    DataRegion = DataRegion.ANY,
        consent:   ConsentStatus = ConsentStatus.EXPLICIT,
        tenant_id: str = "default",
    ) -> UserContext:
        from access_control import UserContext
        ctx = UserContext(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            region=region,
            consent=consent,
        )
        self.access.register_user(ctx)
        return ctx

    def vault_status(self) -> dict:
        return {
            "pii_scrubber":   "active",
            "encryption":     self.encryptor.key_status("default"),
            "access_control": {"users_registered": len(self.access._users)},
            "erasure":        {"pending": len(self.erasure.pending_requests())},
        }

    def _hash(self, value: str) -> str:
        import hashlib
        return hashlib.sha256(value.encode()).hexdigest()[:16]


# ── Vault-aware wrappers for RAG and fact-check engines ───────────────────────

class VaultAwareRAGEngine:
    """
    Wraps RAGEngine with privacy vault middleware.
    Every query is scrubbed inbound and PII-restored outbound.
    """

    def __init__(self, rag_engine, vault: PrivacyVault):
        self._rag   = rag_engine
        self._vault = vault

    async def query(self, text: str, session_id: str, user_id: str = "default"):
        result = self._vault.process_inbound(text, session_id, user_id, action="query")
        if not result.allowed:
            raise PermissionError(f"Access denied: {result.deny_reason()}")

        # Use scrubbed text for RAG
        async for token in self._rag.query(result.scrubbed_text, session_id):
            if token.text:
                token.text = self._vault.process_outbound(token.text, session_id)
            yield token


class VaultAwareFactPipeline:
    """
    Wraps FactCheckPipeline with privacy vault middleware.
    """

    def __init__(self, pipeline, vault: PrivacyVault):
        self._pipeline = pipeline
        self._vault    = vault

    async def check(self, text: str, session_id: str, user_id: str = "default"):
        result = self._vault.process_inbound(text, session_id, user_id, action="query")
        if not result.allowed:
            raise PermissionError(f"Access denied: {result.deny_reason()}")
        return await self._pipeline.check(result.scrubbed_text, session_id)

    async def check_stream(self, text: str, session_id: str, user_id: str = "default"):
        result = self._vault.process_inbound(text, session_id, user_id, action="query")
        if not result.allowed:
            raise PermissionError(f"Access denied: {result.deny_reason()}")
        async for event in self._pipeline.check_stream(result.scrubbed_text, session_id):
            yield event


__all__ = [
    "PrivacyVault",
    "VaultAwareRAGEngine",
    "VaultAwareFactPipeline",
    "PIIScrubber",
    "EncryptionVault",
    "AccessController",
    "ErasurePipeline",
    "Role",
    "DataRegion",
    "ConsentStatus",
    "VaultResult",
]
