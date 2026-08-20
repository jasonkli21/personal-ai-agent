"""Tests for the currently implemented OpenAPI surface."""

from fastapi.testclient import TestClient

from personal_ai.main import app


def test_openapi_documents_health_response() -> None:
    """The existing readiness endpoint remains present in generated OpenAPI."""
    schema = TestClient(app).get("/openapi.json").json()

    assert schema["paths"]["/health"]["get"]["responses"]["200"]
    assert schema["info"]["title"] == "Personal AI System"
