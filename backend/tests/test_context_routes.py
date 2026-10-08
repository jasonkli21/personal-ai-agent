"""Phase 2 API integration on synthetic shared fixtures, with no network."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from personal_ai.api.dependencies import (
    get_context_assembler,
    get_context_trace_repository,
    get_conversation_repository,
    get_current_owner_id,
    get_llm_client,
    get_message_repository,
    get_summary_repository,
)
from personal_ai.context import ContextAssembler
from personal_ai.context.repositories import InMemorySummaryRepository
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.context.traces import (
    InMemoryContextTraceRepository,
    UnsupportedContextTraceSchemaError,
)
from personal_ai.entities import Conversation
from personal_ai.evaluation.context import (
    FactSummarizer,
    build_fixture,
    fixture_settings,
    load_fixtures,
)
from personal_ai.llm import FakeLLMClient, LLMUnavailableError
from personal_ai.main import app
from personal_ai.settings import get_settings
from personal_ai.storage import InMemoryConversationRepository, InMemoryMessageRepository
from personal_ai.storage.errors import ConversationConflictError


@pytest.fixture
def environment():
    settings = fixture_settings(context_inspection_enabled=True)
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    summaries = InMemorySummaryRepository()
    llm = FakeLLMClient(["bounded answer"])
    summarizer = FactSummarizer()
    context = ContextAssembler(settings, FakeTokenCounter(), summaries, summarizer)
    traces = InMemoryContextTraceRepository()
    previous = app.dependency_overrides.copy()
    app.dependency_overrides = {
        get_settings: lambda: settings,
        get_current_owner_id: lambda: "local",
        get_conversation_repository: lambda: conversations,
        get_message_repository: lambda: messages,
        get_summary_repository: lambda: summaries,
        get_llm_client: lambda: llm,
        get_context_assembler: lambda: context,
        get_context_trace_repository: lambda: traces,
    }
    with TestClient(app) as client:
        yield client, conversations, messages, summaries, llm, context
    app.dependency_overrides = previous


def install(environment, name="old-fact"):
    _, conversations, messages, _, _, _ = environment
    fixture = next(f for f in load_fixtures() if f["name"] == name)
    active, pending, _ = build_fixture(fixture)
    now = datetime.now(UTC)
    conversations.create(
        Conversation(
            id=pending.conversation_id,
            owner_id="local",
            title="Synthetic",
            created_at=now,
            updated_at=now,
        )
    )
    for message in active:
        messages.create(message)
    return active, pending


def test_summary_backed_streaming_is_bounded_and_success_event_order_unchanged(environment):
    client, _, _, summaries, llm, context = environment
    _, pending = install(environment, "beyond-fixed-cap")
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": pending.content}
    )
    assert response.status_code == 200
    events = [line for line in response.text.splitlines() if line.startswith("event:")]
    assert events == [
        "event: message.created",
        "event: message.created",
        "event: response.delta",
        "event: response.completed",
    ]
    assert summaries.records
    assert llm.requests[0][0].role == "system"
    assert "Launch color is amber" in llm.requests[0][0].content
    assert context.counter.count(llm.requests[0]).tokens <= context.input_budget()
    trace_response = client.get(
        f"/v1/conversations/{pending.conversation_id}/context",
        headers={"X-Request-ID": "inspect-context-14"},
    )
    trace_report = trace_response.json()
    assert trace_report["trace_state"] == "available"
    assert trace_report["actual_build_trace"]["view_kind"] == "actual_build"
    assert trace_report["actual_build_trace"]["request_id"] == response.headers["X-Request-ID"]
    assert trace_report["inspection_request_id"] == "inspect-context-14"
    assert trace_report["view_kind"] == "estimated_current_view"
    assert "bounded answer" not in str(trace_report)


def test_mandatory_overflow_keeps_user_without_placeholder_and_can_be_edited(environment):
    client, conversations, messages, _, llm, _ = environment
    _, pending = install(environment, "oversized-newest")
    path = f"/v1/conversations/{pending.conversation_id}"
    response = client.post(path + "/messages", json={"content": pending.content})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "context_message_too_large"
    active = messages.list_active(owner_id="local", conversation_id=pending.conversation_id)
    assert active[-1].role.value == "user" and active[-1].content == pending.content
    assert active[-1].status.value == "completed"
    assert not llm.requests
    assert (
        conversations.get(
            owner_id="local", conversation_id=pending.conversation_id
        ).context_preparation_id
        is None
    )
    retry = client.post(
        path + f"/messages/{active[-1].id}/edit-and-retry", json={"content": "shorter"}
    )
    assert retry.status_code == 200 and "event: response.completed" in retry.text
    assert llm.requests[-1][-1].content == "shorter"


def test_regenerate_and_edit_use_same_assembler_and_invalidate_old_summary(environment):
    client, _, messages, summaries, llm, context = environment
    active, pending = install(environment)
    context.assemble(active, pending)
    assert summaries.records
    original_ids = set(summaries.records)
    path = f"/v1/conversations/{pending.conversation_id}/messages"
    regenerated = client.post(path + f"/{active[1].id}/regenerate")
    assert regenerated.status_code == 200
    assert all(m.role != "system" for m in llm.requests[-1])
    assert llm.requests[-1][-1].content == active[0].content
    edited = client.post(
        path + f"/{active[0].id}/edit-and-retry", json={"content": "Corrected prompt"}
    )
    assert edited.status_code == 200
    assert llm.requests[-1][-1].content == "Corrected prompt"
    assert all(m.role != "system" for m in llm.requests[-1])
    assert set(summaries.records) == original_ids
    assert all(
        m.status.value != "superseded"
        for m in messages.list_active(owner_id="local", conversation_id=pending.conversation_id)
    )


def test_summary_failure_falls_back_to_recent_context(environment):
    client, _, _, summaries, llm, context = environment
    _, pending = install(environment)

    class FailedSummary:
        def summarize(self, source, prior):
            raise LLMUnavailableError("private summary failure")

    context.summarizer = FailedSummary()
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": pending.content}
    )
    assert response.status_code == 200 and "response.completed" in response.text
    assert not summaries.records
    assert context.counter.count(llm.requests[-1]).tokens <= context.input_budget()


def test_inspector_enabled_is_read_only_estimated_metadata_without_provider_calls(environment):
    client, conversations, messages, summaries, llm, context = environment
    _, pending = install(environment)
    app.dependency_overrides[get_settings] = lambda: context.settings.model_copy(
        update={
            "max_context_tokens": 1000,
            "max_summary_tokens": 400,
        }
    )
    before = conversations.get(
        owner_id="local", conversation_id=pending.conversation_id
    ).model_dump()
    active_before = messages.list_active(owner_id="local", conversation_id=pending.conversation_id)
    response = client.get(f"/v1/conversations/{pending.conversation_id}/context")
    assert response.status_code == 200
    report = response.json()
    assert report["counter_kind"] == "estimated"
    assert report["view_kind"] == "estimated_current_view"
    assert report["historical_reconstruction"] is False
    assert report["manifest"]["actual_build"] is False
    assert report["manifest"]["view_kind"] == "estimated_current_view"
    assert report["trace_state"] == "manifest_missing"
    assert report["selected"] and report["excluded"]
    assert "content" not in str(report) and "test-key" not in str(report)
    assert not llm.requests and not context.summarizer.calls and not summaries.records
    assert (
        before
        == conversations.get(owner_id="local", conversation_id=pending.conversation_id).model_dump()
    )
    assert active_before == messages.list_active(
        owner_id="local", conversation_id=pending.conversation_id
    )


def test_inspector_disabled_unknown_foreign_and_malformed(environment):
    client, _, _, _, _, context = environment
    _, pending = install(environment, "short-control")
    path = f"/v1/conversations/{pending.conversation_id}/context"
    assert client.get(f"/v1/conversations/{uuid4()}/context").status_code == 404
    assert client.get("/v1/conversations/not-a-uuid/context").status_code == 422
    app.dependency_overrides[get_current_owner_id] = lambda: "foreign"
    assert client.get(path).status_code == 404
    app.dependency_overrides[get_current_owner_id] = lambda: "local"
    app.dependency_overrides[get_settings] = lambda: context.settings.model_copy(
        update={"context_inspection_enabled": False}
    )
    # Guards run before resolving repository/model dependencies.
    app.dependency_overrides[get_summary_repository] = lambda: (_ for _ in ()).throw(
        AssertionError("disabled inspector touched storage")
    )
    assert client.get(path).status_code == 404


def test_preparation_reservation_blocks_an_overlapping_send_before_assistant_creation(environment):
    from personal_ai.services import ChatTurnService

    client, conversations, messages, _, llm, context = environment
    _, pending = install(environment, "short-control")
    checked = False

    class Counter(FakeTokenCounter):
        def count(self, request):
            nonlocal checked
            if not checked:
                checked = True
                active = messages.list_active(
                    owner_id="local", conversation_id=pending.conversation_id
                )
                assert active[-1].role.value == "user"
                assert all(m.status.value != "streaming" for m in active)
                service = ChatTurnService(
                    conversations,
                    messages,
                    llm,
                    owner_id="local",
                    model="fake",
                    context_assembler=context,
                )
                with pytest.raises(ConversationConflictError):
                    service.send(pending.conversation_id, "overlapping", request_id="overlap")
            return super().count(request)

    context.counter = Counter()
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": "newest"}
    )
    assert response.status_code == 200 and checked


def test_provider_count_failure_is_safe_json_without_an_assistant(environment):
    client, conversations, messages, _, llm, context = environment
    _, pending = install(environment, "short-control")

    class Counter:
        def count(self, request):
            raise LLMUnavailableError("private count details")

    context.counter = Counter()
    response = client.post(
        f"/v1/conversations/{pending.conversation_id}/messages", json={"content": "newest"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_unavailable"
    assert "private" not in response.text
    assert (
        messages.list_active(owner_id="local", conversation_id=pending.conversation_id)[
            -1
        ].role.value
        == "user"
    )
    assert (
        conversations.get(
            owner_id="local", conversation_id=pending.conversation_id
        ).context_preparation_id
        is None
    )
    assert not llm.requests


def test_inspection_overflow_reports_budget_without_model_or_mutation(environment):
    client, _, messages, summaries, llm, _ = environment
    _, pending = install(environment, "oversized-newest")
    messages.create(pending)
    before = messages.list_active(owner_id="local", conversation_id=pending.conversation_id)
    response = client.get(f"/v1/conversations/{pending.conversation_id}/context")
    report = response.json()
    assert report["overflow"] == "context_message_too_large"
    assert report["budget"]["mandatory_tokens"] > report["budget"]["input_budget"]
    assert not llm.requests and not summaries.records
    assert before == messages.list_active(owner_id="local", conversation_id=pending.conversation_id)


def test_invalid_operator_budget_returns_safe_configuration_error(environment, monkeypatch):
    from personal_ai.settings import get_settings as configured_settings

    client = environment[0]
    conversation = client.post("/v1/conversations", json={})
    assert conversation.status_code == 201
    configured_settings.cache_clear()
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("AI_MODEL", "offline-fake")
    monkeypatch.setenv("AI_API_KEY", "offline-fake")
    monkeypatch.setenv("MAX_CONTEXT_TOKENS", "100")
    monkeypatch.setenv("MAX_RESPONSE_TOKENS", "200")
    app.dependency_overrides[get_settings] = lambda: configured_settings()
    try:
        response = client.get(f"/v1/conversations/{conversation.json()['id']}/context")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "context_budget_invalid"
        assert "offline-fake" not in response.text
    finally:
        configured_settings.cache_clear()


def test_post_reservation_read_failure_releases_lease_and_retry_succeeds(environment, monkeypatch):
    client, conversations, messages, _, _, _ = environment
    _, pending = install(environment, 'short-control')
    original = messages.list_active
    reads = 0
    def read(**kwargs):
        nonlocal reads
        reads += 1
        if reads == 2:
            from personal_ai.storage import StorageUnavailableError
            raise StorageUnavailableError('synthetic read failure')
        return original(**kwargs)
    monkeypatch.setattr(messages, 'list_active', read)
    path = f'/v1/conversations/{pending.conversation_id}/messages'
    response = client.post(path, json={'content': 'new prompt'})
    assert response.status_code == 503
    assert conversations.get(owner_id='local', conversation_id=pending.conversation_id).context_preparation_id is None
    retry = client.post(path, json={'content': 'retry'})
    assert retry.status_code == 200 and 'response.completed' in retry.text


def test_overall_preparation_deadline_releases_lease_without_assistant(environment, monkeypatch):
    from personal_ai.context import deadline
    client, conversations, messages, _, llm, context = environment
    _, pending = install(environment, 'short-control')
    clock = [0.0]
    monkeypatch.setattr('personal_ai.services.chat_turns.monotonic', lambda: clock[0])
    monkeypatch.setattr(deadline, 'monotonic', lambda: clock[0])
    class Counter(FakeTokenCounter):
        def count(self, request):
            clock[0] += context.settings.request_timeout_seconds + 1
            return super().count(request)
    context.counter = Counter()
    response = client.post(f'/v1/conversations/{pending.conversation_id}/messages', json={'content': 'prompt'})
    assert response.status_code == 503 and response.json()['error']['code'] == 'llm_timeout'
    assert not llm.requests
    assert messages.list_active(owner_id='local', conversation_id=pending.conversation_id)[-1].role.value == 'user'
    assert conversations.get(owner_id='local', conversation_id=pending.conversation_id).context_preparation_id is None


def test_trace_persistence_deadline_releases_lease_before_model_call(environment, monkeypatch):
    from personal_ai.context import deadline
    from personal_ai.context.traces import InMemoryContextTraceRepository

    client, conversations, messages, _, llm, context = environment
    _, pending = install(environment, 'short-control')
    clock = [0.0]
    monkeypatch.setattr('personal_ai.services.chat_turns.monotonic', lambda: clock[0])
    monkeypatch.setattr(deadline, 'monotonic', lambda: clock[0])

    class SlowTraceRepository(InMemoryContextTraceRepository):
        def put(self, *, owner_id, trace, deadline=None):
            super().put(owner_id=owner_id, trace=trace, deadline=deadline)
            assert deadline == context.settings.request_timeout_seconds
            clock[0] = deadline + 1

    app.dependency_overrides[get_context_trace_repository] = lambda: SlowTraceRepository()
    response = client.post(
        f'/v1/conversations/{pending.conversation_id}/messages', json={'content': 'prompt'}
    )

    assert response.status_code == 503
    assert response.json()['error']['code'] == 'llm_timeout'
    assert not llm.requests
    assert messages.list_active(owner_id='local', conversation_id=pending.conversation_id)[-1].role.value == 'user'
    assert conversations.get(owner_id='local', conversation_id=pending.conversation_id).context_preparation_id is None


def test_historical_trace_schema_degrades_to_estimated_inspection(environment):
    client, _, _, _, _, _ = environment
    _, pending = install(environment, 'short-control')

    class HistoricalTraceRepository:
        def latest_for_user_turn(self, **_kwargs):
            raise UnsupportedContextTraceSchemaError("unsupported_context_trace_schema")

    app.dependency_overrides[get_context_trace_repository] = lambda: HistoricalTraceRepository()
    response = client.get(f'/v1/conversations/{pending.conversation_id}/context')

    assert response.status_code == 200
    assert response.json()['trace_state'] == 'historical_schema_unsupported'
    assert response.json()['trace_missing_reason'] == 'unsupported_historical_trace_schema'
    assert response.json()['actual_build_trace'] is None
    assert response.json()['view_kind'] == 'estimated_current_view'
