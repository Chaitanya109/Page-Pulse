"""Application exception hierarchy and structured JSON error responses.

Every error returned by this API follows the same envelope so clients
can handle failures generically:

    {
      "error": {
        "code": "URL_VALIDATION_ERROR",
        "message": "human readable summary",
        "details": {...optional machine-readable context...}
      },
      "request_id": "..."
    }
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_config import get_request_id

logger = logging.getLogger(__name__)


class PagePulseError(Exception):
    """Base class for all domain errors raised by Page Pulse."""

    code: str = "INTERNAL_ERROR"
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class URLValidationError(PagePulseError):
    code = "URL_VALIDATION_ERROR"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


class URLNotAllowedError(PagePulseError):
    """Raised when a URL resolves to a blocked network (SSRF guard)."""

    code = "URL_NOT_ALLOWED"
    status_code = status.HTTP_400_BAD_REQUEST


class UpstreamTimeoutError(PagePulseError):
    code = "UPSTREAM_TIMEOUT"
    status_code = status.HTTP_504_GATEWAY_TIMEOUT


class UpstreamConnectionError(PagePulseError):
    code = "UPSTREAM_CONNECTION_ERROR"
    status_code = status.HTTP_502_BAD_GATEWAY


class ConcurrencyLimitExceededError(PagePulseError):
    code = "CONCURRENCY_LIMIT_EXCEEDED"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


class CacheUnavailableError(PagePulseError):
    """Raised only where cache availability is required, not on best-effort reads."""

    code = "CACHE_UNAVAILABLE"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


def _error_body(
    code: str, message: str, request: Request, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "request_id": get_request_id(),
        "path": str(request.url.path),
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Attach structured-JSON handlers for every error class the API can raise."""

    @app.exception_handler(PagePulseError)
    async def page_pulse_error_handler(request: Request, exc: PagePulseError) -> JSONResponse:
        logger.warning(
            "handled_application_error",
            extra={"error_code": exc.code, "detail": exc.message},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, request, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.info("request_validation_error", extra={"errors": exc.errors()})
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body(
                "REQUEST_VALIDATION_ERROR",
                "The request could not be validated.",
                request,
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("HTTP_ERROR", str(exc.detail), request),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(
                "INTERNAL_ERROR",
                "An unexpected error occurred. It has been logged for investigation.",
                request,
            ),
        )
