# 🚀 PROOF-AI Live Demo — Quick Start

## What You Get

**A live web page where anyone can paste their AI API key and test PROOF-AI's hallucination detection instantly.**

No setup, no database, just run and use.

---

## ✅ Already Done

- Backend API built (`demo_server.py`) — FastAPI server with caching
- Frontend updated (`Website/`) — Added API key input + real streaming
- Tested and working — Verified with Groq API

---

## How to Run (2 Steps)

### 1. Start the Server

**Windows**: Double-click `run_demo.bat`  **or**  run in terminal:
```bash
python demo_server.py
```

**Expected output**:
```
======================================
  PROOF-AI LIVE DEMO SERVER
======================================
  Starting server on http://localhost:8080
  Serving SPA from: D:\PROOF-AI demo\Website
  PROOF-AI modules: ✅ Available
======================================
```

### 2. Open in Browser

Go to: **http://localhost:8080#fact-checker**

You'll see the Fact Checker interface with:
- Provider dropdown (Groq/Anthropic/OpenAI/Together)
- API Key input field
- Query textarea
- Results terminal

---

## Live Demo Walkthrough

### Example Test (with GROQ)

1. Select **Provider**: Groq
2. **API Key**: Paste your Groq API key
3. **Query**: `Python was created by Guido van Rossum in 1991.`
4. Click **"Run Live Verification (Streaming)"**

**What you'll see in the terminal**:
```
🔍 Initializing PROOF-AI fact-check...
   Provider: groq
✅ Connected. Streaming verdicts...
   Extracted 1 claim(s)
✅ [VERIFIED   ] conf: 0.94
   Claim: Python was created by Guido van Ross...
   Hallucination: none
   ↳ Claim matches verified corpus
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Summary: 1 verified, 0 blocked, 0 conflicts
   Hallucination rate: 0.0%
   Latency: 1234.5ms
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Try with a False Claim

Query: `Python was written in Java and runs on the JVM.`

You should see:
```
🚫 [BLOCKED   ] conf: 0.00
   Claim: Python was written in Java...
   Hallucination: factual_contradiction
   ↳ No verified evidence found
```

---

## Supported Models

| Provider | Default Model | Your API Key Format |
|----------|--------------|---------------------|
| Groq | `groq/llama-3.3-70b-versatile` | `gsk_...` |
| Anthropic | `claude-3-5-sonnet-20241022` | `sk-ant-...` |
| OpenAI | `gpt-4o` | `sk-...` |
| Together | `togethercomputer/llama-2-70b` | `together_...` |

**Any LiteLLM-supported provider works!** Override model name in the field if needed.

---

## File Structure

```
PROOF-AI demo/
├── demo_server.py              ← Main server (FastAPI)
├── demo_server_requirements.txt
├── test_demo_server.py         ← Test script
├── run_demo.bat                ← Windows launcher
├── Website/
│   ├── index.html              ← Updated with API key UI
│   ├── js/app.js               ← Real API calls + streaming
│   └── css/styles.css          ← Existing styles
├── Fact_checker/               ← PROOF-AI core (unchanged)
├── hallucination_detectors/    ← 7 detector modules
└── README.md                   ← Full project docs
```

---

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serve SPA |
| `/api/fact-check` | POST | Run fact-check with user's API key |
| `/api/health` | GET | Health check |
| `/css/*` | GET | Static CSS |
| `/js/*` | GET | Static JS |

---

## Troubleshooting

**"PROOF-AI modules not available"**
→ Run from project root, install dependencies: `pip install litellm fastapi uvicorn`

**Import errors on startup**
→ Ensure Python 3.11+, check `Fact_checker/` directory exists

**Port 8080 already in use**
→ Change `port=8080` in `demo_server.py` to another port (e.g., 8090)

**Slow first request (5-10 seconds)**
→ Normal! FactCheckPipeline initializes on first use per API key, then cached.

**Unicode errors on Windows console**
→ Set environment: `set PYTHONIOENCODING=utf-8` before running

---

## Behind the Scenes

### What Happens When You Click "Verify"

1. **Frontend** sends your API key + query to backend via POST `/api/fact-check`
2. **Backend** checks cache: have we seen this API key before?
   - **No**: Creates new `FactCheckPipeline(api_key, model)` (expensive, ~2s)
   - **Yes**: Reuses cached pipeline (fast, ~200ms)
3. **Pipeline loads** default corpus (5 knowledge chunks) or your custom corpus
4. **Claim extraction**: LLM extracts atomic claims from your query
5. **7 detectors run in parallel**:
   - Entity Verification
   - Drift Detection
   - Logical Structure
   - Semantic Precision
   - Temporal Consistency
   - Confidence Calibration
   - Structural Integrity
6. **VerdictComposer** applies confidence penalties based on flags
7. **Streaming response**: Each verdict emitted as it's ready (SSE)
8. **Frontend** displays icons: ✅ Verified, 🚫 Blocked, ⚡ Conflict, ⚠️ Uncertain

---

## Next Steps

✅ **Demo is ready**: Run `python demo_server.py` and open `http://localhost:8080#fact-checker`

✅ **Share with anyone**: They just need their own AI API key (no setup on your side)

🔧 **Customize further**:
- Add more providers to the dropdown (edit `Website/index.html`)
- Change default corpus (edit `DEFAULT_CORPUS` in `demo_server.py`)
- Add authentication/rate limiting (modify `demo_server.py`)
- Deploy to cloud (Railway, Fly.io, Heroku) — just push the code

---

## Test It Now!

```bash
python demo_server.py
```

Then open: **http://localhost:8080#fact-checker**

**Quick test query**:
```
Query: "OpenAI was founded in December 2015."
Expected: ✅ VERIFIED (should match corpus)
```

---

**Enjoy your live PROOF-AI demo!** 🎉
