"""
╔══════════════════════════════════════════════════════╗
║  ACCESS CONTROL — RBAC + Consent Management          ║
║  Roles · Permissions · Data residency · Audit        ║
╚══════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import time, uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Role(str, Enum):
    ADMIN    = "admin"      # full access
    ANALYST  = "analyst"    # read + query, no admin
    VIEWER   = "viewer"     # read only
    API_USER = "api_user"   # query only, no corpus access
    SYSTEM   = "system"     # internal service-to-service


class ConsentStatus(str, Enum):
    EXPLICIT  = "explicit"    # user explicitly agreed
    IMPLIED   = "implied"     # implied by ToS
    NONE      = "none"        # no consent — block


class DataRegion(str, Enum):
    EU  = "eu"
    US  = "us"
    IN  = "in"
    ANY = "any"


ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN:    {"query", "corpus_read", "corpus_write", "audit_read", "user_manage", "key_rotate"},
    Role.ANALYST:  {"query", "corpus_read", "audit_read"},
    Role.VIEWER:   {"corpus_read"},
    Role.API_USER: {"query"},
    Role.SYSTEM:   {"query", "corpus_read", "corpus_write", "audit_read"},
}


@dataclass
class UserContext:
    user_id:    str
    tenant_id:  str
    role:       Role
    region:     DataRegion
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    consent:    ConsentStatus = ConsentStatus.NONE
    metadata:   dict = field(default_factory=dict)


@dataclass
class AccessDecision:
    allowed:    bool
    reason:     str
    user_id:    str
    action:     str
    resource:   str
    timestamp:  float = field(default_factory=time.time)


class AccessController:
    """
    Role-Based Access Control with consent management and data residency.

    Every query to the RAG engine or fact-check pipeline must pass
    through check_access() first. Unauthorized access is blocked
    at the data layer — not just hidden in the UI.
    """

    def __init__(self):
        self._users:    dict[str, UserContext] = {}
        self._audit:    list[AccessDecision]   = []
        self._consents: dict[str, ConsentStatus] = {}

    def register_user(self, ctx: UserContext) -> None:
        self._users[ctx.user_id] = ctx

    def get_user(self, user_id: str) -> Optional[UserContext]:
        return self._users.get(user_id)

    def check_access(
        self,
        user_id:  str,
        action:   str,           # e.g. "query", "corpus_read"
        resource: str = "*",     # e.g. "fact_record", "audit_log"
        required_consent: ConsentStatus = ConsentStatus.IMPLIED,
    ) -> AccessDecision:
        """
        Check if a user has permission to perform an action.
        Records every decision in the audit log.
        """
        user = self._users.get(user_id)
        if not user:
            return self._deny(user_id, action, resource, "User not found")

        # Consent gate
        if not self._consent_ok(user.consent, required_consent):
            return self._deny(user_id, action, resource,
                f"Insufficient consent: have {user.consent.value}, need {required_consent.value}")

        # Permission gate
        allowed_perms = ROLE_PERMISSIONS.get(user.role, set())
        if action not in allowed_perms and "*" not in allowed_perms:
            return self._deny(user_id, action, resource,
                f"Role {user.role.value} does not permit '{action}'")

        decision = AccessDecision(
            allowed=True,
            reason=f"Role {user.role.value} permits '{action}'",
            user_id=user_id,
            action=action,
            resource=resource,
        )
        self._audit.append(decision)
        return decision

    def set_consent(self, user_id: str, status: ConsentStatus) -> None:
        user = self._users.get(user_id)
        if user:
            user.consent = status
        self._consents[user_id] = status

    def check_data_residency(self, user_id: str, data_region: DataRegion) -> bool:
        """Block cross-region data access (EU data must stay in EU, etc.)."""
        user = self._users.get(user_id)
        if not user:
            return False
        if data_region == DataRegion.ANY:
            return True
        return user.region == data_region or user.region == DataRegion.ANY

    def _consent_ok(self, have: ConsentStatus, need: ConsentStatus) -> bool:
        order = {ConsentStatus.NONE: 0, ConsentStatus.IMPLIED: 1, ConsentStatus.EXPLICIT: 2}
        return order.get(have, 0) >= order.get(need, 0)

    def _deny(self, user_id: str, action: str, resource: str, reason: str) -> AccessDecision:
        d = AccessDecision(allowed=False, reason=reason,
                           user_id=user_id, action=action, resource=resource)
        self._audit.append(d)
        return d

    def audit_tail(self, n: int = 50) -> list[dict]:
        return [
            {"user_id": d.user_id[:8]+"...", "action": d.action,
             "allowed": d.allowed, "reason": d.reason,
             "ts": round(d.timestamp)}
            for d in self._audit[-n:]
        ]

    def create_default_user(
        self,
        user_id: str = "default",
        role: Role = Role.API_USER,
        region: DataRegion = DataRegion.ANY,
    ) -> UserContext:
        """Create and register a default user context (for dev/testing)."""
        ctx = UserContext(
            user_id=user_id,
            tenant_id="default",
            role=role,
            region=region,
            consent=ConsentStatus.EXPLICIT,
        )
        self.register_user(ctx)
        return ctx
