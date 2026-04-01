"""
╔══════════════════════════════════════════════════════════════════════════╗
║  PHASE 3 PRODUCTION SERVER                                              ║
║  Agent Loop + API v1 + Privacy Vault + RAG + Fact-Check                ║
║  Single uvicorn entry point: uvicorn server:app --port 8080             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import os
import sys
import time

# ── Path setup ────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "core"))
sys.path.insert(0, os.path.join(BASE, "api", "v1"))
sys.path.insert(0, os.path.join(BASE, "..", "privacy_vault", "privacy"))
sys.path.insert(0, os.path.join(BASE, "..", "Rag_engine", "core"))
sys.path.insert(0, os.path.join(BASE, "..", "Fact_checker"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Import Phase 3 components ─────────────────────────────────────────────
from agent_loop import AgentLoop
import router as v1_router

# ── Import Phase 2 components ─────────────────────────────────────────────
try:
    from privacy import PrivacyVault, Role, ConsentStatus
    VAULT_OK = True
except ImportError:
    VAULT_OK = False
    print("[Server] Privacy vault not found — running without vault")

try:
    from engine import RAGEngine, FactRecord
    RAG_OK = True
except ImportError:
    RAG_OK = False
    print("[Server] RAG engine not found — agent will use fact-check only")

try:
    from fact_checker import FactCheckPipeline, KnowledgeChunk
    FACT_OK = True
except ImportError:
    FACT_OK = False
    print("[Server] Fact-check pipeline not found")

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ════════════════════════════════════════════════════════════════════════════
# APPLICATION
# ════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Agent Accelerator — Phase 3",
    description="Anti-hallucination verified-fact agent with real-time SSE streaming",
    version="3.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Include versioned router ──────────────────────────────────────────────
app.include_router(v1_router.app.routes[0].__class__.__mro__[0] if False else v1_router.app.router)

# ════════════════════════════════════════════════════════════════════════════
# STARTUP
# ════════════════════════════════════════════════════════════════════════════

DEMO_FACTS = [
    {"fact_id": "F001", "claim_text": "OpenAI was founded in December 2015 in San Francisco.",
     "source_urls": ["https://en.wikipedia.org/wiki/OpenAI"], "source_type": "wikipedia",
     "authority_tier": 4, "trust_score": 0.88, "last_verified_at": time.time() - 86400},
    {"fact_id": "F002", "claim_text": "Anthropic was founded in 2021 by Dario Amodei, Daniela Amodei and former OpenAI researchers.",
     "source_urls": ["https://en.wikipedia.org/wiki/Anthropic"], "source_type": "wikipedia",
     "authority_tier": 4, "trust_score": 0.92, "last_verified_at": time.time() - 86400},
    {"fact_id": "F003", "claim_text": "GDPR Article 17 grants individuals the right to erasure of personal data.",
     "source_urls": ["https://gdpr-info.eu/art-17-gdpr/"], "source_type": "gov_site",
     "authority_tier": 1, "trust_score": 0.99, "last_verified_at": time.time() - 86400 * 7},
    {"fact_id": "F004", "claim_text": "Retrieval-Augmented Generation (RAG) was proposed by Lewis et al. at Facebook AI in 2020.",
     "source_urls": ["https://arxiv.org/abs/2005.11401"], "source_type": "academic",
     "authority_tier": 2, "trust_score": 0.97, "last_verified_at": time.time() - 86400 * 14},
    {"fact_id": "F005", "claim_text": "Python was created by Guido van Rossum and first released in 1991.",
     "source_urls": ["https://en.wikipedia.org/wiki/Python_(programming_language)"], "source_type": "wikipedia",
     "authority_tier": 4, "trust_score": 0.91, "last_verified_at": time.time() - 86400},
    {"fact_id": "F006", "claim_text": "Claude is an AI assistant developed by Anthropic, first released in 2023.",
     "source_urls": ["https://www.anthropic.com/claude"], "source_type": "brand_owned",
     "authority_tier": 1, "trust_score": 0.98, "last_verified_at": time.time() - 86400 * 2},
    {"fact_id": "F007", "claim_text": "SOC 2 Type II is a security audit standard developed by the AICPA.",
     "source_urls": ["https://www.aicpa.org/soc2"], "source_type": "gov_site",
     "authority_tier": 1, "trust_score": 0.97, "last_verified_at": time.time() - 86400 * 30},
    {"fact_id": "F008", "claim_text": "Large language models can hallucinate by generating plausible but factually incorrect text.",
     "source_urls": ["https://arxiv.org/abs/2309.01219"], "source_type": "academic",
     "authority_tier": 2, "trust_score": 0.95, "last_verified_at": time.time() - 86400 * 10},
]


@app.on_event("startup")
async def startup():
    """Wire all Phase 2 + Phase 3 components on startup."""
    if not API_KEY:
        print("[Server] WARNING: ANTHROPIC_API_KEY not set — agent will have limited functionality")
        return

    # Phase 2: Privacy Vault
    vault = None
    if VAULT_OK:
        vault = PrivacyVault()
        vault.register_user("default", Role.API_USER, consent=ConsentStatus.EXPLICIT)
        vault.register_user("admin",   Role.ADMIN,    consent=ConsentStatus.EXPLICIT)
        print("[Server] Privacy vault ready")

    # Phase 2: RAG Engine
    rag = None
    if RAG_OK:
        rag = RAGEngine(api_key=API_KEY)
        facts = [FactRecord(**f) for f in DEMO_FACTS]
        rag.load_corpus(facts)
        print(f"[Server] RAG engine ready — {len(facts)} facts")

    # Phase 2: Fact-Check Pipeline
    fact = None
    if FACT_OK:
        fact = FactCheckPipeline(api_key=API_KEY)
        chunks = [KnowledgeChunk(
            chunk_id=f["fact_id"],
            text=f["claim_text"],
            source_url=f["source_urls"][0],
            source_domain=f["source_urls"][0].split("/")[2],
            authority_tier=f["authority_tier"],
            trust_score=f["trust_score"],
        ) for f in DEMO_FACTS]
        fact.load_corpus(chunks)
        print(f"[Server] Fact-check pipeline ready — {len(chunks)} chunks")

    # Phase 3: Agent Loop
    v1_router.agent_loop = AgentLoop(
        api_key=API_KEY,
        rag_engine=rag,
        fact_pipeline=fact,
        vault=vault,
    )
    print("[Server] Agent loop ready — Phase 3 online")
    print("[Server] All systems connected: Vault + RAG + Fact-Check + Agent")


@app.get("/")
async def root():
    return {
        "product":     "Agent Accelerator",
        "phase":       3,
        "description": "Anti-hallucination verified-fact agent",
        "api_docs":    "/docs",
        "health":      "/v1/health",
        "stream":      "/v1/agent/stream",
    }
