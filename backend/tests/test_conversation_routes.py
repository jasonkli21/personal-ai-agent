"""Route tests for the non-streaming Phase 1 conversation surface."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from personal_ai.api.dependencies import (
    get_conversation_repository,
    get_current_owner_id,
    get_llm_client,
    get_message_repository,
)
from personal_ai.entities import Conversation, Message, MessageRole, MessageStatus
from personal_ai.llm import FakeLLMClient, LLMTimeoutError
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
    app.dependency_overrides = {
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
        async def stream(self, _: object):
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


def test_history_cap_instructs_the_user_to_start_a_new_chat(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        ai_provider="gemini", ai_model="test-model", ai_api_key="test-key", max_phase_1_history_messages=1
    )
    conversation_id = client.post("/v1/conversations", json={}).json()["id"]
    assert client.post(
        f"/v1/conversations/{conversation_id}/messages", json={"content": "first"}
    ).status_code == 200

    response = client.post(f"/v1/conversations/{conversation_id}/messages", json={"content": "second"})

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "history_limit_exceeded", "message": "Please start a new chat."}
    }
