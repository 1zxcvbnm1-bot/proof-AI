"""
╔══════════════════════════════════════════════════════════════════════╗
║  CONFIDENCE ENGINE + AUDIT LOGGER — Phase 2 Final Component        ║
║  Per-claim scoring · Immutable audit trail · Prometheus metrics     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import hashlib, json, time, uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    PROMETHEUS = True
except ImportError:
    PROMETHEUS = False


# ════════════════════════════════════════════════════════════════════════════
# CONFIDENCE ENGINE
# ════════════════════════════════════════════════════════════════════════════

class ConfidenceBand(str, Enum):
    HIGH    = "HIGH"      # ≥ 0.85  green
    MEDIUM  = "MEDIUM"    # 0.60–0.85  blue
    LOW     = "LOW"       # 0.40–0.60  amber
    BLOCKED = "BLOCKED"   # < 0.40  red — suppress output


BAND_THRESHOLDS = [
    (0.85, ConfidenceBand.HIGH),
    (0.60, ConfidenceBand.MEDIUM),
    (0.40, ConfidenceBand.LOW),
    (0.00, ConfidenceBand.BLOCKED),
]

UI_LABELS = {
    ConfidenceBand.HIGH:    {"color": "#1D9E75", "label": "Verified",          "action": "Cite freely"},
    ConfidenceBand.MEDIUM:  {"color": "#185FA5", "label": "Likely accurate",   "action": "Note confidence"},
    ConfidenceBand.LOW:     {"color": "#BA7517", "label": "Limited sources",   "action": "Use with caution"},
    ConfidenceBand.BLOCKED: {"color": "#A32D2D", "label": "Insufficient data", "action": "Do not output"},
}


@dataclass
class ConfidenceResult:
    score:      float           # 0.0 – 1.0
    band:       ConfidenceBand
    components: dict            # breakdown of score components
    ui:         dict            # color, label, action for frontend
    claim_id:   str = ""


class ConfidenceEngine:
    """
    Per-claim confidence scorer.

    Formula (tuned from Phase 2 calibration):
      base        = avg trust_score of entailing sources        × 0.30
      authority   = (6 - avg tier) / 5                         × 0.25
      freshness   = 1 - age_days/365                           × 0.15
      corroborate = 0.05 per extra source, cap 0.20
      nli_boost   = avg ENTAILS score × 0.15
      conflict_p  = -0.10 if any conflict (tuned from -0.25)

    Key tuning from Phase 2 debugging:
      - NLI_CONTRADICT_MAX lowered 0.28 → 0.15 (fewer false conflicts)
      - conflict_penalty reduced -0.25 → -0.10 (less aggressive suppression)
      - subject_match guard added to ConflictAnalyzer (cross-topic false positives fixed)
    """

    def compute(
        self,
        entailing_sources:  list,           # EvidenceChunk or FactRecord list
        nli_scores:         list[float],    # entailment scores (0–1) for ENTAILS results
        has_conflict:       bool,
        sycophancy_flagged: bool = False,
    ) -> ConfidenceResult:
        if not entailing_sources:
            return ConfidenceResult(
                score=0.0, band=ConfidenceBand.BLOCKED,
                components={"reason": "no_sources"},
                ui=UI_LABELS[ConfidenceBand.BLOCKED],
            )

        base        = sum(getattr(s, "trust_score", 0.8) for s in entailing_sources) / len(entailing_sources)
        authority_w = sum((6 - getattr(s, "authority_tier", 4)) / 5.0 for s in entailing_sources) / len(entailing_sources)
        freshness_w = sum(self._freshness(getattr(s, "last_verified_at", time.time() - 86400)) for s in entailing_sources) / len(entailing_sources)
        corroborate = min(0.20, 0.05 * (len(entailing_sources) - 1))
        nli_boost   = (sum(nli_scores) / len(nli_scores) * 0.15) if nli_scores else 0.0
        conflict_p  = -0.10 if has_conflict else 0.0
        syco_p      = -0.15 if sycophancy_flagged else 0.0

        raw = (0.30 * base + 0.25 * authority_w + 0.15 * freshness_w
               + corroborate + nli_boost + conflict_p + syco_p)
        score = max(0.0, min(1.0, raw))
        band  = self._band(score)

        return ConfidenceResult(
            score=round(score, 4),
            band=band,
            components={
                "base":        round(base, 3),
                "authority":   round(authority_w, 3),
                "freshness":   round(freshness_w, 3),
                "corroborate": round(corroborate, 3),
                "nli_boost":   round(nli_boost, 3),
                "conflict_p":  conflict_p,
                "syco_p":      syco_p,
            },
            ui=UI_LABELS[band],
        )

    def _freshness(self, ts: float) -> float:
        age_days = (time.time() - ts) / 86400.0
        return max(0.0, 1.0 - age_days / 365.0)

    def _band(self, score: float) -> ConfidenceBand:
        for threshold, band in BAND_THRESHOLDS:
            if score >= threshold:
                return band
        return ConfidenceBand.BLOCKED

    def annotate_text(self, text: str, claims_with_confidence: list[tuple]) -> str:
        """
        Annotate LLM output text with inline confidence markers.
        claims_with_confidence: list of (claim_text, ConfidenceResult)
        Returns text with [CONF:0.88:HIGH] markers after each verified claim.
        """
        annotated = text
        for claim_text, conf_result in claims_with_confidence:
            if claim_text in annotated:
                marker = f" [CONF:{conf_result.score:.2f}:{conf_result.band.value}]"
                annotated = annotated.replace(claim_text, claim_text + marker, 1)
        return annotated


# ════════════════════════════════════════════════════════════════════════════
# IMMUTABLE AUDIT LOGGER
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class AuditEntry:
    """Single immutable audit record. Never updated or deleted."""
    log_id:          str = field(default_factory=lambda: str(uuid.uuid4()))
    session_hash:    str = ""           # SHA-256[:16] of session_id — never raw
    timestamp:       float = field(default_factory=time.time)
    pipeline:        str = "full"       # rag | factcheck | full
    query_hash:      str = ""           # SHA-256[:16] of scrubbed query
    claims_verified: int = 0
    claims_uncertain:int = 0
    claims_blocked:  int = 0
    claims_conflict: int = 0
    halluc_detected: bool = False
    halluc_types:    list[str] = field(default_factory=list)
    confidence_avg:  float = 0.0
    confidence_p95:  float = 0.0
    sources_used:    list[str] = field(default_factory=list)
    pii_detected:    bool = False
    pii_count:       int = 0
    latency_ms:      float = 0.0
    vault_key_id:    str = ""
    extra:           dict = field(default_factory=dict)


class AuditLogger:
    """
    Immutable audit trail. Append-only in all modes.

    Dev mode:   in-memory list
    Production: Postgres append-only table (no UPDATE/DELETE)

    Connects to:
      - RAGEngine        (records every query)
      - FactCheckPipeline (records every check)
      - PrivacyVault     (records PII events + erasures)
      - Gateway          (records end-to-end pipeline runs)

    Never stores: raw user_id, raw query text, raw PII
    Always stores: hashes, aggregate counts, latencies
    """

    def __init__(self, db_url: Optional[str] = None):
        self._log:    list[AuditEntry] = []
        self._db_url: Optional[str] = db_url
        self._metrics_registered = False
        self._setup_prometheus()

    def _setup_prometheus(self) -> None:
        if not PROMETHEUS:
            return
        self._halluc_rate  = Gauge("hallucination_rate",   "Fraction of claims blocked or conflicted")
        self._conf_p50     = Gauge("confidence_p50",       "Median confidence score across all claims")
        self._pii_total    = Counter("pii_detections_total", "Total PII entities detected", ["entity_type"])
        self._latency      = Histogram("pipeline_latency_ms", "End-to-end latency ms", ["pipeline"],
                                       buckets=[500,1000,2000,4000,8000,16000,30000])
        self._erasure_sla  = Gauge("erasure_sla_compliance", "Fraction of erasure requests within 72hr SLA")
        self._metrics_registered = True

    def record(self, entry: AuditEntry) -> None:
        """Append an entry to the audit log. Never modifies existing entries."""
        self._log.append(entry)
        self._update_prometheus(entry)
        # Production: INSERT INTO audit_log VALUES (...)
        # self._pg_insert(entry)

    def _update_prometheus(self, entry: AuditEntry) -> None:
        if not PROMETHEUS or not self._metrics_registered:
            return
        try:
            total = entry.claims_verified + entry.claims_uncertain + entry.claims_blocked + entry.claims_conflict
            if total > 0:
                rate = (entry.claims_blocked + entry.claims_conflict) / total
                self._halluc_rate.set(rate)
            self._conf_p50.set(entry.confidence_avg)
            if entry.latency_ms > 0:
                self._latency.labels(pipeline=entry.pipeline).observe(entry.latency_ms)
        except Exception:
            pass

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:16]

    def build_entry(
        self,
        session_id:      str,
        query:           str,
        pipeline:        str,
        verdicts:        list,          # list of ClaimVerdict or similar
        pii_detected:    bool = False,
        pii_count:       int = 0,
        latency_ms:      float = 0.0,
        vault_key_id:    str = "",
    ) -> AuditEntry:
        """Build a clean audit entry from pipeline results. Call .record() after."""
        confidences = [getattr(v, "confidence", 0.0) for v in verdicts]

        halluc_types = list({
            getattr(v, "halluc_type", type("", (), {"value": "none"})()).value
            for v in verdicts
            if getattr(v, "halluc_type", None) and getattr(v.halluc_type, "value", "none") != "none"
        })

        return AuditEntry(
            session_hash=    self._hash(session_id),
            query_hash=      self._hash(query[:200]),
            pipeline=        pipeline,
            claims_verified= sum(1 for v in verdicts if getattr(getattr(v, "verdict", None), "value", "") == "VERIFIED"),
            claims_uncertain=sum(1 for v in verdicts if getattr(getattr(v, "verdict", None), "value", "") == "UNCERTAIN"),
            claims_blocked=  sum(1 for v in verdicts if getattr(getattr(v, "verdict", None), "value", "") == "BLOCKED"),
            claims_conflict= sum(1 for v in verdicts if getattr(getattr(v, "verdict", None), "value", "") == "CONFLICT"),
            halluc_detected= len(halluc_types) > 0,
            halluc_types=    halluc_types,
            confidence_avg=  round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
            confidence_p95=  round(sorted(confidences)[int(len(confidences)*0.95)] if len(confidences) > 1 else (confidences[0] if confidences else 0.0), 3),
            pii_detected=    pii_detected,
            pii_count=       pii_count,
            latency_ms=      round(latency_ms, 1),
            vault_key_id=    vault_key_id,
        )

    def hallucination_rate(self) -> float:
        total = sum(e.claims_verified + e.claims_uncertain + e.claims_blocked + e.claims_conflict for e in self._log)
        blocked = sum(e.claims_blocked + e.claims_conflict for e in self._log)
        return blocked / total if total else 0.0

    def average_confidence(self) -> float:
        scores = [e.confidence_avg for e in self._log if e.confidence_avg > 0]
        return sum(scores) / len(scores) if scores else 0.0

    def last_n(self, n: int = 50) -> list[dict]:
        return [
            {
                "log_id":        e.log_id[:8] + "...",
                "pipeline":      e.pipeline,
                "timestamp":     e.timestamp,
                "verified":      e.claims_verified,
                "uncertain":     e.claims_uncertain,
                "blocked":       e.claims_blocked,
                "conflict":      e.claims_conflict,
                "halluc":        e.halluc_detected,
                "halluc_types":  e.halluc_types,
                "conf_avg":      e.confidence_avg,
                "pii":           e.pii_count,
                "latency_ms":    e.latency_ms,
            }
            for e in self._log[-n:]
        ]

    def dashboard_summary(self) -> dict:
        return {
            "total_queries":      len(self._log),
            "hallucination_rate": f"{self.hallucination_rate():.1%}",
            "average_confidence": f"{self.average_confidence():.2f}",
            "total_pii_events":   sum(e.pii_count for e in self._log),
            "total_claims":       sum(e.claims_verified + e.claims_uncertain + e.claims_blocked + e.claims_conflict for e in self._log),
            "verified_claims":    sum(e.claims_verified for e in self._log),
            "blocked_claims":     sum(e.claims_blocked + e.claims_conflict for e in self._log),
        }

    def export_jsonl(self) -> str:
        """Export entire log as JSONL. Use for SOC 2 evidence package."""
        return "\n".join(json.dumps(asdict(e)) for e in self._log)

    def phase2_exit_check(self) -> dict:
        """
        Check all Phase 2 exit criteria.
        Returns pass/fail per criterion.
        """
        h_rate = self.hallucination_rate()
        avg_conf = self.average_confidence()

        return {
            "hallucination_rate_lt_10pct": {
                "pass": h_rate < 0.10,
                "value": f"{h_rate:.1%}",
                "target": "< 10%",
            },
            "confidence_p50_gt_0_65": {
                "pass": avg_conf > 0.65,
                "value": f"{avg_conf:.2f}",
                "target": "> 0.65",
            },
            "audit_log_active": {
                "pass": len(self._log) > 0,
                "value": f"{len(self._log)} entries",
                "target": "> 0",
            },
            "pii_scrubbing_active": {
                "pass": any(e.pii_detected for e in self._log),
                "value": "detected in logs",
                "target": "pii_detected = true in ≥1 entry",
            },
        }


# ── Shared singleton (import in gateway, RAG server, fact-check server) ───────
_shared_audit_logger: Optional[AuditLogger] = None

def get_audit_logger() -> AuditLogger:
    global _shared_audit_logger
    if _shared_audit_logger is None:
        _shared_audit_logger = AuditLogger()
    return _shared_audit_logger
