"""
╔══════════════════════════════════════════════════════════════════════════╗
║  UNIFIED GATEWAY — Single entry point for the agent accelerator        ║
║  Privacy Vault → RAG Engine → Fact-Check Pipeline                      ║
║  Port 8080 · All systems wired and connected                            ║
╚══════════════════════════════════════════════════════════════════════════╝

Every request:
  1. Authenticated + access-checked by PrivacyVault
  2. PII scrubbed before any engine sees the text
  3. Routed to RAG engine (retrieval + generation)
  4. Fact-check pipeline verifies the generated response
  5. PII restored in outbound response
  6. Audit log written (encrypted, zero PII)
  7. Clean verified response returned to user
"""

from __future__ import annotations

import asyncio, json, os, sys, time, uuid
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── Add parent dirs to path ───────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)   # makes Privacy_vault importable as a package
sys.path.insert(0, _HERE)   # allows sibling imports inside Privacy_vault
sys.path.insert(0, os.path.join(_ROOT, "Rag_engine", "core"))
sys.path.insert(0, os.path.join(_ROOT, "Fact_checker"))

# ── Import privacy vault ──────────────────────────────────────────────────────
from Privacy_vault import (
    PrivacyVault, VaultAwareRAGEngine, VaultAwareFactPipeline,
    Role, DataRegion, ConsentStatus,
)

# ── Import engines (graceful fallback if not found) ───────────────────────────
try:
    from engine import RAGEngine, FactRecord
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    print("[Gateway] RAGEngine not found — RAG routes will return 503")

try:
    from fact_checker import FactCheckPipeline, KnowledgeChunk
    FACT_AVAILABLE = True
except ImportError:
    FACT_AVAILABLE = False
    print("[Gateway] FactCheckPipeline not found — fact-check routes will return 503")


# ════════════════════════════════════════════════════════════════════════════
# APP SETUP
# ════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Agent Accelerator — Unified Gateway",
    description="Privacy Vault + RAG Engine + Fact-Check Pipeline — fully connected",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.environ.get("GROQ_API_KEY", "")


# ════════════════════════════════════════════════════════════════════════════
# SYSTEM INITIALIZATION
# ════════════════════════════════════════════════════════════════════════════

# 1. Privacy Vault (always present — everything goes through this)
vault = PrivacyVault(master_secret=os.environ.get("VAULT_MASTER_SECRET"))

# 2. Register default users
vault.register_user("default",   role=Role.API_USER,  consent=ConsentStatus.EXPLICIT)
vault.register_user("admin",     role=Role.ADMIN,      consent=ConsentStatus.EXPLICIT)
vault.register_user("analyst",   role=Role.ANALYST,    consent=ConsentStatus.EXPLICIT)

# 3. RAG Engine (vault-wrapped)
rag_engine = None
vault_rag  = None
if RAG_AVAILABLE and API_KEY:
    rag_engine = RAGEngine(api_key=API_KEY)
    vault_rag  = VaultAwareRAGEngine(rag_engine, vault)
    print("[Gateway] RAGEngine initialised")

# 4. Fact-Check Pipeline (vault-wrapped)
fact_pipeline = None
vault_fact    = None
if FACT_AVAILABLE and API_KEY:
    fact_pipeline = FactCheckPipeline(api_key=API_KEY)
    vault_fact    = VaultAwareFactPipeline(fact_pipeline, vault)
    print("[Gateway] FactCheckPipeline initialised")

# 5. Seed demo corpus
DEMO_CORPUS_FACTS = [
    {"fact_id": "F001", "claim_text": "OpenAI was founded in December 2015.",
     "source_urls": ["https://en.wikipedia.org/wiki/OpenAI"],
     "source_type": "wikipedia", "authority_tier": 4, "trust_score": 0.88,
     "last_verified_at": time.time() - 86400},
    {"fact_id": "F002", "claim_text": "Anthropic was founded in 2021 by former OpenAI researchers.",
     "source_urls": ["https://en.wikipedia.org/wiki/Anthropic"],
     "source_type": "wikipedia", "authority_tier": 4, "trust_score": 0.92,
     "last_verified_at": time.time() - 86400},
    {"fact_id": "F003", "claim_text": "GDPR Article 17 grants the right to erasure of personal data.",
     "source_urls": ["https://gdpr-info.eu/art-17-gdpr/"],
     "source_type": "gov_site", "authority_tier": 1, "trust_score": 0.99,
     "last_verified_at": time.time() - 86400 * 7},
    {"fact_id": "F004", "claim_text": "RAG combines retrieval with generation to ground LLM outputs.",
     "source_urls": ["https://arxiv.org/abs/2005.11401"],
     "source_type": "academic", "authority_tier": 2, "trust_score": 0.97,
     "last_verified_at": time.time() - 86400 * 14},
]

if rag_engine:
    facts = [FactRecord(**f) for f in DEMO_CORPUS_FACTS]
    rag_engine.load_corpus(facts)
    print(f"[Gateway] RAG corpus loaded: {len(facts)} facts")

if fact_pipeline:
    chunks = [KnowledgeChunk(
        chunk_id=f["fact_id"],
        text=f["claim_text"],
        source_url=f["source_urls"][0],
        source_domain=f["source_urls"][0].split("/")[2],
        authority_tier=f["authority_tier"],
        trust_score=f["trust_score"],
    ) for f in DEMO_CORPUS_FACTS]
    fact_pipeline.load_corpus(chunks)
    print(f"[Gateway] Fact-check corpus loaded: {len(chunks)} chunks")


# ════════════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ════════════════════════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    query:      str
    user_id:    str = "default"
    session_id: Optional[str] = None
    verify:     bool = True     # run fact-check on RAG output?
    mode:       str = "full"    # full | rag_only | factcheck_only

class FactCheckRequest(BaseModel):
    text:       str
    user_id:    str = "default"
    session_id: Optional[str] = None

class ErasureRequest(BaseModel):
    user_id:   str
    tenant_id: str = "default"

class RegisterUserRequest(BaseModel):
    user_id:   str
    role:      str = "api_user"
    region:    str = "any"
    tenant_id: str = "default"


# ════════════════════════════════════════════════════════════════════════════
# STREAMING HELPERS
# ════════════════════════════════════════════════════════════════════════════

async def full_pipeline_stream(
    query: str, session_id: str, user_id: str
) -> AsyncIterator[str]:
    """
    Full pipeline: Privacy Vault → RAG Engine → Fact-Check → Stream.
    Emits SSE events with vault, rag, and factcheck stages.
    """
    generated_text = ""

    # Stage 1: Vault inbound
    vault_result = vault.process_inbound(query, session_id, user_id)
    if not vault_result.allowed:
        yield f"data: {json.dumps({'stage': 'vault', 'error': vault_result.deny_reason(), 'is_final': True})}\n\n"
        return

    yield f"data: {json.dumps({'stage': 'vault', 'pii_detected': vault_result.pii_detected, 'pii_count': vault_result.pii_count})}\n\n"

    # Stage 2: RAG streaming
    if vault_rag:
        yield f"data: {json.dumps({'stage': 'rag_start'})}\n\n"
        try:
            async for token in vault_rag.query(vault_result.scrubbed_text, session_id, user_id):
                if not token.is_final:
                    generated_text += token.text
                    # Restore PII in outbound token
                    restored = vault.process_outbound(token.text, session_id)
                    event = {
                        "stage":      "rag_token",
                        "text":       restored,
                        "claim_id":   token.claim_id,
                        "confidence": token.confidence,
                        "status":     token.status.value if token.status else None,
                    }
                    yield f"data: {json.dumps(event)}\n\n"
        except PermissionError as e:
            yield f"data: {json.dumps({'stage': 'rag_error', 'error': str(e)})}\n\n"
    else:
        yield f"data: {json.dumps({'stage': 'rag_unavailable', 'message': 'RAG engine not loaded'})}\n\n"
        generated_text = vault_result.scrubbed_text

    yield f"data: {json.dumps({'stage': 'rag_complete', 'response_length': len(generated_text)})}\n\n"

    # Stage 3: Fact-check the generated text
    if vault_fact and generated_text:
        yield f"data: {json.dumps({'stage': 'factcheck_start'})}\n\n"
        try:
            async for event in vault_fact.check_stream(generated_text, session_id, user_id):
                if event.event_type == "verdict":
                    yield f"data: {json.dumps({'stage': 'factcheck_verdict', **event.data})}\n\n"
                elif event.is_final:
                    yield f"data: {json.dumps({'stage': 'factcheck_complete', **event.data})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'stage': 'factcheck_error', 'error': str(e)})}\n\n"

    # Final event
    yield f"data: {json.dumps({'stage': 'complete', 'is_final': True, 'session_id': session_id})}\n\n"


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

@app.post("/query/stream")
async def query_stream(req: QueryRequest):
    """
    Full pipeline streaming endpoint.
    Privacy Vault → RAG Engine → Fact-Check → SSE stream.

    SSE stages:
      vault         → PII detection result
      rag_start     → RAG retrieval begins
      rag_token     → streamed text token with confidence
      rag_complete  → RAG done
      factcheck_verdict → per-claim verdict as it arrives
      factcheck_complete → aggregate stats
      complete      → pipeline finished
    """
    if not req.query.strip():
        raise HTTPException(400, "Query cannot be empty")
    sid = req.session_id or str(uuid.uuid4())
    return StreamingResponse(
        full_pipeline_stream(req.query, sid, req.user_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/query")
async def query_sync(req: QueryRequest):
    """Synchronous full-pipeline query. Collects entire stream."""
    if not req.query.strip():
        raise HTTPException(400, "Query cannot be empty")
    sid = req.session_id or str(uuid.uuid4())

    stages, rag_text, verdicts = [], "", []
    async for line in full_pipeline_stream(req.query, sid, req.user_id):
        if line.startswith("data: "):
            event = json.loads(line[6:])
            stage = event.get("stage", "")
            if stage == "rag_token":
                rag_text += event.get("text", "")
            elif stage == "factcheck_verdict":
                verdicts.append(event)
            stages.append(stage)

    return {
        "query":    req.query,
        "response": rag_text,
        "verdicts": verdicts,
        "stages":   stages,
        "session_id": sid,
    }


@app.post("/factcheck/stream")
async def factcheck_stream(req: FactCheckRequest):
    """Standalone fact-check (vault + fact-check, no RAG)."""
    if not vault_fact:
        raise HTTPException(503, "Fact-check pipeline not available")
    sid = req.session_id or str(uuid.uuid4())

    async def _gen():
        vault_result = vault.process_inbound(req.text, sid, req.user_id)
        if not vault_result.allowed:
            yield f"data: {json.dumps({'error': vault_result.deny_reason(), 'is_final': True})}\n\n"
            return
        async for event in vault_fact.check_stream(vault_result.scrubbed_text, sid, req.user_id):
            yield f"data: {json.dumps({'event_type': event.event_type, 'claim_id': event.claim_id, 'data': event.data, 'is_final': event.is_final})}\n\n"
            if event.is_final:
                break

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.post("/users/register")
async def register_user(req: RegisterUserRequest):
    """Register a user with role and consent settings."""
    role_map   = {r.value: r for r in Role}
    region_map = {r.value: r for r in DataRegion}
    role   = role_map.get(req.role, Role.API_USER)
    region = region_map.get(req.region, DataRegion.ANY)
    ctx = vault.register_user(req.user_id, role=role, region=region, tenant_id=req.tenant_id)
    return {"registered": True, "user_id": ctx.user_id, "role": ctx.role.value}


@app.post("/privacy/erasure")
async def request_erasure(req: ErasureRequest):
    """Submit GDPR Article 17 erasure request. Returns receipt."""
    receipt = await vault.request_erasure(req.user_id, req.tenant_id)
    return receipt


@app.get("/privacy/status")
async def privacy_status():
    return vault.vault_status()


@app.get("/privacy/audit")
async def privacy_audit():
    return {"decisions": vault.access.audit_tail(20)}


@app.get("/stats")
async def stats():
    result = {"privacy_vault": vault.vault_status()}
    if rag_engine:
        result["rag_engine"] = rag_engine.stats()
    if fact_pipeline:
        result["fact_pipeline"] = fact_pipeline.stats()
    return result


@app.get("/health")
async def health():
    return {
        "status":           "ok",
        "privacy_vault":    True,
        "rag_engine":       rag_engine is not None,
        "fact_pipeline":    fact_pipeline is not None,
        "all_connected":    all([vault is not None, rag_engine is not None, fact_pipeline is not None]),
    }
