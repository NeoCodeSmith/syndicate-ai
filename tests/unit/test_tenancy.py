"""Unit tests for multi-tenant isolation middleware."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from syndicate.tenancy.middleware import TenantResolver, UsageMeter, PLANS


def make_redis_mock() -> MagicMock:
    store: dict = {}
    mock = MagicMock()
    mock.get.side_effect = lambda k: store.get(k)
    mock.setex.side_effect = lambda k, t, v: store.update({k: v})
    mock.incr.side_effect = lambda k: store.update({k: int(store.get(k, 0)) + 1}) or store[k]
    mock.expire.side_effect = lambda k, t: None
    return mock


class TestTenantResolver:
    def test_valid_key_resolves_to_default_org(self):
        redis = make_redis_mock()
        resolver = TenantResolver(redis)
        with patch("syndicate.tenancy.middleware.TenantResolver._resolve_from_source") as mock_src:
            from syndicate.tenancy.middleware import TenantContext
            mock_src.return_value = TenantContext(
                org_id="default", org_name="Default", plan="pro",
                api_key_id="abc", **PLANS["pro"]
            )
            ctx = resolver.resolve("sk-valid-key")
            assert ctx is not None
            assert ctx.org_id == "default"
            assert ctx.plan == "pro"

    def test_invalid_key_returns_none(self):
        redis = make_redis_mock()
        resolver = TenantResolver(redis)
        with patch("syndicate.tenancy.middleware.TenantResolver._resolve_from_source") as mock_src:
            mock_src.return_value = None
            result = resolver.resolve("sk-fake-key")
            assert result is None


class TestUsageMeter:
    def test_increment_returns_count(self):
        redis = make_redis_mock()
        meter = UsageMeter(redis)
        count = meter.increment_execution("org-123")
        assert count == 1

    def test_increment_accumulates(self):
        redis = make_redis_mock()
        meter = UsageMeter(redis)
        meter.increment_execution("org-123")
        meter.increment_execution("org-123")
        count = meter.increment_execution("org-123")
        assert count == 3

    def test_free_plan_limit_enforced(self):
        from syndicate.tenancy.middleware import TenantContext
        redis = make_redis_mock()
        meter = UsageMeter(redis)
        ctx = TenantContext(
            org_id="org-free", org_name="Free Org", plan="free",
            api_key_id="x", **PLANS["free"]
        )
        # At limit
        for _ in range(100):
            meter.increment_execution("org-free")
        assert meter.check_limit(ctx) is False

    def test_enterprise_plan_unlimited(self):
        from syndicate.tenancy.middleware import TenantContext
        redis = make_redis_mock()
        meter = UsageMeter(redis)
        ctx = TenantContext(
            org_id="org-ent", org_name="Enterprise", plan="enterprise",
            api_key_id="x", **PLANS["enterprise"]
        )
        assert meter.check_limit(ctx) is True
