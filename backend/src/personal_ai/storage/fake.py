"""Deterministic in-memory repositories used by unit tests and fake development."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from personal_ai.entities import Conversation, Message, MessageStatus
from personal_ai.storage.errors import ResourceNotFoundError


class InMemoryConversationRepository:
    """An owner-isolated conversation repository with no external I/O."""

    def __init__(self) -> None:
        self._conversations: dict[UUID, Conversation] = {}

    def create(self, conversation: Conversation) -> Conversation:
        self._conversations[conversation.id] = conversation
        return conversation

    def get(self, *, owner_id: str, conversation_id: UUID) -> Conversation:
        conversation = self._conversations.get(conversation_id)
        if conversation is None or conversation.owner_id != owner_id:
            raise ResourceNotFoundError("conversation not found")
        return conversation

    def list(self, *, owner_id: str, limit: int = 50) -> list[Conversation]:
        if limit < 1:
            return []
        return sorted(
            (item for item in self._conversations.values() if item.owner_id == owner_id),
            key=lambda item: (item.updated_at, str(item.id)),
            reverse=True,
        )[:limit]

    def update(self, conversation: Conversation) -> Conversation:
        self.get(owner_id=conversation.owner_id, conversation_id=conversation.id)
        self._conversations[conversation.id] = conversation
        return conversation

    def touch(self, *, owner_id: str, conversation_id: UUID, updated_at: datetime) -> Conversation:
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

    def create(self, message: Message) -> Message:
        self._messages[message.id] = message
        self._touch_conversation(message.owner_id, message.conversation_id, message.created_at)
        return message

    def get(self, *, owner_id: str, conversation_id: UUID, message_id: UUID) -> Message:
        message = self._messages.get(message_id)
        if (
            message is None
            or message.owner_id != owner_id
            or message.conversation_id != conversation_id
        ):
            raise ResourceNotFoundError("message not found")
        return message

    def list_active(self, *, owner_id: str, conversation_id: UUID) -> list[Message]:
        messages = [
            message
            for message in self._messages.values()
            if message.owner_id == owner_id and message.conversation_id == conversation_id
        ]
        return _active_path(messages)

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
    ) -> Message:
        message = self.get(
            owner_id=owner_id, conversation_id=conversation_id, message_id=message_id
        )
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
        self.get(owner_id=owner_id, conversation_id=conversation_id, message_id=message_id)
        descendants = _descendant_ids(list(self._messages.values()), message_id)
        replaced = []
        for identifier in descendants:
            message = self._messages[identifier]
            if message.owner_id == owner_id and message.conversation_id == conversation_id:
                updated = message.model_copy(update={"status": MessageStatus.SUPERSEDED})
                self._messages[identifier] = updated
                replaced.append(updated)
        self._touch_conversation(owner_id, conversation_id, updated_at)
        return sorted(replaced, key=lambda item: (item.created_at, str(item.id)))

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


def _descendant_ids(messages: list[Message], root_id: UUID) -> set[UUID]:
    """Return a message and every child in its historical branch."""
    children: dict[UUID, list[UUID]] = {}
    for message in messages:
        if message.parent_message_id is not None:
            children.setdefault(message.parent_message_id, []).append(message.id)
    found = {root_id}
    pending = [root_id]
    while pending:
        current = pending.pop()
        for child in children.get(current, []):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def _active_path(messages: list[Message]) -> list[Message]:
    """Choose the newest viable leaf and return its root-to-leaf path."""
    by_id = {message.id: message for message in messages}
    viable: dict[UUID, Message] = {}
    for message in messages:
        if message.status is MessageStatus.SUPERSEDED:
            continue
        parent_id = message.parent_message_id
        seen: set[UUID] = set()
        while parent_id is not None and parent_id not in seen:
            seen.add(parent_id)
            parent = by_id.get(parent_id)
            if parent is None or parent.status is MessageStatus.SUPERSEDED:
                break
            parent_id = parent.parent_message_id
        else:
            viable[message.id] = message
    parents = {
        message.parent_message_id for message in viable.values() if message.parent_message_id
    }
    leaves = [message for message in viable.values() if message.id not in parents]
    if not leaves:
        return []
    leaf = max(leaves, key=lambda item: (item.created_at, str(item.id)))
    path: list[Message] = []
    while True:
        path.append(leaf)
        if leaf.parent_message_id is None:
            break
        leaf = viable.get(leaf.parent_message_id)  # type: ignore[assignment]
        if leaf is None:
            return []
    return list(reversed(path))
