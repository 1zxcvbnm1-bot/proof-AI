"""
Fact-Check Pipeline — Real-Time Streaming API Server
FastAPI + Server-Sent Events (SSE) · Connects to RAG engine
"""

from __future__ import annotations
import json, os, time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import AsyncIterator

from fact_checker import (
    FactCheckPipeline, KnowledgeChunk,
    Verdict, HalluType,
)

app = FastAPI(
    title="Real-Time Fact-Check Pipeline API",
    description="7-stage atomic claim verification with NLI, conflict detection, and confidence scoring",
    version="1.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Pipeline singleton ────────────────────────────────────────────────────────
API_KEY = os.environ.get("LLM_API_KEY", os.environ.get("GROQ_API_KEY", ""))
MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "groq/llama-3.3-70b-versatile")
pipeline = FactCheckPipeline(api_key=API_KEY, model_name=MODEL_NAME)

# ── Seed knowledge corpus ─────────────────────────────────────────────────────
DEMO_CORPUS = [
    KnowledgeChunk(
        chunk_id="KC001",
        text="OpenAI was founded in December 2015 in San Francisco, California.",
        source_url="https://en.wikipedia.org/wiki/OpenAI",
        source_domain="en.wikipedia.org",
        authority_tier=4, trust_score=0.88,
    ),
    KnowledgeChunk(
        chunk_id="KC002",
        text="Anthropic was founded in 2021 by Dario Amodei, Daniela Amodei, and other former OpenAI researchers.",
        source_url="https://en.wikipedia.org/wiki/Anthropic",
        source_domain="en.wikipedia.org",
        authority_tier=4, trust_score=0.92,
    ),
    KnowledgeChunk(
        chunk_id="KC003",
        text="Hallucination in AI is when a language model generates text that is factually incorrect but presented as true.",
        source_url="https://arxiv.org/abs/2309.01219",
        source_domain="arxiv.org",
        authority_tier=2, trust_score=0.95,
    ),
    KnowledgeChunk(
        chunk_id="KC004",
        text="GDPR Article 17 establishes the right to erasure, giving individuals the right to have personal data deleted.",
        source_url="https://gdpr-info.eu/art-17-gdpr/",
        source_domain="gdpr-info.eu",
        authority_tier=1, trust_score=0.99,
    ),
    KnowledgeChunk(
        chunk_id="KC005",
        text="Retrieval-Augmented Generation (RAG) was proposed in 2020 by Lewis et al. at Facebook AI Research.",
        source_url="https://arxiv.org/abs/2005.11401",
        source_domain="arxiv.org",
        authority_tier=2, trust_score=0.97,
    ),
    KnowledgeChunk(
        chunk_id="KC006",
        text="Python programming language was created by Guido van Rossum and first released in 1991.",
        source_url="https://en.wikipedia.org/wiki/Python_(programming_language)",
        source_domain="en.wikipedia.org",
        authority_tier=4, trust_score=0.91,
    ),
    KnowledgeChunk(
        chunk_id="KC007",
        text="Claude is an AI assistant made by Anthropic, first released in 2023.",
        source_url="https://www.anthropic.com/claude",
        source_domain="anthropic.com",
        authority_tier=1, trust_score=0.98,
    ),
]
pipeline.load_corpus(DEMO_CORPUS)


# ── Request models ────────────────────────────────────────────────────────────
class CheckRequest(BaseModel):
    text:       str
    session_id: str | None = None

class CorpusIngestRequest(BaseModel):
    chunks: list[dict]


# ── SSE helpers ───────────────────────────────────────────────────────────────
async def stream_check_generator(text: str, session_id: str | None) -> AsyncIterator[str]:
    try:
        async for event in pipeline.check_stream(text, session_id):
            payload = {
                "event_type": event.event_type,
                "claim_id":   event.claim_id,
                "data":       event.data,
                "is_final":   event.is_final,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if event.is_final:
                break
    except Exception as e:
        yield f"data: {json.dumps({'event_type': 'error', 'data': {'error': str(e)}, 'is_final': True})}\n\n"


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.post("/check/stream")
async def check_stream(req: CheckRequest):
    """
    Real-time streaming fact-check via SSE.
    Emits a 'verdict' event for each claim as it completes.
    Final 'complete' event contains aggregate stats.

    SSE event shape:
      {
        event_type: "claims_extracted" | "verdict" | "complete" | "error",
        claim_id: "C0001_...",
        data: { claim, verdict, confidence, band, explanation, sources, ... },
        is_final: false | true
      }
    """
    if not req.text.strip():
        raise HTTPException(400, "Text cannot be empty")
    return StreamingResponse(
        stream_check_generator(req.text, req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/check")
async def check_sync(req: CheckRequest):
    """Synchronous fact-check. Returns full JSON result (use /check/stream for UX)."""
    if not req.text.strip():
        raise HTTPException(400, "Text cannot be empty")
    result = await pipeline.check(req.text, req.session_id)
    return {
        "result_id":     result.result_id,
        "total_claims":  result.total_claims,
        "verified":      result.verified,
        "uncertain":     result.uncertain,
        "blocked":       result.blocked,
        "conflicts":     result.conflicts,
        "halluc_rate":   f"{result.halluc_rate:.1%}",
        "overall_score": f"{result.overall_score:.2f}",
        "latency_ms":    f"{result.latency_ms:.0f}ms",
        "verdicts": [
            {
                "claim_id":    v.claim.claim_id,
                "claim":       v.claim.text,
                "claim_type":  v.claim.claim_type.value,
                "verdict":     v.verdict.value,
                "confidence":  round(v.confidence, 3),
                "band":        pipeline.conf_eng.band(v.confidence),
                "explanation": v.explanation,
                "halluc_type": v.halluc_type.value,
                "sources":     [c.source_url for c in v.supporting[:3]],
                "conflicts":   [
                    {"source_a": cr.source_a_url, "source_b": cr.source_b_url}
                    for cr in v.conflicts
                ],
            }
            for v in result.verdicts
        ],
        "stats": pipeline.stats(),
    }


@app.post("/corpus/ingest")
async def ingest_corpus(req: CorpusIngestRequest):
    """Ingest new knowledge chunks into the pipeline corpus."""
    chunks = []
    for item in req.chunks:
        try:
            chunks.append(KnowledgeChunk(**item))
        except Exception as e:
            raise HTTPException(422, f"Invalid chunk: {e}")
    pipeline.load_corpus(chunks)
    return {"ingested": len(chunks), "stats": pipeline.stats()}


@app.get("/stats")
async def get_stats():
    return pipeline.stats()


@app.get("/audit")
async def get_audit():
    return {
        "hallucination_rate":  f"{pipeline.audit.hallucination_rate():.1%}",
        "average_confidence":  f"{pipeline.audit.average_confidence():.2f}",
        "recent_checks":       pipeline.audit.last_n(20),
    }


@app.get("/health")
async def health():
    return {"status": "ok", "corpus_size": pipeline._corpus_size}
