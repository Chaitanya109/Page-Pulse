"""Configurable Redis-backed cache for audit results.

Design notes
------------
* Caching is best-effort: if Redis is unreachable, ``get`` returns
  ``None`` (cache miss) and ``set`` silently no-ops after logging a
  warning. A cache outage must never take the whole service down —
  it should only remove the speedup.
* The cache key is derived from the normalized target URL plus a
  fixed prefix, so identical audits (same URL) within the TTL window
  are served instantly without a new outbound request.
* TTL is configurable per environment (``CACHE_TTL_SECONDS``), and
  caching can be disabled entirely via ``CACHE_ENABLED=false`` for
  local development or debugging.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class AuditCache:
    """Thin async wrapper around Redis for storing serialized audit results."""

    def __init__(
        self,
        redis_url: str,
        prefix: str = "pagepulse:audit:",
        ttl_seconds: int = 300,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._prefix = prefix
        self._ttl = ttl_seconds
        self._redis: redis.Redis | None = None
        if enabled:
            self._redis = redis.from_url(redis_url, decode_responses=True)

    def _key(self, url: str) -> str:
        return f"{self._prefix}{url}"

    async def get(self, url: str) -> dict[str, Any] | None:
        if not self._enabled or self._redis is None:
            return None
        try:
            raw = await self._redis.get(self._key(url))
        except RedisError as exc:
            logger.warning("cache_get_failed", extra={"error": str(exc)})
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("cache_corrupt_entry", extra={"url": url})
            return None

    async def set(self, url: str, value: dict[str, Any]) -> None:
        if not self._enabled or self._redis is None or self._ttl <= 0:
            return
        try:
            await self._redis.set(self._key(url), json.dumps(value, default=str), ex=self._ttl)
        except RedisError as exc:
            logger.warning("cache_set_failed", extra={"error": str(exc)})

    async def ping(self) -> bool:
        """Used by the health endpoint to report cache connectivity."""
        if not self._enabled or self._redis is None:
            return False
        try:
            return bool(await self._redis.ping())
        except RedisError:
            return False

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
