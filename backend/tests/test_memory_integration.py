"""Shared-fixture chat/inspection integration; providers and storage stay offline."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from personal_ai.api.dependencies import (
    get_chat_turn_service,
    get_context_assembler,
    get_conversation_repository,
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

    class CurrentExtractor:
        def extract(self, source_turn, *, timeout):
            assert source_turn[-1].status == MessageStatus.COMPLETED
            return [candidate.model_copy(update={"source_message_ids": (source_turn[0].id,)})]

    service._memory_extraction.extractor = CurrentExtractor()
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": candidate.content}
    )
    assert events(response)[-1] == "response.completed"
    assert len(repo.records) == 2
    assert all(m.source_message_ids for m in repo.records.values())
    monkeypatch.setattr(
        service._memory_extraction.extractor,
        "extract",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("private")),
    )
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": candidate.content}
    )
    assert events(response)[-1] == "response.completed"
    assert "private" not in response.text
    assert (
        messages.list_active(owner_id="local", conversation_id=pending.conversation_id)[-1].status
        == MessageStatus.COMPLETED
    )


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
