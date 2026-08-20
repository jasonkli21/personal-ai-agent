"""HTTP request and response schemas for the documented Phase 1 API."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from personal_ai.entities import Conversation, Message


class APIModel(BaseModel):
    """Reject unknown client fields to keep the HTTP contract explicit."""

    model_config = ConfigDict(extra="forbid")


class CreateConversationRequest(APIModel):
    """Optional initial title for a new conversation."""

    title: str | None = Field(default=None, min_length=1, max_length=200)


class ConversationListResponse(APIModel):
    """Newest-first conversations for the current Phase 1 owner."""

    conversations: list[Conversation]


class ConversationDetailResponse(APIModel):
    """A conversation with its selected active message branch."""

    conversation: Conversation
    messages: list[Message]


class CreateMessageRequest(APIModel):
    """Content for a new user message."""

    content: str = Field(min_length=1, max_length=20_000)


class EditAndRetryRequest(CreateMessageRequest):
    """Replacement content for an existing user message."""


class SSEMessageCreated(APIModel):
    """Payload for a ``message.created`` SSE event."""

    message: Message


class SSEResponseDelta(APIModel):
    """Payload for a ``response.delta`` SSE event."""

    message_id: UUID
    delta: str = Field(min_length=1, max_length=20_000)


class SSEResponseCompleted(APIModel):
    """Payload for a ``response.completed`` SSE event."""

    message: Message


class SSEResponseError(APIModel):
    """Payload for a safe, stable ``response.error`` SSE event."""

    message_id: UUID
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    message: str = Field(min_length=1, max_length=500)
