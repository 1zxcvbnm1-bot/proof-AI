"""
╔══════════════════════════════════════════════════════════════════════════╗
║  BILLING ENGINE — Phase 4                                               ║
║  Usage metering · Stripe webhooks · Invoice generation · Enterprise    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class BillingPlan(str, Enum):
    FREE       = "free"
    STARTER    = "starter"
    PRO        = "pro"
    ENTERPRISE = "enterprise"


# Pricing table — production source of truth
PRICING = {
    BillingPlan.FREE: {
        "name":           "Free",
        "monthly_usd":    0,
        "queries_per_mo": 50,
        "claims_per_mo":  500,
        "overage_per_k":  0,
        "features":       ["RAG queries", "Basic fact-check", "Community support"],
    },
    BillingPlan.STARTER: {
        "name":           "Starter",
        "monthly_usd":    299,
        "queries_per_mo": 2000,
        "claims_per_mo":  20_000,
        "overage_per_k":  8.00,          # $8 per 1000 additional claims
        "features":       ["Full pipeline", "Citation badges", "Email support", "SOC 2 summary"],
    },
    BillingPlan.PRO: {
        "name":           "Pro",
        "monthly_usd":    999,
        "queries_per_mo": 10_000,
        "claims_per_mo":  100_000,
        "overage_per_k":  6.00,
        "features":       ["All Starter", "Custom corpus", "Slack support", "SLA 99.5%", "Audit export"],
    },
    BillingPlan.ENTERPRISE: {
        "name":           "Enterprise",
        "monthly_usd":    2999,
        "queries_per_mo": -1,            # unlimited
        "claims_per_mo":  -1,
        "overage_per_k":  0,
        "features":       ["Unlimited", "Dedicated infra", "Data residency", "SOC 2 Type II", "24/7 SLA", "MSA", "Custom SLA"],
    },
}


@dataclass
class UsageRecord:
    tenant_id:   str
    period_start:float
    period_end:  float
    queries:     int   = 0
    claims:      int   = 0
    tokens_used: int   = 0
    cost_usd:    float = 0.0


@dataclass
class Invoice:
    invoice_id:   str = field(default_factory=lambda: f"INV-{str(uuid.uuid4())[:8].upper()}")
    tenant_id:    str = ""
    company_name: str = ""
    period_start: float = 0.0
    period_end:   float = 0.0
    plan:         BillingPlan = BillingPlan.STARTER
    base_usd:     float = 0.0
    overage_usd:  float = 0.0
    total_usd:    float = 0.0
    status:       str = "draft"      # draft | sent | paid | overdue
    due_date:     float = 0.0
    line_items:   list[dict] = field(default_factory=list)
    created_at:   float = field(default_factory=time.time)


class BillingEngine:
    """
    Usage-based billing with Stripe integration.

    Pricing:
      Free:       $0 / mo    — 50 queries, 500 claims
      Starter:    $299/mo    — 2K queries, 20K claims + $8/1K overage
      Pro:        $999/mo    — 10K queries, 100K claims + $6/1K overage
      Enterprise: $2,999/mo  — unlimited + MSA + SLA

    Metering: every query to /v1/agent/stream increments the tenant's
    monthly claim counter. Overage billed at end of month.

    Production: use Stripe Metered Billing API.
    """

    def __init__(self):
        self._usage:    dict[str, UsageRecord]  = {}
        self._invoices: list[Invoice]            = []
        self._plans:    dict[str, BillingPlan]   = {}

    def assign_plan(self, tenant_id: str, plan: BillingPlan) -> None:
        self._plans[tenant_id] = plan
        if tenant_id not in self._usage:
            self._reset_period(tenant_id)

    def meter(self, tenant_id: str, queries: int = 1, claims: int = 0, tokens: int = 0) -> dict:
        """Increment usage counters. Called after every agent run."""
        if tenant_id not in self._usage:
            self._reset_period(tenant_id)

        usage = self._usage[tenant_id]
        usage.queries     += queries
        usage.claims      += claims
        usage.tokens_used += tokens
        usage.cost_usd     = self._compute_cost(tenant_id, usage.claims)

        # Check limit breach
        plan     = self._plans.get(tenant_id, BillingPlan.FREE)
        limits   = PRICING[plan]
        over_q   = limits["queries_per_mo"] != -1 and usage.queries > limits["queries_per_mo"]
        over_c   = limits["claims_per_mo"]  != -1 and usage.claims  > limits["claims_per_mo"]

        return {
            "tenant_id":       tenant_id,
            "plan":            plan.value,
            "queries_used":    usage.queries,
            "claims_used":     usage.claims,
            "cost_usd":        round(usage.cost_usd, 4),
            "over_query_limit":over_q,
            "over_claim_limit":over_c,
            "action":          "upgrade_required" if (over_q or over_c) and plan == BillingPlan.FREE else "ok",
        }

    def generate_invoice(self, tenant_id: str, company_name: str = "") -> Invoice:
        """Generate end-of-period invoice for a tenant."""
        usage  = self._usage.get(tenant_id)
        plan   = self._plans.get(tenant_id, BillingPlan.FREE)
        p      = PRICING[plan]

        if not usage:
            usage = UsageRecord(
                tenant_id=tenant_id,
                period_start=time.time() - 30*86400,
                period_end=time.time(),
            )

        base_usd    = p["monthly_usd"]
        overage_usd = 0.0
        line_items  = [{"description": f"{p['name']} plan (monthly)", "amount_usd": base_usd}]

        if p["claims_per_mo"] != -1 and usage.claims > p["claims_per_mo"]:
            overage_claims = usage.claims - p["claims_per_mo"]
            overage_k      = overage_claims / 1000
            overage_usd    = round(overage_k * p["overage_per_k"], 2)
            line_items.append({
                "description": f"Claim overage: {overage_claims:,} claims × ${p['overage_per_k']}/1K",
                "amount_usd":  overage_usd,
            })

        invoice = Invoice(
            tenant_id=   tenant_id,
            company_name=company_name,
            period_start=usage.period_start,
            period_end=  usage.period_end,
            plan=        plan,
            base_usd=    base_usd,
            overage_usd= overage_usd,
            total_usd=   base_usd + overage_usd,
            status=      "draft",
            due_date=    time.time() + 30 * 86400,
            line_items=  line_items,
        )
        self._invoices.append(invoice)
        return invoice

    def invoice_text(self, invoice: Invoice) -> str:
        """Human-readable invoice."""
        from_dt = time.strftime("%d %b %Y", time.localtime(invoice.period_start))
        to_dt   = time.strftime("%d %b %Y", time.localtime(invoice.period_end))
        due_dt  = time.strftime("%d %b %Y", time.localtime(invoice.due_date))
        lines   = [
            f"INVOICE {invoice.invoice_id}",
            f"Company:  {invoice.company_name or invoice.tenant_id}",
            f"Period:   {from_dt} – {to_dt}",
            f"Due:      {due_dt}",
            "─" * 50,
        ]
        for item in invoice.line_items:
            lines.append(f"  {item['description']:<40} ${item['amount_usd']:>8.2f}")
        lines += ["─" * 50, f"  {'TOTAL':<40} ${invoice.total_usd:>8.2f}", ""]
        lines.append("Pay via Stripe: https://pay.your-domain.ai/" + invoice.invoice_id)
        return "\n".join(lines)

    def mrr(self) -> dict:
        """Monthly Recurring Revenue — the investor number."""
        total_mrr = sum(
            PRICING[p]["monthly_usd"]
            for p in self._plans.values()
            if p != BillingPlan.FREE
        )
        by_plan = {}
        for p in BillingPlan:
            count = sum(1 for plan in self._plans.values() if plan == p)
            if count:
                by_plan[p.value] = {
                    "customers": count,
                    "mrr_usd":   PRICING[p]["monthly_usd"] * count,
                }
        return {
            "total_mrr_usd": total_mrr,
            "total_arr_usd": total_mrr * 12,
            "paying_customers": sum(1 for p in self._plans.values() if p != BillingPlan.FREE),
            "by_plan": by_plan,
        }

    def _compute_cost(self, tenant_id: str, claims: int) -> float:
        plan = self._plans.get(tenant_id, BillingPlan.FREE)
        p    = PRICING[plan]
        base = p["monthly_usd"]
        if p["claims_per_mo"] == -1 or claims <= p["claims_per_mo"]:
            return float(base)
        overage = ((claims - p["claims_per_mo"]) / 1000) * p["overage_per_k"]
        return base + overage

    def _reset_period(self, tenant_id: str) -> None:
        now = time.time()
        self._usage[tenant_id] = UsageRecord(
            tenant_id=   tenant_id,
            period_start=now,
            period_end=  now + 30 * 86400,
        )
