"""Deterministic in-memory repositories used by unit tests and fake development."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from threading import RLock
from uuid import UUID

from personal_ai.auth.scope import scope_matches, scoped_record
from personal_ai.entities import Conversation, Message, MessageStatus
from personal_ai.storage.branches import active_path, descendant_ids, effective_message
from personal_ai.storage.errors import (
    ConversationConflictError,
    ResourceNotFoundError,
    StorageUnavailableError,
)


class InMemoryConversationRepository:
    """An owner-isolated conversation repository with no external I/O."""

    def __init__(self) -> None:
        self._conversations: dict[UUID, Conversation] = {}
        self._lock = RLock()

    def create(self, conversation: Conversation) -> Conversation:
        conversation = scoped_record(conversation)
        with self._lock:
            if conversation.id in self._conversations:
                raise ConversationConflictError("conversation already exists")
            self._conversations[conversation.id] = conversation
        return conversation

    def get(self, *, owner_id: str, conversation_id: UUID) -> Conversation:
        with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.owner_id != owner_id or not scope_matches(conversation):
                raise ResourceNotFoundError("conversation not found")
            return conversation

    def list(self, *, owner_id: str, limit: int = 50) -> list[Conversation]:
        if limit < 1:
            return []
        with self._lock:
            return sorted(
                (
                    item for item in self._conversations.values()
                    if item.owner_id == owner_id and scope_matches(item)
                ),
                key=lambda item: (item.updated_at, str(item.id)),
                reverse=True,
            )[:limit]

    def update(self, conversation: Conversation) -> Conversation:
        with self._lock:
            self.get(owner_id=conversation.owner_id, conversation_id=conversation.id)
            if not scope_matches(conversation):
                raise ResourceNotFoundError("conversation not found")
            self._conversations[conversation.id] = conversation
        return conversation

    def touch(self, *, owner_id: str, conversation_id: UUID, updated_at: datetime) -> Conversation:
        with self._lock:
            conversation = self.get(owner_id=owner_id, conversation_id=conversation_id)
            updated = conversation.model_copy(update={"updated_at": updated_at})
            self._conversations[conversation_id] = updated
            return updated


class InMemoryMessageRepository:
    """Append-only message fake with active-branch selection.

    ``conversations`` is optional so message-only tests stay lightweight. When
    supplied, adding or finalizing a message also touches the conversation.
    """

    def __init__(self, conversations: InMemoryConversationRepository | None = None) -> None:
        self._messages: dict[UUID, Message] = {}
        self._conversations = conversations
        self._mutation_lock = RLock()

    def create(self, message: Message) -> Message:
        message = scoped_record(message)
        with self._mutation_lock:
            if message.id in self._messages:
                raise ConversationConflictError("message already exists")
            self._validate_conversation(message.owner_id, message.conversation_id)
            self._messages[message.id] = message
            self._touch_conversation(message.owner_id, message.conversation_id, message.created_at)
        return message

    def release_preparation(
        self, *, owner_id: str, conversation_id: UUID, preparation_id: UUID,
    ) -> None:
        with self._mutation_lock:
            if self._conversations:
                conversation = self._conversations.get(
                    owner_id=owner_id, conversation_id=conversation_id,
                )
                if conversation.context_preparation_id == preparation_id:
                    self._conversations.update(conversation.model_copy(update={
                        "context_preparation_id": None, "context_preparation_started_at": None,
                    }))

    def recover_stale_turn(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        stale_before: datetime,
        updated_at: datetime,
    ) -> None:
        """Fail expired active placeholders so a restarted app can accept turns."""
        with self._mutation_lock:
            active = active_path(
                [
                    item
                    for item in self._messages.values()
                    if item.owner_id == owner_id and item.conversation_id == conversation_id
                    and scope_matches(item)
                ]
            )
            stale = [
                item
                for item in active
                if item.status is MessageStatus.STREAMING and item.created_at < stale_before
            ]
            if self._conversations:
                conversation = self._conversations.get(
                    owner_id=owner_id, conversation_id=conversation_id
                )
                started = conversation.context_preparation_started_at
                if started and started < stale_before:
                    self._conversations.update(conversation.model_copy(update={
                        "context_preparation_id": None, "context_preparation_started_at": None,
                        "updated_at": updated_at,
                    }))
            if stale:
                self._validate_conversation(owner_id, conversation_id)
            for item in stale:
                self._messages[item.id] = item.model_copy(
                    update={"status": MessageStatus.FAILED, "error_code": "turn_interrupted"}
                )
            if stale:
                self._touch_conversation(owner_id, conversation_id, updated_at)

    def prepare_message_turn(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        expected_active_ids: Sequence[UUID],
        supersede_from_message_id: UUID | None,
        messages: Sequence[Message],
        updated_at: datetime,
        preparation_id: UUID | None = None,
        complete_preparation: bool = False,
    ) -> list[Message]:
        """Atomically validate the active snapshot and append a complete turn."""
        messages = tuple(scoped_record(item) for item in messages)
        with self._mutation_lock:
            stored = [
                item
                for item in self._messages.values()
                if item.owner_id == owner_id and item.conversation_id == conversation_id
                and scope_matches(item)
            ]
            active = active_path(stored)
            if [item.id for item in active] != list(expected_active_ids):
                raise ConversationConflictError("conversation changed; retry the request")
            if any(item.status is MessageStatus.STREAMING for item in active):
                raise ConversationConflictError("a response is already in progress")
            if supersede_from_message_id is not None and supersede_from_message_id not in {
                item.id for item in active
            }:
                raise ConversationConflictError("retry target is no longer active")
            if any(item.id in self._messages for item in messages):
                raise ConversationConflictError("message already exists")
            if any(
                item.owner_id != owner_id or item.conversation_id != conversation_id
                for item in messages
            ):
                raise ResourceNotFoundError("conversation not found")
            if len(messages) + 1 + (supersede_from_message_id is not None) > 500:
                raise StorageUnavailableError("message storage unavailable")
            self._validate_conversation(owner_id, conversation_id)
            conversation = self._conversations.get(
                owner_id=owner_id, conversation_id=conversation_id
            ) if self._conversations else None
            lease = conversation.context_preparation_id if conversation else None
            if complete_preparation and lease != preparation_id:
                raise ConversationConflictError("context preparation expired")
            if not complete_preparation and lease is not None:
                raise ConversationConflictError("context preparation is in progress")

            if supersede_from_message_id is not None:
                existing = self._messages[supersede_from_message_id]
                self._messages[existing.id] = existing.model_copy(
                    update={"status": MessageStatus.SUPERSEDED}
                )

            for message in messages:
                self._messages[message.id] = message
            if conversation and preparation_id:
                self._conversations.update(conversation.model_copy(update={
                    "context_preparation_id": None if complete_preparation else preparation_id,
                    "context_preparation_started_at": None if complete_preparation else updated_at,
                }))
            self._touch_conversation(owner_id, conversation_id, updated_at)
            return list(messages)

    def get(self, *, owner_id: str, conversation_id: UUID, message_id: UUID) -> Message:
        with self._mutation_lock:
            message = self._messages.get(message_id)
            if (
                message is None
                or message.owner_id != owner_id
                or message.conversation_id != conversation_id
                or not scope_matches(message)
            ):
                raise ResourceNotFoundError("message not found")
            scoped_messages = {key: value for key, value in self._messages.items() if scope_matches(value)}
            return effective_message(message, scoped_messages)

    def list_active(self, *, owner_id: str, conversation_id: UUID, timeout: float | None = None) -> list[Message]:
        with self._mutation_lock:
            messages = [
                message
                for message in self._messages.values()
                if message.owner_id == owner_id and message.conversation_id == conversation_id
                and scope_matches(message)
            ]
            return active_path(messages)

    def update_status(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        message_id: UUID,
        status: MessageStatus,
        content: str | None = None,
        model: str | None = None,
        error_code: str | None = None,
        updated_at: datetime,
        expected_status: MessageStatus | None = None,
    ) -> Message | None:
        with self._mutation_lock:
            message = self.get(
                owner_id=owner_id, conversation_id=conversation_id, message_id=message_id
            )
            if expected_status is not None and message.status is not expected_status:
                return None
            self._validate_conversation(owner_id, conversation_id)
            changes: dict[str, object] = {"status": status}
            if content is not None:
                changes["content"] = content
            if model is not None:
                changes["model"] = model
            if error_code is not None:
                changes["error_code"] = error_code
            updated = message.model_copy(update=changes)
            self._messages[message_id] = updated
            self._touch_conversation(owner_id, conversation_id, updated_at)
            return updated

    def supersede_path(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        message_id: UUID,
        updated_at: datetime,
    ) -> list[Message]:
        with self._mutation_lock:
            self.get(owner_id=owner_id, conversation_id=conversation_id, message_id=message_id)
            self._validate_conversation(owner_id, conversation_id)
            scoped_messages = [item for item in self._messages.values() if scope_matches(item)]
            descendants = descendant_ids(scoped_messages, message_id)
            replaced = []
            for identifier in descendants:
                message = self._messages[identifier]
                if (
                    message.owner_id == owner_id
                    and message.conversation_id == conversation_id
                    and effective_message(message, {
                        key: value for key, value in self._messages.items() if scope_matches(value)
                    }).status is not MessageStatus.SUPERSEDED
                ):
                    updated = message.model_copy(update={"status": MessageStatus.SUPERSEDED})
                    replaced.append(updated)
            root = self._messages[message_id]
            self._messages[message_id] = root.model_copy(update={"status": MessageStatus.SUPERSEDED})
            self._touch_conversation(owner_id, conversation_id, updated_at)
            return sorted(replaced, key=lambda item: (item.created_at, str(item.id)))

    def _validate_conversation(self, owner_id: str, conversation_id: UUID) -> None:
        if self._conversations is not None:
            self._conversations.get(owner_id=owner_id, conversation_id=conversation_id)

    def _touch_conversation(
        self, owner_id: str, conversation_id: UUID, updated_at: datetime
    ) -> None:
        if self._conversations is not None:
            self._conversations.touch(
                owner_id=owner_id, conversation_id=conversation_id, updated_at=updated_at
            )


# Explicit fake aliases keep test setup readable at composition sites.
FakeConversationRepository = InMemoryConversationRepository
FakeMessageRepository = InMemoryMessageRepository
