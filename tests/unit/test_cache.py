from __future__ import annotations

import pytest
from redis.exceptions import RedisError

from app.core.cache import AuditCache


class TestAuditCache:
    async def test_miss_returns_none(self, audit_cache: AuditCache) -> None:
        result = await audit_cache.get("https://example.com/never-set")
        assert result is None

    async def test_set_then_get_round_trips(self, audit_cache: AuditCache) -> None:
        payload = {"status_code": 200, "url": "https://example.com/"}
        await audit_cache.set("https://example.com/", payload)

        result = await audit_cache.get("https://example.com/")

        assert result == payload

    async def test_disabled_cache_is_always_a_miss(self) -> None:
        cache = AuditCache(redis_url="redis://localhost:6379/0", enabled=False)
        await cache.set("https://example.com/", {"foo": "bar"})
        assert await cache.get("https://example.com/") is None

    async def test_zero_ttl_disables_writes(self, audit_cache: AuditCache) -> None:
        audit_cache._ttl = 0
        await audit_cache.set("https://example.com/notl", {"foo": "bar"})
        assert await audit_cache.get("https://example.com/notl") is None

    async def test_ping_reports_true_when_reachable(self, audit_cache: AuditCache) -> None:
        assert await audit_cache.ping() is True

    async def test_ping_reports_false_when_disabled(self) -> None:
        cache = AuditCache(redis_url="redis://localhost:6379/0", enabled=False)
        assert await cache.ping() is False

    async def test_get_swallows_redis_errors(
        self, audit_cache: AuditCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _boom(*_args, **_kwargs):
            raise RedisError("boom")

        monkeypatch.setattr(audit_cache._redis, "get", _boom)
        result = await audit_cache.get("https://example.com/")
        assert result is None

    async def test_set_swallows_redis_errors(
        self, audit_cache: AuditCache, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _boom(*_args, **_kwargs):
            raise RedisError("boom")

        monkeypatch.setattr(audit_cache._redis, "set", _boom)
        # Should not raise.
        await audit_cache.set("https://example.com/", {"foo": "bar"})

    async def test_corrupt_cache_entry_is_treated_as_a_miss(
        self, audit_cache: AuditCache
    ) -> None:
        await audit_cache._redis.set(audit_cache._key("https://example.com/bad"), "{not-json")
        result = await audit_cache.get("https://example.com/bad")
        assert result is None
