"""Tests for the current API health contract."""

from fastapi.testclient import TestClient

from personal_ai.main import app


def test_health_reports_api_ready() -> None:
    """The deployment health endpoint reports the API service as ready."""
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}
