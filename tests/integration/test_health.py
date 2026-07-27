from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


class TestHealthEndpoint:
    def test_health_returns_200_and_ok_status(self) -> None:
        with TestClient(app) as client:
            response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "environment" in body
        assert body["components"]["cache"]["status"] == "ok"

    def test_health_response_has_request_id_header(self) -> None:
        with TestClient(app) as client:
            response = client.get("/health")

        assert "x-request-id" in {h.lower() for h in response.headers}

    def test_health_echoes_supplied_request_id(self) -> None:
        with TestClient(app) as client:
            response = client.get("/health", headers={"X-Request-ID": "test-req-123"})

        assert response.headers["x-request-id"] == "test-req-123"
