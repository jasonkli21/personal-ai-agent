"""Deterministic integration coverage for streaming response teardown."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock
from uuid import uuid4

import pytest
from starlette.requests import ClientDisconnect

from personal_ai.api.dependencies import (
    get_chat_turn_service,
    get_conversation_repository,
    get_current_owner_id,
    get_llm_client,
    get_message_repository,
    get_settings,
)
from personal_ai.applications.contracts import ApplicationContextRequest
from personal_ai.applications.registry import default_application_registry
from personal_ai.auth.scope import RequestScope
from personal_ai.context import ContextAssembler
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.entities import Conversation, Message, MessageRole, MessageStatus
from personal_ai.llm import (
    GenerationEvent,
    GenerationMetadata,
    LLMTimeoutError,
    ProviderIdentity,
    UsageMetadata,
)
from personal_ai.main import app
from personal_ai.services import ChatTurnService
from personal_ai.settings import Settings
from personal_ai.storage import (
    ConversationConflictError,
    InMemoryConversationRepository,
    InMemoryMessageRepository,
    StorageUnavailableError,
)


class ControlledLLM:
    """Fake provider with explicit wait and iterator-finalization signals."""

    requires_inference_context = False

    def __init__(self, *, wait_after_first: bool = False, fail_after_first: bool = False) -> None:
        self.wait_after_first = wait_after_first
        self.fail_after_first = fail_after_first
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()
        self.finalized = False
        self.started = False

    async def stream_events(
        self,
        _: object,
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context=None,
    ) -> AsyncIterator[GenerationEvent]:
        del inference_context
        assert max_output_tokens > 0 and timeout_seconds > 0
        self.started = True
        try:
            if self.fail_after_first:
                raise LLMTimeoutError("private provider detail")
            yield GenerationEvent.text_delta("partial")
            if self.wait_after_first:
                self.waiting.set()
                await self.release.wait()
                yield GenerationEvent.text_delta(" never")
            yield GenerationEvent.terminal(
                GenerationMetadata(
                    status="success",
                    identity=ProviderIdentity("synthetic", "test-model", "synthetic-v1"),
                    usage=UsageMetadata(
                        input_tokens=3,
                        output_tokens=2,
                        total_tokens=5,
                        source="estimated",
                        confidence="estimated",
                    ),
                )
            )
        finally:
            await asyncio.sleep(0)
            self.finalized = True


class SnapshotBarrierMessages(InMemoryMessageRepository):
    """Make concurrent callers prepare from the same deterministic snapshot."""

    def __init__(self, conversations: InMemoryConversationRepository) -> None:
        super().__init__(conversations)
        self.barrier = Barrier(2)
        self._barrier_lock = Lock()
        self._barrier_calls = 0

    def list_active(self, *, owner_id: str, conversation_id):  # type: ignore[no-untyped-def]
        result = super().list_active(owner_id=owner_id, conversation_id=conversation_id)
        with self._barrier_lock:
            wait_for_pair = self._barrier_calls < 2
            self._barrier_calls += 1
        if wait_for_pair:
            self.barrier.wait(timeout=2)
        return result


def _install_dependencies(llm: ControlledLLM):
    previous = app.dependency_overrides.copy()
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    conversation = Conversation(
        id=uuid4(),
        owner_id="local",
        title="Lifecycle test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    conversations.create(conversation)
    app.dependency_overrides = {
        get_settings: lambda: Settings(ai_provider="fake", ai_model="test"),
        get_conversation_repository: lambda: conversations,
        get_message_repository: lambda: messages,
        get_current_owner_id: lambda: "local",
        get_llm_client: lambda: llm,
        get_chat_turn_service: lambda: ChatTurnService(
            conversations,
            messages,
            llm,
            owner_id="local",
            model="test-model",
            context_assembler=ContextAssembler(
                Settings(ai_provider="gemini", ai_model="test"), EstimatedTokenCounter()
            ),
        ),
    }
    return previous, conversations, messages, conversation


def _scope(conversation_id, spec_version: str) -> dict[str, object]:  # type: ignore[no-untyped-def]
    path = f"/v1/conversations/{conversation_id}/messages"
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"x-request-id", b"lifecycle-test"),
        ],
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
        "state": {},
    }


async def _invoke_asgi(
    conversation_id,
    llm: ControlledLLM,
    *,
    spec_version: str,
    disconnect_after_body: int | None = None,
    disconnect_when_provider_waits: bool = False,
    fail_on_start: bool = False,
) -> list[dict[str, object]]:
    sent: list[dict[str, object]] = []
    disconnect = asyncio.Event()
    request_delivered = False
    body_count = 0

    async def receive() -> dict[str, object]:
        nonlocal request_delivered
        if not request_delivered:
            request_delivered = True
            return {
                "type": "http.request",
                "body": b'{"content":"hello"}',
                "more_body": False,
            }
        if disconnect_when_provider_waits:
            await llm.waiting.wait()
            return {"type": "http.disconnect"}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        nonlocal body_count
        if message["type"] == "http.response.start" and fail_on_start:
            raise OSError("synthetic response start failure")
        if message["type"] == "http.response.body":
            body_count += 1
            if disconnect_after_body == body_count:
                if spec_version == "2.4":
                    raise OSError("synthetic client disconnect")
                disconnect.set()
                await asyncio.Event().wait()
        sent.append(message)

    try:
        await asyncio.wait_for(app(_scope(conversation_id, spec_version), receive, send), timeout=2)
    except (OSError, ClientDisconnect):
        if disconnect_after_body is None and not fail_on_start:
            raise
    return sent


def _active_assistant(messages: InMemoryMessageRepository, conversation_id):  # type: ignore[no-untyped-def]
    active = messages.list_active(owner_id="local", conversation_id=conversation_id)
    return next(message for message in active if message.role is MessageRole.ASSISTANT)


@pytest.mark.parametrize("body_number", [1, 2, 3])
def test_asgi_24_send_failure_marks_partial_turn_failed_and_closes_provider(
    body_number: int,
) -> None:
    llm = ControlledLLM()
    previous, _, messages, conversation = _install_dependencies(llm)
    try:
        asyncio.run(
            _invoke_asgi(
                conversation.id,
                llm,
                spec_version="2.4",
                disconnect_after_body=body_number,
            )
        )
        assistant = _active_assistant(messages, conversation.id)
        assert assistant.status is MessageStatus.FAILED
        assert assistant.error_code == "client_cancelled"
        assert assistant.content == ("partial" if body_number == 3 else "")
        assert llm.finalized is (body_number == 3)
    finally:
        app.dependency_overrides = previous


@pytest.mark.parametrize("body_number", [1, 3])
def test_asgi_23_disconnect_during_initial_or_delta_send_fails_turn(body_number: int) -> None:
    llm = ControlledLLM()
    previous, _, messages, conversation = _install_dependencies(llm)
    try:
        asyncio.run(
            _invoke_asgi(
                conversation.id,
                llm,
                spec_version="2.3",
                disconnect_after_body=body_number,
            )
        )
        assistant = _active_assistant(messages, conversation.id)
        assert assistant.status is MessageStatus.FAILED
        assert assistant.error_code == "client_cancelled"
        assert assistant.content == ("partial" if body_number == 3 else "")
        assert llm.finalized is (body_number == 3)
    finally:
        app.dependency_overrides = previous


def test_asgi_23_disconnect_while_provider_waits_cancels_provider_and_persists_partial() -> None:
    llm = ControlledLLM(wait_after_first=True)
    previous, _, messages, conversation = _install_dependencies(llm)
    try:
        asyncio.run(
            _invoke_asgi(
                conversation.id,
                llm,
                spec_version="2.3",
                disconnect_when_provider_waits=True,
            )
        )
        assistant = _active_assistant(messages, conversation.id)
        assert assistant.status is MessageStatus.FAILED
        assert assistant.error_code == "client_cancelled"
        assert assistant.content == "partial"
        assert llm.finalized
    finally:
        app.dependency_overrides = previous


def test_response_start_failure_before_iteration_finalizes_placeholder() -> None:
    llm = ControlledLLM()
    previous, _, messages, conversation = _install_dependencies(llm)
    try:
        asyncio.run(
            _invoke_asgi(
                conversation.id,
                llm,
                spec_version="2.4",
                fail_on_start=True,
            )
        )
        assistant = _active_assistant(messages, conversation.id)
        assert assistant.status is MessageStatus.FAILED
        assert assistant.error_code == "client_cancelled"
        assert assistant.content == ""
        assert not llm.started
    finally:
        app.dependency_overrides = previous


def test_disconnect_after_completed_event_does_not_overwrite_completion() -> None:
    llm = ControlledLLM()
    previous, _, messages, conversation = _install_dependencies(llm)
    try:
        asyncio.run(
            _invoke_asgi(
                conversation.id,
                llm,
                spec_version="2.4",
                disconnect_after_body=4,
            )
        )
        assistant = _active_assistant(messages, conversation.id)
        assert assistant.status is MessageStatus.COMPLETED
        assert assistant.content == "partial"
        assert assistant.error_code is None
    finally:
        app.dependency_overrides = previous


def test_disconnect_after_error_event_does_not_overwrite_provider_failure() -> None:
    llm = ControlledLLM(fail_after_first=True)
    previous, _, messages, conversation = _install_dependencies(llm)
    try:
        asyncio.run(
            _invoke_asgi(
                conversation.id,
                llm,
                spec_version="2.4",
                disconnect_after_body=3,
            )
        )
        assistant = _active_assistant(messages, conversation.id)
        assert assistant.status is MessageStatus.FAILED
        assert assistant.error_code == "llm_timeout"
        assert assistant.content == ""
    finally:
        app.dependency_overrides = previous


def test_concurrent_sends_from_one_snapshot_only_prepare_one_turn() -> None:
    llm = ControlledLLM()
    conversations = InMemoryConversationRepository()
    conversation = Conversation(
        id=uuid4(),
        owner_id="local",
        title="Concurrent test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    conversations.create(conversation)
    messages = SnapshotBarrierMessages(conversations)
    service = ChatTurnService(
        conversations,
        messages,
        llm,
        owner_id="local",
        model="test-model",
        context_assembler=ContextAssembler(
            Settings(ai_provider="gemini", ai_model="test"), EstimatedTokenCounter()
        ),
    )

    def prepare(request_id: str):
        try:
            return service.send(conversation.id, request_id, request_id=request_id)
        except ConversationConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(prepare, ("first", "second")))

    assert sum(isinstance(result, ConversationConflictError) for result in results) == 1
    assert len(messages.list_active(owner_id="local", conversation_id=conversation.id)) == 2


def test_stale_stream_is_recovered_before_a_new_turn_is_prepared() -> None:
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid4(),
        owner_id="local",
        title="Recovered test",
        created_at=now,
        updated_at=now,
    )
    conversations.create(conversation)
    old_user = Message(
        id=uuid4(),
        conversation_id=conversation.id,
        owner_id="local",
        role=MessageRole.USER,
        content="old prompt",
        status=MessageStatus.COMPLETED,
        created_at=now - timedelta(minutes=10),
    )
    stale_assistant = Message(
        id=uuid4(),
        conversation_id=conversation.id,
        owner_id="local",
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
        created_at=now - timedelta(minutes=10),
        parent_message_id=old_user.id,
    )
    messages.create(old_user)
    messages.create(stale_assistant)
    service = ChatTurnService(
        conversations,
        messages,
        ControlledLLM(),
        owner_id="local",
        model="test-model",
        context_assembler=ContextAssembler(
            Settings(ai_provider="gemini", ai_model="test"), EstimatedTokenCounter()
        ),
    )

    stream = service.send(conversation.id, "new prompt", request_id="recovered")

    async def drain() -> None:
        async for _ in stream:
            pass

    asyncio.run(drain())
    stored_stale = messages.get(
        owner_id="local",
        conversation_id=conversation.id,
        message_id=stale_assistant.id,
    )
    active = messages.list_active(owner_id="local", conversation_id=conversation.id)
    assert stored_stale.status is MessageStatus.FAILED
    assert stored_stale.error_code == "turn_interrupted"
    assert active[-1].status is MessageStatus.COMPLETED


@pytest.mark.parametrize("operation", ["send", "regenerate", "edit"])
def test_failed_turn_preparation_preserves_existing_active_history(operation: str) -> None:
    class FailingPrepareMessages(InMemoryMessageRepository):
        def prepare_message_turn(self, **_: object) -> list[Message]:
            raise StorageUnavailableError("synthetic transaction failure")

    conversations = InMemoryConversationRepository()
    conversation = Conversation(
        id=uuid4(),
        owner_id="local",
        title="Atomic test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    conversations.create(conversation)
    messages = FailingPrepareMessages(conversations)
    original: list[Message] = []
    target_id = uuid4()
    if operation != "send":
        now = datetime.now(UTC)
        user = Message(
            id=target_id if operation == "edit" else uuid4(),
            conversation_id=conversation.id,
            owner_id="local",
            role=MessageRole.USER,
            content="original prompt",
            status=MessageStatus.COMPLETED,
            created_at=now,
        )
        assistant = Message(
            id=target_id if operation == "regenerate" else uuid4(),
            conversation_id=conversation.id,
            owner_id="local",
            role=MessageRole.ASSISTANT,
            content="original answer",
            status=MessageStatus.COMPLETED,
            created_at=now + timedelta(seconds=1),
            parent_message_id=user.id,
        )
        messages.create(user)
        messages.create(assistant)
        original = [user, assistant]
    service = ChatTurnService(
        conversations,
        messages,
        ControlledLLM(),
        owner_id="local",
        model="test-model",
        context_assembler=ContextAssembler(
            Settings(ai_provider="gemini", ai_model="test"), EstimatedTokenCounter()
        ),
    )

    with pytest.raises(StorageUnavailableError):
        if operation == "send":
            service.send(conversation.id, "new prompt", request_id="failed-prep")
        elif operation == "regenerate":
            service.regenerate(conversation.id, target_id, request_id="failed-prep")
        else:
            service.edit_and_retry(conversation.id, target_id, "edited", request_id="failed-prep")

    active = messages.list_active(owner_id="local", conversation_id=conversation.id)
    assert [item.id for item in active] == [item.id for item in original]
    assert all(item.status is not MessageStatus.STREAMING for item in active)


def test_streaming_request_conflict_does_not_append_another_turn() -> None:
    llm = ControlledLLM()
    previous, _, messages, conversation = _install_dependencies(llm)
    try:
        service = app.dependency_overrides[get_chat_turn_service]()
        original = service.send(conversation.id, "first", request_id="first")
        before = messages.list_active(owner_id="local", conversation_id=conversation.id)
        with pytest.raises(ConversationConflictError):
            service.send(conversation.id, "second", request_id="second")
        after = messages.list_active(owner_id="local", conversation_id=conversation.id)
        assert [item.id for item in after] == [item.id for item in before]
        asyncio.run(original.aclose())
        assert _active_assistant(messages, conversation.id).status is MessageStatus.FAILED
    finally:
        app.dependency_overrides = previous


def test_streaming_body_has_no_provider_exception_detail() -> None:
    """The actual event stream keeps provider exception text out of its body."""
    llm = ControlledLLM(fail_after_first=True)
    previous, _, messages, conversation = _install_dependencies(llm)
    try:
        sent = asyncio.run(_invoke_asgi(conversation.id, llm, spec_version="2.4"))
        body = b"".join(
            message.get("body", b"") for message in sent if message["type"] == "http.response.body"
        ).decode()
        assert "private provider detail" not in body
        assert "llm_timeout" in body
        assistant = _active_assistant(messages, conversation.id)
        assert assistant.status is MessageStatus.FAILED
    finally:
        app.dependency_overrides = previous


def test_gemini_timeout_after_first_delta_finalizes_partial_turn() -> None:
    """SDK timeout scopes must remain in one task across service-driven yields."""
    from types import SimpleNamespace

    from personal_ai.llm import GeminiLLMClient
    from personal_ai.llm.context import GeminiTokenCounter

    class ProviderStream:
        finalized = False

        async def __aiter__(self):
            try:
                yield SimpleNamespace(text="partial")
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                self.finalized = True

    provider = ProviderStream()

    class Models:
        async def generate_content_stream(self, **_: object) -> ProviderStream:
            return provider

    llm = GeminiLLMClient(
        Settings(
            ai_provider="gemini",
            ai_model="test",
            ai_api_key="test-key",
            request_timeout_seconds=0.02,
        ),
        client=SimpleNamespace(aio=SimpleNamespace(models=Models())),
    )
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid4(),
        owner_id="local",
        title="Timeout test",
        created_at=now,
        updated_at=now,
    )
    conversations.create(conversation)
    registry = default_application_registry()
    registration = registry.registration("personal_ai")
    application_context = ApplicationContextRequest(
        definition=registration.definition,
        scope=RequestScope(
            owner_id="local", request_id="gemini-timeout-test", application_id="personal_ai"
        ),
        context_provider_capabilities=registration.context_providers,
        tool_capabilities=registration.tools,
    )
    class Api:
        def request(self, *args, **kwargs):
            del args, kwargs
            return SimpleNamespace(body='{"totalTokens":3}')

    test_settings = Settings(ai_provider="gemini", ai_model="test")
    service = ChatTurnService(
        conversations,
        messages,
        llm,
        owner_id="local",
        application_context=application_context,
        model="test",
        context_assembler=ContextAssembler(
            test_settings,
            GeminiTokenCounter(test_settings, client=SimpleNamespace(_api_client=Api())),
        ),
    )

    async def scenario() -> list[str]:
        async def collect() -> list[str]:
            return [
                frame
                async for frame in service.send(
                    conversation.id,
                    "Hello",
                    request_id="timeout-regression",
                )
            ]

        return await asyncio.wait_for(collect(), timeout=2)

    frames = asyncio.run(scenario())
    assert any("event: response.delta" in frame for frame in frames)
    assert "event: response.error" in frames[-1]
    assert '"code":"llm_timeout"' in frames[-1]
    assistant = _active_assistant(messages, conversation.id)
    assert assistant.status is MessageStatus.FAILED
    assert assistant.content == "partial"
    assert assistant.error_code == "llm_timeout"
    assert provider.finalized


@pytest.mark.parametrize("violation", ["trailing_delta", "duplicate_terminal", "exception", "stalled"])
def test_chat_rejects_data_or_errors_after_terminal_without_persisting_success(violation):
    class MalformedLLM:
        requires_inference_context = False

        def __init__(self):
            self.finalized = False

        async def stream_events(
            self, messages, *, max_output_tokens, timeout_seconds, inference_context=None
        ):
            del messages, max_output_tokens, timeout_seconds, inference_context
            metadata = GenerationMetadata(
                status="success",
                identity=ProviderIdentity("synthetic", "malformed-stream", "fixture-v1"),
            )
            try:
                yield GenerationEvent.text_delta("partial")
                yield GenerationEvent.terminal(metadata)
                if violation == "trailing_delta":
                    yield GenerationEvent.text_delta("tail")
                elif violation == "duplicate_terminal":
                    yield GenerationEvent.terminal(metadata)
                elif violation == "exception":
                    raise RuntimeError("private provider error")
                elif violation == "stalled":
                    await asyncio.Event().wait()
            finally:
                self.finalized = True

    llm = MalformedLLM()
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid4(), owner_id="local", title="Protocol test", created_at=now, updated_at=now
    )
    conversations.create(conversation)
    settings = Settings(ai_provider="fake", ai_model="test", request_timeout_seconds=0.05)
    service = ChatTurnService(
        conversations,
        messages,
        llm,
        owner_id="local",
        model="test",
        context_assembler=ContextAssembler(settings, EstimatedTokenCounter()),
    )

    async def collect():
        return [
            frame
            async for frame in service.send(
                conversation.id, "hello", request_id=f"protocol-{violation}"
            )
        ]

    frames = asyncio.run(collect())
    assistant = _active_assistant(messages, conversation.id)
    assert llm.finalized
    if violation == "stalled":
        assert '"code":"llm_timeout"' in frames[-1]
    elif violation == "exception":
        assert '"code":"llm_unavailable"' in frames[-1]
    else:
        assert '"code":"llm_invalid_response"' in frames[-1]
    assert assistant.status is MessageStatus.FAILED
    assert assistant.content == "partial"


@pytest.mark.parametrize("provider_fails", [False, True])
def test_terminal_persistence_runs_outside_the_request_event_loop(monkeypatch, provider_fails):
    llm = ControlledLLM(fail_after_first=provider_fails)
    previous, _, messages, conversation = _install_dependencies(llm)
    original_update = messages.update_status
    transitions = []

    def update_status(**kwargs):
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        transitions.append(kwargs["status"])
        return original_update(**kwargs)

    monkeypatch.setattr(messages, "update_status", update_status)
    try:
        asyncio.run(_invoke_asgi(conversation.id, llm, spec_version="2.4"))
    finally:
        app.dependency_overrides = previous
    expected = MessageStatus.FAILED if provider_fails else MessageStatus.COMPLETED
    assert transitions == [expected]
    assert _active_assistant(messages, conversation.id).status is expected
