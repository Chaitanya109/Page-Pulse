"""URL audit endpoint."""

from fastapi import APIRouter, Depends, Request

from app.config import get_settings
from app.core.rate_limit import build_limiter
from app.dependencies import get_audit_service
from app.logging_config import get_request_id
from app.models.schemas import AuditRequest, AuditResponse
from app.services.audit_service import AuditService

router = APIRouter(prefix="/api/v1", tags=["Audit"])

_settings = get_settings()
# The same Limiter instance is attached to `app.state.limiter` in app.main
# (SlowAPI's exception handler looks it up there); constructing it here
# from settings keeps the per-route `@limiter.limit(...)` decorator usable
# without introducing a circular import with app.main.
limiter = build_limiter(_settings.rate_limit_storage_url, _settings.rate_limit_enabled)


@router.post(
    "/audit",
    response_model=AuditResponse,
    summary="Audit a URL",
    description=(
        "Fetches the given URL and returns status code, timing, redirect "
        "chain length, content metadata, and the presence of common "
        "security response headers. Results are cached (when enabled) "
        "for a configurable TTL, and this endpoint is rate-limited per "
        "client."
    ),
)
@limiter.limit(_settings.rate_limit_audit)
async def audit_url(
    request: Request,
    payload: AuditRequest,
    service: AuditService = Depends(get_audit_service),
) -> AuditResponse:
    result = await service.audit(payload.url, use_cache=payload.use_cache)
    return AuditResponse(request_id=get_request_id(), result=result)
