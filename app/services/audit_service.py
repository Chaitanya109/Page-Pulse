"""Core business logic: fetch a URL and produce a structured audit report.

This module has no knowledge of FastAPI, HTTP status codes for the
*inbound* request, or rate limiting — it is a plain, testable service
class. It depends only on:

  * an ``httpx.AsyncClient`` for the outbound request (injected, so
    tests can substitute ``httpx.MockTransport``),
  * an ``AuditCache`` for optional response caching,
  * a ``ConcurrencyLimiter`` to bound in-flight outbound requests,
  * ``Settings`` for timeouts and behavior flags.

Single Responsibility: this class answers exactly one question —
"what does auditing this URL look like right now?"
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.core.cache import AuditCache
from app.core.concurrency import ConcurrencyLimiter
from app.core.exceptions import UpstreamConnectionError, UpstreamTimeoutError
from app.models.schemas import AuditResult, SecurityHeaders
from app.services.url_validator import enforce_ssrf_guard, validate_url_structure

logger = logging.getLogger(__name__)

_SECURITY_HEADER_MAP = {
    "strict_transport_security": "strict-transport-security",
    "content_security_policy": "content-security-policy",
    "x_content_type_options": "x-content-type-options",
    "x_frame_options": "x-frame-options",
    "referrer_policy": "referrer-policy",
}


class AuditService:
    """Orchestrates URL validation, caching, and the outbound HTTP audit."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient,
        cache: AuditCache,
        limiter: ConcurrencyLimiter,
    ) -> None:
        self._settings = settings
        self._http_client = http_client
        self._cache = cache
        self._limiter = limiter

    async def audit(self, raw_url: str, use_cache: bool = True) -> AuditResult:
        """Validate, (optionally) serve from cache, or perform a live audit."""
        normalized_url = validate_url_structure(raw_url, self._settings)
        enforce_ssrf_guard(normalized_url, self._settings)

        if use_cache and self._settings.cache_enabled:
            cached = await self._cache.get(normalized_url)
            if cached is not None:
                logger.info("audit_cache_hit", extra={"url": normalized_url})
                cached["from_cache"] = True
                return AuditResult.model_validate(cached)

        async with self._limiter.acquire():
            result = await self._perform_live_audit(normalized_url)

        if use_cache and self._settings.cache_enabled:
            await self._cache.set(normalized_url, result.model_dump())

        return result

    async def _perform_live_audit(self, url: str) -> AuditResult:
        start = time.perf_counter()
        try:
            response = await self._http_client.get(
                url,
                follow_redirects=True,
                headers={"User-Agent": self._settings.user_agent},
            )
        except httpx.TimeoutException as exc:
            logger.warning("audit_timeout", extra={"url": url})
            raise UpstreamTimeoutError(
                f"The target URL did not respond within "
                f"{self._settings.request_timeout_seconds}s.",
                details={"url": url, "timeout_seconds": self._settings.request_timeout_seconds},
            ) from exc
        except httpx.ConnectError as exc:
            logger.warning("audit_connect_error", extra={"url": url, "error": str(exc)})
            raise UpstreamConnectionError(
                "Could not establish a connection to the target URL.",
                details={"url": url, "reason": str(exc)},
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("audit_http_error", extra={"url": url, "error": str(exc)})
            raise UpstreamConnectionError(
                "An error occurred while contacting the target URL.",
                details={"url": url, "reason": str(exc)},
            ) from exc

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        headers = response.headers

        security_headers = SecurityHeaders(
            **{
                field: header_name in headers
                for field, header_name in _SECURITY_HEADER_MAP.items()
            }
        )

        content_length = headers.get("content-length")
        result = AuditResult(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            is_reachable=response.status_code < 500,
            response_time_ms=elapsed_ms,
            redirect_count=len(response.history),
            content_type=headers.get("content-type"),
            content_length_bytes=(
                int(content_length) if content_length and content_length.isdigit() else None
            ),
            server=headers.get("server"),
            security_headers=security_headers,
            checked_at=datetime.now(UTC).isoformat(),
            from_cache=False,
        )
        logger.info(
            "audit_completed",
            extra={
                "url": url,
                "status_code": result.status_code,
                "response_time_ms": result.response_time_ms,
            },
        )
        return result
