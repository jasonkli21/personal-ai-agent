"""FastAPI dependencies for the Phase 1 conversation surface."""

from typing import Annotated

from fastapi import Depends

from personal_ai.services import ConversationService
from personal_ai.settings import Settings, get_settings
from personal_ai.storage import FirestoreConversationRepository, FirestoreMessageRepository
from personal_ai.storage.repositories import ConversationRepository, MessageRepository

PHASE_1_OWNER_ID = "local"


def get_current_owner_id() -> str:
    """Return the temporary single-user identity used in Phase 1."""
    return PHASE_1_OWNER_ID


def get_conversation_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationRepository:
    """Build the production conversation repository from application settings."""
    return FirestoreConversationRepository(project_id=settings.firestore_project_id)


def get_message_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MessageRepository:
    """Build the production message repository from application settings."""
    return FirestoreMessageRepository(project_id=settings.firestore_project_id)


def get_conversation_service(
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    messages: Annotated[MessageRepository, Depends(get_message_repository)],
    owner_id: Annotated[str, Depends(get_current_owner_id)],
) -> ConversationService:
    """Compose the conversation use cases from injectable boundaries."""
    return ConversationService(conversations, messages, owner_id=owner_id)
