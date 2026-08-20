"""Tests for the currently implemented OpenAPI surface."""

from fastapi.testclient import TestClient

from personal_ai.main import app


def test_openapi_documents_health_response() -> None:
    """The existing readiness endpoint remains present in generated OpenAPI."""
    schema = TestClient(app).get("/openapi.json").json()

    assert schema["paths"]["/health"]["get"]["responses"]["200"]
    assert schema["info"]["title"] == "Personal AI System"


def test_openapi_documents_non_streaming_conversation_routes() -> None:
    """The generated schema exposes the documented Phase 1 route contracts."""
    schema = TestClient(app).get("/openapi.json").json()

    routes = schema["paths"]
    assert routes["/v1/conversations"]["post"]["responses"]["201"]
    assert routes["/v1/conversations"]["get"]["responses"]["200"]
    assert routes["/v1/conversations/{conversation_id}"]["get"]["responses"]["200"]
