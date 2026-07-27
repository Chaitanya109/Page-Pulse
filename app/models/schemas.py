"""Pydantic models: request/response contracts for the public API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class AuditRequest(BaseModel):
    """Body of ``POST /api/v1/audit``."""

    url: str = Field(
        ...,
        description="The absolute URL to audit (http/https only).",
        examples=["https://example.com"],
    )
    use_cache: bool = Field(
        default=True,
        description="Whether a cached result may be returned if available.",
    )

    @field_validator("url")
    @classmethod
    def _basic_shape_check(cls, value: str) -> str:
        # Deeper validation (scheme allow-list, SSRF guard) happens in the
        # service layer where settings are available; this only guards
        # against obviously empty/whitespace input at the schema boundary.
        if not value or not value.strip():
            raise ValueError("url must not be empty")
        return value.strip()


class SecurityHeaders(BaseModel):
    """Presence of common security-relevant response headers."""

    strict_transport_security: bool = False
    content_security_policy: bool = False
    x_content_type_options: bool = False
    x_frame_options: bool = False
    referrer_policy: bool = False


class AuditResult(BaseModel):
    """Successful audit payload."""

    url: str
    final_url: str = Field(description="URL after following redirects.")
    status_code: int
    is_reachable: bool
    response_time_ms: float
    redirect_count: int
    content_type: str | None = None
    content_length_bytes: int | None = None
    server: str | None = None
    security_headers: SecurityHeaders
    checked_at: str
    from_cache: bool = False


class AuditResponse(BaseModel):
    """Envelope returned by ``POST /api/v1/audit``."""

    request_id: str | None = None
    result: AuditResult


class ComponentHealth(BaseModel):
    status: str  # "ok" | "degraded" | "down"
    detail: str | None = None


class HealthResponse(BaseModel):
    """Payload returned by ``GET /health``."""

    status: str  # "ok" | "degraded"
    version: str
    environment: str
    components: dict[str, ComponentHealth]


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str | None = None
    path: str
