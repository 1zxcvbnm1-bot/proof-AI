"""
FULL SYSTEM DEMO — Privacy Vault + RAG Engine + Fact-Check Pipeline
All connected and running together.

Run: python full_system_demo.py
"""

import asyncio, os, sys, time

# Insert the project root (parent of Privacy_vault) so Privacy_vault is importable as a package
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)  # allow sibling-module imports within Privacy_vault

from Privacy_vault import (
    PrivacyVault, Role, DataRegion, ConsentStatus,
    VaultAwareRAGEngine, VaultAwareFactPipeline,
)

try:
    sys.path.insert(0, os.path.join(_ROOT, "Rag_engine", "core"))
    from engine import RAGEngine, FactRecord
    RAG_OK = True
except ImportError:
    RAG_OK = False

try:
    sys.path.insert(0, os.path.join(_ROOT, "Fact_checker"))
    from fact_checker import FactCheckPipeline, KnowledgeChunk
    FACT_OK = True
except ImportError:
    FACT_OK = False

from dotenv import load_dotenv
load_dotenv()

API_KEY = os.environ.get("GROQ_API_KEY", "gsk_P1ac3h0ld3rGr0qK3yT0B3R3plac3dByR3alOn3")


async def main():
    print("\n" + "═"*65)
    print("  AGENT ACCELERATOR — FULL SYSTEM DEMO")
    print("  Privacy Vault + RAG Engine + Fact-Check Pipeline")
    print("═"*65)

    # ── 1. Initialize Privacy Vault ──────────────────────────────────────
    print("\n[1/5] Initialising Privacy Vault...")
    vault = PrivacyVault()
    alice = vault.register_user("alice", role=Role.ANALYST, region=DataRegion.IN)
    print(f"  ✅ Vault ready. Registered user: alice ({alice.role.value})")

    # ── 2. PII scrubbing test ────────────────────────────────────────────
    print("\n[2/5] PII scrubbing test...")
    raw_query = "My email is alice@example.com and my SSN is 123-45-6789. What is GDPR?"
    result = vault.process_inbound(raw_query, "session-001", "alice")
    print(f"  Original : {raw_query}")
    print(f"  Scrubbed : {result.scrubbed_text}")
    print(f"  PII found: {result.pii_count} entities — {[m.entity_type for m in vault.scrubber.scrub(raw_query, 'test').matches]}")
    restored = vault.process_outbound(result.scrubbed_text, "session-001")
    print(f"  Restored : {restored}")

    # ── 3. Access control test ───────────────────────────────────────────
    print("\n[3/5] Access control test...")
    allowed  = vault.access.check_access("alice", "query")
    denied   = vault.access.check_access("alice", "key_rotate")   # analyst can't rotate keys
    print(f"  alice → query:      {'✅ ALLOWED' if allowed.allowed else '🚫 DENIED'}")
    print(f"  alice → key_rotate: {'✅ ALLOWED' if denied.allowed else '🚫 DENIED — ' + denied.reason}")

    # ── 4. GDPR erasure test ─────────────────────────────────────────────
    print("\n[4/5] GDPR Article 17 erasure test...")
    receipt = await vault.request_erasure("alice", "default")
    print(f"  Request ID : {receipt['request_id'][:16]}...")
    print(f"  Status     : {receipt['status']}")
    print(f"  SLA met    : {receipt['sla_met']} ({receipt['elapsed_hours']}h elapsed)")
    print(f"  Systems purged: {receipt['systems_purged']}")
    print(f"  Receipt hash : {receipt['receipt_hash'][:20]}...")

    # ── 5. Full pipeline with RAG + Fact-check ──────────────────────────
    print("\n[5/5] Full pipeline test...")

    if not API_KEY:
        print("  ⚠️  GROQ_API_KEY not set — skipping live engine test")
        print("  Set it with: $env:GROQ_API_KEY = 'gsk_...'")
    elif not RAG_OK or not FACT_OK:
        print("  ⚠️  engine.py or fact_checker.py not found in path")
        print("  Ensure Rag_engine/core/engine.py and Fact_checker/fact_checker.py exist")
    else:
        # Re-register alice (was erased above — demo re-register)
        alice = vault.register_user("alice", role=Role.ANALYST, region=DataRegion.IN)

        # Init engines
        rag = RAGEngine(api_key=API_KEY)
        rag.load_corpus([
            FactRecord(
                fact_id="F001",
                claim_text="Anthropic was founded in 2021 by Dario Amodei and Daniela Amodei.",
                source_urls=["https://en.wikipedia.org/wiki/Anthropic"],
                source_type="wikipedia", authority_tier=4,
                trust_score=0.92, last_verified_at=time.time() - 86400
            ),
            FactRecord(
                fact_id="F002",
                claim_text="GDPR Article 17 gives individuals the right to erasure of personal data.",
                source_urls=["https://gdpr-info.eu/art-17-gdpr/"],
                source_type="gov_site", authority_tier=1,
                trust_score=0.99, last_verified_at=time.time() - 86400 * 7
            ),
        ])

        pipeline = FactCheckPipeline(api_key=API_KEY)
        pipeline.load_corpus([
            KnowledgeChunk("KC001", "Anthropic was founded in 2021 by Dario Amodei.",
                "https://en.wikipedia.org/wiki/Anthropic", "wikipedia.org", 4, 0.92),
            KnowledgeChunk("KC002", "GDPR Article 17 grants the right to erasure.",
                "https://gdpr-info.eu/art-17-gdpr/", "gdpr-info.eu", 1, 0.99),
        ])

        # Vault-wrap both engines
        vault_rag  = VaultAwareRAGEngine(rag, vault)
        vault_fact = VaultAwareFactPipeline(pipeline, vault)

        # Test query with PII embedded
        test_query = "Who founded Anthropic? My email is test@example.com"
        print(f"\n  Query: {test_query}")
        print("  Pipeline: Vault → RAG → Fact-Check\n")

        # Step A: Vault scrubs inbound
        vault_in = vault.process_inbound(test_query, "session-002", "alice")
        print(f"  Vault scrubbed: {vault_in.scrubbed_text}")
        print(f"  PII removed: {vault_in.pii_count} entities\n")

        # Step B: RAG streaming
        print("  RAG response (streaming):")
        rag_text = ""
        async for token in vault_rag.query(vault_in.scrubbed_text, "session-002", "alice"):
            if not token.is_final and token.text:
                rag_text += token.text
                print(token.text, end="", flush=True)
        print(f"\n\n  RAG response length: {len(rag_text)} chars")

        # Step C: Fact-check the RAG output
        if rag_text:
            print("\n  Fact-check verdict:")
            fact_result = await vault_fact.check(rag_text, "session-002", "alice")
            icons = {"VERIFIED": "✅", "UNCERTAIN": "⚠️", "BLOCKED": "🚫", "CONFLICT": "⚡"}
            for v in fact_result.verdicts:
                icon = icons.get(v.verdict.value, "?")
                print(f"  {icon} {v.verdict.value:<10} | conf: {v.confidence:.2f} | {v.claim.text[:60]}")
            print(f"\n  Overall score: {fact_result.overall_score:.2f} | Hallucination rate: {fact_result.halluc_rate:.1%}")

    # ── Final vault status ───────────────────────────────────────────────
    print("\n" + "─"*65)
    print("  VAULT STATUS")
    status = vault.vault_status()
    print(f"  PII scrubber     : {status['pii_scrubber']}")
    print(f"  Encryption       : {status['encryption']['algorithm']} | key: {status['encryption']['active_key_id']}")
    print(f"  Users registered : {status['access_control']['users_registered']}")
    print(f"  Pending erasures : {status['erasure']['pending']}")
    print("\n" + "═"*65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
