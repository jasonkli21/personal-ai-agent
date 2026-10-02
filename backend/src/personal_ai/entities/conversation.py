"""Provider- and storage-independent conversation domain records."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_MESSAGE_CONTENT_CHARS = 20_000


class MessageRole(StrEnum):
    """The two message authors supported by the Phase 1 chat surface."""

    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(StrEnum):
    """Durable states for append-only messages and replacements."""

    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class TimestampedRecord(BaseModel):
    """Require timezone-aware timestamps and normalize them to UTC."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("created_at", "updated_at", check_fields=False)
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Reject naive datetimes and store all instants as UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        return value.astimezone(UTC)


class Conversation(TimestampedRecord):
    """A persisted conversation owned by the current logical user."""

    id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    context_preparation_id: UUID | None = Field(default=None, exclude=True)
    context_preparation_started_at: datetime | None = Field(default=None, exclude=True)
    title: str = Field(min_length=1, max_length=200)
    created_at: datetime
    updated_at: datetime


class Message(TimestampedRecord):
    """A persisted, branchable message in a conversation."""

    id: UUID
    conversation_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    role: MessageRole
    content: str = Field(max_length=MAX_MESSAGE_CONTENT_CHARS)
    status: MessageStatus
    created_at: datetime
    parent_message_id: UUID | None = None
    supersedes_message_id: UUID | None = None
    model: str | None = Field(default=None, max_length=200)
    error_code: str | None = Field(default=None, max_length=100)
