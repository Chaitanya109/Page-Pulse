"""Per-client rate limiting via SlowAPI, backed by Redis.

Clients are identified primarily by the ``X-API-Key`` header (for
authenticated / partner traffic) and fall back to the caller's IP
address. Using Redis as the limiter storage means limits are enforced
correctly even when the service is horizontally scaled across many
replicas — an in-memory limiter would let a client get N requests
*per replica*.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def client_identifier(request: Request) -> str:
    """Resolve a stable identifier for rate-limiting purposes.

    Prefers an explicit API key (so partners can be given individual
    quotas); falls back to the remote IP address for anonymous callers.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{api_key}"
    return f"ip:{get_remote_address(request)}"


def build_limiter(storage_url: str, enabled: bool) -> Limiter:
    """Construct a SlowAPI Limiter. Storage is Redis so limits hold across replicas."""
    return Limiter(
        key_func=client_identifier,
        storage_uri=storage_url if enabled else "memory://",
        enabled=enabled,
        headers_enabled=True,  # emit X-RateLimit-* response headers
        swallow_errors=True,   # a limiter-storage outage degrades to "allow", not "500"
    )
