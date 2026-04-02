# PROOF-AI Live Demo Server

Quick setup for a live web demo where users can input any AI API key and see PROOF-AI fact-checking in action.

## Files Added/Modified

- ✅ `demo_server.py` - FastAPI server that serves the SPA and handles fact-check API
- ✅ `Website/index.html` - Updated with API key inputs
- ✅ `Website/js/app.js` - Updated to make real API calls with streaming
- ✅ `test_demo_server.py` - Test script to verify everything works
- ✅ `demo_server_requirements.txt` - Dependencies

## Quick Start

### 1. Install Dependencies (if needed)

```bash
pip install -r demo_server_requirements.txt
```

### 2. Start the Server

```bash
python demo_server.py
```

Server runs on: **http://localhost:8080**

### 3. Open in Browser

Navigate to: **http://localhost:8080#fact-checker**

### 4. Enter Your API Key

- **Provider**: Select (Groq, Anthropic, OpenAI, Together)
- **API Key**: Paste your key
- **Model** (optional): Override default model
- **Claim**: Enter text to fact-check
- Click **"Run Live Verification (Streaming)"**

## How It Works

1. **Frontend**: User enters API key + query → POST `/api/fact-check` with streaming
2. **Backend**: Caches `FactCheckPipeline` per API key (reuses for subsequent requests)
3. **PROOF-AI**: Loads default corpus (or custom if provided), runs claim extraction + 7 detectors
4. **Streaming**: Server-Sent Events (SSE) deliver verdicts as they're computed
5. **UI**: Real-time terminal shows ✅ VERIFIED, 🚫 BLOCKED, ⚡ CONFLICT with explanations

## API Reference

### POST `/api/fact-check`

**Request:**
```json
{
  "api_key": "your-api-key",
  "provider": "groq",
  "model": "groq/llama-3.3-70b-versatile",
  "query": "Python was created in 1991 by Guido van Rossum.",
  "corpus": null,
  "stream": true
}
```

**Response (streaming SSE):**

Events:
- `claims_extracted`: `{count: N}`
- `verdict`: `{claim, verdict, confidence, halluc_type, explanation}`
- `complete`: `{total_claims, verified, blocked, conflicts, halluc_rate, halluc_types, latency_ms}`
- `error`: `{message}`

**Non-streaming:**
```json
{
  "success": true,
  "total_claims": 1,
  "verified": 0,
  "blocked": 1,
  "conflicts": 0,
  "overall_score": 0.0,
  "halluc_rate": 1.0,
  "halluc_types": ["sentence_contradiction"],
  "verdicts": [...],
  "latency_ms": 626.1
}
```

### GET `/api/health`

Returns server health and cache status.

## Supported Providers

| Provider | Default Model |
|----------|---------------|
| Groq | `groq/llama-3.3-70b-versatile` |
| Anthropic | `claude-3-5-sonnet-20241022` |
| OpenAI | `gpt-4o` |
| Together | `togethercomputer/llama-2-70b` |

Any LiteLLM-supported provider works via the `provider` field format.

## Custom Corpus (Optional)

Include a `corpus` array in the request:

```json
{
  "corpus": [
    {
      "chunk_id": "C1",
      "text": "Your verified fact here",
      "source_url": "https://...",
      "source_domain": "example.com",
      "authority_tier": 4,
      "trust_score": 0.95
    }
  ]
}
```

Fields: `chunk_id`, `text` (required), `source_url`, `source_domain`, `authority_tier` (1-4), `trust_score` (0-1).

## Testing

Run the automated test:

```bash
python test_demo_server.py
```

This starts the server, makes a test request with mock API key, and verifies the response.

## Notes

- The server uses an in-memory cache for `FactCheckPipeline` instances. Different API keys = different cached pipelines.
- No database required — everything is ephemeral.
- CORS is enabled for all origins (`allow_origins=["*"]`) for demo purposes.
- For production, restrict origins and add rate limiting.
- The frontend UI is served from `Website/` directory.

## Troubleshooting

**"PROOF-AI modules not available"**: Ensure `Fact_checker/` and `hallucination_detectors/` are in the Python path (run from project root).

**Import errors**: Install dependencies: `pip install litellm fastapi uvicorn ...`

**Unicode errors on Windows**: Set `PYTHONIOENCODING=utf-8` environment variable.

**Slow first request**: Pipeline initialization + model loading happens on first use per API key (cached thereafter).
