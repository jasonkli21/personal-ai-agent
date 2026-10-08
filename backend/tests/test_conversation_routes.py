"""Route tests for the Phase 1 conversation surface."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

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
from personal_ai.applications.contracts import ApplicationDefinition, CapabilityRegistration
from personal_ai.applications.registry import ApplicationRegistry
from personal_ai.context import ContextAssembler
from personal_ai.context.repositories import InMemorySummaryRepository
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.context.traces import InMemoryContextTraceRepository
from personal_ai.entities import (
    MAX_MESSAGE_CONTENT_CHARS,
    Conversation,
    Message,
    MessageRole,
    MessageStatus,
)
from personal_ai.llm import ChatMessage, FakeLLMClient, LLMTimeoutError
from personal_ai.main import app
from personal_ai.settings import Settings, get_settings
from personal_ai.storage import InMemoryConversationRepository, InMemoryMessageRepository
from personal_ai.storage.errors import StorageUnavailableError


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide a route client backed only by owner-scoped in-memory repositories."""
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    llm = FakeLLMClient(["Hello", " there"])
    summaries = InMemorySummaryRepository()
    traces = InMemoryContextTraceRepository()
    app.dependency_overrides = {
        get_summary_repository: lambda: summaries,
        get_context_trace_repository: lambda: traces,
        get_context_assembler: lambda: ContextAssembler(
            app.dependency_overrides[get_settings](), EstimatedTokenCounter(), summaries,
        ),
        get_conversation_repository: lambda: conversations,
        get_message_repository: lambda: messages,
        get_current_owner_id: lambda: "local",
        get_llm_client: lambda: llm,
        get_settings: lambda: Settings(
            ai_provider="gemini", ai_model="test-model", ai_api_key="test-key"
        ),
    }
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _sse_events(body: str) -> list[tuple[str, dict[str, object]]]:
    blocks = [block for block in body.strip().split("\n\n") if block]
    return [
        (block.split("\n", 1)[0].removeprefix("event: "), __import__("json").loads(block.split("\n", 1)[1].removeprefix("data: ")))
        for block in blocks
    ]


def test_create_list_and_get_empty_conversation(client: TestClient) -> None:
    """Routes create and retrieve empty conversations without invoking an LLM."""
    assert client.get("/v1/conversations").json() == {"conversations": []}

    created = client.post("/v1/conversations", json={})

    assert created.status_code == 201
    conversation = created.json()
    assert conversation["owner_id"] == "local"
    assert conversation["title"] == "New conversation"
    assert conversation["created_at"].endswith("Z")

    listed = client.get("/v1/conversations")
    detail = client.get(f"/v1/conversations/{conversation['id']}")

    assert listed.status_code == 200
    assert listed.json()["conversations"] == [conversation]
    assert detail.status_code == 200
    assert detail.json() == {"conversation": conversation, "messages": []}


def test_application_scope_isolated_and_client_owner_context_is_not_authority(
    client: TestClient,
) -> None:
    standalone_response = client.post("/v1/conversations", json={})
    travel_response = client.post(
        "/v1/conversations",
        json={},
        headers={
            "X-Application-ID": "travel",
            "X-Client-Context": '{"owner_id":"forged-owner"}',
        },
    )

    assert standalone_response.status_code == travel_response.status_code == 201
    standalone = standalone_response.json()
    travel = travel_response.json()
    assert standalone["owner_id"] == travel["owner_id"] == "local"
    assert standalone["application_id"] == "personal_ai"
    assert travel["application_id"] == "travel"
    assert client.get("/v1/conversations").json()["conversations"] == [standalone]
    assert client.get(f"/v1/conversations/{travel['id']}").status_code == 404
    assert client.get(
        f"/v1/conversations/{travel['id']}", headers={"X-Application-ID": "travel"}
    ).status_code == 200


def test_unknown_registered_application_is_denied_with_a_stable_error(
    client: TestClient,
) -> None:
    response = client.get(
        "/v1/conversations", headers={"X-Application-ID": "not-registered"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "application_not_registered"


def test_registered_synthetic_application_reaches_scoped_context_without_core_branching(
    client: TestClient, monkeypatch,
) -> None:
    definition = ApplicationDefinition(
        application_id="synthetic",
        display_name="Synthetic",
        memory_namespace="synthetic",
        context_provider_ids=("synthetic.context",),
    )
    capability = CapabilityRegistration(
        capability_id="synthetic.context",
        kind="context_provider",
        available=True,
    )
    registry = ApplicationRegistry((definition,), (capability,))
    monkeypatch.setattr(app.state, "application_registry", registry)
    context = app.dependency_overrides[get_context_assembler]()
    application_contexts = []
    original_assemble = context.assemble

    def record_application_context(*args, **kwargs):
        application_contexts.append(kwargs.get("application_context"))
        return original_assemble(*args, **kwargs)

    monkeypatch.setattr(context, "assemble", record_application_context)
    app.dependency_overrides[get_context_assembler] = lambda: context

    conversation_response = client.post(
        "/v1/conversations", json={}, headers={"X-Application-ID": "synthetic"}
    )
    assert conversation_response.status_code == 201
    conversation = conversation_response.json()
    message_response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "hello from a registered app"},
        headers={"X-Application-ID": "synthetic"},
    )

    assert message_response.status_code == 200
    assert application_contexts[0].definition.application_id == "synthetic"
    assert application_contexts[0].scope.application_id == "synthetic"
    assert application_contexts[0].scope.owner_id == "local"


def test_chat_creation_and_terminal_events_use_the_persisted_scope(client: TestClient) -> None:
    conversation = client.post(
        "/v1/conversations", json={}, headers={"X-Application-ID": "travel"}
    ).json()
    response = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        json={"content": "Hello"},
        headers={"X-Application-ID": "travel", "X-Request-ID": "scope-event-test"},
    )
    assert response.status_code == 200
    events = _sse_events(response.text)
    created = [payload["message"] for name, payload in events if name == "message.created"]
    terminal = [payload["message"] for name, payload in events if name == "response.completed"]
    assert len(created) == 2
    assert len(terminal) == 1
    assert all(item["application_id"] == "travel" and item["scope_version"] == 2
               for item in (*created, *terminal))


def test_workspace_scope_fails_closed_without_membership_authority(client: TestClient) -> None:
    response = client.post(
        "/v1/conversations", json={}, headers={"X-Workspace-ID": "team-a"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "workspace_not_authorized"


def test_get_returns_only_active_path(client: TestClient) -> None:
    """The detail route does not expose superseded branch history."""
    conversations = app.dependency_overrides[get_conversation_repository]()
    messages = app.dependency_overrides[get_message_repository]()
    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid4(),
        owner_id="local",
        title="Active branch",
        created_at=now,
        updated_at=now,
    )
    user = Message(
        id=uuid4(),
        conversation_id=conversation.id,
        owner_id="local",
        role=MessageRole.USER,
        content="Hello",
        status=MessageStatus.COMPLETED,
        created_at=now,
    )
    obsolete = Message(
        id=uuid4(),
        conversation_id=conversation.id,
        owner_id="local",
        role=MessageRole.ASSISTANT,
        content="Old answer",
        status=MessageStatus.SUPERSEDED,
        created_at=now,
        parent_message_id=user.id,
    )
    replacement = obsolete.model_copy(
        update={"id": uuid4(), "content": "Current answer", "status": MessageStatus.COMPLETED}
    )
    conversations.create(conversation)
    for message in (user, obsolete, replacement):
        messages.create(message)

    response = client.get(f"/v1/conversations/{conversation.id}")

    assert response.status_code == 200
    assert [message["content"] for message in response.json()["messages"]] == [
        "Hello",
        "Current answer",
    ]


@pytest.mark.parametrize("identifier", ["not-a-uuid", str(uuid4())])
def test_get_rejects_malformed_and_unknown_conversation_ids(
    client: TestClient, identifier: str
) -> None:
    """Malformed and unknown IDs have stable, safe client responses."""
    response = client.get(f"/v1/conversations/{identifier}")

    if identifier == "not-a-uuid":
        assert response.status_code == 422
        assert response.json() == {
            "error": {"code": "validation_error", "message": "Request validation failed."}
        }
    else:
        assert response.status_code == 404
        assert response.json() == {
            "error": {"code": "not_found", "message": "The requested resource was not found."}
        }


def test_routes_do_not_return_another_owners_conversation(client: TestClient) -> None:
    """Repository-level ownership isolation is preserved at the HTTP boundary."""
    conversations = app.dependency_overrides[get_conversation_repository]()
    now = datetime.now(UTC)
    private = Conversation(
        id=uuid4(),
        owner_id="another-owner",
        title="Private",
        created_at=now,
        updated_at=now,
    )
    conversations.create(private)

    assert client.get("/v1/conversations").json() == {"conversations": []}
    assert client.get(f"/v1/conversations/{private.id}").status_code == 404


def test_storage_failures_have_safe_json_error_response(client: TestClient) -> None:
    """Infrastructure failure details never appear in the API response."""

    class FailingRepository(InMemoryConversationRepository):
        def list(self, *, owner_id: str, limit: int = 50) -> list[Conversation]:
            raise StorageUnavailableError("sensitive backend detail")

    app.dependency_overrides[get_conversation_repository] = FailingRepository

    response = client.get("/v1/conversations")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "storage_unavailable",
            "message": "Storage is temporarily unavailable.",
        }
    }


def test_message_turn_streams_and_persists_completed_response(client: TestClient) -> None:
    conversation = client.post("/v1/conversations", json={}).json()

    response = client.post(f"/v1/conversations/{conversation['id']}/messages", json={"content": "Hi"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    events = _sse_events(response.text)
    assert [event for event, _ in events] == [
        "message.created", "message.created", "response.delta", "response.delta", "response.completed"
    ]
    completed = events[-1][1]["message"]
    assert completed["content"] == "Hello there"
    assert completed["status"] == "completed"
    detail = client.get(f"/v1/conversations/{conversation['id']}").json()
    assert [message["content"] for message in detail["messages"]] == ["Hi", "Hello there"]


def test_regenerate_and_edit_retry_replace_the_active_path(client: TestClient) -> None:
    conversation_id = client.post("/v1/conversations", json={}).json()["id"]
    first = client.post(f"/v1/conversations/{conversation_id}/messages", json={"content": "first"})
    first_events = _sse_events(first.text)
    assistant_id = first_events[-1][1]["message"]["id"]

    regenerated = client.post(f"/v1/conversations/{conversation_id}/messages/{assistant_id}/regenerate")
    assert [event for event, _ in _sse_events(regenerated.text)] == [
        "message.created", "response.delta", "response.delta", "response.completed"
    ]
    user_id = client.get(f"/v1/conversations/{conversation_id}").json()["messages"][0]["id"]
    retried = client.post(
        f"/v1/conversations/{conversation_id}/messages/{user_id}/edit-and-retry",
        json={"content": "edited"},
    )
    assert [event for event, _ in _sse_events(retried.text)] == [
        "message.created", "message.created", "response.delta", "response.delta", "response.completed"
    ]
    detail = client.get(f"/v1/conversations/{conversation_id}").json()
    assert [message["content"] for message in detail["messages"]] == ["edited", "Hello there"]


def test_model_failure_is_streamed_once_and_persisted(client: TestClient) -> None:
    class FailingLLM:
        async def stream_events(
            self,
            _: object,
            *,
            max_output_tokens,
            timeout_seconds,
            inference_context=None,
        ):
            del max_output_tokens, timeout_seconds
            del inference_context
            raise LLMTimeoutError("provider timeout")
            yield ""  # pragma: no cover

    app.dependency_overrides[get_llm_client] = FailingLLM
    conversation_id = client.post("/v1/conversations", json={}).json()["id"]

    response = client.post(f"/v1/conversations/{conversation_id}/messages", json={"content": "Hi"})

    events = _sse_events(response.text)
    assert [event for event, _ in events] == ["message.created", "message.created", "response.error"]
    assert events[-1][1]["code"] == "llm_timeout"
    detail = client.get(f"/v1/conversations/{conversation_id}").json()
    assert detail["messages"][-1]["status"] == "failed"
    assert detail["messages"][-1]["error_code"] == "llm_timeout"


def test_oversized_model_response_is_rejected_without_persisting_it(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        ai_provider="fake",
        ai_model="fake-model",
        max_context_tokens=70_000,
        max_response_tokens=MAX_MESSAGE_CONTENT_CHARS,
    )
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient(
        ["partial", "x" * MAX_MESSAGE_CONTENT_CHARS]
    )
    conversation_id = client.post("/v1/conversations", json={}).json()["id"]

    response = client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"content": "Hi"}
    )

    events = _sse_events(response.text)
    assert [event for event, _ in events][-1] == "response.error"
    assert events[-1][1]["code"] == "llm_invalid_response"
    detail = client.get(f"/v1/conversations/{conversation_id}").json()
    failed = detail["messages"][-1]
    assert failed["status"] == "failed"
    assert failed["content"] == "partial"
    assert len(failed["content"]) <= MAX_MESSAGE_CONTENT_CHARS


def test_message_count_cap_is_replaced_by_context_budget(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        ai_provider="gemini", ai_model="test-model", max_phase_1_history_messages=1,
    )
    conversation_id = client.post("/v1/conversations", json={}).json()["id"]
    for content in ("first", "second"):
        response = client.post(f"/v1/conversations/{conversation_id}/messages", json={"content": content})
        assert response.status_code == 200
        assert _sse_events(response.text)[-1][0] == "response.completed"


@pytest.mark.parametrize("deltas", [[], [" \t\n"]])
def test_empty_or_whitespace_model_output_fails_and_keeps_next_turn_usable(
    client: TestClient, deltas: list[str]
) -> None:
    llm = FakeLLMClient(deltas)
    app.dependency_overrides[get_llm_client] = lambda: llm
    conversation_id = client.post("/v1/conversations", json={}).json()["id"]

    first = client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"content": "first"}
    )

    events = _sse_events(first.text)
    assert events[-1][0] == "response.error"
    assert events[-1][1]["code"] == "llm_invalid_response"
    detail = client.get(f"/v1/conversations/{conversation_id}").json()
    failed = detail["messages"][-1]
    assert failed["status"] == "failed"
    assert failed["error_code"] == "llm_invalid_response"

    next_llm = FakeLLMClient(["usable"])
    app.dependency_overrides[get_llm_client] = lambda: next_llm
    second = client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"content": "second"}
    )
    assert _sse_events(second.text)[-1][0] == "response.completed"
    assert next_llm.requests == [
        (
            ChatMessage(role=MessageRole.USER, content="second"),
        )
    ]


def test_regenerate_and_edit_retry_send_only_the_replacement_active_prefix(
    client: TestClient,
) -> None:
    llm = FakeLLMClient(["answer"])
    app.dependency_overrides[get_llm_client] = lambda: llm
    conversation_id = client.post("/v1/conversations", json={}).json()["id"]
    first = client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"content": "first"}
    )
    first_assistant_id = _sse_events(first.text)[-1][1]["message"]["id"]
    client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"content": "second"}
    )
    assert len(llm.requests) == 2

    regenerated = client.post(
        f"/v1/conversations/{conversation_id}/messages/{first_assistant_id}/regenerate"
    )
    assert _sse_events(regenerated.text)[-1][0] == "response.completed"
    assert llm.requests[2] == (ChatMessage(role=MessageRole.USER, content="first"),)

    first_user_id = client.get(f"/v1/conversations/{conversation_id}").json()["messages"][0]["id"]
    edited = client.post(
        f"/v1/conversations/{conversation_id}/messages/{first_user_id}/edit-and-retry",
        json={"content": "edited"},
    )
    assert _sse_events(edited.text)[-1][0] == "response.completed"
    assert llm.requests[3] == (ChatMessage(role=MessageRole.USER, content="edited"),)


def test_edit_and_retry_capacity_uses_the_replacement_prefix(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        ai_provider="gemini",
        ai_model="test-model",
        ai_api_key="test-key",
        max_phase_1_history_messages=3,
    )
    conversation_id = client.post("/v1/conversations", json={}).json()["id"]
    first = client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"content": "first"}
    )
    first_user_id = _sse_events(first.text)[0][1]["message"]["id"]
    client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"content": "second"}
    )

    edited = client.post(
        f"/v1/conversations/{conversation_id}/messages/{first_user_id}/edit-and-retry",
        json={"content": "short replacement"},
    )

    assert edited.status_code == 200
    assert _sse_events(edited.text)[-1][0] == "response.completed"


def test_concurrent_mutation_returns_conflict_and_preserves_the_active_turn(
    client: TestClient,
) -> None:
    conversation_id = client.post("/v1/conversations", json={}).json()["id"]
    conversations = app.dependency_overrides[get_conversation_repository]()
    messages = app.dependency_overrides[get_message_repository]()
    now = datetime.now(UTC)
    user = Message(
        id=uuid4(),
        conversation_id=UUID(conversation_id),
        owner_id="local",
        role=MessageRole.USER,
        content="first",
        status=MessageStatus.COMPLETED,
        created_at=now,
    )
    assistant = Message(
        id=uuid4(),
        conversation_id=UUID(conversation_id),
        owner_id="local",
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
        created_at=now,
        parent_message_id=user.id,
    )
    conversations.get(owner_id="local", conversation_id=UUID(conversation_id))
    messages.create(user)
    messages.create(assistant)

    response = client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"content": "second"}
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "conversation_busy",
            "message": "A response is already in progress. Please retry.",
        }
    }
    active = client.get(f"/v1/conversations/{conversation_id}").json()["messages"]
    assert [message["content"] for message in active] == ["first", ""]
