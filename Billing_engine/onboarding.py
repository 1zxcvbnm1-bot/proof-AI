"""
╔══════════════════════════════════════════════════════════════════════════╗
║  PILOT ONBOARDING ENGINE — Phase 4                                      ║
║  Tenant setup · API keys · Corpus seed · SLA config · Welcome flow      ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PilotTier(str, Enum):
    COMPLIANCE_TEAM = "compliance_team"
    LEGAL_TEAM      = "legal_team"
    ENGINEERING     = "engineering"
    EXECUTIVE       = "executive"


class PilotStatus(str, Enum):
    INVITED     = "invited"
    ONBOARDING  = "onboarding"
    ACTIVE      = "active"
    CHURNED     = "churned"
    CONVERTED   = "converted"


@dataclass
class SLAConfig:
    uptime_pct:         float = 99.5
    response_p95_ms:    int   = 8000
    hallucination_max:  float = 0.05     # max 5% hallucination rate
    support_hours:      str   = "business"
    erasure_sla_hrs:    int   = 72
    data_residency:     str   = "IN"


@dataclass
class PilotTenant:
    tenant_id:       str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    company_name:    str = ""
    contact_name:    str = ""
    contact_email:   str = ""
    tier:            PilotTier = PilotTier.COMPLIANCE_TEAM
    status:          PilotStatus = PilotStatus.INVITED
    api_key:         str = ""
    api_key_hash:    str = ""
    created_at:      float = field(default_factory=time.time)
    activated_at:    Optional[float] = None
    converted_at:    Optional[float] = None
    sla:             SLAConfig = field(default_factory=SLAConfig)
    corpus_seeded:   bool = False
    queries_total:   int  = 0
    queries_today:   int  = 0
    nps_score:       Optional[float] = None
    mrr_usd:         float = 0.0
    notes:           list[str] = field(default_factory=list)


@dataclass
class OnboardingStep:
    step_id:     str
    name:        str
    description: str
    completed:   bool = False
    completed_at: Optional[float] = None


class PilotOnboardingEngine:
    """
    Manages the full pilot customer lifecycle.

    Steps for each pilot:
      1. Create tenant record + provision API key
      2. Seed knowledge corpus with company-specific data
      3. Configure SLA thresholds
      4. Send welcome email with credentials + docs
      5. Schedule weekly check-in cadence
      6. Track activation (first real query within 7 days)
      7. Trigger conversion flow when NPS ≥ 8

    Production: persist to Postgres tenants table.
    """

    ONBOARDING_STEPS = [
        ("S01", "Tenant created",       "Account and API key provisioned"),
        ("S02", "Corpus seeded",        "Company-specific knowledge loaded"),
        ("S03", "SLA configured",       "Thresholds and residency set"),
        ("S04", "Welcome sent",         "Credentials and docs delivered"),
        ("S05", "First query",          "Pilot made their first real API call"),
        ("S06", "Week-1 check-in",      "Usage review and feedback call"),
        ("S07", "NPS collected",        "Net Promoter Score recorded"),
        ("S08", "Conversion decision",  "Pilot → paid evaluation"),
    ]

    def __init__(self):
        self._tenants: dict[str, PilotTenant] = {}
        self._progress: dict[str, list[OnboardingStep]] = {}

    def onboard(
        self,
        company_name:  str,
        contact_name:  str,
        contact_email: str,
        tier:          PilotTier = PilotTier.COMPLIANCE_TEAM,
        sla_override:  Optional[SLAConfig] = None,
    ) -> PilotTenant:
        """Provision a new pilot tenant end-to-end."""
        raw_key    = f"aa-pilot-{secrets.token_urlsafe(32)}"
        key_hash   = hashlib.sha256(raw_key.encode()).hexdigest()

        tenant = PilotTenant(
            company_name=  company_name,
            contact_name=  contact_name,
            contact_email= contact_email,
            tier=          tier,
            status=        PilotStatus.ONBOARDING,
            api_key=       raw_key,      # shown ONCE — never store in logs
            api_key_hash=  key_hash,
            sla=           sla_override or SLAConfig(),
        )

        self._tenants[tenant.tenant_id] = tenant
        self._progress[tenant.tenant_id] = [
            OnboardingStep(s[0], s[1], s[2])
            for s in self.ONBOARDING_STEPS
        ]
        self._complete_step(tenant.tenant_id, "S01")
        return tenant

    def seed_corpus(self, tenant_id: str, facts: list[dict]) -> bool:
        """Mark corpus as seeded after loading company-specific facts."""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False
        tenant.corpus_seeded = True
        self._complete_step(tenant_id, "S02")
        return True

    def activate(self, tenant_id: str) -> None:
        """Called on first real API query from pilot."""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return
        if not tenant.activated_at:
            tenant.activated_at = time.time()
            tenant.status       = PilotStatus.ACTIVE
            self._complete_step(tenant_id, "S05")

    def record_nps(self, tenant_id: str, score: float, comment: str = "") -> None:
        """Record NPS score (0–10). Triggers conversion flow if ≥ 8."""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return
        tenant.nps_score = score
        self._complete_step(tenant_id, "S07")
        if comment:
            tenant.notes.append(f"NPS {score}: {comment}")
        if score >= 8:
            self._trigger_conversion(tenant_id)

    def record_query(self, tenant_id: str) -> None:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return
        tenant.queries_total += 1
        tenant.queries_today += 1
        if tenant.queries_total == 1:
            self.activate(tenant_id)

    def convert(self, tenant_id: str, mrr_usd: float, plan: str = "enterprise") -> dict:
        """Convert pilot to paid customer."""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return {"error": "Tenant not found"}
        tenant.status       = PilotStatus.CONVERTED
        tenant.converted_at = time.time()
        tenant.mrr_usd      = mrr_usd
        self._complete_step(tenant_id, "S08")
        days_to_convert = (tenant.converted_at - tenant.created_at) / 86400
        return {
            "tenant_id":       tenant_id,
            "company":         tenant.company_name,
            "mrr_usd":         mrr_usd,
            "plan":            plan,
            "days_to_convert": round(days_to_convert, 1),
            "total_queries":   tenant.queries_total,
            "nps":             tenant.nps_score,
        }

    def welcome_email(self, tenant_id: str) -> dict:
        """Generate welcome email content (send via SendGrid/SES in production)."""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return {}
        self._complete_step(tenant_id, "S04")
        return {
            "to":      tenant.contact_email,
            "subject": f"Your Agent Accelerator pilot is ready — {tenant.company_name}",
            "body": f"""Hi {tenant.contact_name},

Your pilot account is provisioned. Here's everything you need:

API Key:     {tenant.api_key}
Tenant ID:   {tenant.tenant_id}
Docs:        https://your-domain.ai/docs
Stream URL:  https://your-domain.ai/v1/agent/stream

Quick start:
  curl -X POST https://your-domain.ai/v1/agent/stream \\
    -H "Authorization: Bearer {tenant.api_key}" \\
    -H "Content-Type: application/json" \\
    -d '{{"query": "What is your hallucination rate vs GPT-5?"}}'

Your SLA:
  - Uptime guarantee:    {tenant.sla.uptime_pct}%
  - Response time p95:   {tenant.sla.response_p95_ms}ms
  - Max hallucination:   {tenant.sla.hallucination_max:.0%}
  - Data residency:      {tenant.sla.data_residency}

I'll check in with you in 7 days to review your first week.

Best,
Vimal Kumar
Founder, Agent Accelerator""",
            "api_key_shown_once": True,
        }

    def pilot_dashboard(self, tenant_id: str) -> dict:
        tenant   = self._tenants.get(tenant_id)
        progress = self._progress.get(tenant_id, [])
        if not tenant:
            return {}
        completed = sum(1 for s in progress if s.completed)
        return {
            "tenant_id":     tenant.tenant_id,
            "company":       tenant.company_name,
            "status":        tenant.status.value,
            "progress":      f"{completed}/{len(progress)} steps",
            "activated":     tenant.activated_at is not None,
            "queries_total": tenant.queries_total,
            "nps":           tenant.nps_score,
            "mrr_usd":       tenant.mrr_usd,
            "corpus_seeded": tenant.corpus_seeded,
            "steps": [
                {"id": s.step_id, "name": s.name, "done": s.completed}
                for s in progress
            ],
        }

    def all_pilots_summary(self) -> dict:
        tenants = list(self._tenants.values())
        return {
            "total":      len(tenants),
            "active":     sum(1 for t in tenants if t.status == PilotStatus.ACTIVE),
            "converted":  sum(1 for t in tenants if t.status == PilotStatus.CONVERTED),
            "total_mrr":  sum(t.mrr_usd for t in tenants),
            "avg_nps":    round(sum(t.nps_score for t in tenants if t.nps_score is not None) /
                                max(1, sum(1 for t in tenants if t.nps_score is not None)), 1),
            "pilots": [
                {
                    "company":  t.company_name,
                    "status":   t.status.value,
                    "queries":  t.queries_total,
                    "nps":      t.nps_score,
                    "mrr":      t.mrr_usd,
                }
                for t in tenants
            ],
        }

    def _complete_step(self, tenant_id: str, step_id: str) -> None:
        for step in self._progress.get(tenant_id, []):
            if step.step_id == step_id and not step.completed:
                step.completed    = True
                step.completed_at = time.time()

    def _trigger_conversion(self, tenant_id: str) -> None:
        tenant = self._tenants.get(tenant_id)
        if tenant:
            tenant.notes.append("NPS ≥ 8 — conversion flow triggered")
