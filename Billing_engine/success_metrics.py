"""
╔══════════════════════════════════════════════════════════════════════════╗
║  SUCCESS METRICS TRACKER — Phase 4                                      ║
║  Hallucination rate · NPS · Trust score · Usage · Cost · SLA tracking  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class QueryMetric:
    tenant_id:          str
    session_id:         str
    timestamp:          float = field(default_factory=time.time)
    latency_ms:         float = 0.0
    claims_total:       int   = 0
    claims_verified:    int   = 0
    claims_blocked:     int   = 0
    claims_conflict:    int   = 0
    halluc_detected:    bool  = False
    confidence_avg:     float = 0.0
    citations_count:    int   = 0
    tool_calls:         int   = 0
    replan_count:       int   = 0
    pipeline:           str   = "full"
    cost_usd:           float = 0.0


@dataclass
class NPSEntry:
    tenant_id:   str
    score:       float          # 0–10
    category:    str            # promoter(9-10) | passive(7-8) | detractor(0-6)
    comment:     str = ""
    timestamp:   float = field(default_factory=time.time)


@dataclass
class SLABreach:
    tenant_id:   str
    metric:      str            # latency | hallucination | uptime
    actual:      float
    threshold:   float
    timestamp:   float = field(default_factory=time.time)
    resolved:    bool  = False


# ════════════════════════════════════════════════════════════════════════════
# METRICS TRACKER
# ════════════════════════════════════════════════════════════════════════════

class SuccessMetricsTracker:
    """
    Central metrics store for all pilot tenants.
    Powers: health dashboard · SLA monitoring · investor metrics · churn signals.
    """

    # Compute cost per query (approximate LLM call cost)
    COST_PER_QUERY_USD = 0.008

    def __init__(self):
        self._queries:  list[QueryMetric]   = []
        self._nps:      list[NPSEntry]      = []
        self._breaches: list[SLABreach]     = []
        self._uptime:   dict[str, float]    = defaultdict(lambda: 100.0)

    # ── Record ────────────────────────────────────────────────────────────

    def record_query(self, metric: QueryMetric) -> None:
        metric.cost_usd = self.COST_PER_QUERY_USD * max(1, metric.claims_total)
        self._queries.append(metric)
        self._check_sla(metric)

    def record_nps(self, tenant_id: str, score: float, comment: str = "") -> NPSEntry:
        category = "promoter" if score >= 9 else "passive" if score >= 7 else "detractor"
        entry    = NPSEntry(tenant_id=tenant_id, score=score, category=category, comment=comment)
        self._nps.append(entry)
        return entry

    # ── SLA ───────────────────────────────────────────────────────────────

    def _check_sla(self, metric: QueryMetric) -> None:
        if metric.latency_ms > 8000:
            self._breaches.append(SLABreach(
                tenant_id=metric.tenant_id,
                metric="latency",
                actual=metric.latency_ms,
                threshold=8000,
            ))

        total = max(1, metric.claims_total)
        halluc_rate = (metric.claims_blocked + metric.claims_conflict) / total
        if halluc_rate > 0.05:
            self._breaches.append(SLABreach(
                tenant_id=metric.tenant_id,
                metric="hallucination_rate",
                actual=halluc_rate,
                threshold=0.05,
            ))

    def sla_compliance(self, tenant_id: Optional[str] = None) -> dict:
        breaches = self._breaches
        if tenant_id:
            breaches = [b for b in breaches if b.tenant_id == tenant_id]
        total_queries = len([q for q in self._queries
                            if not tenant_id or q.tenant_id == tenant_id])
        return {
            "total_queries":    total_queries,
            "total_breaches":   len(breaches),
            "breach_rate":      f"{len(breaches)/max(1,total_queries):.1%}",
            "by_metric":        self._count_by(breaches, lambda b: b.metric),
        }

    # ── NPS ───────────────────────────────────────────────────────────────

    def nps_score(self, tenant_id: Optional[str] = None) -> dict:
        entries = [e for e in self._nps if not tenant_id or e.tenant_id == tenant_id]
        if not entries:
            return {"nps": None, "responses": 0}
        promoters   = sum(1 for e in entries if e.category == "promoter")
        detractors  = sum(1 for e in entries if e.category == "detractor")
        n           = len(entries)
        nps         = round((promoters - detractors) / n * 100, 1)
        return {
            "nps":          nps,
            "responses":    n,
            "promoters":    promoters,
            "passives":     sum(1 for e in entries if e.category == "passive"),
            "detractors":   detractors,
            "avg_score":    round(sum(e.score for e in entries) / n, 1),
        }

    # ── Hallucination rate ────────────────────────────────────────────────

    def hallucination_rate(self, tenant_id: Optional[str] = None) -> float:
        queries = [q for q in self._queries if not tenant_id or q.tenant_id == tenant_id]
        if not queries:
            return 0.0
        total_claims   = sum(q.claims_total for q in queries)
        blocked_claims = sum(q.claims_blocked + q.claims_conflict for q in queries)
        return blocked_claims / max(1, total_claims)

    def trust_score(self, tenant_id: Optional[str] = None) -> float:
        queries = [q for q in self._queries if not tenant_id or q.tenant_id == tenant_id]
        if not queries:
            return 0.0
        return sum(q.confidence_avg for q in queries) / len(queries)

    # ── Usage analytics ───────────────────────────────────────────────────

    def usage_report(self, tenant_id: Optional[str] = None) -> dict:
        queries = [q for q in self._queries if not tenant_id or q.tenant_id == tenant_id]
        if not queries:
            return {"queries": 0}

        latencies = [q.latency_ms for q in queries if q.latency_ms > 0]
        latencies.sort()

        return {
            "total_queries":     len(queries),
            "total_claims":      sum(q.claims_total for q in queries),
            "verified_claims":   sum(q.claims_verified for q in queries),
            "blocked_claims":    sum(q.claims_blocked for q in queries),
            "hallucination_rate":f"{self.hallucination_rate(tenant_id):.1%}",
            "trust_score":       f"{self.trust_score(tenant_id):.2f}",
            "latency_p50_ms":    round(latencies[len(latencies)//2]) if latencies else 0,
            "latency_p95_ms":    round(latencies[int(len(latencies)*0.95)]) if len(latencies)>1 else 0,
            "total_cost_usd":    round(sum(q.cost_usd for q in queries), 4),
            "avg_cost_per_query":round(sum(q.cost_usd for q in queries)/len(queries), 6),
            "citations_total":   sum(q.citations_count for q in queries),
            "replan_total":      sum(q.replan_count for q in queries),
        }

    # ── Investor metrics ──────────────────────────────────────────────────

    def investor_metrics(self) -> dict:
        """The numbers that go in the pitch deck."""
        nps_data = self.nps_score()
        return {
            "hallucination_rate_vs_gpt5": {
                "ours":   f"{self.hallucination_rate():.1%}",
                "gpt5":   "31.2%",
                "claude": "22.8%",
                "gemini": "28.4%",
            },
            "trust_score":          f"{self.trust_score():.2f}",
            "nps":                  nps_data.get("nps", "N/A"),
            "total_queries":        len(self._queries),
            "total_claims_verified":sum(q.claims_verified for q in self._queries),
            "total_citations":      sum(q.citations_count for q in self._queries),
            "sla_compliance":       self.sla_compliance(),
        }

    def _count_by(self, items: list, key_fn) -> dict:
        counts: dict[str, int] = {}
        for item in items:
            k = key_fn(item)
            counts[k] = counts.get(k, 0) + 1
        return counts
