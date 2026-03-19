"""
SYNDICATE AI — Multi-Tenant Isolation
File: src/syndicate/tenancy/middleware.py

Organisation-scoped isolation for all resources.
Every workflow execution, agent invocation, and memory entry
is scoped to an org_id extracted from the API key.

Architecture:
- Shared DB schema (single PostgreSQL instance)
- Row-level security via org_id column on all mutable tables
- Redis key prefix: {org_id}:execution:{id} etc.
- Agent registry: org agents override global agents (same id = org wins)
- Rate limits applied per-org, not per-IP

Security guarantee:
- Org A cannot read, write, or enumerate Org B's data
- API key → org_id mapping is validated on every request
- org_id is NEVER sourced from request body/params
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Tenant context ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TenantContext:
    """Immutable tenant context attached to each request."""

    org_id: str
    org_name: str
    plan: str  # free | pro | business | enterprise
    api_key_id: str

    # Plan limits
    max_executions_per_month: int
    max_concurrent_executions: int
    max_agents: int  # custom org agents (global always available)
    streaming_enabled: bool
    custom_agents_enabled: bool

    @property
    def redis_prefix(self) -> str:
        """All Redis keys for this tenant are prefixed with org_id."""
        return f"org:{self.org_id}"

    @property
    def is_enterprise(self) -> bool:
        return self.plan == "enterprise"

    @property
    def is_free(self) -> bool:
        return self.plan == "free"


# ── Plan definitions ────────────────────────────────────────────────────────

PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "max_executions_per_month": 100,
        "max_concurrent_executions": 2,
        "max_agents": 0,  # global agents only
        "streaming_enabled": False,
        "custom_agents_enabled": False,
    },
    "pro": {
        "max_executions_per_month": 5000,
        "max_concurrent_executions": 10,
        "max_agents": 25,
        "streaming_enabled": True,
        "custom_agents_enabled": True,
    },
    "business": {
        "max_executions_per_month": 50000,
        "max_concurrent_executions": 50,
        "max_agents": 200,
        "streaming_enabled": True,
        "custom_agents_enabled": True,
    },
    "enterprise": {
        "max_executions_per_month": -1,  # unlimited
        "max_concurrent_executions": -1,
        "max_agents": -1,
        "streaming_enabled": True,
        "custom_agents_enabled": True,
    },
}


# ── API key → Tenant resolver ───────────────────────────────────────────────


class TenantResolver:
    """
    Resolves API keys to TenantContext.

    Production: backed by PostgreSQL (api_keys table).
    Dev/single-tenant: uses SYNDICATE_API_KEYS env var, all map to org 'default'.
    """

    def __init__(self, redis_client: Any, db_enabled: bool = False) -> None:
        self._redis = redis_client
        self._db_enabled = db_enabled
        self._cache_ttl = 300  # 5 minutes

    def resolve(self, api_key: str) -> TenantContext | None:
        """
        Resolve an API key to a TenantContext.
        Returns None if the key is invalid.

        Cache: Redis TTL-based (5 min) to avoid DB on every request.
        """
        # Check Redis cache first
        cache_key = f"apikey:ctx:{self._hash_key(api_key)}"
        cached = self._redis.get(cache_key)
        if cached:
            import json

            data = json.loads(cached)
            return TenantContext(**data)

        # Resolve from source
        ctx = self._resolve_from_source(api_key)
        if ctx:
            import json

            self._redis.setex(cache_key, self._cache_ttl, json.dumps(self._ctx_to_dict(ctx)))

        return ctx

    def _resolve_from_source(self, api_key: str) -> TenantContext | None:
        if self._db_enabled:
            return self._resolve_from_db(api_key)
        return self._resolve_from_env(api_key)

    def _resolve_from_env(self, api_key: str) -> TenantContext | None:
        """Single-tenant mode: all valid keys map to org 'default'."""
        from syndicate.app import get_settings

        settings = get_settings()
        if api_key not in settings.valid_api_keys:
            return None

        plan_name = getattr(settings, "default_plan", "pro")
        plan = PLANS.get(plan_name, PLANS["pro"])

        return TenantContext(
            org_id="default",
            org_name="Default Organisation",
            plan=plan_name,
            api_key_id=self._hash_key(api_key)[:16],
            **plan,
        )

    def _resolve_from_db(self, api_key: str) -> TenantContext | None:
        """Multi-tenant DB mode. Implement when adding org management UI."""
        # TODO: implement PostgreSQL lookup when adding org management
        # SELECT ak.id, o.id, o.name, o.plan FROM api_keys ak
        # JOIN organisations o ON ak.org_id = o.id
        # WHERE ak.key_hash = $1 AND ak.revoked_at IS NULL
        raise NotImplementedError("DB-backed multi-tenancy not yet implemented")

    def _hash_key(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode()).hexdigest()

    def _ctx_to_dict(self, ctx: TenantContext) -> dict[str, Any]:
        return {
            "org_id": ctx.org_id,
            "org_name": ctx.org_name,
            "plan": ctx.plan,
            "api_key_id": ctx.api_key_id,
            "max_executions_per_month": ctx.max_executions_per_month,
            "max_concurrent_executions": ctx.max_concurrent_executions,
            "max_agents": ctx.max_agents,
            "streaming_enabled": ctx.streaming_enabled,
            "custom_agents_enabled": ctx.custom_agents_enabled,
        }


# ── Tenant-scoped Redis key builder ────────────────────────────────────────


def tenant_key(org_id: str, *parts: str) -> str:
    """Build a tenant-scoped Redis key. org_id is always the first segment."""
    from syndicate.memory.store import _safe_key

    return _safe_key(f"org:{org_id}", *parts)


# ── Usage metering ─────────────────────────────────────────────────────────


class UsageMeter:
    """
    Tracks per-tenant execution counts.
    Used for plan enforcement and billing.
    """

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def increment_execution(self, org_id: str) -> int:
        """Increment monthly execution count. Returns new count."""
        import datetime

        month = datetime.datetime.utcnow().strftime("%Y-%m")
        key = f"usage:{org_id}:executions:{month}"
        count = self._redis.incr(key)
        # Expire at end of next month (generous TTL)
        self._redis.expire(key, 86400 * 62)
        return int(count)

    def get_execution_count(self, org_id: str) -> int:
        """Get current month's execution count."""
        import datetime

        month = datetime.datetime.utcnow().strftime("%Y-%m")
        key = f"usage:{org_id}:executions:{month}"
        val = self._redis.get(key)
        return int(val) if val else 0

    def check_limit(self, ctx: TenantContext) -> bool:
        """Return True if org is within their plan limit."""
        if ctx.max_executions_per_month == -1:
            return True  # unlimited
        count = self.get_execution_count(ctx.org_id)
        return count < ctx.max_executions_per_month
