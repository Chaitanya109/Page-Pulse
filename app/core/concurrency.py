"""Process-wide concurrency guard for outbound audit requests.

Without a limiter, a burst of audit requests could open unbounded
numbers of outbound HTTP connections, starving the event loop and the
downstream targets alike. We cap in-flight audits with an
``asyncio.Semaphore`` sized from configuration, and fail fast with a
503 (rather than queuing indefinitely) once the cap is reached -- a
form of load-shedding that keeps latency predictable for accepted
requests instead of degrading everyone equally.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from app.core.exceptions import ConcurrencyLimitExceededError


class ConcurrencyLimiter:
    """A bounded semaphore that raises instead of blocking when exhausted."""

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def capacity(self) -> int:
        return self._max_concurrent

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        # Fail fast (load-shed) instead of queuing when we're already at
        # capacity, so accepted requests keep predictable latency.
        if self._semaphore.locked():
            raise ConcurrencyLimitExceededError(
                "The service is at maximum audit concurrency. Please retry shortly.",
                details={"max_concurrent_audits": self._max_concurrent},
            )

        await self._semaphore.acquire()
        self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1
            self._semaphore.release()
