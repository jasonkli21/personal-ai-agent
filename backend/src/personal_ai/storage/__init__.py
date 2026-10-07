"""Persistence interfaces and implementations for application records."""

from personal_ai.storage.errors import (
    ConversationConflictError,
    NotFoundError,
    RepositoryError,
    ResourceNotFoundError,
    StorageError,
    StorageUnavailableError,
)
from personal_ai.storage.fake import (
    FakeConversationRepository,
    FakeMessageRepository,
    InMemoryConversationRepository,
    InMemoryMessageRepository,
)
from personal_ai.storage.repositories import ConversationRepository, MessageRepository

__all__ = [
    "ConversationConflictError",
    "ConversationRepository",
    "FakeConversationRepository",
    "FakeMessageRepository",
    "InMemoryConversationRepository",
    "InMemoryMessageRepository",
    "MessageRepository",
    "NotFoundError",
    "RepositoryError",
    "ResourceNotFoundError",
    "StorageError",
    "StorageUnavailableError",
]
