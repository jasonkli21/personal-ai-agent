"""Shared-fixture chat/inspection integration; providers and storage stay offline."""

import asyncio
import json
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from personal_ai.api.dependencies import (
    get_chat_turn_service,
    get_context_assembler,
    get_conversation_repository,
    get_lifecycle_repository,
    get_memory_adapter,
    get_memory_repository,
    get_message_repository,
    get_summary_repository,
)
from personal_ai.context import ContextAssembler
from personal_ai.context.repositories import InMemorySummaryRepository
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import MessageStatus
from personal_ai.evaluation.memory import build_fixture, load_fixtures
from personal_ai.llm import FakeLLMClient, LLMUnavailableError
from personal_ai.main import app
from personal_ai.memory.fake import FakeMemoryExtractor
from personal_ai.memory.services import MemoryExtractionService, MemoryRetriever
from personal_ai.services.chat_turns import ChatTurnService
from personal_ai.settings import get_settings


@pytest.fixture
def environment():
    f = next(f for f in load_fixtures() if f["name"] == "later-preference")
    settings, conversations, messages, repo, turns, candidates, pending, embedder = build_fixture(f)
    settings.context_inspection_enabled = settings.memory_inspection_enabled = True
    extraction = MemoryExtractionService(
        settings, repo, messages, FakeMemoryExtractor(candidates), embedder
    )
    extraction.run(turns[0][1])
    llm = FakeLLMClient(["Synthetic answer."])
    summaries = InMemorySummaryRepository()
    context = ContextAssembler(settings, FakeTokenCounter(), summaries)
    retriever = MemoryRetriever(settings, repo, messages, embedder)
    service = ChatTurnService(
        conversations,
        messages,
        llm,
        owner_id="local",
        model="fake",
        context_assembler=context,
        memory_retriever=retriever,
        memory_extraction=extraction,
    )
    overrides = {
        get_settings: lambda: settings,
        get_conversation_repository: lambda: conversations,
        get_message_repository: lambda: messages,
        get_summary_repository: lambda: summaries,
        get_context_assembler: lambda: context,
        get_memory_repository: lambda: repo,
        get_memory_adapter: lambda: embedder,
        get_chat_turn_service: lambda: service,
    }
    previous = app.dependency_overrides.copy()
    app.dependency_overrides.update(overrides)
    with TestClient(app) as client:
        yield client, settings, messages, repo, pending, service, llm, embedder
    app.dependency_overrides = previous


def events(response):
    return [
        line.removeprefix("event: ")
        for line in response.text.splitlines()
        if line.startswith("event:")
    ]


def test_retrieval_injection_and_sse_order(environment):
    client, _, messages, _, pending, _, llm, _ = environment
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": pending.content}
    )
    assert events(response) == [
        "message.created",
        "message.created",
        "response.delta",
        "response.completed",
    ]
    assert "Historical personal memory" in llm.requests[0][0].content
    assert "I prefer quiet mountain cabins." in llm.requests[0][0].content
    active = messages.list_active(owner_id="local", conversation_id=pending.conversation_id)
    assert active[-1].status == MessageStatus.COMPLETED


@pytest.mark.parametrize("mode", ["disabled", "no_match", "failed", "budget"])
def test_chat_succeeds_without_optional_memory(environment, monkeypatch, mode):
    client, settings, _, _, pending, _service, llm, embedder = environment
    if mode == "disabled":
        settings.memory_enabled = False
    elif mode == "no_match":
        embedder.vectors[pending.content] = [0, 1, 0]
    elif mode == "failed":
        monkeypatch.setattr(
            embedder, "embed", lambda *a, **kw: (_ for _ in ()).throw(LLMUnavailableError("safe"))
        )
    else:
        settings.memory_max_context_tokens = 1
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": pending.content}
    )
    assert events(response)[-1] == "response.completed"
    assert llm.requests[0][-1].content == pending.content
    assert all(m.role != "system" for m in llm.requests[0])


def test_successful_post_completion_extraction_and_failure_isolated(environment, monkeypatch):
    client, _, messages, repo, pending, service, _, _ = environment
    candidate = service._memory_extraction.extractor.candidates[0]
    original_run = service._memory_extraction.run

    def signal_completion(event):
        def run(completed):
            try:
                return original_run(completed)
            finally:
                event.set()

        monkeypatch.setattr(service._memory_extraction, "run", run)

    class CurrentExtractor:
        def extract(self, source_turn, *, timeout):
            assert source_turn[-1].status == MessageStatus.COMPLETED
            return [candidate.model_copy(update={"source_message_ids": (source_turn[0].id,)})]

    service._memory_extraction.extractor = CurrentExtractor()
    completed_extraction = Event()
    signal_completion(completed_extraction)
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": candidate.content}
    )
    assert events(response)[-1] == "response.completed"
    assert completed_extraction.wait(timeout=1)
    assert len(repo.records) == 2
    assert all(m.source_message_ids for m in repo.records.values())
    monkeypatch.setattr(
        service._memory_extraction.extractor,
        "extract",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("private")),
    )
    failed_extraction = Event()
    signal_completion(failed_extraction)
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": candidate.content}
    )
    assert events(response)[-1] == "response.completed"
    assert failed_extraction.wait(timeout=1)
    assert "private" not in response.text
    assert (
        messages.list_active(owner_id="local", conversation_id=pending.conversation_id)[-1].status
        == MessageStatus.COMPLETED
    )


def test_lifecycle_accounting_receives_only_injected_ids_after_terminal_send(environment):
    from threading import Event

    client, _, _, repo, pending, service, _, _ = environment
    received = []
    finished = Event()

    class LifecycleRecorder:
        def after_completed(self, completed, selected_memory_ids):
            received.append((completed, tuple(selected_memory_ids)))
            finished.set()

    service._memory_lifecycle = LifecycleRecorder()
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": pending.content}
    )
    assert events(response)[-1] == "response.completed"
    assert finished.wait(timeout=1)
    completed, selected_ids = received[0]
    assert completed.status is MessageStatus.COMPLETED
    assert selected_ids == tuple(repo.records)


def test_lifecycle_inspector_is_read_only_and_reports_safe_event_metadata(environment):
    from datetime import UTC, datetime

    from personal_ai.memory.lifecycle_jobs import make_event
    from personal_ai.memory.lifecycle_repositories import InMemoryMemoryLifecycleRepository

    client, settings, messages, repo, pending, _, _, embedder = environment
    messages.create(pending)
    lifecycle = InMemoryMemoryLifecycleRepository(repo, messages)
    memory = next(iter(repo.records.values()))
    applied = lifecycle.apply_event(make_event(
        owner_id=memory.owner_id,
        memory_id=memory.id,
        event_type="retrieved",
        reason_code="synthetic_completion",
        policy_version="score-v1",
        idempotency_key="inspection-synthetic-event",
        expected_state_version=0,
        occurred_at=datetime.now(UTC),
    ))
    assert applied.status == "applied"
    previous = app.dependency_overrides.get(get_lifecycle_repository)
    app.dependency_overrides[get_lifecycle_repository] = lambda: lifecycle
    settings.memory_lifecycle_inspection_enabled = True
    before_records, before_calls = dict(repo.records), list(embedder.calls)
    try:
        response = client.get(
            f"/v1/conversations/{pending.conversation_id}/context",
            params={"memory_ids": str(memory.id)},
        )
    finally:
        settings.memory_lifecycle_inspection_enabled = False
        if previous is None:
            app.dependency_overrides.pop(get_lifecycle_repository, None)
        else:
            app.dependency_overrides[get_lifecycle_repository] = previous
    assert response.status_code == 200
    record = response.json()["memory"]["records"][0]
    assert record["lifecycle"]["retrieval_count"] == 1
    assert record["events"][0]["reason_code"] == "synthetic_completion"
    assert record["score"] is None
    assert record["score_reason"] == "similarity_unavailable_in_inspector"
    assert "content" not in record and memory.content not in response.text
    assert repo.records == before_records and embedder.calls == before_calls


def test_regenerate_and_edit_retrieve_post_mutation_path(environment, monkeypatch):
    client, _, messages, _, pending, service, _, embedder = environment
    snapshots = []
    original = service._memory_retriever.retrieve

    def capture(owner, query, active, **kwargs):
        snapshots.append(tuple(active))
        return original(owner, query, active, **kwargs)

    monkeypatch.setattr(service._memory_retriever, "retrieve", capture)
    path = f"/v1/conversations/{pending.conversation_id}"
    client.post(path + "/messages", json={"content": pending.content})
    user, assistant = messages.list_active(
        owner_id="local", conversation_id=pending.conversation_id
    )
    response = client.post(path + f"/messages/{assistant.id}/regenerate")
    assert events(response)[-1] == "response.completed"
    assert snapshots[-1] == (user,)
    edited = "What lodging atmosphere do I enjoy?"
    embedder.vectors[edited] = [1, 0, 0]
    response = client.post(path + f"/messages/{user.id}/edit-and-retry", json={"content": edited})
    assert events(response)[-1] == "response.completed"
    assert snapshots[-1][-1].content == edited
    assert all(m.id not in (user.id, assistant.id) for m in snapshots[-1])


def test_provider_failure_does_not_extract(environment, monkeypatch):
    client, _, _, repo, pending, service, _, _ = environment

    class FailedLLM:
        async def stream(self, messages):
            raise LLMUnavailableError("safe")
            yield "unreachable"

    service._llm = FailedLLM()
    called = []
    monkeypatch.setattr(
        service._memory_extraction, "run", lambda completed: called.append(completed)
    )
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": pending.content}
    )
    assert events(response)[-1] == "response.error"
    assert not called and len(repo.records) == 1


def test_read_only_inspection_never_embeds_or_writes_and_reports_exclusion(environment):
    client, settings, messages, repo, pending, _, _, embedder = environment
    messages.create(pending)
    memory = next(iter(repo.records.values()))
    before, calls = dict(repo.records), list(embedder.calls)
    path = f"/v1/conversations/{pending.conversation_id}/context"
    response = client.get(path, params={"memory_ids": str(memory.id)})
    assert response.status_code == 200
    report = response.json()["memory"]
    assert report["records"][0]["selected"]
    assert report["records"][0]["similarity"] is None
    assert "content" not in report["records"][0]
    assert memory.content not in json.dumps(report)
    assert repo.records == before and embedder.calls == calls
    settings.memory_max_context_tokens = 1
    assert (
        client.get(path, params={"memory_ids": str(memory.id)}).json()["memory"]["records"][0][
            "reason"
        ]
        == "budget"
    )
    settings.memory_inspection_enabled = False
    assert client.get(path, params={"memory_ids": str(memory.id)}).status_code == 404
    settings.memory_inspection_enabled = True
    assert client.get(path, params={"memory_ids": str(uuid4())}).status_code == 404
    assert client.get(path, params={"memory_ids": "bad"}).status_code == 422
    repo.records[memory.id] = memory.model_copy(update={"owner_id": "foreign"})
    assert client.get(path, params={"memory_ids": str(memory.id)}).status_code == 404


def test_client_closes_partial_response_without_extracting(environment, monkeypatch):
    import asyncio

    _, _, messages, _, pending, service, _, _ = environment
    called = []
    monkeypatch.setattr(
        service._memory_extraction, "run", lambda completed: called.append(completed)
    )

    async def close_partial():
        stream = service.send(
            pending.conversation_id, pending.content, request_id="synthetic-cancel"
        )
        await anext(stream)
        await anext(stream)
        await anext(stream)
        await stream.aclose()

    asyncio.run(close_partial())
    assert not called
    assert (
        messages.list_active(owner_id="local", conversation_id=pending.conversation_id)[-1].status
        == MessageStatus.FAILED
    )


def test_terminal_frame_cancellation_still_runs_bounded_extraction(environment):
    from starlette.requests import ClientDisconnect

    from personal_ai.api.routes import _sse_response

    _, settings, messages, repo, pending, service, _, embedder = environment
    candidate = service._memory_extraction.extractor.candidates[0]
    finished = Event()
    outcomes = []

    class CurrentExtractor:
        def extract(self, source_turn, *, timeout):
            return [candidate.model_copy(update={"source_message_ids": (source_turn[0].id,)})]

    extraction = MemoryExtractionService(settings, repo, messages, CurrentExtractor(), embedder)

    class RecordingExtraction:
        def run(self, completed):
            result = extraction.run(completed)
            outcomes.append(result)
            finished.set()
            return result

    service._memory_extraction = RecordingExtraction()
    stream = service.send(
        pending.conversation_id, candidate.content, request_id="terminal-cancel"
    )
    response = _sse_response(stream, request_id="terminal-cancel")

    async def close_after_terminal_frame():
        terminal_sent = False

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            nonlocal terminal_sent
            body = message.get("body", b"")
            if b"event: response.completed" in body.splitlines():
                terminal_sent = True
                return
            if terminal_sent and message.get("type") == "http.response.body":
                raise OSError("simulated client cancellation after terminal event")

        scope = {"type": "http", "asgi": {"spec_version": "2.4"}, "method": "POST"}
        try:
            await response(scope, receive, send)
        except ClientDisconnect:
            pass
        assert terminal_sent
        await asyncio.to_thread(finished.wait, 1)

    asyncio.run(close_after_terminal_frame())
    assert finished.is_set()
    assert len(outcomes) == 1 and outcomes[0].created
    assert len(repo.records) == 2
