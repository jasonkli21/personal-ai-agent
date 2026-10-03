import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from personal_ai.api.research import research_service
from personal_ai.evaluation.research import build_fixture, load_fixtures
from personal_ai.main import app
from personal_ai.settings import Settings, get_settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def environment():
    service, request = build_fixture(load_fixtures()[0])
    prior = app.dependency_overrides.copy()
    app.dependency_overrides[research_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: service.settings
    try:
        yield service, request, TestClient(app)
    finally:
        app.dependency_overrides = prior


def test_create_run_detail_inspection_and_foreign_owner(environment):
    service, request, client = environment
    first = client.post("/v1/research", json=request.model_dump(mode="json"))
    assert first.status_code == 201
    session_id = first.json()["id"]
    assert "run_token" not in first.json()
    assert (
        client.post("/v1/research", json=request.model_dump(mode="json")).json()["id"] == session_id
    )
    changed = request.model_copy(update={"question": "Other question"})
    assert client.post("/v1/research", json=changed.model_dump(mode="json")).status_code == 409
    result = client.post(f"/v1/research/{session_id}/run")
    assert result.headers["content-type"].startswith("text/event-stream")
    assert '"state": "completed"' in result.text
    detail = client.get(f"/v1/research/{session_id}").json()
    assert detail["citations"][0]["url"] == "https://example.org/star"
    assert client.get(f"/v1/research/{session_id}/inspection").status_code == 404
    service.settings.research_inspection_enabled = True
    report = client.get(f"/v1/research/{session_id}/inspection").json()
    assert report["source_count"] == 1 and "question" not in report
    service.owner_id = "other"
    assert client.get(f"/v1/research/{session_id}").status_code == 404


def test_disabled_route_does_not_construct_storage():
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, ai_provider="gemini", ai_model="test"
    )
    try:
        client = TestClient(app)
        assert (
            client.post(
                "/v1/research", json={"question": "test", "idempotency_key": str(uuid4())}
            ).status_code
            == 404
        )
        assert client.get(f"/v1/research/{uuid4()}").status_code == 404
    finally:
        app.dependency_overrides = previous


@pytest.mark.anyio
@pytest.mark.parametrize("spec_version", ["2.0", "2.4"])
async def test_asgi_disconnect_persists_failure(environment, spec_version):
    service, request, _ = environment
    session = await service.create(request)
    path = f"/v1/research/{session.id}/run"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 1234),
        "server": ("testserver", 80),
        "state": {},
    }
    disconnect = asyncio.Event()
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            if spec_version == "2.4":
                raise OSError("disconnected")
            disconnect.set()
            await asyncio.sleep(0)

    try:
        await asyncio.wait_for(app(scope, receive, send), 2)
    except ClientDisconnect:
        assert spec_version == "2.4"
    assert (await service.detail(session.id)).failure_code == "research_cancelled"
    assert not service.adapter.calls


def test_bad_request_and_openapi(environment):
    _, _, client = environment
    assert (
        client.post(
            "/v1/research", json={"question": "", "idempotency_key": str(uuid4())}
        ).status_code
        == 422
    )
    paths = client.get("/openapi.json").json()["paths"]
    assert (
        "text/event-stream"
        in paths["/v1/research/{session_id}/run"]["post"]["responses"]["200"]["content"]
    )


def test_research_does_not_resolve_chat_or_memory_storage(environment):
    from personal_ai.api.dependencies import get_memory_repository, get_message_repository

    _, request, client = environment

    def forbidden():
        raise AssertionError("Research must not touch chat or memory storage")

    app.dependency_overrides[get_memory_repository] = forbidden
    app.dependency_overrides[get_message_repository] = forbidden
    created = client.post("/v1/research", json=request.model_dump(mode="json")).json()
    response = client.post(f"/v1/research/{created['id']}/run")
    assert '"state": "completed"' in response.text
