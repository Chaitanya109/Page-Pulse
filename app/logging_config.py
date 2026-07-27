"""Structured (JSON) logging configuration.

Every log line is emitted as a single JSON object so it can be shipped
to and indexed by any log aggregator (CloudWatch, Datadog, ELK, Loki)
without a custom parser. The request id is threaded through via a
`contextvars.ContextVar` so it appears on every log line emitted while
handling a given HTTP request, including logs from deep inside the
service layer.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the request id bound to the current async context, if any."""
    return request_id_ctx_var.get()


class JSONFormatter(logging.Formatter):
    """Renders log records as single-line JSON objects."""

    RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id

        # Include any extra fields passed via logger.info("msg", extra={...})
        for key, value in record.__dict__.items():
            if key not in self.RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class PlainFormatter(logging.Formatter):
    """Human-friendly formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        request_id = get_request_id() or "-"
        base = (
            f"{self.formatTime(record)} [{record.levelname:<8}] "
            f"({request_id}) {record.name}: {record.getMessage()}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    """Configure the root logger once at process startup."""
    root = logging.getLogger()
    root.setLevel(level)

    # Remove pre-existing handlers (uvicorn attaches its own by default)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JSONFormatter() if json_logs else PlainFormatter())
    root.addHandler(handler)

    # Quiet down noisy third-party loggers but keep them structured.
    for noisy in ("uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        logging.getLogger(noisy).handlers = [handler]
        logging.getLogger(noisy).propagate = False
