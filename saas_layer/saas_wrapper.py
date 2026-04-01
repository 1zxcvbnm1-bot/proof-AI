"""
SaaS Wrapper for FactCheckPipeline

Adds:
  - Multi-tenancy via API keys
  - Rate limiting (requests per minute)
  - Quota enforcement (monthly request limits)
  - Real-time usage metrics (WebSocket/SSE)
  - Audit trail with tenant_id
"""

from __future__ import annotations
import time
from typing import Optional, Dict, List
from collections import defaultdict, deque
from dataclasses import dataclass, field

from Fact_checker.fact_checker import FactCheckPipeline, FactCheckResult


@dataclass
class Tenant:
    """Tenant configuration."""
    tenant_id: str
    name: str
    api_key: str
    rate_limit_rpm: int = 100           # requests per minute
    monthly_quota: int = 10000          # requests per month
    allowed_detectors: List[str] = field(default_factory=lambda: ["all"])  # or whitelist
    created_at: float = field(default_factory=time.time)


@dataclass
class UsageRecord:
    """Track usage for a tenant."""
    tenant_id: str
    timestamp: float
    request_id: str
    latency_ms: float
    claims_processed: int
    hallucinations_detected: int


class RateLimiter:
    """Token bucket rate limiter per tenant."""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self._tokens: Dict[str, float] = defaultdict(float)
        self._last_refill: Dict[str, float] = defaultdict(time.time)

    def consume(self, tenant_id: str, tokens: int = 1) -> bool:
        """Consume tokens; return False if not enough."""
        now = time.time()
        # Refill
        dt = now - self._last_refill[tenant_id]
        self._tokens[tenant_id] = min(
            self.capacity,
            self._tokens[tenant_id] + dt * self.refill_rate
        )
        self._last_refill[tenant_id] = now

        if self._tokens[tenant_id] >= tokens:
            self._tokens[tenant_id] -= tokens
            return True
        return False


class SaaSFactCheckService:
    """
    SaaS wrapper providing multi-tenant fact-checking with quotas and monitoring.

    Usage:
        service = SaaSFactCheckService()
        service.register_tenant(tenant_id="acme_corp", api_key="secret123", ...)
        result = await service.check(text, api_key="secret123")
    """

    def __init__(self, api_key: Optional[str] = None, model_name: str = "groq/llama-3.3-70b-versatile"):
        self._model_name = model_name
        self._api_key = api_key  # for pipeline; not used for tenant auth

        # Tenant management
        self._tenants: Dict[str, Tenant] = {}           # api_key -> Tenant
        self._tenant_by_id: Dict[str, Tenant] = {}     # tenant_id -> Tenant

        # Rate limiting (per minute)
        self._limiter = RateLimiter(capacity=100, refill_rate=100/60.0)

        # Quota tracking (per calendar month)
        self._monthly_usage: Dict[str, int] = defaultdict(int)
        self._usage_log: List[UsageRecord] = []

        # Real-time metrics (in-memory; could be Prometheus)
        self._total_requests = 0
        self._total_latency = 0.0
        self._hallucination_counts: Dict[str, int] = defaultdict(int)

        # Pipeline cache per tenant (independent)
        self._pipelines: Dict[str, FactCheckPipeline] = {}

    def register_tenant(
        self,
        tenant_id: str,
        name: str,
        api_key: str,
        rate_limit_rpm: int = 100,
        monthly_quota: int = 10000,
    ) -> Tenant:
        """Register a new tenant."""
        if api_key in self._tenants:
            raise ValueError(f"API key already registered")
        if tenant_id in self._tenant_by_id:
            raise ValueError(f"Tenant ID already exists")

        tenant = Tenant(
            tenant_id=tenant_id,
            name=name,
            api_key=api_key,
            rate_limit_rpm=rate_limit_rpm,
            monthly_quota=monthly_quota,
        )
        self._tenants[api_key] = tenant
        self._tenant_by_id[tenant_id] = tenant
        return tenant

    def _get_tenant(self, api_key: str) -> Optional[Tenant]:
        return self._tenants.get(api_key)

    def _get_pipeline(self, tenant: Tenant) -> FactCheckPipeline:
        """Get or create pipeline for tenant."""
        if tenant.tenant_id not in self._pipelines:
            # Create a new pipeline for this tenant
            pipeline = FactCheckPipeline(api_key=self._api_key, model_name=self._model_name)
            # Could load tenant-specific corpus here
            self._pipelines[tenant.tenant_id] = pipeline
        return self._pipelines[tenant.tenant_id]

    async def check(
        self,
        text: str,
        api_key: str,
        session_id: Optional[str] = None,
    ) -> FactCheckResult:
        """
        Check text for hallucinations with tenant context.

        Raises:
            ValueError: if API key invalid or quota exceeded
        """
        tenant = self._get_tenant(api_key)
        if not tenant:
            raise ValueError("Invalid API key")

        # Rate limit check
        if not self._limiter.consume(tenant.tenant_id):
            raise ValueError("Rate limit exceeded. Please slow down requests.")

        # Monthly quota check
        if self._monthly_usage[tenant.tenant_id] >= tenant.monthly_quota:
            raise ValueError("Monthly quota exceeded. Please upgrade your plan.")

        # Perform check
        pipeline = self._get_pipeline(tenant)
        t_start = time.time()
        try:
            result = await pipeline.check(text, session_id=session_id)
        except Exception as e:
            # Log error
            raise
        latency = (time.time() - t_start) * 1000

        # Record usage
        self._total_requests += 1
        self._total_latency += latency
        self._monthly_usage[tenant.tenant_id] += 1

        # Record usage for audit
        record = UsageRecord(
            tenant_id=tenant.tenant_id,
            timestamp=time.time(),
            request_id=result.result_id,
            latency_ms=latency,
            claims_processed=result.total_claims,
            hallucinations_detected=result.blocked + result.conflicts,
        )
        self._usage_log.append(record)

        # Update metrics
        if result.halluc_rate > 0:
            self._hallucination_counts[tenant.tenant_id] += 1

        return result

    async def check_stream(
        self,
        text: str,
        api_key: str,
        session_id: Optional[str] = None,
    ):
        """Streaming version of check."""
        tenant = self._get_tenant(api_key)
        if not tenant:
            raise ValueError("Invalid API key")
        if not self._limiter.consume(tenant.tenant_id):
            raise ValueError("Rate limit exceeded")

        pipeline = self._get_pipeline(tenant)
        t_start = time.time()
        try:
            async for token in pipeline.check_stream(text, session_id=session_id):
                yield token
        finally:
            latency = (time.time() - t_start) * 1000
            self._total_requests += 1
            self._total_latency += latency

    # ── Monitoring & Admin ─────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        """Return aggregate metrics for all tenants."""
        avg_latency = self._total_latency / self._total_requests if self._total_requests else 0
        return {
            "total_requests": self._total_requests,
            "average_latency_ms": round(avg_latency, 2),
            "active_tenants": len(self._tenants),
            "monthly_usage": dict(self._monthly_usage),
            "hallucination_rates_by_tenant": {
                tid: count / max(usage, 1)
                for (tid, count), (tid_key, usage) in zip(
                    self._hallucination_counts.items(),
                    self._monthly_usage.items()
                ) if tid == tid_key and usage > 0
            },
        }

    def get_tenant_usage(self, tenant_id: str) -> Optional[dict]:
        """Get usage for a specific tenant."""
        tenant = self._tenant_by_id.get(tenant_id)
        if not tenant:
            return None
        recent_records = [r for r in self._usage_log[-1000:] if r.tenant_id == tenant_id]
        return {
            "tenant_id": tenant_id,
            "requests_this_month": self._monthly_usage[tenant_id],
            "quota": tenant.monthly_quota,
            "remaining": max(0, tenant.monthly_quota - self._monthly_usage[tenant_id]),
            "recent_requests": [
                {"time": r.timestamp, "latency_ms": r.latency_ms, "claims": r.claims_processed}
                for r in recent_records[-10:]
            ],
        }

    def list_tenants(self) -> List[dict]:
        """List all tenants (admin)."""
        return [
            {
                "tenant_id": t.tenant_id,
                "name": t.name,
                "rate_limit_rpm": t.rate_limit_rpm,
                "monthly_quota": t.monthly_quota,
                "requests_used": self._monthly_usage[t.tenant_id],
            }
            for t in self._tenants.values()
        ]

    # ── Webhooks & Alerts ───────────────────────────────────────────────────────

    def get_alerts(self) -> List[dict]:
        """Check for any quota warnings or high hallucination rates."""
        alerts = []
        for tenant in self._tenants.values():
            used = self._monthly_usage[tenant.tenant_id]
            if used / tenant.monthly_quota > 0.8:
                alerts.append({
                    "tenant_id": tenant.tenant_id,
                    "type": "quota_warning",
                    "message": f"{used}/{tenant.monthly_quota} quota used",
                    "severity": "warning" if used < tenant.monthly_quota else "critical",
                })
        return alerts


# Convenience singleton for the server
_global_service: Optional[SaaSFactCheckService] = None

def get_saas_service() -> SaaSFactCheckService:
    global _global_service
    if _global_service is None:
        _global_service = SaaSFactCheckService()
    return _global_service
