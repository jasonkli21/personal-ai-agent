"""Phase 1 conversation routes."""

import asyncio
import logging
from collections.abc import Callable
from typing import Annotated
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from personal_ai.api.dependencies import (
    get_chat_turn_service,
    get_conversation_service,
    get_summary_repository,
)
from personal_ai.api.schemas import (
    ConversationDetailResponse,
    ConversationListResponse,
    CreateConversationRequest,
    CreateMessageRequest,
    EditAndRetryRequest,
    ErrorResponse,
)
from personal_ai.context.contracts import ConversationSummaryRepository
from personal_ai.context.inspection import ContextInspector
from personal_ai.entities import Conversation
from personal_ai.services import ChatTurnService, ConversationService
from personal_ai.settings import Settings, get_settings
from personal_ai.storage.errors import ResourceNotFoundError

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])
logger = logging.getLogger(__name__)

SSE_RESPONSES = {
    200: {
        "description": "Server-sent event stream",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    },
    404: {"model": ErrorResponse, "description": "Conversation or message not found"},
    409: {"model": ErrorResponse, "description": "A conversation turn is already in progress"},
    422: {"model": ErrorResponse, "description": "Invalid request or retry target"},
    503: {"model": ErrorResponse, "description": "Storage unavailable"},
}


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


class _LifecycleStreamingResponse(StreamingResponse):
    """Close async body iterators when the ASGI send path fails or is cancelled."""

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            close = getattr(self.body_iterator, "aclose", None)
            if close is not None:
                with anyio.CancelScope(shield=True):
                    with anyio.move_on_after(1) as timeout_scope:
                        try:
                            await close()
                        # Keep cleanup failures from replacing the original send error.
                        except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001
                            logger.error(
                                "Failed to close streaming response iterator request_id=%s "
                                "error_class=%s",
                                self.headers.get("X-Request-ID", "unknown"),
                                type(error).__name__,
                            )
                    if timeout_scope.cancel_called:
                        logger.error(
                            "Streaming response iterator cleanup timed out request_id=%s",
                            self.headers.get("X-Request-ID", "unknown"),
                        )


def _sse_response(stream: object, *, request_id: str) -> StreamingResponse:
    return _LifecycleStreamingResponse(
        stream,  # type: ignore[arg-type]
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )


@router.post("/{conversation_id}/messages", response_class=StreamingResponse, responses=SSE_RESPONSES)
def create_message(
    conversation_id: UUID,
    request: CreateMessageRequest,
    http_request: Request,
    service: Annotated[ChatTurnService, Depends(get_chat_turn_service)],
) -> StreamingResponse:
    """Persist and stream a new chat turn."""
    request_id = _request_id(http_request)
    return _sse_response(service.send(conversation_id, request.content, request_id=request_id), request_id=request_id)


@router.post(
    "/{conversation_id}/messages/{message_id}/regenerate",
    response_class=StreamingResponse,
    responses=SSE_RESPONSES,
)
def regenerate_message(
    conversation_id: UUID,
    message_id: UUID,
    request: Request,
    service: Annotated[ChatTurnService, Depends(get_chat_turn_service)],
) -> StreamingResponse:
    """Stream an append-only replacement for a completed assistant response."""
    request_id = _request_id(request)
    return _sse_response(service.regenerate(conversation_id, message_id, request_id=request_id), request_id=request_id)


@router.post(
    "/{conversation_id}/messages/{message_id}/edit-and-retry",
    response_class=StreamingResponse,
    responses=SSE_RESPONSES,
)
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


def _inspection_enabled(settings: Annotated[Settings, Depends(get_settings)]) -> Settings:
    if not settings.context_inspection_enabled:
        raise ResourceNotFoundError("resource not found")
    return settings


@router.get("/{conversation_id}/context", responses={404: {"model": ErrorResponse}})
def inspect_context(
    conversation_id: UUID,
    settings: Annotated[Settings, Depends(_inspection_enabled)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    summaries: Annotated[ConversationSummaryRepository, Depends(get_summary_repository)],
) -> dict:
    """Read-only planning estimate: never call counting/generation provider APIs."""
    _, active = service.get_conversation(conversation_id)
    return ContextInspector(settings, summaries).inspect(active)
