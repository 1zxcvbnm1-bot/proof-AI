"""
╔══════════════════════════════════════════════════════════════════════════╗
║  PHASE 4 SERVER — Complete pilot + market fit system                   ║
║  Onboarding · Metrics · Flywheel · Billing · SOC 2 · GTM               ║
║  Run: uvicorn phase4_server:app --port 8090                             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import json, os, sys, time, uuid

BASE = os.path.dirname(os.path.abspath(__file__))
for sub in ["pilot", "metrics", "feedback", "billing", "gtm"]:
    sys.path.insert(0, os.path.join(BASE, sub))

# Phase 3 agent (if available)
sys.path.insert(0, os.path.join(BASE, "..", "phase3", "core"))
sys.path.insert(0, os.path.join(BASE, "..", "phase3", "api", "v1"))

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from typing import Optional

from onboarding     import PilotOnboardingEngine, PilotTier, SLAConfig
from success_metrics import SuccessMetricsTracker, QueryMetric
from flywheel       import FeedbackFlywheel, CorrectionType
from billing_engine import BillingEngine, BillingPlan
from soc2_gtm       import SOC2Engine, GTMKit


# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Agent Accelerator — Phase 4",
    description="Pilot + market fit: onboarding, metrics, flywheel, billing, SOC 2, GTM",
    version="4.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── System singletons ──────────────────────────────────────────────────────
onboarding = PilotOnboardingEngine()
metrics    = SuccessMetricsTracker()
flywheel   = FeedbackFlywheel()
billing    = BillingEngine()
soc2       = SOC2Engine()
gtm        = GTMKit(metrics, billing, soc2, onboarding)

# ── Auto-map Phase 1-4 work to SOC 2 controls on startup ─────────────────
CONTROLS_MAPPED = soc2.auto_map_phase_work()

# ── Seed 3 fictional pilot tenants ────────────────────────────────────────
def _seed_pilots():
    t1 = onboarding.onboard("TechCorp India", "Priya Sharma",  "priya@techcorp.in",  PilotTier.COMPLIANCE_TEAM)
    t2 = onboarding.onboard("FinanceHub",     "Arjun Mehta",   "arjun@financehub.com",PilotTier.LEGAL_TEAM)
    t3 = onboarding.onboard("DataVault Inc",  "Sneha Reddy",   "sneha@datavault.io", PilotTier.ENGINEERING)
    for t in [t1, t2, t3]:
        billing.assign_plan(t.tenant_id, BillingPlan.STARTER)
        onboarding.seed_corpus(t.tenant_id, [])
    # Simulate usage
    for _ in range(47):
        metrics.record_query(QueryMetric(
            tenant_id=t1.tenant_id, session_id=str(uuid.uuid4()),
            latency_ms=1850, claims_total=3, claims_verified=3,
            confidence_avg=0.84, citations_count=3,
        ))
        billing.meter(t1.tenant_id, queries=1, claims=3)
        onboarding.record_query(t1.tenant_id)
    metrics.record_nps(t1.tenant_id, 9.0, "Finally — cited AI that doesn't make things up")
    onboarding.record_nps(t1.tenant_id, 9.0)
    for _ in range(22):
        metrics.record_query(QueryMetric(
            tenant_id=t2.tenant_id, session_id=str(uuid.uuid4()),
            latency_ms=2100, claims_total=4, claims_verified=3, claims_uncertain=1,
            confidence_avg=0.76, citations_count=2,
        ))
        billing.meter(t2.tenant_id, queries=1, claims=4)
        onboarding.record_query(t2.tenant_id)
    metrics.record_nps(t2.tenant_id, 8.0)
    onboarding.record_nps(t2.tenant_id, 8.0)
    return t1, t2, t3

PILOT_T1, PILOT_T2, PILOT_T3 = _seed_pilots()

# ════════════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ════════════════════════════════════════════════════════════════════════════

class OnboardRequest(BaseModel):
    company_name:  str
    contact_name:  str
    contact_email: str
    tier:          str = "compliance_team"

class CorrectionRequest(BaseModel):
    tenant_id:       str
    session_id:      str
    query:           str
    agent_response:  str
    correct_response:str
    correction_type: str = "factual_error"
    source_url:      str = ""

class NPSRequest(BaseModel):
    tenant_id: str
    score:     float
    comment:   str = ""

class MeterRequest(BaseModel):
    tenant_id: str
    queries:   int = 1
    claims:    int = 0

class ConvertRequest(BaseModel):
    tenant_id: str
    mrr_usd:   float
    plan:      str = "enterprise"


# ════════════════════════════════════════════════════════════════════════════
# ONBOARDING ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

@app.post("/v4/pilots/onboard")
async def onboard_pilot(req: OnboardRequest):
    tier_map = {t.value: t for t in PilotTier}
    tier     = tier_map.get(req.tier, PilotTier.COMPLIANCE_TEAM)
    tenant   = onboarding.onboard(req.company_name, req.contact_name, req.contact_email, tier)
    billing.assign_plan(tenant.tenant_id, BillingPlan.STARTER)
    welcome  = onboarding.welcome_email(tenant.tenant_id)
    return {
        "tenant_id":  tenant.tenant_id,
        "api_key":    tenant.api_key,     # shown once
        "status":     tenant.status.value,
        "welcome_email": welcome,
        "warning":    "Save the API key — it will not be shown again",
    }

@app.get("/v4/pilots/{tenant_id}/dashboard")
async def pilot_dashboard(tenant_id: str):
    return onboarding.pilot_dashboard(tenant_id)

@app.get("/v4/pilots")
async def all_pilots():
    return onboarding.all_pilots_summary()

@app.post("/v4/pilots/{tenant_id}/convert")
async def convert_pilot(tenant_id: str, req: ConvertRequest):
    result = onboarding.convert(tenant_id, req.mrr_usd, req.plan)
    billing.assign_plan(tenant_id, BillingPlan(req.plan.lower()) if req.plan.lower() in BillingPlan._value2member_map_ else BillingPlan.ENTERPRISE)
    return result


# ════════════════════════════════════════════════════════════════════════════
# METRICS ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

@app.post("/v4/metrics/query")
async def record_query_metric(req: MeterRequest):
    metric = QueryMetric(
        tenant_id=req.tenant_id, session_id=str(uuid.uuid4()),
        queries=req.queries, claims_total=req.claims,
        timestamp=time.time(),
    )
    metrics.record_query(metric)
    billing.meter(req.tenant_id, req.queries, req.claims)
    onboarding.record_query(req.tenant_id)
    return {"recorded": True}

@app.post("/v4/metrics/nps")
async def record_nps(req: NPSRequest):
    entry = metrics.record_nps(req.tenant_id, req.score, req.comment)
    onboarding.record_nps(req.tenant_id, req.score, req.comment)
    return {"category": entry.category, "nps_score": metrics.nps_score(req.tenant_id)}

@app.get("/v4/metrics/usage")
async def usage_report(tenant_id: Optional[str] = None):
    return metrics.usage_report(tenant_id)

@app.get("/v4/metrics/investor")
async def investor_metrics():
    return metrics.investor_metrics()

@app.get("/v4/metrics/sla")
async def sla_compliance(tenant_id: Optional[str] = None):
    return metrics.sla_compliance(tenant_id)


# ════════════════════════════════════════════════════════════════════════════
# FEEDBACK FLYWHEEL ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

@app.post("/v4/feedback/correction")
async def submit_correction(req: CorrectionRequest):
    type_map   = {t.value: t for t in CorrectionType}
    c_type     = type_map.get(req.correction_type, CorrectionType.FACTUAL_ERROR)
    correction = flywheel.submit(
        req.tenant_id, req.session_id, req.query,
        req.agent_response, req.correct_response, c_type, req.source_url,
    )
    return {
        "correction_id": correction.correction_id,
        "priority":      correction.priority.value,
        "validated":     correction.validated,
        "rlhf_pair_created": correction.incorporated,
    }

@app.get("/v4/feedback/stats")
async def flywheel_stats():
    return flywheel.flywheel_stats()

@app.get("/v4/feedback/dataset")
async def export_rlhf():
    """Download RLHF training pairs as JSONL."""
    return {"jsonl": flywheel.export_rlhf_dataset(), "pairs": len(flywheel._rlhf_pairs)}

@app.get("/v4/feedback/corpus-updates")
async def pending_corpus_updates():
    return {"updates": flywheel.pending_corpus_updates()}


# ════════════════════════════════════════════════════════════════════════════
# BILLING ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/v4/billing/mrr")
async def mrr():
    return billing.mrr()

@app.post("/v4/billing/invoice/{tenant_id}")
async def generate_invoice(tenant_id: str, company_name: str = ""):
    inv = billing.generate_invoice(tenant_id, company_name)
    return {
        "invoice_id": inv.invoice_id,
        "total_usd":  inv.total_usd,
        "text":       billing.invoice_text(inv),
    }


# ════════════════════════════════════════════════════════════════════════════
# SOC 2 + GTM ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/v4/compliance/soc2")
async def soc2_status():
    return soc2.compliance_score()

@app.get("/v4/compliance/evidence")
async def soc2_evidence():
    return {"controls": soc2.evidence_package(), "count": len(soc2.evidence_package())}

@app.get("/v4/gtm/pitch-deck")
async def pitch_deck():
    return gtm.pitch_deck_data()

@app.get("/v4/gtm/benchmark")
async def benchmark():
    return {"table": gtm.benchmark_table()}

@app.get("/v4/gtm/security-review")
async def security_review():
    return gtm.enterprise_security_review()

@app.get("/v4/gtm/conversion-email/{tenant_id}")
async def conversion_email(tenant_id: str):
    return gtm.pilot_to_paid_email(tenant_id)


# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD — single endpoint that surfaces everything
# ════════════════════════════════════════════════════════════════════════════

@app.get("/v4/dashboard")
async def full_dashboard():
    """Everything in one call — the founder's real-time view."""
    return {
        "pilots":      onboarding.all_pilots_summary(),
        "metrics":     metrics.usage_report(),
        "nps":         metrics.nps_score(),
        "mrr":         billing.mrr(),
        "flywheel":    flywheel.flywheel_stats(),
        "soc2":        soc2.compliance_score(),
        "investor":    metrics.investor_metrics(),
        "benchmark":   gtm.benchmark_table(),
    }

@app.get("/v4/health")
async def health():
    return {
        "status":           "ok",
        "phase":            4,
        "controls_mapped":  CONTROLS_MAPPED,
        "pilots":           onboarding.all_pilots_summary()["total"],
        "mrr_usd":          billing.mrr()["total_mrr_usd"],
    }
