"""
RAG Engine — Real-Time Streaming API Server
FastAPI + Server-Sent Events (SSE) for live token streaming
"""

from __future__ import annotations

import json
import os
import time
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))
from engine import (
    RAGEngine,
    FactRecord,
    StreamToken,
    ClaimStatus,
)

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="RAG Orchestration Engine API",
    description="Real-time anti-hallucination RAG with verified data layer",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Engine singleton ─────────────────────────────────────────────────────────
API_KEY = os.environ.get("LLM_API_KEY", os.environ.get("GROQ_API_KEY", ""))
MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "groq/llama-3.3-70b-versatile")
engine = RAGEngine(api_key=API_KEY, model_name=MODEL_NAME)

# ── Seed corpus with demo facts ──────────────────────────────────────────────
DEMO_CORPUS = [
    FactRecord(
        fact_id="F001",
        claim_text="OpenAI was founded in December 2015 in San Francisco.",
        source_urls=["https://en.wikipedia.org/wiki/OpenAI"],
        source_type="wikipedia",
        authority_tier=4,
        trust_score=0.88,
        last_verified_at=time.time() - 86400,
    ),
    FactRecord(
        fact_id="F002",
        claim_text="Anthropic was founded in 2021 by former OpenAI researchers including Dario Amodei and Daniela Amodei.",
        source_urls=["https://en.wikipedia.org/wiki/Anthropic"],
        source_type="wikipedia",
        authority_tier=4,
        trust_score=0.92,
        last_verified_at=time.time() - 86400,
    ),
    FactRecord(
        fact_id="F003",
        claim_text="Hallucination in large language models refers to the generation of text that is factually incorrect or nonsensical but presented confidently.",
        source_urls=["https://arxiv.org/abs/2309.01219"],
        source_type="academic",
        authority_tier=2,
        trust_score=0.95,
        last_verified_at=time.time() - 86400 * 7,
    ),
    FactRecord(
        fact_id="F004",
        claim_text="GDPR Article 17 grants individuals the right to erasure, also known as the right to be forgotten.",
        source_urls=["https://gdpr-info.eu/art-17-gdpr/"],
        source_type="gov_site",
        authority_tier=1,
        trust_score=0.99,
        last_verified_at=time.time() - 86400 * 30,
    ),
    FactRecord(
        fact_id="F005",
        claim_text="Retrieval-Augmented Generation (RAG) combines a retrieval mechanism with a generative model to ground outputs in external knowledge.",
        source_urls=["https://arxiv.org/abs/2005.11401"],
        source_type="academic",
        authority_tier=2,
        trust_score=0.97,
        last_verified_at=time.time() - 86400 * 14,
    ),
]

engine.load_corpus(DEMO_CORPUS)


# ── Request / Response Models ────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None


class FactIngestRequest(BaseModel):
    facts: list[dict]


# ── SSE Streaming endpoint ───────────────────────────────────────────────────

async def token_stream_generator(
    query: str, session_id: str | None
) -> AsyncIterator[str]:
    """Converts StreamToken async iterator to SSE format."""
    try:
        async for token in engine.query(query, session_id):
            event = {
                "text":       token.text,
                "claim_id":   token.claim_id,
                "confidence": token.confidence,
                "status":     token.status.value if token.status else None,
                "is_final":   token.is_final,
            }
            yield f"data: {json.dumps(event)}\n\n"
            if token.is_final:
                break
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e), 'is_final': True})}\n\n"


@app.post("/query/stream")
async def query_stream(req: QueryRequest):
    """
    Real-time streaming query endpoint.
    Returns Server-Sent Events (SSE) stream of verified tokens.

    Each SSE event contains:
      text:       the token text
      claim_id:   fact_id if this token is a cited claim
      confidence: 0–1 confidence score for cited claims
      status:     VERIFIED | UNCERTAIN | BLOCKED | CONFLICT
      is_final:   true on the last event
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    return StreamingResponse(
        token_stream_generator(req.query, req.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/query")
async def query_sync(req: QueryRequest):
    """
    Synchronous query endpoint — collects full stream and returns JSON.
    Use /query/stream for real-time UX; use this for batch/testing.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    full_text = ""
    citations = []
    async for token in engine.query(req.query, req.session_id):
        full_text += token.text
        if token.claim_id:
            citations.append({
                "claim_id":   token.claim_id,
                "confidence": token.confidence,
                "status":     token.status.value if token.status else None,
            })

    return {
        "query":     req.query,
        "response":  full_text,
        "citations": citations,
        "stats":     engine.stats(),
    }


@app.post("/corpus/ingest")
async def ingest_facts(req: FactIngestRequest):
    """Ingest new verified facts into the corpus."""
    new_facts = []
    for f in req.facts:
        try:
            new_facts.append(FactRecord(**f))
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid fact: {e}")
    engine.load_corpus(new_facts)
    return {"ingested": len(new_facts), "stats": engine.stats()}


@app.get("/stats")
async def get_stats():
    """Engine health + performance stats."""
    return engine.stats()


@app.get("/audit")
async def get_audit(session_id: str | None = None):
    """Retrieve audit logs (session-scoped or all)."""
    if session_id:
        logs = engine.audit.get_session_logs(session_id)
    else:
        logs = engine.audit._log[-50:]  # last 50 entries
    return {
        "count":              len(logs),
        "hallucination_rate": f"{engine.audit.hallucination_rate():.1%}",
        "logs":               [
            {
                "log_id":      e.log_id,
                "timestamp":   e.timestamp,
                "verified":    e.claims_verified,
                "uncertain":   e.claims_uncertain,
                "blocked":     e.claims_blocked,
                "h_detected":  e.hallucination_detected,
                "h_types":     e.hallucination_types,
                "latency_ms":  e.latency_ms,
            }
            for e in logs
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "corpus_size": engine._corpus_size}
