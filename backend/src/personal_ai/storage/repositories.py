"""Storage contracts for the Phase 1 conversation surface."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from personal_ai.entities import Conversation, Message, MessageStatus


class ConversationRepository(Protocol):
    """Persistence operations for owner-scoped conversations."""

    def create(self, conversation: Conversation) -> Conversation: ...

    def get(self, *, owner_id: str, conversation_id: UUID) -> Conversation: ...

    def list(self, *, owner_id: str, limit: int = 50) -> list[Conversation]: ...

    def update(self, conversation: Conversation) -> Conversation: ...

    def touch(
        self, *, owner_id: str, conversation_id: UUID, updated_at: datetime
    ) -> Conversation: ...


class MessageRepository(Protocol):
    """Append-only, owner-scoped message persistence operations."""

    def create(self, message: Message) -> Message: ...

    def get(self, *, owner_id: str, conversation_id: UUID, message_id: UUID) -> Message: ...

    def list_active(self, *, owner_id: str, conversation_id: UUID) -> list[Message]: ...

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
    ) -> Message: ...

    def supersede_path(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        message_id: UUID,
        updated_at: datetime,
    ) -> list[Message]: ...
