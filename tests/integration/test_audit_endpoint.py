from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app


class TestAuditEndpoint:
    def test_successful_audit(self, mock_transport: respx.MockRouter) -> None:
        mock_transport.get("https://example.com/").mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/html", "server": "nginx"},
            )
        )

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/audit", json={"url": "https://example.com/", "use_cache": False}
            )

        assert response.status_code == 200
        body = response.json()
        assert body["result"]["status_code"] == 200
        assert body["result"]["is_reachable"] is True
        assert body["result"]["server"] == "nginx"
        assert body["request_id"] is not None
        assert "x-request-id" in {h.lower() for h in response.headers}

    def test_invalid_url_returns_422_with_structured_error(self) -> None:
        with TestClient(app) as client:
            response = client.post("/api/v1/audit", json={"url": "not-a-url"})

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] in {"URL_VALIDATION_ERROR", "REQUEST_VALIDATION_ERROR"}
        assert "request_id" in body

    def test_private_network_target_returns_400(self) -> None:
        with TestClient(app) as client:
            response = client.post("/api/v1/audit", json={"url": "http://127.0.0.1/admin"})

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "URL_NOT_ALLOWED"

    def test_missing_url_field_returns_422(self) -> None:
        with TestClient(app) as client:
            response = client.post("/api/v1/audit", json={})

        assert response.status_code == 422

    def test_upstream_5xx_is_reported_not_masked(self, mock_transport: respx.MockRouter) -> None:
        mock_transport.get("https://example.com/broken").mock(return_value=httpx.Response(500))

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/audit",
                json={"url": "https://example.com/broken", "use_cache": False},
            )

        assert response.status_code == 200  # the audit itself succeeded
        assert response.json()["result"]["status_code"] == 500
        assert response.json()["result"]["is_reachable"] is False

    def test_connection_failure_returns_502(self, mock_transport: respx.MockRouter) -> None:
        mock_transport.get("https://example.com/down").mock(
            side_effect=httpx.ConnectError("refused")
        )

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/audit", json={"url": "https://example.com/down", "use_cache": False}
            )

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "UPSTREAM_CONNECTION_ERROR"

    def test_response_includes_security_headers_breakdown(
        self, mock_transport: respx.MockRouter
    ) -> None:
        mock_transport.get("https://example.com/secure").mock(
            return_value=httpx.Response(
                200,
                headers={
                    "strict-transport-security": "max-age=63072000",
                    "content-security-policy": "default-src 'self'",
                    "x-content-type-options": "nosniff",
                    "x-frame-options": "DENY",
                    "referrer-policy": "no-referrer",
                },
            )
        )

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/audit",
                json={"url": "https://example.com/secure", "use_cache": False},
            )

        headers = response.json()["result"]["security_headers"]
        assert all(headers.values())
