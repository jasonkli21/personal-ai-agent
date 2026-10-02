"""Use cases for the non-streaming Phase 1 conversation API."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from personal_ai.entities import Conversation, Message
from personal_ai.storage.repositories import ConversationRepository, MessageRepository

DEFAULT_CONVERSATION_TITLE = "New conversation"


class ConversationService:
    """Coordinate owner-scoped conversation and active-message retrieval."""

    def __init__(
        self,
        conversations: ConversationRepository,
        messages: MessageRepository,
        *,
        owner_id: str,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._owner_id = owner_id

    def inspect_memories(
        self, settings, repository, memory_ids, lifecycle_repository=None
    ):
        from personal_ai.memory.inspection import inspect_records

        return inspect_records(
            settings, repository, self._messages, self._owner_id, memory_ids,
            lifecycle_repository=lifecycle_repository,
        )

    def create_conversation(self, *, title: str | None = None) -> Conversation:
        """Create an empty conversation for the current logical owner."""
        now = datetime.now(UTC)
        cleaned_title = title.strip() if title else ""
        conversation = Conversation(
            id=uuid4(),
            owner_id=self._owner_id,
            title=cleaned_title or DEFAULT_CONVERSATION_TITLE,
            created_at=now,
            updated_at=now,
        )
        return self._conversations.create(conversation)

    def list_conversations(self) -> list[Conversation]:
        """Return the current owner's conversations in repository-defined order."""
        return self._conversations.list(owner_id=self._owner_id)

    def get_conversation(self, conversation_id: UUID) -> tuple[Conversation, list[Message]]:
        """Return a conversation and only its active message path."""
        conversation = self._conversations.get(
            owner_id=self._owner_id, conversation_id=conversation_id
        )
        messages = self._messages.list_active(
            owner_id=self._owner_id, conversation_id=conversation_id
        )
        return conversation, messages
