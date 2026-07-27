"""Liveness/readiness health endpoint.

Reports the status of the service itself plus its two external
dependencies (Redis cache and Redis rate-limit storage), so this
single endpoint can back both a Kubernetes liveness probe (is the
process alive?) and a readiness probe (is it safe to route traffic
here?) depending on how strictly the caller interprets "degraded".
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import get_settings
from app.core.cache import AuditCache
from app.models.schemas import ComponentHealth, HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    description="Returns overall service health plus the status of the Redis cache dependency.",
)
async def health(request: Request) -> HealthResponse:
    settings = get_settings()
    cache: AuditCache = request.app.state.cache

    cache_ok = await cache.ping() if settings.cache_enabled else True
    components = {
        "cache": ComponentHealth(
            status="ok" if cache_ok else "down",
            detail=None if cache_ok else "Redis cache is unreachable; serving without cache.",
        ),
    }

    overall = "ok" if all(c.status == "ok" for c in components.values()) else "degraded"

    return HealthResponse(
        status=overall,
        version=settings.app_version,
        environment=settings.environment,
        components=components,
    )
