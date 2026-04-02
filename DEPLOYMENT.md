# 🚀 Deployment Guide for PROOF-AI Demo

## Quick Deploy to Railway (Recommended)

Railway provides free hosting with automatic HTTPS and no configuration needed.

### Prerequisites
- GitHub account
- Railway account (free at railway.app)
- Git installed locally

### Deployment Steps

#### 1. Push to GitHub
```bash
git add .
git commit -m "Prepare for Railway deployment"
git push origin main
```

#### 2. Create Railway Project
1. Go to [railway.app](https://railway.app) and sign in
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Choose your PROOF-AI repository
5. Railway will auto-detect the configuration from `railway.json`

#### 3. Configure Environment Variables (Optional)
Add these in Railway dashboard if needed:
- `PROOF_AI_API_KEY` (optional, users provide their own)
- Any other provider-specific keys

#### 4. Deploy
- Railway will build and deploy automatically
- Wait for build to complete (2-3 minutes)
- Click "Settings" → "Generate Domain" to get your public URL

#### 5. Test Your Deployment
```bash
# Health check
curl https://your-domain.up.railway.app/api/health

# Test fact-check API
curl -X POST https://your-domain.up.railway.app/api/fact-check \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "your-openai-or-anthropic-key",
    "provider": "openai",
    "query": "Python was created by Guido van Rossum in 1991."
  }'
```

---

## Alternative: Deploy to Render

1. Create Render account
2. Create "Web Service"
3. Connect GitHub repo
4. Settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python demo_server.py`
   - Port: 8080
5. Deploy

---

## Alternative: Deploy to Heroku

```bash
heroku create proof-ai-demo
heroku addons:create heroku-postgresql:hobby-dev  # optional
git push heroku main
heroku open
```

---

## Local Testing Before Deployment

```bash
# Install dependencies
pip install -r demo_server_requirements.txt

# Run server locally
python demo_server.py

# Open browser
http://localhost:8080

# API health check
curl http://localhost:8080/api/health
```

---

## Expected Behavior

✅ **Health endpoint** returns JSON with status "ok"
✅ **Frontend** loads and shows three-panel interface
✅ **API** accepts fact-check requests
✅ **Response** includes verdicts, hallucinations detected, latency
✅ **Streaming** works with `stream: true`

---

## Troubleshooting

**Issue:** Server fails to start
**Fix:** Check Python dependencies (`pip install -r demo_server_requirements.txt`)

**Issue:** Cannot import PROOF-AI modules
**Fix:** Ensure Fact_checker/ and hallucination_types.py are in project root

**Issue:** Static files not found
**Fix:** Ensure Website/ directory exists with index.html, css/, js/

**Issue:** API calls fail with "PROOF-AI modules not available"
**Fix:** Check server logs for import errors

**Issue:** CORS errors
**Fix:** CORS is already enabled for all origins in demo_server.py

---

## Deployment Optimization

### For Production (Beyond Demo):
1. Add Redis for session/cache storage (replace in-memory pipelines)
2. Add rate limiting (slowller for API abuse)
3. Add request logging (JSON logs to stdout)
4. Set up monitoring (Sentry, LogDNA)
5. Enable gzip compression (Uvicorn)
6. Add proper domain and SSL (automatic on Railway/Render)

---

## Success Criteria

Your deployment is successful if:
- ✅ `https://your-domain/api/health` returns 200 OK
- ✅ Frontend loads in browser
- ✅ Can submit fact-check query with API key
- ✅ Receives JSON response with hallucination analysis
- ✅ Page loads in <3 seconds
- ✅ Demo URL works on mobile

---

## Share Your Demo

Once deployed, your demo URL is:
```
https://your-app-name.up.railway.app
```

**YC Application Tip:** Put this URL FRONT AND CENTER in your application.

---

## Next Steps After Deployment

1. Test with 3+ external users
2. Collect feedback
3. Document benchmark results
4. Create 60-second demo video
5. Start YC application

---

**Need help?** Check README.md for API documentation and usage examples.
