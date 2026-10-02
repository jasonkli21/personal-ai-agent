"""Durable Phase 1 chat-turn lifecycle and server-sent event payloads."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID, uuid4

import anyio

from personal_ai.api.schemas import (
    SSEMessageCreated,
    SSEResponseCompleted,
    SSEResponseDelta,
    SSEResponseError,
)
from personal_ai.context import ContextAssembler
from personal_ai.context.deadline import remaining
from personal_ai.entities import MAX_MESSAGE_CONTENT_CHARS, Message, MessageRole, MessageStatus
from personal_ai.llm import ChatMessage, LLMClient, LLMError, LLMInvalidResponseError
from personal_ai.storage import ConversationConflictError
from personal_ai.storage.repositories import ConversationRepository, MessageRepository

logger = logging.getLogger(__name__)


class InvalidRetryTargetError(Exception):
    """A regenerate or edit-and-retry target is not in a retryable state."""


@dataclass(frozen=True, slots=True)
class _PreparedTurn:
    created: tuple[Message, ...]
    assistant: Message
    history: tuple[ChatMessage, ...]
    request_id: str
    selected_memory_ids: tuple[UUID, ...] = ()


class _ManagedStream:
    """Async iterator that finalizes a prepared turn when abandoned before start."""

    def __init__(self, iterator: AsyncIterator[str], on_abandon: Callable[[], object]) -> None:
        self._iterator = iterator.__aiter__()
        self._on_abandon = on_abandon
        self._on_terminal_sent: Callable[[], object] | None = None
        self._terminal_notified = False
        self._started = False
        self._closed = False

    def __aiter__(self) -> _ManagedStream:
        return self

    async def __anext__(self) -> str:
        if self._closed:
            raise StopAsyncIteration
        self._started = True
        try:
            return await self._iterator.__anext__()
        except StopAsyncIteration:
            self._closed = True
            raise

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._started:
            close = getattr(self._iterator, "aclose", None)
            if close is not None:
                await close()
        else:
            self._on_abandon()

    def set_terminal_callback(self, callback: Callable[[], object]) -> None:
        self._on_terminal_sent = callback

    def terminal_sent(self) -> None:
        if self._terminal_notified:
            return
        self._terminal_notified = True
        if self._on_terminal_sent is not None:
            self._on_terminal_sent()


class ChatTurnService:
    """Create append-only turns, stream model output, and finalize state."""

    def __init__(
        self,
        conversations: ConversationRepository,
        messages: MessageRepository,
        llm: LLMClient,
        *,
        owner_id: str,
        model: str,
        stale_stream_after_seconds: float = 360,
        context_assembler: ContextAssembler,
        memory_retriever=None,
        memory_extraction=None,
        memory_lifecycle=None,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._llm = llm
        self._owner_id = owner_id
        self._context = context_assembler
        self._memory_retriever = memory_retriever
        self._memory_extraction = memory_extraction
        self._memory_lifecycle = memory_lifecycle
        self._post_completion_tasks: set[asyncio.Task[None]] = set()
        self._model = model
        self._stale_stream_after_seconds = stale_stream_after_seconds

    def _active(self, conversation_id: UUID) -> list[Message]:
        self._conversations.get(owner_id=self._owner_id, conversation_id=conversation_id)
        self._recover_stale_turn(conversation_id)
        active = self._messages.list_active(
            owner_id=self._owner_id, conversation_id=conversation_id
        )
        self._ensure_no_streaming_turn(active)
        return active

    def send(self, conversation_id: UUID, content: str, *, request_id: str) -> AsyncIterator[str]:
        active = self._active(conversation_id)
        user = self._new_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content,
            status=MessageStatus.COMPLETED,
            now=datetime.now(UTC),
            parent_message_id=active[-1].id if active else None,
        )
        return self._prepare_context_stream(active, user, (user,), None, None, request_id)

    def regenerate(
        self,
        conversation_id: UUID,
        message_id: UUID,
        *,
        request_id: str,
    ) -> AsyncIterator[str]:
        active = self._active(conversation_id)
        target = self._messages.get(
            owner_id=self._owner_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        index = next((i for i, m in enumerate(active) if m.id == message_id), -1)
        if (
            target.role is not MessageRole.ASSISTANT
            or target.status is not MessageStatus.COMPLETED
            or index < 1
        ):
            raise InvalidRetryTargetError("Only active completed assistants can be regenerated.")
        user = active[index - 1]
        if user.role is not MessageRole.USER or target.parent_message_id != user.id:
            raise InvalidRetryTargetError("Assistant has no active user parent.")
        return self._prepare_context_stream(active, user, (), target.id, target.id, request_id)

    def edit_and_retry(
        self,
        conversation_id: UUID,
        message_id: UUID,
        content: str,
        *,
        request_id: str,
    ) -> AsyncIterator[str]:
        active = self._active(conversation_id)
        target = self._messages.get(
            owner_id=self._owner_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        if (
            target.role is not MessageRole.USER
            or target.status is not MessageStatus.COMPLETED
            or not any(m.id == target.id for m in active)
        ):
            raise InvalidRetryTargetError("Only active completed user messages can be retried.")
        user = self._new_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content,
            status=MessageStatus.COMPLETED,
            now=datetime.now(UTC),
            parent_message_id=target.parent_message_id,
            supersedes_message_id=target.id,
        )
        return self._prepare_context_stream(active, user, (user,), target.id, None, request_id)

    def _prepare_context_stream(
        self,
        active: Sequence[Message],
        user: Message,
        created_users: tuple[Message, ...],
        supersede_from: UUID | None,
        assistant_supersedes: UUID | None,
        request_id: str,
    ) -> AsyncIterator[str]:
        reservation = uuid4()
        deadline = monotonic() + self._context.settings.request_timeout_seconds
        self._messages.prepare_message_turn(
            owner_id=self._owner_id,
            conversation_id=user.conversation_id,
            expected_active_ids=[m.id for m in active],
            supersede_from_message_id=supersede_from,
            messages=created_users,
            updated_at=datetime.now(UTC),
            preparation_id=reservation,
        )
        try:
            post_active = self._messages.list_active(
                owner_id=self._owner_id, conversation_id=user.conversation_id,
            )
            retrieval = None
            if self._memory_retriever is not None:
                retrieval = self._memory_retriever.retrieve(
                    self._owner_id, user.content, post_active,
                    timeout=min(self._context.settings.memory_timeout_seconds,
                                remaining(deadline) / 4),
                )
            assembled = self._context.assemble(
                post_active[:-1], user, deadline=deadline, retrieval=retrieval,
            )
            remaining(deadline)
            assistant = self._new_message(
                conversation_id=user.conversation_id,
                role=MessageRole.ASSISTANT,
                content="",
                status=MessageStatus.STREAMING,
                now=datetime.now(UTC),
                parent_message_id=user.id,
                supersedes_message_id=assistant_supersedes,
            )
            self._messages.prepare_message_turn(
                owner_id=self._owner_id,
                conversation_id=user.conversation_id,
                expected_active_ids=[m.id for m in post_active],
                supersede_from_message_id=None,
                messages=(assistant,),
                updated_at=datetime.now(UTC),
                preparation_id=reservation,
                complete_preparation=True,
            )
        except BaseException:
            # Release only our lease. Recovery handles unavailable storage/process death;
            # an expired request must never release a newer request's reservation.
            try:
                self._messages.release_preparation(
                    owner_id=self._owner_id,
                    conversation_id=user.conversation_id,
                    preparation_id=reservation,
                )
            except Exception as error:  # noqa: BLE001 - preserve the original safe failure
                logger.error(
                    "Context reservation cleanup failed request_id=%s error_class=%s",
                    request_id,
                    type(error).__name__,
                )
            raise
        logger.info(
            "Context prepared request_id=%s counter_kind=%s tokens=%s selected_count=%s",
            request_id,
            assembled.budget.counter_kind,
            assembled.budget.selected_total,
            len(assembled.selected_message_ids),
        )
        return self._stream(
            _PreparedTurn(
                (*created_users, assistant),
                assistant,
                assembled.messages,
                request_id,
                assembled.selected_memory_ids,
            )
        )

    def _stream(self, turn: _PreparedTurn) -> AsyncIterator[str]:
        completed: list[Message] = []
        stream = _ManagedStream(
            self._stream_events(turn, completed), lambda: self._abandon_before_start(turn)
        )
        stream.set_terminal_callback(lambda: self._schedule_memory_extraction(completed, turn))
        return stream

    def _schedule_memory_extraction(
        self, completed: list[Message], turn: _PreparedTurn
    ) -> None:
        if (self._memory_extraction is None and self._memory_lifecycle is None) or not completed:
            return

        async def run() -> None:
            try:
                if self._memory_lifecycle is not None:
                    await anyio.to_thread.run_sync(
                        self._memory_lifecycle.after_completed,
                        completed[0],
                        turn.selected_memory_ids,
                    )
                elif self._memory_extraction is not None:
                    await anyio.to_thread.run_sync(self._memory_extraction.run, completed[0])
            except Exception as error:  # noqa: BLE001 - optional post-completion work
                logger.info(
                    "Memory post-turn failed request_id=%s error_class=%s",
                    turn.request_id,
                    type(error).__name__,
                )

        try:
            task = asyncio.create_task(run(), name="post-completion-memory-extraction")
        except RuntimeError as error:
            logger.info(
                "Memory post-turn scheduling failed request_id=%s error_class=%s",
                turn.request_id,
                type(error).__name__,
            )
            return
        self._post_completion_tasks.add(task)
        task.add_done_callback(self._post_completion_tasks.discard)

    def _abandon_before_start(self, turn: _PreparedTurn) -> None:
        self._fail(turn.assistant, "client_cancelled", "")
        logger.info("Chat stream abandoned before start request_id=%s", turn.request_id)

    def _recover_stale_turn(self, conversation_id: UUID) -> None:
        now = datetime.now(UTC)
        self._messages.recover_stale_turn(
            owner_id=self._owner_id,
            conversation_id=conversation_id,
            stale_before=now - timedelta(seconds=self._stale_stream_after_seconds),
            updated_at=now,
        )

    async def _stream_events(
        self, turn: _PreparedTurn, completed_turn: list[Message]
    ) -> AsyncIterator[str]:
        parts: list[str] = []
        content_length = 0
        terminal = False
        try:
            # Keep creation events inside the protected lifecycle. A disconnect
            # while sending either event must fail the already-persisted turn.
            for message in turn.created:
                yield _sse("message.created", SSEMessageCreated(message=message).model_dump_json())
            events: asyncio.Queue[str | Exception | None] = asyncio.Queue(maxsize=1)
            demand = asyncio.Semaphore(0)
            provider_iterator = self._llm.stream(turn.history).__aiter__()
            # One task owns the entire iterator: SDK timeout scopes and cleanup
            # may depend on task identity remaining stable across every yield.
            provider_task = asyncio.create_task(
                _produce_deltas(provider_iterator, events, demand, request_id=turn.request_id)
            )
            try:
                while True:
                    demand.release()
                    event = await events.get()
                    if event is None:
                        break
                    if isinstance(event, Exception):
                        raise event
                    delta = event
                    if not delta:
                        continue
                    if content_length + len(delta) > MAX_MESSAGE_CONTENT_CHARS:
                        raise LLMInvalidResponseError(
                            "language model response exceeded the size limit"
                        )
                    parts.append(delta)
                    content_length += len(delta)
                    yield _sse(
                        "response.delta",
                        SSEResponseDelta(
                            message_id=turn.assistant.id, delta=delta
                        ).model_dump_json(),
                    )
            finally:
                await _cancel_provider_task(provider_task, request_id=turn.request_id)

            content = "".join(parts)
            if not content.strip():
                raise LLMInvalidResponseError("language model response was empty")
            completed = self._messages.update_status(
                owner_id=self._owner_id,
                conversation_id=turn.assistant.conversation_id,
                message_id=turn.assistant.id,
                status=MessageStatus.COMPLETED,
                content=content,
                model=self._model,
                expected_status=MessageStatus.STREAMING,
                updated_at=datetime.now(UTC),
            )
            if completed is None:
                terminal = True
                yield self._stale_turn_event(turn.assistant)
                return
            terminal = True
            completed_turn.append(completed)
            yield _sse(
                "response.completed", SSEResponseCompleted(message=completed).model_dump_json()
            )
        except asyncio.CancelledError:
            if not terminal:
                self._fail(turn.assistant, "client_cancelled", "".join(parts))
            logger.info(
                "Chat stream cancelled request_id=%s error_class=CancelledError", turn.request_id
            )
            raise
        except GeneratorExit:
            if not terminal:
                self._fail(turn.assistant, "client_cancelled", "".join(parts))
                logger.info("Chat stream closed request_id=%s", turn.request_id)
            raise
        except LLMError as error:
            logger.warning(
                "Chat stream failed request_id=%s error_class=%s",
                turn.request_id,
                type(error).__name__,
            )
            event = self._error_event(turn.assistant, error.code, "".join(parts))
            terminal = True
            yield event
        except Exception:  # noqa: BLE001
            logger.error(
                "Chat stream failed request_id=%s error_class=UnexpectedError", turn.request_id
            )
            event = self._error_event(turn.assistant, "llm_unavailable", "".join(parts))
            terminal = True
            yield event

    def _error_event(self, assistant: Message, code: str, content: str) -> str:
        failed = self._fail(assistant, code, content)
        if failed is None:
            return self._stale_turn_event(assistant)
        return _sse(
            "response.error",
            SSEResponseError(
                message_id=failed.id,
                code=code,
                message="The response could not be completed. Please retry.",
            ).model_dump_json(),
        )

    def _fail(self, assistant: Message, code: str, content: str) -> Message | None:
        return self._messages.update_status(
            owner_id=self._owner_id,
            conversation_id=assistant.conversation_id,
            message_id=assistant.id,
            status=MessageStatus.FAILED,
            content=content,
            error_code=code,
            expected_status=MessageStatus.STREAMING,
            updated_at=datetime.now(UTC),
        )

    @staticmethod
    def _stale_turn_event(assistant: Message) -> str:
        return _sse(
            "response.error",
            SSEResponseError(
                message_id=assistant.id,
                code="turn_interrupted",
                message="The response was interrupted. Please refresh and retry.",
            ).model_dump_json(),
        )

    @staticmethod
    def _ensure_no_streaming_turn(active: Sequence[Message]) -> None:
        if any(message.status is MessageStatus.STREAMING for message in active):
            raise ConversationConflictError("a response is already in progress")

    def _new_message(
        self,
        *,
        conversation_id: UUID,
        role: MessageRole,
        content: str,
        status: MessageStatus,
        now: datetime,
        parent_message_id: UUID | None = None,
        supersedes_message_id: UUID | None = None,
    ) -> Message:
        return Message(
            id=uuid4(),
            conversation_id=conversation_id,
            owner_id=self._owner_id,
            role=role,
            content=content,
            status=status,
            created_at=now,
            parent_message_id=parent_message_id,
            supersedes_message_id=supersedes_message_id,
        )


async def _produce_deltas(
    iterator: AsyncIterator[str],
    events: asyncio.Queue[str | Exception | None],
    demand: asyncio.Semaphore,
    *,
    request_id: str,
) -> None:
    """Own provider iteration and teardown in a single task with backpressure."""
    failure: Exception | None = None
    try:
        while True:
            await demand.acquire()
            try:
                delta = await anext(iterator)
            except StopAsyncIteration:
                break
            await events.put(delta)
    except asyncio.CancelledError:
        raise
    # The consumer applies the normal safe model/storage error mapping.
    except Exception as error:  # noqa: BLE001
        failure = error
    finally:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            with anyio.CancelScope(shield=True):
                with anyio.move_on_after(1) as timeout_scope:
                    try:
                        await close()
                    # Teardown must not replace a model failure or cancellation.
                    except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001
                        logger.error(
                            "Provider stream cleanup failed request_id=%s error_class=%s",
                            request_id,
                            type(error).__name__,
                        )
                if timeout_scope.cancel_called:
                    logger.error("Provider stream cleanup timed out request_id=%s", request_id)
    # Never queue a terminal event on cancellation: the disconnected consumer
    # may no longer be draining the queue. The finally block above still runs.
    await events.put(failure)


async def _cancel_provider_task(task: asyncio.Task[None], *, request_id: str) -> None:
    """Cancel and briefly join provider iteration outside the ASGI cancel scope."""
    if not task.done():
        task.cancel()
    with anyio.CancelScope(shield=True):
        with anyio.move_on_after(1) as timeout_scope:
            try:
                await task
            except asyncio.CancelledError:
                pass
            # Cleanup errors must not replace the request cancellation.
            except Exception as error:  # noqa: BLE001
                logger.error(
                    "Provider task cleanup failed request_id=%s error_class=%s",
                    request_id,
                    type(error).__name__,
                )
        if timeout_scope.cancel_called:
            logger.error("Provider task cleanup timed out request_id=%s", request_id)


def _sse(event: str, data: str) -> str:
    """Return one correctly terminated SSE frame."""
    return f"event: {event}\ndata: {data}\n\n"
