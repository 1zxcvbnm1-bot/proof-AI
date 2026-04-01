"""
╔══════════════════════════════════════════════════════════════════════════╗
║  GROWTH ANALYTICS ENGINE — Phase 5                                      ║
║  Funnel · Lead scoring · Cohort · Churn signals · GTM scale             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import time, uuid, hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FunnelStage(str, Enum):
    VISITOR       = "visitor"
    SIGNUP        = "signup"
    API_CALL      = "api_call"           # made first API call
    ACTIVATED     = "activated"          # 10+ queries in first week
    PAYING        = "paying"             # entered credit card
    CHAMPION      = "champion"           # NPS ≥ 9 + referral


class ICPSignal(str, Enum):
    COMPLIANCE_TEAM  = "compliance_team"
    LEGAL_TEAM       = "legal_team"
    BIG_TECH         = "big_tech"
    FINTECH          = "fintech"
    HEALTHTECH       = "healthtech"
    DEVELOPER_TOOLS  = "developer_tools"


@dataclass
class LeadEvent:
    lead_id:     str
    event_type:  str      # page_view | signup | api_call | query | upgrade | churn
    timestamp:   float = field(default_factory=time.time)
    metadata:    dict  = field(default_factory=dict)


@dataclass
class Lead:
    lead_id:       str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    email_hash:    str = ""             # SHA-256 of email — never raw
    company:       str = ""
    stage:         FunnelStage = FunnelStage.VISITOR
    icp_signals:   list[ICPSignal] = field(default_factory=list)
    score:         int = 0              # 0–100
    events:        list[LeadEvent] = field(default_factory=list)
    created_at:    float = field(default_factory=time.time)
    converted_at:  Optional[float] = None
    churned_at:    Optional[float] = None
    mrr_usd:       float = 0.0
    referrer:      str = ""


class GrowthAnalyticsEngine:
    """
    Full-funnel growth analytics.

    Tracks:
      - Visitor → Signup → Activation → Paying → Champion funnel
      - Lead scoring by ICP signals + behaviour
      - Weekly cohort retention
      - Churn risk signals
      - Referral tracking

    Production: push events to Mixpanel/Amplitude + Postgres.
    """

    # ICP scoring weights
    ICP_WEIGHTS = {
        ICPSignal.BIG_TECH:         30,
        ICPSignal.COMPLIANCE_TEAM:  25,
        ICPSignal.LEGAL_TEAM:       20,
        ICPSignal.FINTECH:          20,
        ICPSignal.HEALTHTECH:       15,
        ICPSignal.DEVELOPER_TOOLS:  10,
    }

    # Behaviour scoring
    BEHAVIOUR_SCORES = {
        "api_call":        +5,
        "query_10":        +15,    # reached 10 queries
        "query_100":       +20,    # reached 100 queries
        "correction_sent": +10,    # gave feedback
        "docs_visit":      +3,
        "pricing_visit":   +8,
        "upgrade_page":    +12,
        "no_activity_7d":  -10,    # churn signal
    }

    def __init__(self):
        self._leads:   dict[str, Lead] = {}
        self._cohorts: dict[str, list[str]] = {}    # week_key → [lead_ids]

    # ── Lead lifecycle ────────────────────────────────────────────────────

    def track_visitor(self, referrer: str = "", company: str = "") -> Lead:
        lead = Lead(referrer=referrer, company=company)
        self._leads[lead.lead_id] = lead
        week = self._week_key(lead.created_at)
        self._cohorts.setdefault(week, []).append(lead.lead_id)
        self._event(lead, "page_view")
        return lead

    def track_signup(self, lead_id: str, email: str, company: str = "",
                     icp_signals: list[ICPSignal] = None) -> None:
        lead = self._leads.get(lead_id)
        if not lead:
            return
        lead.email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
        lead.company    = company or lead.company
        lead.stage      = FunnelStage.SIGNUP
        if icp_signals:
            lead.icp_signals = icp_signals
        self._rescore(lead)
        self._event(lead, "signup", {"company": company})

    def track_api_call(self, lead_id: str, query_count: int = 1) -> None:
        lead = self._leads.get(lead_id)
        if not lead:
            return
        if lead.stage == FunnelStage.SIGNUP:
            lead.stage = FunnelStage.API_CALL
        self._event(lead, "api_call", {"query_count": query_count})
        total = sum(e.metadata.get("query_count", 0) for e in lead.events
                    if e.event_type == "api_call")
        if total >= 10 and lead.stage == FunnelStage.API_CALL:
            lead.stage = FunnelStage.ACTIVATED
            self._event(lead, "query_10")
        if total >= 100:
            self._event(lead, "query_100")
        self._rescore(lead)

    def track_payment(self, lead_id: str, mrr_usd: float) -> None:
        lead = self._leads.get(lead_id)
        if not lead:
            return
        lead.stage        = FunnelStage.PAYING
        lead.mrr_usd      = mrr_usd
        lead.converted_at = time.time()
        self._event(lead, "payment", {"mrr_usd": mrr_usd})
        self._rescore(lead)

    def track_champion(self, lead_id: str) -> None:
        lead = self._leads.get(lead_id)
        if not lead:
            return
        lead.stage = FunnelStage.CHAMPION
        self._event(lead, "champion")

    # ── Analytics ─────────────────────────────────────────────────────────

    def funnel_report(self) -> dict:
        stages = {s: 0 for s in FunnelStage}
        for lead in self._leads.values():
            stages[lead.stage] += 1
        total = max(1, stages[FunnelStage.VISITOR])
        return {
            "total_leads": len(self._leads),
            "stages": {
                stage.value: {
                    "count":       count,
                    "conv_rate":   f"{count/total:.1%}",
                }
                for stage, count in stages.items()
            },
            "paying_count":    stages[FunnelStage.PAYING],
            "total_mrr":       sum(l.mrr_usd for l in self._leads.values()),
            "activation_rate": f"{stages[FunnelStage.ACTIVATED]/max(1,stages[FunnelStage.SIGNUP]):.1%}",
            "paid_conv_rate":  f"{stages[FunnelStage.PAYING]/max(1,stages[FunnelStage.ACTIVATED]):.1%}",
        }

    def top_leads(self, n: int = 10) -> list[dict]:
        """Highest-scoring unpaid leads — outreach queue."""
        unpaid = [l for l in self._leads.values()
                  if l.stage not in (FunnelStage.PAYING, FunnelStage.CHAMPION)]
        unpaid.sort(key=lambda l: l.score, reverse=True)
        return [
            {
                "lead_id":  l.lead_id,
                "company":  l.company,
                "stage":    l.stage.value,
                "score":    l.score,
                "icp":      [s.value for s in l.icp_signals],
                "events":   len(l.events),
            }
            for l in unpaid[:n]
        ]

    def churn_risk(self) -> list[dict]:
        """Paying customers with low engagement — at risk of churning."""
        at_risk = []
        now = time.time()
        for lead in self._leads.values():
            if lead.stage != FunnelStage.PAYING:
                continue
            last_event = max((e.timestamp for e in lead.events), default=lead.created_at)
            days_silent = (now - last_event) / 86400
            if days_silent > 14:
                at_risk.append({
                    "lead_id":     lead.lead_id,
                    "company":     lead.company,
                    "mrr_usd":     lead.mrr_usd,
                    "days_silent": round(days_silent, 1),
                    "risk_level":  "high" if days_silent > 21 else "medium",
                })
        at_risk.sort(key=lambda x: x["mrr_usd"], reverse=True)
        return at_risk

    def cohort_retention(self) -> dict:
        """Week-0 to Week-4 retention by signup cohort."""
        now = time.time()
        result = {}
        for week, lead_ids in list(self._cohorts.items())[-8:]:
            cohort_leads = [self._leads[lid] for lid in lead_ids if lid in self._leads]
            if not cohort_leads:
                continue
            week_ts = self._week_ts(week)
            retained = {
                "week_0": len(cohort_leads),
                "week_1": sum(1 for l in cohort_leads if self._active_in_window(l, week_ts + 86400*7,  week_ts + 86400*14)),
                "week_2": sum(1 for l in cohort_leads if self._active_in_window(l, week_ts + 86400*14, week_ts + 86400*21)),
                "week_4": sum(1 for l in cohort_leads if self._active_in_window(l, week_ts + 86400*28, week_ts + 86400*35)),
            }
            n = max(1, retained["week_0"])
            result[week] = {k: f"{v}/{n} ({v/n:.0%})" for k, v in retained.items()}
        return result

    def _rescore(self, lead: Lead) -> None:
        score = sum(self.ICP_WEIGHTS.get(s, 0) for s in lead.icp_signals)
        for e in lead.events:
            score += self.BEHAVIOUR_SCORES.get(e.event_type, 0)
        lead.score = max(0, min(100, score))

    def _event(self, lead: Lead, event_type: str, metadata: dict = None) -> None:
        lead.events.append(LeadEvent(lead_id=lead.lead_id, event_type=event_type,
                                     metadata=metadata or {}))

    def _week_key(self, ts: float) -> str:
        import datetime
        d = datetime.datetime.fromtimestamp(ts)
        return f"{d.year}-W{d.isocalendar()[1]:02d}"

    def _week_ts(self, week_key: str) -> float:
        import datetime
        year, week = int(week_key.split("-W")[0]), int(week_key.split("-W")[1])
        d = datetime.datetime.fromisocalendar(year, week, 1)
        return d.timestamp()

    def _active_in_window(self, lead: Lead, start: float, end: float) -> bool:
        return any(start <= e.timestamp < end for e in lead.events)
