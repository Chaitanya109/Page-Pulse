"""Page Pulse application factory.

Wires together configuration, structured logging, the shared httpx
client, the Redis cache, the concurrency limiter, SlowAPI rate
limiting, request-id middleware, CORS, structured error handlers, and
the API routers -- then exposes a single ``app`` object for uvicorn /
gunicorn to serve.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import audit as audit_routes
from app.api.routes import health as health_routes
from app.config import get_settings
from app.core.cache import AuditCache
from app.core.concurrency import ConcurrencyLimiter
from app.core.exceptions import register_exception_handlers
from app.core.middleware import RequestIDMiddleware
from app.dependencies import build_http_client
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    app.state.settings = settings
    app.state.cache = AuditCache(
        redis_url=settings.redis_url,
        prefix=settings.cache_key_prefix,
        ttl_seconds=settings.cache_ttl_seconds,
        enabled=settings.cache_enabled,
    )
    app.state.concurrency_limiter = ConcurrencyLimiter(settings.max_concurrent_audits)

    logger.info(
        "startup",
        extra={
            "environment": settings.environment,
            "version": settings.app_version,
            "cache_enabled": settings.cache_enabled,
            "rate_limit_enabled": settings.rate_limit_enabled,
            "max_concurrent_audits": settings.max_concurrent_audits,
        },
    )

    async with build_http_client(settings) as client:
        app.state.http_client = client
        yield

    await app.state.cache.close()
    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Page Pulse is a production-grade URL Audit Service: it fetches a "
            "target URL and reports status, timing, redirects, content "
            "metadata, and security-header posture."
        ),
        lifespan=lifespan,
    )

    # --- Rate limiting (SlowAPI) ---
    app.state.limiter = audit_routes.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # --- Structured JSON error handlers ---
    register_exception_handlers(app)

    # --- Middleware (order matters: outermost added last) ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)

    # --- Routers ---
    app.include_router(health_routes.router)
    app.include_router(audit_routes.router)

    return app


app = create_app()
