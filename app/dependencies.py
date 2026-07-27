"""FastAPI dependency providers.

All shared, expensive-to-construct resources (the httpx client, the
Redis-backed cache, the concurrency limiter) are created once at
application startup and stored on ``app.state``. These dependency
functions simply hand out references to those singletons — this keeps
route handlers thin and makes it trivial to substitute fakes in tests
via ``app.dependency_overrides``.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import Request

from app.config import Settings, get_settings
from app.core.cache import AuditCache
from app.core.concurrency import ConcurrencyLimiter
from app.services.audit_service import AuditService


def get_app_settings() -> Settings:
    return get_settings()


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def get_cache(request: Request) -> AuditCache:
    return request.app.state.cache


def get_concurrency_limiter(request: Request) -> ConcurrencyLimiter:
    return request.app.state.concurrency_limiter


def get_audit_service(request: Request) -> AuditService:
    return AuditService(
        settings=request.app.state.settings,
        http_client=request.app.state.http_client,
        cache=request.app.state.cache,
        limiter=request.app.state.concurrency_limiter,
    )


@asynccontextmanager
async def build_http_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """Async-context-managed httpx client with sane production defaults."""
    timeout = httpx.Timeout(
        timeout=settings.request_timeout_seconds,
        connect=settings.connect_timeout_seconds,
    )
    limits = httpx.Limits(
        max_connections=settings.max_concurrent_audits * 2,
        max_keepalive_connections=settings.max_concurrent_audits,
    )
    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        max_redirects=settings.max_redirects,
        follow_redirects=True,
    ) as client:
        yield client
