"""
╔══════════════════════════════════════════════════════════════════════════╗
║  VERSIONED API v1 — Phase 3                                             ║
║  JWT auth · Rate limiting · /v1/agent/run · /v1/agent/stream           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from collections import defaultdict
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel


# ════════════════════════════════════════════════════════════════════════════
# JWT AUTH  (lightweight — no PyJWT dependency)
# ════════════════════════════════════════════════════════════════════════════

JWT_SECRET  = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
JWT_EXPIRY  = 3600 * 24 * 30    # 30 days

def _b64url_encode(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _b64url_decode(s: str) -> bytes:
    import base64
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)

def create_token(user_id: str, plan: str = "free") -> str:
    header  = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps({
        "sub":  user_id,
        "plan": plan,
        "iat":  int(time.time()),
        "exp":  int(time.time()) + JWT_EXPIRY,
        "jti":  str(uuid.uuid4())[:8],
    }).encode())
    sig = _b64url_encode(
        hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{sig}"

def verify_token(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid token format")
        header, payload, sig = parts
        expected_sig = _b64url_encode(
            hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("Invalid signature")
        claims = json.loads(_b64url_decode(payload).decode())
        if claims.get("exp", 0) < time.time():
            raise ValueError("Token expired")
        return claims
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Unauthorized: {e}")


# ════════════════════════════════════════════════════════════════════════════
# RATE LIMITER
# ════════════════════════════════════════════════════════════════════════════

PLAN_LIMITS = {
    "free":       {"rpm": 5,   "rpd": 50},
    "starter":    {"rpm": 20,  "rpd": 500},
    "pro":        {"rpm": 60,  "rpd": 5000},
    "enterprise": {"rpm": 300, "rpd": 100_000},
}

class RateLimiter:
    def __init__(self):
        self._minute_counts: dict[str, list[float]] = defaultdict(list)
        self._day_counts:    dict[str, list[float]] = defaultdict(list)

    def check(self, user_id: str, plan: str) -> None:
        now    = time.time()
        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

        # Clean old timestamps
        self._minute_counts[user_id] = [t for t in self._minute_counts[user_id] if now - t < 60]
        self._day_counts[user_id]    = [t for t in self._day_counts[user_id]    if now - t < 86400]

        if len(self._minute_counts[user_id]) >= limits["rpm"]:
            raise HTTPException(429, detail=f"Rate limit exceeded: {limits['rpm']} req/min on {plan} plan")
        if len(self._day_counts[user_id]) >= limits["rpd"]:
            raise HTTPException(429, detail=f"Daily limit exceeded: {limits['rpd']} req/day on {plan} plan")

        self._minute_counts[user_id].append(now)
        self._day_counts[user_id].append(now)


# ════════════════════════════════════════════════════════════════════════════
# APP + DEPENDENCIES
# ════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Agent Accelerator API",
    version="1.0.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer_scheme = HTTPBearer(auto_error=False)
rate_limiter  = RateLimiter()
agent_loop    = None   # injected by server startup

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> dict:
    if not credentials:
        raise HTTPException(401, "Authorization header required")
    return verify_token(credentials.credentials)

def require_plan(min_plan: str):
    plan_order = ["free", "starter", "pro", "enterprise"]
    def _check(user: dict = Depends(get_current_user)) -> dict:
        user_plan = user.get("plan", "free")
        if plan_order.index(user_plan) < plan_order.index(min_plan):
            raise HTTPException(403, f"Requires {min_plan} plan or above")
        return user
    return _check


# ════════════════════════════════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ════════════════════════════════════════════════════════════════════════════

class AgentRunRequest(BaseModel):
    query:      str
    session_id: Optional[str] = None

class TokenRequest(BaseModel):
    user_id: str
    plan:    str = "free"
    secret:  str                        # admin secret to issue tokens

class FeedbackRequest(BaseModel):
    session_id:   str
    query:        str
    was_helpful:  bool
    correction:   Optional[str] = None  # user correction if wrong


# ════════════════════════════════════════════════════════════════════════════
# STREAMING SSE HELPER
# ════════════════════════════════════════════════════════════════════════════

async def agent_sse_generator(query: str, session_id: str, user_id: str):
    """Convert AgentStreamEvents to SSE format."""
    try:
        async for event in agent_loop.run(query, session_id, user_id):
            payload = {
                "event":    event.event.value,
                "data":     event.data,
                "is_final": event.is_final,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if event.is_final:
                break
    except Exception as e:
        yield f"data: {json.dumps({'event': 'error', 'data': {'message': str(e)}, 'is_final': True})}\n\n"


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS — v1
# ════════════════════════════════════════════════════════════════════════════

@app.post("/v1/agent/stream")
async def agent_stream(
    req:  AgentRunRequest,
    user: dict = Depends(get_current_user),
):
    """
    Real-time agent run via SSE.
    Full pipeline: plan → act → verify → cite → stream.

    SSE event types:
      plan_created   → execution plan with steps
      step_start     → tool invocation begins
      tool_call      → tool name + input
      tool_result    → tool output metadata
      verify_start   → self-verification begins
      verify_done    → confidence + replan decision
      replan         → insufficient result, retrying
      cite_start     → citation attachment begins
      token          → streamed response text
      complete       → full response + trust UI + citations
      error          → pipeline failure
    """
    if not req.query.strip():
        raise HTTPException(400, "Query cannot be empty")
    if not agent_loop:
        raise HTTPException(503, "Agent loop not initialised")

    user_id    = user["sub"]
    session_id = req.session_id or str(uuid.uuid4())
    rate_limiter.check(user_id, user.get("plan", "free"))

    return StreamingResponse(
        agent_sse_generator(req.query, session_id, user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control":       "no-cache",
            "X-Accel-Buffering":   "no",
            "X-Session-Id":        session_id,
        },
    )


@app.post("/v1/agent/run")
async def agent_run(
    req:  AgentRunRequest,
    user: dict = Depends(get_current_user),
):
    """
    Synchronous agent run (waits for completion).
    Use /v1/agent/stream for real-time UX.
    """
    if not req.query.strip():
        raise HTTPException(400, "Query cannot be empty")
    if not agent_loop:
        raise HTTPException(503, "Agent loop not initialised")

    user_id    = user["sub"]
    session_id = req.session_id or str(uuid.uuid4())
    rate_limiter.check(user_id, user.get("plan", "free"))

    response_text = ""
    trust_data    = {}
    citations     = []
    plan_data     = {}

    async for event in agent_loop.run(req.query, session_id, user_id):
        if event.event.value == "token":
            response_text += event.data.get("text", "")
        elif event.event.value == "complete":
            trust_data  = event.data.get("trust", {})
            citations   = event.data.get("citations", [])
            plan_data   = {k: event.data[k] for k in ["plan_id", "steps_executed", "attempts", "latency_ms"] if k in event.data}

    return {
        "session_id":  session_id,
        "query":       req.query,
        "response":    response_text,
        "trust":       trust_data,
        "citations":   citations,
        "plan":        plan_data,
    }


@app.delete("/v1/agent/session/{session_id}")
async def clear_session(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Clear conversation memory for a session."""
    if agent_loop:
        agent_loop.memory.clear(session_id)
    return {"cleared": True, "session_id": session_id}


@app.post("/v1/feedback")
async def submit_feedback(
    req:  FeedbackRequest,
    user: dict = Depends(get_current_user),
):
    """
    Submit user feedback on agent response.
    Corrections feed the fine-tuning flywheel.
    Production: write to feedback_log table.
    """
    entry = {
        "feedback_id":  str(uuid.uuid4()),
        "user_id_hash": hashlib.sha256(user["sub"].encode()).hexdigest()[:12],
        "session_id":   req.session_id,
        "query_hash":   hashlib.sha256(req.query.encode()).hexdigest()[:12],
        "was_helpful":  req.was_helpful,
        "has_correction": req.correction is not None,
        "timestamp":    time.time(),
    }
    # Production: INSERT INTO feedback_log VALUES (...)
    return {"recorded": True, "feedback_id": entry["feedback_id"]}


@app.post("/v1/auth/token")
async def issue_token(req: TokenRequest):
    """
    Issue JWT token. Admin secret required.
    Production: validate against users table.
    """
    admin_secret = os.environ.get("ADMIN_SECRET", "admin-dev-secret")
    if req.secret != admin_secret:
        raise HTTPException(403, "Invalid admin secret")
    if req.plan not in PLAN_LIMITS:
        raise HTTPException(400, f"Invalid plan. Choose: {list(PLAN_LIMITS.keys())}")
    token = create_token(req.user_id, req.plan)
    return {
        "token":      token,
        "user_id":    req.user_id,
        "plan":       req.plan,
        "expires_in": JWT_EXPIRY,
    }


@app.get("/v1/agent/stats")
async def agent_stats(user: dict = Depends(require_plan("analyst"))):
    """Agent loop stats (analyst plan+)."""
    if not agent_loop:
        raise HTTPException(503, "Agent loop not initialised")
    return agent_loop.stats()


@app.get("/v1/health")
async def health():
    return {
        "status":        "ok",
        "version":       "1.0.0",
        "agent_ready":   agent_loop is not None,
    }
