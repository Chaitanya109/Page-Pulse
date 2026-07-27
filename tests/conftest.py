from __future__ import annotations

import os

# Configure the environment BEFORE anything under `app` is imported, since
# Settings() reads env vars at construction time and get_settings() caches
# the result for the process lifetime.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("CACHE_ENABLED", "true")
os.environ.setdefault("CACHE_TTL_SECONDS", "60")
os.environ.setdefault("MAX_CONCURRENT_AUDITS", "5")
os.environ.setdefault("REQUEST_TIMEOUT_SECONDS", "2.0")
os.environ.setdefault("CONNECT_TIMEOUT_SECONDS", "1.0")

import fakeredis.aioredis
import httpx
import pytest
import respx

import app.core.cache as cache_module
from app.config import Settings, get_settings
from app.core.cache import AuditCache
from app.core.concurrency import ConcurrencyLimiter
from app.services.audit_service import AuditService


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route every `redis.from_url(...)` call to an in-memory FakeRedis."""

    def _fake_from_url(*_args, **_kwargs):
        return fakeredis.aioredis.FakeRedis(decode_responses=True)

    monkeypatch.setattr(cache_module.redis, "from_url", _fake_from_url)


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def audit_cache(settings: Settings) -> AuditCache:
    return AuditCache(
        redis_url=settings.redis_url,
        prefix=settings.cache_key_prefix,
        ttl_seconds=settings.cache_ttl_seconds,
        enabled=settings.cache_enabled,
    )


@pytest.fixture
def concurrency_limiter(settings: Settings) -> ConcurrencyLimiter:
    return ConcurrencyLimiter(settings.max_concurrent_audits)


@pytest.fixture
def mock_transport() -> respx.MockRouter:
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


@pytest.fixture
def audit_service(
    settings: Settings,
    http_client: httpx.AsyncClient,
    audit_cache: AuditCache,
    concurrency_limiter: ConcurrencyLimiter,
) -> AuditService:
    return AuditService(
        settings=settings,
        http_client=http_client,
        cache=audit_cache,
        limiter=concurrency_limiter,
    )
