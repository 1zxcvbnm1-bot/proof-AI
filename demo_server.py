"""
Live PROOF-AI Demo Server
Serves the frontend SPA and provides API endpoint for fact-checking with user's AI API key.
"""

from __future__ import annotations
import os
import sys
import json
import time
import uuid
from typing import Optional, Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add project root to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Import PROOF-AI components
try:
    from Fact_checker.fact_checker import FactCheckPipeline, KnowledgeChunk
    from hallucination_types import HallucinationType
    PROOF_AI_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import PROOF-AI modules: {e}")
    PROOF_AI_AVAILABLE = False

app = FastAPI(title="PROOF-AI Live Demo", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory cache of FactCheckPipeline instances per API key
pipelines: Dict[str, FactCheckPipeline] = {}
pipeline_models: Dict[str, str] = {}  # track which model each api_key uses

# Default corpus for demo (from test_simple.py)
DEFAULT_CORPUS = [
    KnowledgeChunk(
        chunk_id="D1",
        text="OpenAI was founded in December 2015 by Elon Musk, Sam Altman, and others.",
        source_url="https://en.wikipedia.org/wiki/OpenAI",
        source_domain="wikipedia.org",
        authority_tier=4,
        trust_score=0.93
    ),
    KnowledgeChunk(
        chunk_id="D2",
        text="Python was created by Guido van Rossum and first released in 1991.",
        source_url="https://en.wikipedia.org/wiki/Python_(programming_language)",
        source_domain="wikipedia.org",
        authority_tier=4,
        trust_score=0.97
    ),
    KnowledgeChunk(
        chunk_id="D3",
        text="RAG (Retrieval-Augmented Generation) was introduced by Facebook AI Research in 2020.",
        source_url="https://arxiv.org/abs/2005.11401",
        source_domain="arxiv.org",
        authority_tier=2,
        trust_score=0.98
    ),
    KnowledgeChunk(
        chunk_id="D4",
        text="Anthropic was founded in 2021 by former OpenAI researchers.",
        source_url="https://en.wikipedia.org/wiki/Anthropic",
        source_domain="wikipedia.org",
        authority_tier=4,
        trust_score=0.95
    ),
    KnowledgeChunk(
        chunk_id="D5",
        text="Claude is Anthropic's AI assistant, launched in March 2023.",
        source_url="https://www.anthropic.com/claude",
        source_domain="anthropic.com",
        authority_tier=4,
        trust_score=0.94
    )
]


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────

class FactCheckRequest(BaseModel):
    api_key: str
    provider: str = "groq"  # groq, anthropic, openai, together, etc.
    model: Optional[str] = None  # defaults per provider
    query: str
    corpus: Optional[list] = None  # custom corpus list of dicts with chunk_id, text, source_url, source_domain, authority_tier, trust_score
    stream: bool = False  # whether to stream results


class FactCheckResponse(BaseModel):
    success: bool
    total_claims: int
    verified: int
    blocked: int
    conflicts: int
    overall_score: float
    halluc_rate: float
    halluc_types: list[str]
    verdicts: list[dict]
    latency_ms: float
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Management
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_pipeline(api_key: str, provider: str, model: Optional[str] = None) -> FactCheckPipeline:
    """Get cached pipeline or create a new one."""
    cache_key = f"{provider}:{api_key}"

    if cache_key in pipelines:
        return pipelines[cache_key]

    # Determine model name based on provider
    if not model:
        model_map = {
            "groq": "groq/llama-3.3-70b-versatile",
            "anthropic": "claude-3-5-sonnet-20241022",
            "openai": "gpt-4o",
            "together": "togethercomputer/llama-2-70b",
        }
        model = model_map.get(provider.lower(), "groq/llama-3.3-70b-versatile")

    print(f"[DemoServer] Creating new pipeline for {provider} with model {model}")
    pipeline = FactCheckPipeline(api_key=api_key, model_name=model)
    pipelines[cache_key] = pipeline
    pipeline_models[cache_key] = model
    return pipeline


def load_corpus(corpus_data: Optional[list]) -> list[KnowledgeChunk]:
    """Load custom corpus or use default."""
    if corpus_data:
        chunks = []
        for item in corpus_data:
            chunk = KnowledgeChunk(
                chunk_id=item.get("chunk_id", str(uuid.uuid4())[:8]),
                text=item["text"],
                source_url=item.get("source_url", "https://example.com"),
                source_domain=item.get("source_domain", "example.com"),
                authority_tier=item.get("authority_tier", 4),
                trust_score=item.get("trust_score", 0.9),
            )
            chunks.append(chunk)
        return chunks
    return DEFAULT_CORPUS


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/fact-check")
async def fact_check(req: FactCheckRequest):
    """Run fact-check on a query. Can stream or return single JSON response."""
    if not PROOF_AI_AVAILABLE:
        raise HTTPException(status_code=500, detail="PROOF-AI modules not available")

    try:
        # Get or create pipeline for this API key
        pipeline = get_or_create_pipeline(req.api_key, req.provider, req.model)

        # Load corpus
        corpus = load_corpus(req.corpus)
        pipeline.load_corpus(corpus)

        if req.stream:
            # Return streaming response
            async def generate():
                try:
                    async for event in pipeline.check_stream(req.query):
                        if event.event_type == "claims_extracted":
                            data = {
                                "event": "claims_extracted",
                                "count": event.data.get("count", 0),
                            }
                            yield f"data: {json.dumps(data)}\n\n"
                        elif event.event_type == "verdict":
                            v = event.data
                            data = {
                                "event": "verdict",
                                "claim": v.claim.text if hasattr(v, 'claim') else str(v.claim)[:100],
                                "verdict": v.verdict.value,
                                "confidence": v.confidence,
                                "halluc_type": v.halluc_type.value,
                                "explanation": v.explanation[:150],
                            }
                            yield f"data: {json.dumps(data)}\n\n"
                        elif event.is_final:
                            d = event.data
                            data = {
                                "event": "complete",
                                "total_claims": d.get("total_claims", 0),
                                "verified": d.get("verified", 0),
                                "blocked": d.get("blocked", 0),
                                "conflicts": d.get("conflicts", 0),
                                "overall_score": d.get("overall_score", 0.0),
                                "halluc_rate": d.get("halluc_rate", 0.0),
                                "halluc_types": d.get("halluc_types", []),
                                "latency_ms": d.get("latency_ms", 0.0),
                            }
                            yield f"data: {json.dumps(data)}\n\n"
                            break
                except Exception as e:
                    error_data = {"event": "error", "message": str(e)}
                    yield f"data: {json.dumps(error_data)}\n\n"

            return StreamingResponse(generate(), media_type="text/event-stream")
        else:
            # Return single JSON response
            start = time.time()
            result = await pipeline.check(req.query)
            latency = (time.time() - start) * 1000

            verdicts_list = []
            for v in result.verdicts:
                verdicts_list.append({
                    "claim": v.claim.text,
                    "verdict": v.verdict.value,
                    "confidence": v.confidence,
                    "halluc_type": v.halluc_type.value,
                    "explanation": v.explanation,
                    "conflicts": [{"url": c.source_a_url, "vs": c.source_b_url} for c in v.conflicts] if v.conflicts else [],
                })

            return FactCheckResponse(
                success=True,
                total_claims=result.total_claims,
                verified=result.verified,
                blocked=result.blocked,
                conflicts=result.conflicts,
                overall_score=getattr(result, 'overall_score', 0.0),
                halluc_rate=result.halluc_rate,
                halluc_types=result.halluc_types,
                verdicts=verdicts_list,
                latency_ms=latency,
            ).dict()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "PROOF-AI Demo",
        "pipelines_cached": len(pipelines),
        "timestamp": time.time(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Static File Serving
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main SPA."""
    index_path = os.path.join(BASE_DIR, "Website", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>PROOF-AI Demo — Website files not found</h1>")


# Mount static files
app.mount("/css", StaticFiles(directory=os.path.join(BASE_DIR, "Website", "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(BASE_DIR, "Website", "js")), name="js")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("=" * 70)
    print("  PROOF-AI LIVE DEMO SERVER")
    print("=" * 70)
    print(f"  Starting server on http://localhost:8080")
    print(f"  Serving SPA from: {os.path.join(BASE_DIR, 'Website')}")
    status = "Available" if PROOF_AI_AVAILABLE else "Not found"
    print(f"  PROOF-AI modules: {status}")
    print("=" * 70)

    uvicorn.run(app, host="0.0.0.0", port=8080)
