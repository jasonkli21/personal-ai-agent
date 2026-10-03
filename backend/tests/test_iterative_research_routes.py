"""HTTP/API checks for the opt-in iterative research contract."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from personal_ai.agents.research.iterative_contracts import IterativeResearchRequest
from personal_ai.api.iterative_research import iterative_research_service
from personal_ai.main import app
from personal_ai.settings import Settings, get_settings
from tests.test_iterative_research import build_service, result


@pytest.fixture
def environment():
    service, _, _, _, _ = build_service(sources=(result(
        "https://example.org/private-synthetic",
        "Synthetic observatory opens Saturday.",
    ),))
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[iterative_research_service] = lambda: service
    try:
        yield service, TestClient(app)
    finally:
        app.dependency_overrides = previous


def make_request(question="Private synthetic observatory schedule?"):
    return IterativeResearchRequest(question=question, idempotency_key=uuid4())


def test_iterative_routes_stream_persisted_replay_and_owner_fencing(environment):
    service, client = environment
    request = make_request()
    response = client.post("/v1/research/iterative", json=request.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert "event: research.iterative.searching" in response.text
    assert "Saturday" not in response.text and request.question not in response.text

    import json

    payloads = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    run_id = payloads[-1]["run_id"]
    assert [item["sequence"] for item in payloads] == list(range(len(payloads)))
    detail = client.get(f"/v1/research/iterative/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run"]["state"] == "completed"
    assert detail.json()["session"]["citations"][0]["url"] == "https://example.org/private-synthetic"

    replay = client.get(f"/v1/research/iterative/runs/{run_id}/events?after=3")
    replay_payloads = [
        json.loads(line[6:])
        for line in replay.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [item["sequence"] for item in replay_payloads] == list(range(4, len(payloads)))
    assert len(service.adapter.calls) == 1
    assert client.post(f"/v1/research/iterative/runs/{run_id}/cancel").json()["state"] == "completed"

    service.owner_id = "another-owner"
    assert client.get(f"/v1/research/iterative/runs/{run_id}").status_code == 404
    assert client.get(f"/v1/research/iterative/runs/{run_id}/events").status_code == 404


def test_iterative_api_is_independently_disabled_before_storage_access():
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="test",
        research_enabled=True,
        iterative_research_enabled=False,
        iterative_progress_enabled=True,
    )
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/research/iterative",
            json=make_request().model_dump(mode="json"),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    finally:
        app.dependency_overrides = previous
