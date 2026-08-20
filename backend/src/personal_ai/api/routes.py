"""Non-streaming Phase 1 conversation routes."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from personal_ai.api.dependencies import get_chat_turn_service, get_conversation_service
from personal_ai.api.schemas import (
    ConversationDetailResponse,
    ConversationListResponse,
    CreateConversationRequest,
    CreateMessageRequest,
    EditAndRetryRequest,
)
from personal_ai.entities import Conversation
from personal_ai.services import ChatTurnService, ConversationService

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


def _sse_response(stream: object, *, request_id: str) -> StreamingResponse:
    return StreamingResponse(
        stream,  # type: ignore[arg-type]
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )


@router.post("/{conversation_id}/messages")
def create_message(
    conversation_id: UUID,
    request: CreateMessageRequest,
    http_request: Request,
    service: Annotated[ChatTurnService, Depends(get_chat_turn_service)],
) -> StreamingResponse:
    """Persist and stream a new chat turn."""
    request_id = _request_id(http_request)
    return _sse_response(service.send(conversation_id, request.content, request_id=request_id), request_id=request_id)


@router.post("/{conversation_id}/messages/{message_id}/regenerate")
def regenerate_message(
    conversation_id: UUID,
    message_id: UUID,
    request: Request,
    service: Annotated[ChatTurnService, Depends(get_chat_turn_service)],
) -> StreamingResponse:
    """Stream an append-only replacement for a completed assistant response."""
    request_id = _request_id(request)
    return _sse_response(service.regenerate(conversation_id, message_id, request_id=request_id), request_id=request_id)


@router.post("/{conversation_id}/messages/{message_id}/edit-and-retry")
def edit_and_retry_message(
    conversation_id: UUID,
    message_id: UUID,
    request: EditAndRetryRequest,
    http_request: Request,
    service: Annotated[ChatTurnService, Depends(get_chat_turn_service)],
) -> StreamingResponse:
    """Replace a user message and stream its new assistant response."""
    request_id = _request_id(http_request)
    return _sse_response(
        service.edit_and_retry(conversation_id, message_id, request.content, request_id=request_id),
        request_id=request_id,
    )


def _request_id(request: Request) -> str:
    """Use a supplied correlation ID or create one without exposing request content."""
    return request.headers.get("X-Request-ID") or str(uuid4())
