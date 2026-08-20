"""Contract examples for Phase 1 domain and HTTP schemas."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai.api import CreateMessageRequest, SSEResponseDelta, SSEResponseError
from personal_ai.entities import Conversation, Message, MessageRole, MessageStatus


def test_conversation_and_message_accept_valid_persisted_records() -> None:
    """Stored records serialize UUIDs and UTC timestamps for API responses."""
    now = datetime.now(UTC)
    conversation_id = uuid4()
    conversation = Conversation(
        id=conversation_id,
        owner_id="local",
        title="Plan dinner",
        created_at=now,
        updated_at=now,
    )
    message = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        owner_id="local",
        role=MessageRole.USER,
        content="Suggest pasta.",
        status=MessageStatus.COMPLETED,
        created_at=now,
    )

    assert conversation.model_dump(mode="json")["created_at"].endswith("Z")
    assert message.model_dump(mode="json")["role"] == "user"


@pytest.mark.parametrize(
    "schema, payload",
    [
        (CreateMessageRequest, {"content": ""}),
        (CreateMessageRequest, {"content": "hello", "unexpected": True}),
        (SSEResponseDelta, {"message_id": "not-a-uuid", "delta": "hello"}),
        (
            SSEResponseError,
            {"message_id": str(uuid4()), "code": "provider-error", "message": "Try again."},
        ),
    ],
)
def test_api_schemas_reject_invalid_client_or_sse_payloads(
    schema: type[CreateMessageRequest | SSEResponseDelta | SSEResponseError],
    payload: dict[str, object],
) -> None:
    """Invalid examples fail at the documented HTTP boundary."""
    with pytest.raises(ValidationError):
        schema.model_validate(payload)
