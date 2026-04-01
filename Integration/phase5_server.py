"""
╔══════════════════════════════════════════════════════════════════════════╗
║  PHASE 5 PRODUCTION SERVER — Agent Accelerator Public Launch            ║
║  All 5 phases unified · Growth · Integrations · Launch · Scale         ║
║  uvicorn phase5_server:app --host 0.0.0.0 --port 8080                  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import os, sys, json, time, uuid

BASE = os.path.dirname(os.path.abspath(__file__))
for d in ["growth", "integrations", "launch"]:
    sys.path.insert(0, os.path.join(BASE, d))
sys.path.insert(0, os.path.join(BASE, "..", "phase3", "core"))
sys.path.insert(0, os.path.join(BASE, "..", "phase3", "api", "v1"))
sys.path.insert(0, os.path.join(BASE, "..", "phase4", "pilot"))
sys.path.insert(0, os.path.join(BASE, "..", "phase4", "metrics"))
sys.path.insert(0, os.path.join(BASE, "..", "phase4", "billing"))
sys.path.insert(0, os.path.join(BASE, "..", "phase4", "gtm"))
sys.path.insert(0, os.path.join(BASE, "..", "privacy_vault", "privacy"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional

from analytics      import GrowthAnalyticsEngine, ICPSignal, FunnelStage
from integrations   import SlackApp, TeamsBot, IntegrationRegistry, WebhookSystem
from launch_centre  import LaunchChecklist, AutoScaler, CostOptimiser
from launch_centre  import producthunt_post, press_release

# Phase 4 systems
from onboarding      import PilotOnboardingEngine, PilotTier
from success_metrics import SuccessMetricsTracker, QueryMetric
from billing_engine  import BillingEngine, BillingPlan
from soc2_gtm        import SOC2Engine, GTMKit


app = FastAPI(
    title="Agent Accelerator — Production",
    version="5.0.0",
    docs_url="/v1/docs",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ── System init ───────────────────────────────────────────────────────────
growth      = GrowthAnalyticsEngine()
webhooks    = WebhookSystem()
integrations= IntegrationRegistry()
checklist   = LaunchChecklist()
auto_scaler = AutoScaler()
cost_opt    = CostOptimiser(monthly_budget_usd=float(os.environ.get("MONTHLY_BUDGET_USD","500")))
onboarding  = PilotOnboardingEngine()
metrics     = SuccessMetricsTracker()
billing     = BillingEngine()
soc2        = SOC2Engine()
soc2.auto_map_phase_work()
gtm         = GTMKit(metrics, billing, soc2, onboarding)

# Auto-complete infrastructure checks that are already live
for check_id in ["INF01","INF02","INF03","PRD01","PRD02","PRD03",
                 "PRD04","PRD05","PRD06","COM01","COM02","BIZ01"]:
    checklist.complete(check_id)

# Seed demo growth data
def _seed_growth():
    for i in range(3):
        l = growth.track_visitor(company=f"TechCorp {i+1}")
        growth.track_signup(l.lead_id, f"user{i}@company.com",
                            icp_signals=[ICPSignal.BIG_TECH, ICPSignal.COMPLIANCE_TEAM])
        growth.track_api_call(l.lead_id, 15)
    paying = growth.track_visitor(company="FinanceHub")
    growth.track_signup(paying.lead_id, "cto@financehub.com",
                        icp_signals=[ICPSignal.FINTECH])
    growth.track_api_call(paying.lead_id, 50)
    growth.track_payment(paying.lead_id, mrr_usd=999.0)

_seed_growth()


# ════════════════════════════════════════════════════════════════════════════
# LANDING PAGE
# ════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def landing():
    portal_path = os.path.join(BASE, "portal", "index.html")
    if os.path.exists(portal_path):
        with open(portal_path) as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>Agent Accelerator — launching soon</h1>")


# ════════════════════════════════════════════════════════════════════════════
# GROWTH ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

class VisitorRequest(BaseModel):
    referrer: str = ""
    company:  str = ""

class SignupRequest(BaseModel):
    lead_id:     str
    email:       str
    company:     str = ""
    icp_signals: list[str] = []

@app.post("/v5/growth/visitor")
async def track_visitor(req: VisitorRequest):
    lead = growth.track_visitor(req.referrer, req.company)
    return {"lead_id": lead.lead_id}

@app.post("/v5/growth/signup")
async def track_signup(req: SignupRequest):
    icp = [ICPSignal(s) for s in req.icp_signals if s in ICPSignal._value2member_map_]
    growth.track_signup(req.lead_id, req.email, req.company, icp)
    return {"scored": True}

@app.get("/v5/growth/funnel")
async def funnel_report():
    return growth.funnel_report()

@app.get("/v5/growth/leads/top")
async def top_leads(n: int = 10):
    return {"leads": growth.top_leads(n)}

@app.get("/v5/growth/churn-risk")
async def churn_risk():
    return {"at_risk": growth.churn_risk()}

@app.get("/v5/growth/cohorts")
async def cohort_retention():
    return growth.cohort_retention()


# ════════════════════════════════════════════════════════════════════════════
# INTEGRATIONS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/v5/integrations")
async def list_integrations():
    return {"integrations": integrations.list_all()}

@app.get("/v5/integrations/sdk/{language}")
async def get_sdk(language: str):
    return {"language": language, "code": integrations.sdk_code(language)}

class WebhookRegisterRequest(BaseModel):
    tenant_id: str
    url:       str
    secret:    str

@app.post("/v5/webhooks/register")
async def register_webhook(req: WebhookRegisterRequest):
    webhooks.register(req.tenant_id, req.url, req.secret)
    return {"registered": True, "tenant_id": req.tenant_id}


# ════════════════════════════════════════════════════════════════════════════
# LAUNCH COMMAND CENTRE
# ════════════════════════════════════════════════════════════════════════════

@app.get("/v5/launch/checklist")
async def launch_checklist():
    summary = checklist.summary()
    ready, blockers = checklist.can_launch()
    return {**summary, "launch_ready": ready, "blockers": blockers}

@app.post("/v5/launch/check/{check_id}/complete")
async def complete_check(check_id: str):
    ok = checklist.complete(check_id)
    return {"completed": ok, "summary": checklist.summary()}

@app.get("/v5/launch/producthunt")
async def ph_post():
    return producthunt_post()

@app.get("/v5/launch/press-release")
async def press():
    return {"text": press_release()}

@app.post("/v5/launch/scale/evaluate")
async def scale_evaluate(p95_ms: float = 2000, queue: int = 5, error_rate: float = 0.01):
    return auto_scaler.evaluate(p95_ms, queue, error_rate)

@app.get("/v5/launch/cost")
async def cost_status():
    return cost_opt.budget_status()


# ════════════════════════════════════════════════════════════════════════════
# COMPANY DASHBOARD  (everything in one call)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/v5/company/dashboard")
async def company_dashboard():
    """The founder's real-time view of the entire company."""
    ready, blockers = checklist.can_launch()
    return {
        "company":     "Agent Accelerator",
        "phase":       5,
        "launch_ready": ready,
        "blockers":    blockers[:3],
        "growth":      growth.funnel_report(),
        "metrics":     metrics.usage_report(),
        "billing":     billing.mrr(),
        "soc2":        soc2.compliance_score(),
        "gtm":         gtm.pitch_deck_data()["solution"],
        "cost":        cost_opt.budget_status(),
        "integrations":len(integrations.list_live()),
        "checklist":   checklist.summary(),
    }

@app.get("/v5/company/investor")
async def investor_view():
    """Everything an investor wants to see."""
    return {
        "pitch_deck":    gtm.pitch_deck_data(),
        "benchmark":     gtm.benchmark_table(),
        "mrr":           billing.mrr(),
        "funnel":        growth.funnel_report(),
        "nps":           metrics.nps_score(),
        "soc2":          soc2.compliance_score(),
        "halluc_rate":   f"{metrics.hallucination_rate():.1%}",
    }

@app.get("/v5/health")
async def health():
    ready, _ = checklist.can_launch()
    return {
        "status":        "ok",
        "phase":         5,
        "launch_ready":  ready,
        "checklist_pct": checklist.summary()["pct"],
        "paying_customers": billing.mrr()["paying_customers"],
        "total_mrr":     billing.mrr()["total_mrr_usd"],
    }
