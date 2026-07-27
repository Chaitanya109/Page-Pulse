"""ASGI middleware: request-id propagation and structured access logs."""
from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import request_id_ctx_var

logger = logging.getLogger("pagepulse.access")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assigns (or propagates) a unique request id for every inbound request.

    The id is:
      * read from the ``X-Request-ID`` header if the caller supplied one
        (useful for distributed tracing across services), otherwise a new
        UUID4 is generated;
      * stored in a ContextVar so every log line emitted while handling
        this request can include it automatically;
      * echoed back on the response so clients can correlate support
        tickets with server-side logs.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming_id = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming_id or str(uuid.uuid4())
        token = request_id_ctx_var.set(request_id)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_ctx_var.reset(token)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id

        logger.info(
            "http_request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else None,
            },
        )
        return response
