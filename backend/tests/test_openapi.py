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


def test_openapi_documents_sse_and_safe_stream_errors() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    operation = schema["paths"]["/v1/conversations/{conversation_id}/messages"]["post"]

    assert "text/event-stream" in operation["responses"]["200"]["content"]
    for status_code in ("404", "422", "503"):
        error_schema = operation["responses"][status_code]["content"]["application/json"][
            "schema"
        ]
        assert error_schema == {"$ref": "#/components/schemas/ErrorResponse"}
