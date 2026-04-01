# Real-Time Fact-Check Pipeline

7-stage atomic claim verification · NLI-grounded · Conflict-aware · Privacy-first

## Architecture

```
Input text
    │
    ├── S1 ClaimExtractor      decompose → atomic claims (FACTUAL/CITATION/NUMERIC/CAUSAL/IDENTITY)
    │
    ├── S2 EvidenceHunter      parallel retrieval per claim
    │       ├── VectorRetriever     pgvector ANN similarity
    │       ├── BM25Retriever       keyword exact-match
    │       ├── LiveWebRetriever    real-time Tavily/Serper
    │       └── KGRetriever         entity hop graph
    │
    ├── S3 NLIVerifier         DeBERTa-v3 entailment per (claim, source) pair
    │       → ENTAILS | NEUTRAL | CONTRADICTS + score 0–1
    │
    ├── S4 ConflictAnalyzer    pairwise contradiction between sources
    │       → ConflictRecord when mutual contradiction detected
    │
    ├── S5 ConfidenceEngine    per-claim score 0–1
    │       formula: base × authority × freshness + corroboration + nli_boost - conflict_penalty
    │
    ├── S6 VerdictComposer     VERIFIED / UNCERTAIN / BLOCKED / CONFLICT
    │       with explanation + hallucination type classification
    │
    └── S7 StreamAudit         SSE real-time events + immutable audit trail
```

## Hallucination types caught

| Pattern | Provider | Detection |
|---------|----------|-----------|
| Parametric confabulation | GPT-5/o3 | No entailing source found → BLOCKED |
| Sycophancy/premise echo | Claude | False premise extracted, no support → BLOCKED |
| Conflict synthesis | Gemini | Pairwise contradiction → CONFLICT |
| Citation hallucination | Universal | Source exists but NLI = NEUTRAL/CONTRADICTS |

## Quick start

```bash
cd fact_checker
pip install anthropic numpy fastapi uvicorn pydantic
export ANTHROPIC_API_KEY=sk-ant-...

# Demo + all 3 hallucination tests
python fact_check_demo.py

# API server
uvicorn pipeline_server:app --reload --port 8001
```

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /check/stream | Real-time SSE streaming fact-check |
| POST | /check | Synchronous full JSON result |
| POST | /corpus/ingest | Add knowledge chunks |
| GET | /stats | Pipeline metrics |
| GET | /audit | Audit trail |
| GET | /health | Liveness |

## SSE event types

```json
{ "event_type": "claims_extracted", "data": {"count": 3, "claims": [...]} }
{ "event_type": "verdict", "claim_id": "C0001_...", "data": {
    "claim": "OpenAI was founded in 2015",
    "verdict": "VERIFIED",
    "confidence": 0.88,
    "band": "MEDIUM",
    "explanation": "Verified by 2 independent sources...",
    "halluc_type": "none",
    "sources": ["https://en.wikipedia.org/wiki/OpenAI"],
    "conflicts": 0
  }
}
{ "event_type": "complete", "is_final": true, "data": {
    "total_claims": 3, "verified": 2, "blocked": 1,
    "halluc_rate": "33.3%", "overall_score": "0.72"
  }
}
```

## Confidence bands

| Band | Score | Meaning |
|------|-------|---------|
| HIGH | ≥ 0.85 | Green — strong multi-source verification |
| MEDIUM | 0.60–0.85 | Blue — verified, note confidence |
| LOW | 0.40–0.60 | Amber — uncertain, caution advised |
| BLOCKED | < 0.40 | Red — claim suppressed, not output |

## Connect to RAG engine

```python
from integration import FactCheckBridge
from fact_checker import FactCheckPipeline

pipeline = FactCheckPipeline(api_key=KEY)
pipeline.load_corpus(your_chunks)
bridge = FactCheckBridge(fact_pipeline=pipeline)

# Verify any text
report = bridge.summary_report("OpenAI launched in 2015. Mars has 200 people.")
print(report)
```

## Production checklist

- [ ] Replace NLI Claude proxy with `cross-encoder/nli-deberta-v3-large` (HuggingFace)
- [ ] Connect `LiveWebRetriever` to Tavily API
- [ ] Connect `VectorEvidenceRetriever` to real pgvector Postgres
- [ ] Wire `FactCheckAuditLogger` to append-only Postgres table
- [ ] Add OpenTelemetry spans per pipeline stage
- [ ] Add Prometheus: claims_verified_total, hallucination_rate, latency_p99
