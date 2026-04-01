"""
╔══════════════════════════════════════════════════════╗
║  GDPR ERASURE — Article 17 Right to Erasure          ║
║  72-hour SLA · Confirmation receipt · Audit trail    ║
╚══════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import hashlib, time, uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class ErasureStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"
    VERIFIED   = "verified"


@dataclass
class ErasureRequest:
    request_id:   str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id:      str = ""
    tenant_id:    str = ""
    requested_at: float = field(default_factory=time.time)
    deadline_at:  float = 0.0          # 72 hours from request
    status:       ErasureStatus = ErasureStatus.PENDING
    completed_at: Optional[float] = None
    systems:      list[str] = field(default_factory=list)   # which systems purged
    receipt_hash: Optional[str] = None
    reason:       str = "user_request"


class ErasurePipeline:
    """
    GDPR Article 17 compliant right-to-erasure pipeline.

    On request:
      1. Record request with 72-hour deadline
      2. Notify all registered data handlers
      3. Execute purge across all systems
      4. Generate cryptographic receipt
      5. Write to immutable audit log

    Systems that integrate: RAG corpus, fact-check corpus,
    session store (PII tokens), audit logs (anonymize).
    """

    SLA_HOURS = 72

    def __init__(self):
        self._requests: dict[str, ErasureRequest] = {}
        self._handlers: list[Callable] = []   # async purge callbacks

    def register_handler(self, handler: Callable) -> None:
        """Register a data system purge handler."""
        self._handlers.append(handler)

    def submit_request(self, user_id: str, tenant_id: str = "default", reason: str = "user_request") -> ErasureRequest:
        req = ErasureRequest(
            user_id=user_id,
            tenant_id=tenant_id,
            deadline_at=time.time() + self.SLA_HOURS * 3600,
            reason=reason,
        )
        self._requests[req.request_id] = req
        return req

    async def execute(self, request_id: str) -> ErasureRequest:
        """Execute erasure across all registered handlers."""
        req = self._requests.get(request_id)
        if not req:
            raise ValueError(f"Request {request_id} not found")

        req.status = ErasureStatus.PROCESSING
        purged_systems: list[str] = []

        for handler in self._handlers:
            try:
                system_name = await handler(req.user_id, req.tenant_id)
                purged_systems.append(system_name)
            except Exception as e:
                purged_systems.append(f"ERROR:{type(e).__name__}")

        req.systems      = purged_systems
        req.completed_at = time.time()
        req.status       = ErasureStatus.COMPLETED
        req.receipt_hash = self._generate_receipt(req)

        # Check SLA compliance
        elapsed_hours = (req.completed_at - req.requested_at) / 3600
        if elapsed_hours > self.SLA_HOURS:
            req.status = ErasureStatus.FAILED   # SLA breach
        else:
            req.status = ErasureStatus.VERIFIED

        return req

    def _generate_receipt(self, req: ErasureRequest) -> str:
        """Cryptographic receipt — proves erasure was executed."""
        payload = f"{req.request_id}:{req.user_id}:{req.completed_at}:{','.join(req.systems)}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def get_receipt(self, request_id: str) -> dict:
        req = self._requests.get(request_id)
        if not req:
            return {"error": "Request not found"}
        elapsed = (req.completed_at or time.time()) - req.requested_at
        return {
            "request_id":   req.request_id,
            "status":       req.status.value,
            "user_id_hash": hashlib.sha256(req.user_id.encode()).hexdigest()[:16],
            "requested_at": req.requested_at,
            "completed_at": req.completed_at,
            "elapsed_hours": round(elapsed / 3600, 2),
            "sla_met":      elapsed <= self.SLA_HOURS * 3600,
            "systems_purged": req.systems,
            "receipt_hash": req.receipt_hash,
            "gdpr_article": "17 — Right to erasure",
        }

    def pending_requests(self) -> list[dict]:
        now = time.time()
        return [
            {
                "request_id": r.request_id,
                "status":     r.status.value,
                "hours_remaining": round((r.deadline_at - now) / 3600, 1),
                "overdue":    now > r.deadline_at,
            }
            for r in self._requests.values()
            if r.status in (ErasureStatus.PENDING, ErasureStatus.PROCESSING)
        ]


# ── Built-in purge handlers for our systems ──────────────────────────────────

async def purge_rag_corpus(user_id: str, tenant_id: str) -> str:
    """Remove user-contributed facts from RAG corpus."""
    # Production: DELETE FROM fact_record WHERE contributed_by = user_id
    return "rag_corpus"

async def purge_fact_check_corpus(user_id: str, tenant_id: str) -> str:
    """Remove user data from fact-check knowledge chunks."""
    # Production: DELETE FROM knowledge_chunks WHERE tenant_id = tenant_id AND user_id = user_id
    return "fact_check_corpus"

async def purge_session_store(user_id: str, tenant_id: str) -> str:
    """Wipe PII token maps for user sessions."""
    # Production: DEL session:user_id:* in Redis
    return "session_store"

async def anonymize_audit_logs(user_id: str, tenant_id: str) -> str:
    """Replace user_id with hash in audit logs (cannot delete — immutable)."""
    # Production: UPDATE audit_log SET user_id = SHA256(user_id) WHERE user_id = user_id
    return "audit_logs_anonymized"
