"""Firestore implementations of the storage contracts.

The Firestore client is injected or built only when a repository is created;
importing this module and using fakes therefore never makes a cloud call.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.cloud import firestore

from personal_ai.entities import Conversation, Message, MessageStatus
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError
from personal_ai.storage.fake import _active_path, _descendant_ids


class FirestoreConversationRepository:
    """Owner-scoped conversations in the top-level ``conversations`` collection."""

    def __init__(self, client: Any | None = None, *, project_id: str | None = None) -> None:
        self._client = client or firestore.Client(project=project_id)
        self._collection = self._client.collection("conversations")

    def create(self, conversation: Conversation) -> Conversation:
        self._run(
            lambda: self._collection.document(str(conversation.id)).create(
                _conversation_data(conversation)
            )
        )
        return conversation

    def get(self, *, owner_id: str, conversation_id: UUID) -> Conversation:
        snapshot = self._run(lambda: self._collection.document(str(conversation_id)).get())
        if not snapshot.exists:
            raise ResourceNotFoundError("conversation not found")
        conversation = _conversation_from_data(snapshot.to_dict())
        if conversation.owner_id != owner_id:
            raise ResourceNotFoundError("conversation not found")
        return conversation

    def list(self, *, owner_id: str, limit: int = 50) -> list[Conversation]:
        if limit < 1:
            return []
        query = self._collection.where(filter=firestore.FieldFilter("owner_id", "==", owner_id))
        query = query.order_by("updated_at", direction=firestore.Query.DESCENDING).limit(limit)
        return [_conversation_from_data(snapshot.to_dict()) for snapshot in self._run(query.stream)]

    def update(self, conversation: Conversation) -> Conversation:
        self.get(owner_id=conversation.owner_id, conversation_id=conversation.id)
        self._run(
            lambda: self._collection.document(str(conversation.id)).set(
                _conversation_data(conversation)
            )
        )
        return conversation

    def touch(self, *, owner_id: str, conversation_id: UUID, updated_at: datetime) -> Conversation:
        conversation = self.get(owner_id=owner_id, conversation_id=conversation_id)
        self._run(
            lambda: self._collection.document(str(conversation_id)).update(
                {"updated_at": updated_at}
            )
        )
        return conversation.model_copy(update={"updated_at": updated_at})

    @staticmethod
    def _run(operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except (GoogleAPICallError, RetryError, OSError) as exc:
            raise StorageUnavailableError("conversation storage unavailable") from exc


class FirestoreMessageRepository:
    """Append-only messages in top-level ``messages`` documents."""

    def __init__(self, client: Any | None = None, *, project_id: str | None = None) -> None:
        self._client = client or firestore.Client(project=project_id)
        self._collection = self._client.collection("messages")
        self._conversations = self._client.collection("conversations")

    def create(self, message: Message) -> Message:
        def operation() -> None:
            batch = self._client.batch()
            batch.create(self._collection.document(str(message.id)), _message_data(message))
            batch.update(
                self._conversations.document(str(message.conversation_id)),
                {"updated_at": message.created_at},
            )
            batch.commit()

        self._run(operation)
        return message

    def get(self, *, owner_id: str, conversation_id: UUID, message_id: UUID) -> Message:
        snapshot = self._run(lambda: self._collection.document(str(message_id)).get())
        if not snapshot.exists:
            raise ResourceNotFoundError("message not found")
        message = _message_from_data(snapshot.to_dict())
        if message.owner_id != owner_id or message.conversation_id != conversation_id:
            raise ResourceNotFoundError("message not found")
        return message

    def list_active(self, *, owner_id: str, conversation_id: UUID) -> list[Message]:
        query = self._collection.where(
            filter=firestore.FieldFilter("owner_id", "==", owner_id)
        ).where(filter=firestore.FieldFilter("conversation_id", "==", str(conversation_id)))
        query = query.order_by("created_at", direction=firestore.Query.ASCENDING)
        messages = [_message_from_data(snapshot.to_dict()) for snapshot in self._run(query.stream)]
        return _active_path(messages)

    def update_status(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        message_id: UUID,
        status: MessageStatus,
        content: str | None = None,
        model: str | None = None,
        error_code: str | None = None,
        updated_at: datetime,
    ) -> Message:
        message = self.get(
            owner_id=owner_id, conversation_id=conversation_id, message_id=message_id
        )
        changes: dict[str, Any] = {"status": status.value}
        if content is not None:
            changes["content"] = content
        if model is not None:
            changes["model"] = model
        if error_code is not None:
            changes["error_code"] = error_code
        updated = message.model_copy(
            update={"status": status, **{k: v for k, v in changes.items() if k != "status"}}
        )

        def operation() -> None:
            batch = self._client.batch()
            batch.update(self._collection.document(str(message_id)), changes)
            batch.update(
                self._conversations.document(str(conversation_id)), {"updated_at": updated_at}
            )
            batch.commit()

        self._run(operation)
        return updated

    def supersede_path(
        self, *, owner_id: str, conversation_id: UUID, message_id: UUID, updated_at: datetime
    ) -> list[Message]:
        self.get(owner_id=owner_id, conversation_id=conversation_id, message_id=message_id)
        query = self._collection.where(
            filter=firestore.FieldFilter("owner_id", "==", owner_id)
        ).where(filter=firestore.FieldFilter("conversation_id", "==", str(conversation_id)))
        messages = [_message_from_data(snapshot.to_dict()) for snapshot in self._run(query.stream)]
        by_id = {message.id: message for message in messages}
        identifiers = _descendant_ids(messages, message_id)
        replaced = [by_id[identifier] for identifier in identifiers if identifier in by_id]

        def operation() -> None:
            batch = self._client.batch()
            for message in replaced:
                batch.update(
                    self._collection.document(str(message.id)),
                    {"status": MessageStatus.SUPERSEDED.value},
                )
            batch.update(
                self._conversations.document(str(conversation_id)), {"updated_at": updated_at}
            )
            batch.commit()

        self._run(operation)
        return [
            message.model_copy(update={"status": MessageStatus.SUPERSEDED})
            for message in sorted(replaced, key=lambda item: (item.created_at, str(item.id)))
        ]

    @staticmethod
    def _run(operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except (GoogleAPICallError, RetryError, OSError) as exc:
            raise StorageUnavailableError("message storage unavailable") from exc


def _conversation_data(conversation: Conversation) -> dict[str, Any]:
    return {**conversation.model_dump(mode="python"), "id": str(conversation.id)}


def _message_data(message: Message) -> dict[str, Any]:
    data = message.model_dump(mode="python")
    for key in ("id", "conversation_id", "parent_message_id", "supersedes_message_id"):
        if data[key] is not None:
            data[key] = str(data[key])
    data["role"] = message.role.value
    data["status"] = message.status.value
    return data


def _conversation_from_data(data: dict[str, Any]) -> Conversation:
    return Conversation.model_validate(data)


def _message_from_data(data: dict[str, Any]) -> Message:
    return Message.model_validate(data)
