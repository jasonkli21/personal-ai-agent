"""Firestore implementations of the storage contracts.

The Firestore client is injected or built only when a repository is created;
importing this module and using fakes therefore never makes a cloud call.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from time import monotonic
from typing import Any
from uuid import UUID

from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from personal_ai.auth.scope import data_scope_matches, scope_matches, scope_query, scoped_record
from personal_ai.entities import Conversation, Message, MessageStatus
from personal_ai.storage.branches import active_path, descendant_ids, effective_message
from personal_ai.storage.errors import (
    ConversationConflictError,
    ResourceNotFoundError,
    StorageUnavailableError,
)


class FirestoreConversationRepository:
    """Owner-scoped conversations in the top-level ``conversations`` collection."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        project_id: str | None = None,
        emulator_host: str | None = None,
    ) -> None:
        self._client = (
            client if client is not None else _firestore_client(project_id, emulator_host)
        )
        self._collection = self._client.collection("conversations")

    def create(self, conversation: Conversation) -> Conversation:
        conversation = scoped_record(conversation)
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
        if conversation.owner_id != owner_id or not scope_matches(conversation):
            raise ResourceNotFoundError("conversation not found")
        return conversation

    def list(self, *, owner_id: str, limit: int = 50) -> list[Conversation]:
        if limit < 1:
            return []
        def fetch():
            query = scope_query(
                self._collection.where(filter=firestore.FieldFilter("owner_id", "==", owner_id))
            ).order_by("updated_at", direction=firestore.Query.DESCENDING)
            conversations = []
            cursor = None
            scanned = 0
            deadline = monotonic() + 5
            while len(conversations) < limit:
                if monotonic() >= deadline:
                    raise TimeoutError("conversation listing scan bound exceeded")
                if scanned >= 5_000:
                    probe = query.start_after(cursor).limit(1).stream(
                        retry=None, timeout=max(0.1, deadline - monotonic())
                    )
                    if next(iter(probe), None) is not None:
                        raise TimeoutError("conversation listing scan bound exceeded")
                    break
                page_query = query.limit(min(100, 5_000 - scanned))
                if cursor is not None:
                    page_query = page_query.start_after(cursor)
                page = list(page_query.stream(retry=None, timeout=max(0.1, deadline - monotonic())))
                if not page:
                    break
                scanned += len(page)
                cursor = page[-1]
                for snapshot in page:
                    conversation = _conversation_from_data(snapshot.to_dict())
                    if scope_matches(conversation):
                        conversations.append(conversation)
                        if len(conversations) == limit:
                            break
                if len(page) < min(100, 5_000 - scanned + len(page)):
                    break
            return conversations

        return self._run(fetch)

    def update(self, conversation: Conversation) -> Conversation:
        self.get(owner_id=conversation.owner_id, conversation_id=conversation.id)
        if not scope_matches(conversation):
            raise ResourceNotFoundError("conversation not found")
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
        except (GoogleAPICallError, RetryError, OSError, TimeoutError) as exc:
            raise StorageUnavailableError("conversation storage unavailable") from exc


class FirestoreMessageRepository:
    """Append-only messages in top-level ``messages`` documents."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        project_id: str | None = None,
        emulator_host: str | None = None,
    ) -> None:
        self._client = (
            client if client is not None else _firestore_client(project_id, emulator_host)
        )
        self._collection = self._client.collection("messages")
        self._conversations = self._client.collection("conversations")

    def release_preparation(
        self, *, owner_id: str, conversation_id: UUID, preparation_id: UUID,
    ) -> None:
        reference = self._conversations.document(str(conversation_id))

        def operation() -> None:
            @firestore.transactional
            def release(transaction: Any) -> None:
                snapshot = next(transaction.get(reference), None)
                if snapshot is None or not snapshot.exists \
                        or snapshot.to_dict().get("owner_id") != owner_id \
                        or not data_scope_matches(snapshot.to_dict()):
                    raise ResourceNotFoundError("conversation not found")
                if snapshot.to_dict().get("context_preparation_id") == str(preparation_id):
                    transaction.update(reference, {
                        "context_preparation_id": None, "context_preparation_started_at": None,
                    })
            release(self._client.transaction())

        self._run(operation)

    def create(self, message: Message) -> Message:
        message = scoped_record(message)
        FirestoreConversationRepository(self._client).get(
            owner_id=message.owner_id, conversation_id=message.conversation_id
        )
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
        if (message.owner_id != owner_id or message.conversation_id != conversation_id
                or not scope_matches(message)):
            raise ResourceNotFoundError("message not found")
        history = self._run(lambda: list(self._message_query(
            owner_id=owner_id, conversation_id=conversation_id,
        ).stream()))
        scoped_history = [
            item for snapshot in history
            if scope_matches(item := _message_from_data(snapshot.to_dict()))
        ]
        return effective_message(message, {item.id: item for item in scoped_history})

    def list_active(self, *, owner_id: str, conversation_id: UUID, timeout: float | None = None) -> list[Message]:
        snapshots = self._run(
            lambda: list(
                self._message_query(owner_id=owner_id, conversation_id=conversation_id)
                .order_by("created_at", direction=firestore.Query.ASCENDING)
                .stream(**({"retry": None, "timeout": timeout} if timeout is not None else {}))
            )
        )
        messages = [
            message for snapshot in snapshots
            if scope_matches(message := _message_from_data(snapshot.to_dict()))
        ]
        return active_path(messages)

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
        expected_status: MessageStatus | None = None,
    ) -> Message | None:
        message = self.get(
            owner_id=owner_id, conversation_id=conversation_id, message_id=message_id
        )
        FirestoreConversationRepository(self._client).get(
            owner_id=owner_id, conversation_id=conversation_id
        )
        if expected_status is not None and message.status is not expected_status:
            return None
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

        def operation() -> Message | None:
            if expected_status is not None:
                transaction = self._client.transaction()
                message_ref = self._collection.document(str(message_id))
                conversation_ref = self._conversations.document(str(conversation_id))

                @firestore.transactional
                def transition(transaction: Any) -> bool:
                    snapshot = next(transaction.get(message_ref), None)
                    if snapshot is None or not snapshot.exists:
                        return False
                    current = _message_from_data(snapshot.to_dict())
                    if (current.owner_id != owner_id or current.conversation_id != conversation_id
                            or not scope_matches(current)):
                        raise ResourceNotFoundError("message not found")
                    stored = [
                        _message_from_data(item.to_dict())
                        for item in transaction.get(self._message_query(
                            owner_id=owner_id, conversation_id=conversation_id,
                        ))
                        if data_scope_matches(item.to_dict())
                    ]
                    conversation_snapshot = next(transaction.get(conversation_ref), None)
                    if (conversation_snapshot is None or not conversation_snapshot.exists
                            or conversation_snapshot.to_dict().get("owner_id") != owner_id
                            or not data_scope_matches(conversation_snapshot.to_dict())):
                        raise ResourceNotFoundError("conversation not found")
                    current = effective_message(current, {item.id: item for item in stored})
                    if current.status is not expected_status:
                        return False
                    transaction.update(message_ref, changes)
                    transaction.update(conversation_ref, {"updated_at": updated_at})
                    return True

                return updated if transition(transaction) else None

            batch = self._client.batch()
            batch.update(self._collection.document(str(message_id)), changes)
            batch.update(
                self._conversations.document(str(conversation_id)), {"updated_at": updated_at}
            )
            batch.commit()
            return updated

        return self._run(operation)

    def recover_stale_turn(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        stale_before: datetime,
        updated_at: datetime,
    ) -> None:
        """Conditionally fail abandoned active placeholders after process restart."""
        conversation_ref = self._conversations.document(str(conversation_id))

        def operation() -> None:
            transaction = self._client.transaction()

            @firestore.transactional
            def recover(transaction: Any) -> None:
                snapshot = next(transaction.get(conversation_ref), None)
                if snapshot is None or not snapshot.exists:
                    raise ResourceNotFoundError("conversation not found")
                if snapshot.to_dict().get("owner_id") != owner_id \
                        or not data_scope_matches(snapshot.to_dict()):
                    raise ResourceNotFoundError("conversation not found")
                query = self._message_query(owner_id=owner_id, conversation_id=conversation_id)
                messages = [
                    message for item in transaction.get(query)
                    if data_scope_matches(item.to_dict())
                    for message in [_message_from_data(item.to_dict())]
                ]
                active = active_path(messages)
                stale = [
                    item
                    for item in active
                    if item.status is MessageStatus.STREAMING and item.created_at < stale_before
                ]
                data = snapshot.to_dict()
                started = data.get("context_preparation_started_at")
                expired = started is not None and started < stale_before
                if not stale and not expired:
                    return
                if len(stale) + 1 > 500:
                    raise StorageUnavailableError("message storage unavailable")
                for item in stale:
                    transaction.update(
                        self._collection.document(str(item.id)),
                        {
                            "status": MessageStatus.FAILED.value,
                            "error_code": "turn_interrupted",
                        },
                    )
                changes = {"updated_at": updated_at}
                if expired:
                    changes.update({"context_preparation_id": None, "context_preparation_started_at": None})
                transaction.update(conversation_ref, changes)

            recover(transaction)

        self._run(operation)

    def prepare_message_turn(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        expected_active_ids: Sequence[UUID],
        supersede_from_message_id: UUID | None,
        messages: Sequence[Message],
        updated_at: datetime,
        preparation_id: UUID | None = None,
        complete_preparation: bool = False,
    ) -> list[Message]:
        """Commit a turn only if its snapshot is still the active branch.

        The transaction reads the complete conversation history before writing,
        so two requests based on one snapshot cannot both create active turns.
        Supersession and every replacement record share the same atomic commit.
        """
        conversation_ref = self._conversations.document(str(conversation_id))
        messages = tuple(scoped_record(item) for item in messages)
        message_refs = {item.id: self._collection.document(str(item.id)) for item in messages}

        def operation() -> list[Message]:
            transaction = self._client.transaction()

            @firestore.transactional
            def prepare(transaction: Any) -> list[Message]:
                conversation_snapshot = next(transaction.get(conversation_ref), None)
                if conversation_snapshot is None or not conversation_snapshot.exists:
                    raise ResourceNotFoundError("conversation not found")
                conversation_data = conversation_snapshot.to_dict()
                if conversation_data.get("owner_id") != owner_id \
                        or not data_scope_matches(conversation_data):
                    raise ResourceNotFoundError("conversation not found")

                lease = conversation_data.get("context_preparation_id")
                if complete_preparation and lease != str(preparation_id):
                    raise ConversationConflictError("context preparation expired")
                if not complete_preparation and lease is not None:
                    raise ConversationConflictError("context preparation is in progress")

                query = self._message_query(owner_id=owner_id, conversation_id=conversation_id)
                snapshots = list(transaction.get(query))
                stored = [
                    message for snapshot in snapshots
                    if data_scope_matches(snapshot.to_dict())
                    for message in [_message_from_data(snapshot.to_dict())]
                ]
                stored_by_id = {item.id: item for item in stored}
                active = active_path(stored)
                if [item.id for item in active] != list(expected_active_ids):
                    raise ConversationConflictError("conversation changed; retry the request")
                if any(item.status is MessageStatus.STREAMING for item in active):
                    raise ConversationConflictError("a response is already in progress")
                if supersede_from_message_id is not None and supersede_from_message_id not in {
                    item.id for item in active
                }:
                    raise ConversationConflictError("retry target is no longer active")
                if any(item.id in stored_by_id for item in messages):
                    raise ConversationConflictError("message already exists")
                if any(
                    item.owner_id != owner_id or item.conversation_id != conversation_id
                    for item in messages
                ):
                    raise ResourceNotFoundError("conversation not found")
                if len(messages) + 1 > 500:
                    raise StorageUnavailableError("message storage unavailable")

                if supersede_from_message_id is not None:
                    if len(messages) + 2 > 500:
                        raise StorageUnavailableError("message storage unavailable")
                    # A durable root cut supersedes its historical descendants
                    # through repository reads, keeping replacement writes bounded.
                    transaction.update(
                        self._collection.document(str(supersede_from_message_id)),
                        {"status": MessageStatus.SUPERSEDED.value},
                    )

                for item in messages:
                    transaction.create(message_refs[item.id], _message_data(item))
                changes = {"updated_at": updated_at}
                if preparation_id:
                    changes.update({
                        "context_preparation_id": None if complete_preparation else str(preparation_id),
                        "context_preparation_started_at": None if complete_preparation else updated_at,
                    })
                transaction.update(conversation_ref, changes)
                return list(messages)

            return prepare(transaction)

        return self._run(operation)

    def supersede_path(
        self, *, owner_id: str, conversation_id: UUID, message_id: UUID, updated_at: datetime
    ) -> list[Message]:
        self.get(owner_id=owner_id, conversation_id=conversation_id, message_id=message_id)
        snapshots = self._run(
            lambda: list(
                self._message_query(owner_id=owner_id, conversation_id=conversation_id).stream()
            )
        )
        messages = [
            message for snapshot in snapshots
            if scope_matches(message := _message_from_data(snapshot.to_dict()))
        ]
        by_id = {message.id: message for message in messages}
        identifiers = descendant_ids(messages, message_id)
        replaced = [
            by_id[identifier]
            for identifier in identifiers
            if identifier in by_id
            and effective_message(by_id[identifier], by_id).status is not MessageStatus.SUPERSEDED
        ]

        def operation() -> None:
            batch = self._client.batch()
            batch.update(
                self._collection.document(str(message_id)),
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

    def _message_query(self, *, owner_id: str, conversation_id: UUID) -> Any:
        query = self._collection.where(
            filter=firestore.FieldFilter("owner_id", "==", owner_id)
        ).where(filter=firestore.FieldFilter("conversation_id", "==", str(conversation_id)))
        return scope_query(query)

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


def _firestore_client(project_id: str | None, emulator_host: str | None) -> Any:
    """Build an SDK client without changing process-wide emulator settings.

    The Firestore SDK only discovers an emulator through the process environment.
    Setting that environment variable around construction races with concurrent
    dependency creation and any other Google client. Configure the instance's
    emulator endpoint directly instead, and use anonymous credentials so an
    emulator configuration can never fall through to cloud authentication.
    """
    if emulator_host is None:
        return firestore.Client(project=project_id)
    host = emulator_host.strip()
    if not host or "://" in host or "/" in host:
        raise ValueError("firestore_emulator_host must be a host and optional port")
    client = firestore.Client(
        project=project_id,
        credentials=AnonymousCredentials(),
    )
    # google-cloud-firestore has no public emulator_host constructor argument;
    # this field is consumed by its channel, endpoint, and metadata helpers.
    client._emulator_host = host
    return client
