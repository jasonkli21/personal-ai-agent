"""Durable Phase 1 chat-turn lifecycle and server-sent event payloads."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from personal_ai.api.schemas import (
    SSEMessageCreated,
    SSEResponseCompleted,
    SSEResponseDelta,
    SSEResponseError,
)
from personal_ai.entities import MAX_MESSAGE_CONTENT_CHARS, Message, MessageRole, MessageStatus
from personal_ai.llm import ChatMessage, LLMClient, LLMError, LLMInvalidResponseError
from personal_ai.storage.repositories import ConversationRepository, MessageRepository

logger = logging.getLogger(__name__)


class HistoryLimitExceededError(Exception):
    """The active chat context is too large for the Phase 1 safety cap."""


class InvalidRetryTargetError(Exception):
    """A regenerate or edit-and-retry target is not in a retryable state."""


@dataclass(frozen=True, slots=True)
class _PreparedTurn:
    created: tuple[Message, ...]
    assistant: Message
    history: tuple[ChatMessage, ...]
    request_id: str


class ChatTurnService:
    """Create append-only turns, stream model output, and finalize state."""

    def __init__(
        self,
        conversations: ConversationRepository,
        messages: MessageRepository,
        llm: LLMClient,
        *,
        owner_id: str,
        max_history_messages: int,
        model: str,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._llm = llm
        self._owner_id = owner_id
        self._max_history_messages = max_history_messages
        self._model = model

    def send(self, conversation_id: UUID, content: str, *, request_id: str) -> AsyncIterator[str]:
        """Persist a new user/assistant pair and stream the assistant response."""
        self._conversations.get(owner_id=self._owner_id, conversation_id=conversation_id)
        active = self._messages.list_active(
            owner_id=self._owner_id, conversation_id=conversation_id
        )
        self._ensure_history_capacity(active, extra_messages=1)
        now = datetime.now(UTC)
        user = self._new_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content,
            status=MessageStatus.COMPLETED,
            parent_message_id=active[-1].id if active else None,
            now=now,
        )
        self._messages.create(user)
        assistant = self._new_message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.STREAMING,
            parent_message_id=user.id,
            now=now,
        )
        self._messages.create(assistant)
        return self._stream(
            _PreparedTurn((user, assistant), assistant, self._history(active + [user]), request_id)
        )

    def regenerate(
        self, conversation_id: UUID, message_id: UUID, *, request_id: str
    ) -> AsyncIterator[str]:
        """Replace a completed assistant response while retaining its audit record."""
        self._conversations.get(owner_id=self._owner_id, conversation_id=conversation_id)
        replaced = self._messages.get(
            owner_id=self._owner_id, conversation_id=conversation_id, message_id=message_id
        )
        if replaced.role is not MessageRole.ASSISTANT or replaced.status is not MessageStatus.COMPLETED:
            raise InvalidRetryTargetError("Only completed assistant messages can be regenerated.")
        now = datetime.now(UTC)
        self._messages.supersede_path(
            owner_id=self._owner_id,
            conversation_id=conversation_id,
            message_id=message_id,
            updated_at=now,
        )
        active = self._messages.list_active(
            owner_id=self._owner_id, conversation_id=conversation_id
        )
        self._ensure_history_capacity(active, extra_messages=0)
        assistant = self._new_message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.STREAMING,
            parent_message_id=replaced.parent_message_id,
            supersedes_message_id=replaced.id,
            now=now,
        )
        self._messages.create(assistant)
        history = active + [assistant]
        # The streaming placeholder has no content and must not be sent to the model.
        return self._stream(
            _PreparedTurn((assistant,), assistant, self._history(history[:-1]), request_id)
        )

    def edit_and_retry(
        self, conversation_id: UUID, message_id: UUID, content: str, *, request_id: str
    ) -> AsyncIterator[str]:
        """Replace a user prompt and every active descendant with a new turn."""
        self._conversations.get(owner_id=self._owner_id, conversation_id=conversation_id)
        replaced = self._messages.get(
            owner_id=self._owner_id, conversation_id=conversation_id, message_id=message_id
        )
        if replaced.role is not MessageRole.USER or replaced.status is not MessageStatus.COMPLETED:
            raise InvalidRetryTargetError("Only completed user messages can be edited and retried.")
        now = datetime.now(UTC)
        self._messages.supersede_path(
            owner_id=self._owner_id,
            conversation_id=conversation_id,
            message_id=message_id,
            updated_at=now,
        )
        active = self._messages.list_active(
            owner_id=self._owner_id, conversation_id=conversation_id
        )
        self._ensure_history_capacity(active, extra_messages=1)
        user = self._new_message(
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=content,
            status=MessageStatus.COMPLETED,
            parent_message_id=replaced.parent_message_id,
            supersedes_message_id=replaced.id,
            now=now,
        )
        self._messages.create(user)
        assistant = self._new_message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.STREAMING,
            parent_message_id=user.id,
            now=now,
        )
        self._messages.create(assistant)
        return self._stream(
            _PreparedTurn((user, assistant), assistant, self._history(active + [user]), request_id)
        )

    async def _stream(self, turn: _PreparedTurn) -> AsyncIterator[str]:
        for message in turn.created:
            yield _sse("message.created", SSEMessageCreated(message=message).model_dump_json())
        parts: list[str] = []
        content_length = 0
        try:
            async for delta in self._llm.stream(turn.history):
                if not delta:
                    continue
                if content_length + len(delta) > MAX_MESSAGE_CONTENT_CHARS:
                    raise LLMInvalidResponseError("language model response exceeded the size limit")
                parts.append(delta)
                content_length += len(delta)
                yield _sse(
                    "response.delta",
                    SSEResponseDelta(message_id=turn.assistant.id, delta=delta).model_dump_json(),
                )
            completed = self._messages.update_status(
                owner_id=self._owner_id,
                conversation_id=turn.assistant.conversation_id,
                message_id=turn.assistant.id,
                status=MessageStatus.COMPLETED,
                content="".join(parts),
                model=self._model,
                updated_at=datetime.now(UTC),
            )
            yield _sse("response.completed", SSEResponseCompleted(message=completed).model_dump_json())
        except asyncio.CancelledError:
            self._fail(turn.assistant, "client_cancelled", "".join(parts))
            logger.info("Chat stream cancelled request_id=%s error_class=CancelledError", turn.request_id)
            raise
        except LLMError as error:
            logger.warning(
                "Chat stream failed request_id=%s error_class=%s",
                turn.request_id,
                type(error).__name__,
            )
            yield self._error_event(turn.assistant, error.code, "".join(parts))
        except Exception:  # noqa: BLE001
            logger.error("Chat stream failed request_id=%s error_class=UnexpectedError", turn.request_id)
            yield self._error_event(turn.assistant, "llm_unavailable", "".join(parts))

    def _error_event(self, assistant: Message, code: str, content: str) -> str:
        failed = self._fail(assistant, code, content)
        return _sse(
            "response.error",
            SSEResponseError(
                message_id=failed.id, code=code, message="The response could not be completed. Please retry."
            ).model_dump_json(),
        )

    def _fail(self, assistant: Message, code: str, content: str) -> Message:
        return self._messages.update_status(
            owner_id=self._owner_id,
            conversation_id=assistant.conversation_id,
            message_id=assistant.id,
            status=MessageStatus.FAILED,
            content=content,
            error_code=code,
            updated_at=datetime.now(UTC),
        )

    def _ensure_history_capacity(self, active: Sequence[Message], *, extra_messages: int) -> None:
        if len(active) + extra_messages > self._max_history_messages:
            raise HistoryLimitExceededError(
                "This chat has reached its message limit. Please start a new chat."
            )

    def _history(self, messages: Sequence[Message]) -> tuple[ChatMessage, ...]:
        return tuple(
            ChatMessage(role=message.role, content=message.content)
            for message in messages
            if message.status is MessageStatus.COMPLETED
        )

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
            id=uuid4(), conversation_id=conversation_id, owner_id=self._owner_id, role=role,
            content=content, status=status, created_at=now, parent_message_id=parent_message_id,
            supersedes_message_id=supersedes_message_id,
        )


def _sse(event: str, data: str) -> str:
    """Return one correctly terminated SSE frame."""
    return f"event: {event}\ndata: {data}\n\n"
