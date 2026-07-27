from __future__ import annotations

import httpx
import pytest
import respx

from app.core.exceptions import (
    ConcurrencyLimitExceededError,
    UpstreamConnectionError,
    UpstreamTimeoutError,
    URLNotAllowedError,
    URLValidationError,
)
from app.services.audit_service import AuditService


class TestAuditServiceLiveAudit:
    async def test_successful_audit_returns_expected_fields(
        self, audit_service: AuditService, mock_transport: respx.MockRouter
    ) -> None:
        mock_transport.get("https://example.com/").mock(
            return_value=httpx.Response(
                200,
                headers={
                    "content-type": "text/html; charset=utf-8",
                    "content-length": "1234",
                    "server": "nginx",
                    "strict-transport-security": "max-age=63072000",
                    "x-content-type-options": "nosniff",
                },
            )
        )

        result = await audit_service.audit("https://example.com/", use_cache=False)

        assert result.status_code == 200
        assert result.is_reachable is True
        assert result.content_type == "text/html; charset=utf-8"
        assert result.content_length_bytes == 1234
        assert result.server == "nginx"
        assert result.security_headers.strict_transport_security is True
        assert result.security_headers.x_content_type_options is True
        assert result.security_headers.content_security_policy is False
        assert result.redirect_count == 0
        assert result.from_cache is False
        assert result.response_time_ms >= 0

    async def test_redirects_are_counted(
        self, audit_service: AuditService, mock_transport: respx.MockRouter
    ) -> None:
        mock_transport.get("https://example.com/old").mock(
            return_value=httpx.Response(301, headers={"location": "https://example.com/new"})
        )
        mock_transport.get("https://example.com/new").mock(return_value=httpx.Response(200))

        result = await audit_service.audit("https://example.com/old", use_cache=False)

        assert result.status_code == 200
        assert result.final_url == "https://example.com/new"
        assert result.redirect_count == 1

    async def test_5xx_marks_unreachable(
        self, audit_service: AuditService, mock_transport: respx.MockRouter
    ) -> None:
        mock_transport.get("https://example.com/").mock(return_value=httpx.Response(503))

        result = await audit_service.audit("https://example.com/", use_cache=False)

        assert result.status_code == 503
        assert result.is_reachable is False

    async def test_4xx_is_still_reachable(
        self, audit_service: AuditService, mock_transport: respx.MockRouter
    ) -> None:
        mock_transport.get("https://example.com/missing").mock(return_value=httpx.Response(404))

        result = await audit_service.audit("https://example.com/missing", use_cache=False)

        assert result.status_code == 404
        assert result.is_reachable is True

    async def test_timeout_raises_upstream_timeout_error(
        self, audit_service: AuditService, mock_transport: respx.MockRouter
    ) -> None:
        mock_transport.get("https://example.com/slow").mock(
            side_effect=httpx.ConnectTimeout("timed out")
        )

        with pytest.raises((UpstreamTimeoutError, UpstreamConnectionError)):
            await audit_service.audit("https://example.com/slow", use_cache=False)

    async def test_connection_error_raises_upstream_connection_error(
        self, audit_service: AuditService, mock_transport: respx.MockRouter
    ) -> None:
        mock_transport.get("https://example.com/down").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with pytest.raises(UpstreamConnectionError):
            await audit_service.audit("https://example.com/down", use_cache=False)


class TestAuditServiceValidation:
    async def test_invalid_scheme_is_rejected_before_any_request(
        self, audit_service: AuditService
    ) -> None:
        with pytest.raises(URLValidationError):
            await audit_service.audit("ftp://example.com/", use_cache=False)

    async def test_private_network_target_is_rejected(self, audit_service: AuditService) -> None:
        with pytest.raises(URLNotAllowedError):
            await audit_service.audit("http://127.0.0.1/", use_cache=False)


class TestAuditServiceCaching:
    async def test_second_call_is_served_from_cache(
        self, audit_service: AuditService, mock_transport: respx.MockRouter
    ) -> None:
        route = mock_transport.get("https://example.com/cacheme").mock(
            return_value=httpx.Response(200, headers={"content-type": "text/plain"})
        )

        first = await audit_service.audit("https://example.com/cacheme", use_cache=True)
        second = await audit_service.audit("https://example.com/cacheme", use_cache=True)

        assert first.from_cache is False
        assert second.from_cache is True
        assert route.call_count == 1  # only one real outbound request was made

    async def test_use_cache_false_always_hits_upstream(
        self, audit_service: AuditService, mock_transport: respx.MockRouter
    ) -> None:
        route = mock_transport.get("https://example.com/nocache").mock(
            return_value=httpx.Response(200)
        )

        await audit_service.audit("https://example.com/nocache", use_cache=False)
        await audit_service.audit("https://example.com/nocache", use_cache=False)

        assert route.call_count == 2


class TestConcurrencyLimiting:
    async def test_raises_when_capacity_exhausted(self) -> None:
        from app.core.concurrency import ConcurrencyLimiter

        limiter = ConcurrencyLimiter(max_concurrent=1)
        async with limiter.acquire():
            with pytest.raises(ConcurrencyLimitExceededError):
                async with limiter.acquire():
                    pass
