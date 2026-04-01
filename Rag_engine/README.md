# Real-Time RAG Orchestration Engine

Anti-hallucination · Verified data layer · Privacy-first · Real-time streaming

## Architecture

```
User Query
    │
    ├── PII Scrubber (Presidio)          ← strips emails, phones, SSNs
    ├── Sycophancy Guard                 ← catches false premises (Claude pattern)
    │
    └── Query Embedder + Planner
            │
            ├── Vector Search (pgvector)     ┐
            ├── BM25 Keyword Search          │  parallel
            ├── Knowledge Graph Retrieval    │  asyncio.gather
            └── Live Web Fetch (Tavily)      ┘
                        │
                   Reranker
            (cross-encoder + trust filter)
                        │
            ┌───────────┼───────────┐
            │           │           │
        NLI Check   Conflict    Confidence     ← parallel verify
        (DeBERTa)   Detector    Scorer
            │           │           │
            └───────────┴───────────┘
                        │
              Constrained LLM Generator
                 (citation-forced)
                        │
              ┌─────────┼─────────┐
              │         │         │
         SSE Stream  Audit Log  Feedback
```

## Hallucination patterns defeated

| Provider | Pattern | Guard |
|----------|---------|-------|
| GPT-5/o3 | Parametric confabulation | Trust gate + RAG grounding |
| Claude | Sycophancy / premise echo | Sycophancy Guard (pre-retrieval) |
| Gemini | Source-conflict synthesis | Conflict Detector (pairwise NLI) |
| Universal | Citation hallucination | NLI entailment check |

## Quick start

```bash
# Install dependencies
pip install anthropic numpy fastapi uvicorn

# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run demo
python demo.py

# Run API server
uvicorn server:app --reload --port 8000
```

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /query/stream | Real-time SSE streaming query |
| POST | /query | Synchronous query (batch/test) |
| POST | /corpus/ingest | Ingest new verified facts |
| GET | /stats | Engine health + performance |
| GET | /audit | Immutable audit trail |
| GET | /health | Liveness check |

## SSE event format

```json
{
  "text": "OpenAI was founded in 2015",
  "claim_id": "F001",
  "confidence": 0.88,
  "status": "VERIFIED",
  "is_final": false
}
```

## Confidence bands

| Band | Score | UI treatment |
|------|-------|-------------|
| HIGH | ≥ 0.85 | Green badge |
| MEDIUM | 0.60–0.85 | Blue badge |
| LOW | 0.40–0.60 | Amber warning |
| BLOCKED | < 0.40 | Suppressed |

## Production checklist

- [ ] Replace mock embedder with `openai.embeddings.create(model="text-embedding-3-large")`  
- [ ] Replace NLI proxy with `cross-encoder/nli-deberta-v3-large` (HuggingFace)
- [ ] Connect pgvector Postgres for `VectorRetriever`
- [ ] Connect Tavily API for `LiveWebRetriever`
- [ ] Set up HashiCorp Vault for encryption key management
- [ ] Install Presidio: `pip install presidio-analyzer presidio-anonymizer`
- [ ] Download spaCy model: `python -m spacy download en_core_web_lg`
- [ ] Wire audit_log to Postgres append-only table
- [ ] Add OpenTelemetry tracing on each pipeline stage
- [ ] Add Prometheus metrics: latency_ms, hallucination_rate, cache_hit_rate
