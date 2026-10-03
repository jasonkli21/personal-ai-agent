"""FastAPI dependencies for the Phase 1 conversation surface."""

import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from personal_ai.context import ContextAssembler
from personal_ai.context.contracts import ConversationSummaryRepository
from personal_ai.context.repositories import FirestoreSummaryRepository
from personal_ai.llm import GeminiLLMClient, LLMClient
from personal_ai.llm.context import GeminiConversationSummarizer, GeminiTokenCounter
from personal_ai.llm.memory import GeminiMemoryAdapter
from personal_ai.memory.lifecycle_jobs import MemoryLifecycleCoordinator, PubSubMemoryJobPublisher
from personal_ai.memory.lifecycle_repositories import FirestoreMemoryLifecycleRepository
from personal_ai.memory.repositories import FirestoreMemoryRepository
from personal_ai.memory.services import MemoryExtractionService, MemoryRetriever
from personal_ai.services import ChatTurnService, ConversationService
from personal_ai.settings import Settings, get_settings
from personal_ai.storage import FirestoreConversationRepository, FirestoreMessageRepository
from personal_ai.storage.repositories import ConversationRepository, MessageRepository


def get_current_owner_id(request: Request) -> str:
    """Return only the owner resolved from the application authentication boundary."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication_required")
    return principal.owner_id


def get_current_principal(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication_required")
    return principal


def require_recent_auth(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Require a recently issued Google credential for account lifecycle actions."""
    principal = get_current_principal(request)
    now = int(time.time())
    if (
        not principal.authenticated
        or principal.issued_at > now + 60
        or now - principal.issued_at > settings.auth_recent_token_seconds
    ):
        raise HTTPException(status_code=401, detail="reauthentication_required")
    return principal


def get_conversation_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationRepository:
    """Build the production conversation repository from application settings."""
    return FirestoreConversationRepository(
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )


def get_message_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MessageRepository:
    """Build the production message repository from application settings."""
    return FirestoreMessageRepository(
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )


def get_conversation_service(
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    messages: Annotated[MessageRepository, Depends(get_message_repository)],
    owner_id: Annotated[str, Depends(get_current_owner_id)],
) -> ConversationService:
    """Compose the conversation use cases from injectable boundaries."""
    return ConversationService(conversations, messages, owner_id=owner_id)


def get_llm_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LLMClient:
    """Build the configured provider behind the replaceable streaming contract."""
    return GeminiLLMClient(settings)


def get_summary_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationSummaryRepository:
    return FirestoreSummaryRepository(
        project_id=settings.firestore_project_id, emulator_host=settings.firestore_emulator_host,
    )


def get_context_assembler(
    settings: Annotated[Settings, Depends(get_settings)],
    summaries: Annotated[ConversationSummaryRepository, Depends(get_summary_repository)],
) -> ContextAssembler:
    return ContextAssembler(
        settings, GeminiTokenCounter(settings), summaries, GeminiConversationSummarizer(settings),
    )


def get_memory_repository(settings: Annotated[Settings, Depends(get_settings)]):
    if not settings.memory_enabled and not settings.memory_inspection_enabled:
        return None
    return FirestoreMemoryRepository(
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )


def get_memory_adapter(settings: Annotated[Settings, Depends(get_settings)]):
    return GeminiMemoryAdapter(settings)


def get_lifecycle_repository(
    settings: Annotated[Settings, Depends(get_settings)],
    memory_repository: Annotated[object, Depends(get_memory_repository)],
    messages: Annotated[MessageRepository, Depends(get_message_repository)],
):
    if not settings.memory_lifecycle_inspection_enabled or memory_repository is None:
        return None
    return FirestoreMemoryLifecycleRepository(memory_repository, messages)


def get_chat_turn_service(
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    messages: Annotated[MessageRepository, Depends(get_message_repository)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    owner_id: Annotated[str, Depends(get_current_owner_id)],
    context: Annotated[ContextAssembler, Depends(get_context_assembler)],
    memory_repository: Annotated[object, Depends(get_memory_repository)],
    memory_adapter: Annotated[object, Depends(get_memory_adapter)],
    lifecycle_repository: Annotated[object, Depends(get_lifecycle_repository)],
) -> ChatTurnService:
    """Compose the durable streaming chat lifecycle."""
    retriever = extraction = lifecycle_coordinator = None
    if settings.memory_enabled and memory_repository is not None:
        lifecycle_repository = lifecycle_repository or FirestoreMemoryLifecycleRepository(
            memory_repository, messages
        )
        retriever = MemoryRetriever(
            settings, memory_repository, messages, memory_adapter, lifecycle_repository
        )
        if settings.memory_extraction_enabled:
            extraction = MemoryExtractionService(
                settings, memory_repository, messages, memory_adapter, memory_adapter,
            )
        if settings.memory_lifecycle_worker_enabled:
            publisher = PubSubMemoryJobPublisher(settings) if settings.memory_lifecycle_topic else None
            lifecycle_coordinator = MemoryLifecycleCoordinator(
                settings, lifecycle_repository, memory_repository,
                extraction=extraction, publisher=publisher,
            )
    return ChatTurnService(
        conversations,
        messages,
        llm,
        owner_id=owner_id,
        context_assembler=context,
        memory_retriever=retriever,
        memory_extraction=None if lifecycle_coordinator is not None else extraction,
        memory_lifecycle=lifecycle_coordinator,
        model=settings.ai_model,
        stale_stream_after_seconds=settings.request_timeout_seconds + 60,
    )
