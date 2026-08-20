"""Persistence interfaces and implementations for application records."""

from personal_ai.storage.errors import (
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
from personal_ai.storage.firestore import (
    FirestoreConversationRepository,
    FirestoreMessageRepository,
)
from personal_ai.storage.repositories import ConversationRepository, MessageRepository

__all__ = [
    "ConversationRepository",
    "FakeConversationRepository",
    "FakeMessageRepository",
    "FirestoreConversationRepository",
    "FirestoreMessageRepository",
    "InMemoryConversationRepository",
    "InMemoryMessageRepository",
    "MessageRepository",
    "NotFoundError",
    "RepositoryError",
    "ResourceNotFoundError",
    "StorageError",
    "StorageUnavailableError",
]
