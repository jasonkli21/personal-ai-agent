"""Non-streaming Phase 1 conversation routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from personal_ai.api.dependencies import get_conversation_service
from personal_ai.api.schemas import (
    ConversationDetailResponse,
    ConversationListResponse,
    CreateConversationRequest,
)
from personal_ai.entities import Conversation
from personal_ai.services import ConversationService

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


@router.post("", response_model=Conversation, status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: CreateConversationRequest,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> Conversation:
    """Create an empty conversation for the Phase 1 owner."""
    return service.create_conversation(title=request.title)


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationListResponse:
    """List conversations belonging to the current Phase 1 owner."""
    return ConversationListResponse(conversations=service.list_conversations())


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: UUID,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationDetailResponse:
    """Retrieve a conversation and its selected active message path."""
    conversation, messages = service.get_conversation(conversation_id)
    return ConversationDetailResponse(conversation=conversation, messages=messages)
