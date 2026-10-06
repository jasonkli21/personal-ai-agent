"""Offline adapter tests for Firestore error handling and atomic writes."""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from google.api_core.exceptions import ServiceUnavailable
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from personal_ai.api.dependencies import get_conversation_repository, get_message_repository
from personal_ai.entities import Conversation, Message, MessageRole, MessageStatus
from personal_ai.settings import Settings
from personal_ai.storage import (
    FirestoreConversationRepository,
    FirestoreMessageRepository,
    ResourceNotFoundError,
    StorageUnavailableError,
)
from personal_ai.storage.firestore import _message_data

NOW = datetime(2026, 9, 1, tzinfo=UTC)
OWNER = "local"


class FakeSnapshot:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = deepcopy(data)
        self.exists = data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return deepcopy(self._data)


class FakeDocumentReference:
    def __init__(self, client: FakeFirestoreClient, collection: str, identifier: str) -> None:
        self.client = client
        self.collection_name = collection
        self.id = identifier

    def get(self, **_: Any) -> FakeSnapshot:
        return FakeSnapshot(self.client.data[self.collection_name].get(self.id))

    def create(self, data: dict[str, Any]) -> None:
        self.client.apply("create", self, data)

    def set(self, data: dict[str, Any]) -> None:
        self.client.apply("set", self, data)

    def update(self, data: dict[str, Any]) -> None:
        self.client.apply("update", self, data)


class FakeQuery:
    def __init__(
        self,
        client: FakeFirestoreClient,
        collection: str,
        filters: tuple[Any, ...] = (),
        ordering: tuple[str, Any] | None = None,
        result_limit: int | None = None,
    ) -> None:
        self.client = client
        self.collection_name = collection
        self.filters = filters
        self.ordering = ordering
        self.result_limit = result_limit

    def where(self, *, filter: Any) -> FakeQuery:
        return FakeQuery(
            self.client, self.collection_name, self.filters + (filter,), self.ordering,
            self.result_limit,
        )

    def order_by(self, field: str, *, direction: Any = None) -> FakeQuery:
        return FakeQuery(
            self.client, self.collection_name, self.filters, (field, direction),
            self.result_limit,
        )

    def limit(self, count: int) -> FakeQuery:
        return FakeQuery(
            self.client, self.collection_name, self.filters, self.ordering, count
        )

    def stream(self, **_: Any):
        def snapshots():
            if self.client.fail_query_stage == "iteration":
                raise ServiceUnavailable("fake lazy query failure")
            values = list(self.client.data[self.collection_name].items())
            for field_filter in self.filters:
                values = [
                    (identifier, data)
                    for identifier, data in values
                    if data.get(field_filter.field_path) == field_filter.value
                ]
            if self.ordering:
                field, direction = self.ordering
                values.sort(key=lambda item: item[1].get(field), reverse=direction == "DESCENDING")
            if self.result_limit is not None:
                values = values[: self.result_limit]
            for _, data in values:
                yield FakeSnapshot(data)

        return snapshots()


class FakeCollection(FakeQuery):
    def document(self, identifier: str) -> FakeDocumentReference:
        return FakeDocumentReference(self.client, self.collection_name, identifier)

    def where(self, *, filter: Any) -> FakeQuery:
        if self.client.fail_query_stage == "build":
            raise ServiceUnavailable("fake query construction failure")
        return super().where(filter=filter)


class FakeBatch:
    def __init__(self, client: FakeFirestoreClient) -> None:
        self.client = client
        self.writes: list[tuple[str, FakeDocumentReference, dict[str, Any]]] = []

    def create(self, ref: FakeDocumentReference, data: dict[str, Any]) -> None:
        self.writes.append(("create", ref, deepcopy(data)))

    def update(self, ref: FakeDocumentReference, data: dict[str, Any]) -> None:
        self.writes.append(("update", ref, deepcopy(data)))

    def commit(self) -> None:
        self.client.commit(self.writes)


class FakeTransaction:
    def __init__(self, client: FakeFirestoreClient) -> None:
        self.client = client
        self.writes: list[tuple[str, FakeDocumentReference, dict[str, Any]]] = []

    def get(self, ref_or_query: FakeDocumentReference | FakeQuery):
        # Match the installed SDK: reads are generators, including point reads.
        if isinstance(ref_or_query, FakeQuery):
            return iter(ref_or_query.stream(transaction=self))
        return iter([ref_or_query.get()])

    def create(self, ref: FakeDocumentReference, data: dict[str, Any]) -> None:
        self.writes.append(("create", ref, deepcopy(data)))

    def update(self, ref: FakeDocumentReference, data: dict[str, Any]) -> None:
        self.writes.append(("update", ref, deepcopy(data)))

    def commit(self) -> None:
        self.client.commit(self.writes)

    def rollback(self) -> None:
        self.writes.clear()


class FakeFirestoreClient:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, Any]]] = {
            "conversations": {},
            "messages": {},
        }
        self.fail_query_stage: str | None = None
        self.commit_error: Exception | None = None

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, name)

    def batch(self) -> FakeBatch:
        return FakeBatch(self)

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def apply(
        self, operation: str, ref: FakeDocumentReference, data: dict[str, Any]
    ) -> None:
        record = self.data[ref.collection_name]
        if operation == "create":
            if ref.id in record:
                raise ValueError("document already exists")
            record[ref.id] = deepcopy(data)
        elif operation == "set":
            record[ref.id] = deepcopy(data)
        elif operation == "update":
            if ref.id not in record:
                raise KeyError(ref.id)
            record[ref.id].update(deepcopy(data))

    def commit(
        self, writes: list[tuple[str, FakeDocumentReference, dict[str, Any]]]
    ) -> None:
        if self.commit_error is not None:
            error, self.commit_error = self.commit_error, None
            raise error
        # Validate first so the fake has the same all-or-nothing property as a batch.
        for operation, ref, _ in writes:
            found = ref.id in self.data[ref.collection_name]
            if operation == "create" and found:
                raise ValueError("document already exists")
            if operation == "update" and not found:
                raise KeyError(ref.id)
        for operation, ref, data in writes:
            self.apply(operation, ref, data)


@pytest.fixture
def transactional_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    def transactional(function):
        def invoke(transaction: FakeTransaction, *args: Any, **kwargs: Any):
            try:
                result = function(transaction, *args, **kwargs)
                transaction.commit()
                return result
            except BaseException:
                transaction.rollback()
                raise

        return invoke

    monkeypatch.setattr(firestore, "transactional", transactional)


def conversation(identifier: int = 1) -> Conversation:
    return Conversation(
        id=UUID(int=identifier), owner_id=OWNER, scope_version=2, title="Test",
        created_at=NOW, updated_at=NOW,
    )


def message(
    identifier: int,
    conversation_id: UUID,
    *,
    parent_message_id: UUID | None = None,
    status: MessageStatus = MessageStatus.COMPLETED,
    offset: int = 0,
) -> Message:
    return Message(
        id=UUID(int=identifier), conversation_id=conversation_id, owner_id=OWNER,
        scope_version=2,
        role=MessageRole.USER if identifier % 2 else MessageRole.ASSISTANT,
        content=f"message {identifier}", status=status,
        created_at=NOW + timedelta(seconds=offset), parent_message_id=parent_message_id,
    )


@pytest.mark.parametrize("stage", ["build", "iteration"])
@pytest.mark.parametrize("operation", ["conversation_list", "active_list", "supersede"])
def test_query_failures_are_mapped_during_build_and_lazy_iteration(
    stage: str, operation: str
) -> None:
    client = FakeFirestoreClient()
    conversation_record = conversation(100)
    conversation_repo = FirestoreConversationRepository(client)
    message_repo = FirestoreMessageRepository(client)
    conversation_repo.create(conversation_record)
    root = message(101, conversation_record.id)
    message_repo.create(root)
    client.fail_query_stage = stage

    with pytest.raises(StorageUnavailableError):
        if operation == "conversation_list":
            conversation_repo.list(owner_id=OWNER)
        elif operation == "active_list":
            message_repo.list_active(owner_id=OWNER, conversation_id=conversation_record.id)
        else:
            message_repo.supersede_path(
                owner_id=OWNER,
                conversation_id=conversation_record.id,
                message_id=root.id,
                updated_at=NOW + timedelta(seconds=1),
            )


def test_failed_replacement_transaction_preserves_old_branch_and_adds_no_records(
    transactional_fake: None,
) -> None:
    client = FakeFirestoreClient()
    conversation_record = conversation(200)
    conversation_repo = FirestoreConversationRepository(client)
    message_repo = FirestoreMessageRepository(client)
    conversation_repo.create(conversation_record)
    user = message(201, conversation_record.id, offset=1)
    old_answer = message(202, conversation_record.id, parent_message_id=user.id, offset=2)
    message_repo.create(user)
    message_repo.create(old_answer)
    replacement = message(
        204, conversation_record.id, parent_message_id=user.id,
        status=MessageStatus.STREAMING, offset=3,
    ).model_copy(update={"supersedes_message_id": old_answer.id, "content": ""})
    client.commit_error = ServiceUnavailable("fake transaction commit failure")

    with pytest.raises(StorageUnavailableError):
        message_repo.prepare_message_turn(
            owner_id=OWNER,
            conversation_id=conversation_record.id,
            expected_active_ids=[user.id, old_answer.id],
            supersede_from_message_id=old_answer.id,
            messages=[replacement],
            updated_at=NOW + timedelta(seconds=3),
        )

    assert message_repo.list_active(owner_id=OWNER, conversation_id=conversation_record.id) == [
        user, old_answer
    ]
    with pytest.raises(ResourceNotFoundError):
        message_repo.get(
            owner_id=OWNER, conversation_id=conversation_record.id, message_id=replacement.id
        )


def test_transaction_point_reads_support_cas_and_stale_turn_recovery(
    transactional_fake: None,
) -> None:
    client = FakeFirestoreClient()
    conversation_record = conversation(300)
    conversation_repo = FirestoreConversationRepository(client)
    message_repo = FirestoreMessageRepository(client)
    conversation_repo.create(conversation_record)
    user = message(301, conversation_record.id, offset=1)
    stale = message(
        302, conversation_record.id, parent_message_id=user.id,
        status=MessageStatus.STREAMING, offset=2,
    )
    message_repo.create(user)
    message_repo.create(stale)

    message_repo.recover_stale_turn(
        owner_id=OWNER,
        conversation_id=conversation_record.id,
        stale_before=NOW + timedelta(seconds=3),
        updated_at=NOW + timedelta(seconds=4),
    )

    recovered = message_repo.get(
        owner_id=OWNER, conversation_id=conversation_record.id, message_id=stale.id
    )
    assert recovered.status is MessageStatus.FAILED
    assert recovered.error_code == "turn_interrupted"
    completed = message_repo.update_status(
        owner_id=OWNER,
        conversation_id=conversation_record.id,
        message_id=stale.id,
        status=MessageStatus.COMPLETED,
        content="late response",
        updated_at=NOW + timedelta(seconds=5),
        expected_status=MessageStatus.STREAMING,
    )
    assert completed is None
    assert message_repo.get(
        owner_id=OWNER, conversation_id=conversation_record.id, message_id=stale.id
    ).status is MessageStatus.FAILED


def test_replacement_ignores_large_already_superseded_audit_branch(
    transactional_fake: None,
) -> None:
    client = FakeFirestoreClient()
    conversation_record = conversation(400)
    conversation_repo = FirestoreConversationRepository(client)
    message_repo = FirestoreMessageRepository(client)
    conversation_repo.create(conversation_record)
    user = message(401, conversation_record.id, offset=1)
    old_answer = message(402, conversation_record.id, parent_message_id=user.id, offset=2)
    message_repo.create(user)
    message_repo.create(old_answer)
    for identifier in range(1_000, 1_510):
        historical = message(
            identifier,
            conversation_record.id,
            parent_message_id=old_answer.id,
            status=MessageStatus.SUPERSEDED,
            offset=identifier,
        )
        client.data["messages"][str(historical.id)] = _message_data(historical)
    replacement = Message(
        id=UUID(int=1_600), conversation_id=conversation_record.id, owner_id=OWNER,
        scope_version=2,
        role=MessageRole.ASSISTANT, content="", status=MessageStatus.STREAMING,
        created_at=NOW + timedelta(seconds=1), parent_message_id=user.id,
        supersedes_message_id=old_answer.id,
    )

    message_repo.prepare_message_turn(
        owner_id=OWNER,
        conversation_id=conversation_record.id,
        expected_active_ids=[user.id, old_answer.id],
        supersede_from_message_id=old_answer.id,
        messages=[replacement],
        updated_at=NOW + timedelta(seconds=3),
    )

    assert message_repo.list_active(owner_id=OWNER, conversation_id=conversation_record.id) == [
        user, replacement
    ]
    assert all(
        client.data["messages"][str(UUID(int=identifier))]["status"] == "superseded"
        for identifier in range(1_000, 1_510)
    )


def test_env_file_emulator_host_is_applied_per_client_without_global_environment(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AI_PROVIDER=gemini\n"
        "AI_MODEL=gemini-2.5-flash\n"
        "FIRESTORE_PROJECT_ID=local-project\n"
        "FIRESTORE_EMULATOR_HOST=emulator.internal:8080\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    settings = Settings(_env_file=env_file)

    conversation_repo = get_conversation_repository(settings)
    message_repo = get_message_repository(settings)

    for repository in (conversation_repo, message_repo):
        client = repository._client
        assert client._emulator_host == "emulator.internal:8080"
        assert isinstance(client._credentials, AnonymousCredentials)
        assert client.project == "local-project"
        grpc_target = client._firestore_api.transport.grpc_channel._channel.target()
        assert grpc_target.decode().endswith("emulator.internal:8080")
    assert os.environ.get("FIRESTORE_EMULATOR_HOST") is None


def test_context_reservation_is_atomic_expires_and_cannot_be_released_by_old_request(
    transactional_fake: None,
) -> None:
    from personal_ai.storage.errors import ConversationConflictError
    client = FakeFirestoreClient()
    conv = conversation()
    FirestoreConversationRepository(client).create(conv)
    repository = FirestoreMessageRepository(client)
    user = message(1, conv.id)
    old = UUID(int=90)
    new = UUID(int=91)
    repository.prepare_message_turn(
        owner_id=OWNER, conversation_id=conv.id, expected_active_ids=[],
        supersede_from_message_id=None, messages=(user,), updated_at=NOW,
        preparation_id=old,
    )
    assert repository.list_active(owner_id=OWNER, conversation_id=conv.id) == [user]
    with pytest.raises(ConversationConflictError):
        repository.prepare_message_turn(
            owner_id=OWNER, conversation_id=conv.id, expected_active_ids=[user.id],
            supersede_from_message_id=None, messages=(), updated_at=NOW,
            preparation_id=new,
        )
    repository.recover_stale_turn(owner_id=OWNER, conversation_id=conv.id,
                                  stale_before=NOW + timedelta(seconds=1), updated_at=NOW)
    repository.prepare_message_turn(
        owner_id=OWNER, conversation_id=conv.id, expected_active_ids=[user.id],
        supersede_from_message_id=None, messages=(), updated_at=NOW,
        preparation_id=new,
    )
    with pytest.raises(ConversationConflictError):
        repository.prepare_message_turn(
            owner_id=OWNER, conversation_id=conv.id, expected_active_ids=[user.id],
            supersede_from_message_id=None, messages=(), updated_at=NOW,
            preparation_id=old, complete_preparation=True,
        )
    assistant = message(2, conv.id, parent_message_id=user.id, status=MessageStatus.STREAMING)
    repository.prepare_message_turn(
        owner_id=OWNER, conversation_id=conv.id, expected_active_ids=[user.id],
        supersede_from_message_id=None, messages=(assistant,), updated_at=NOW,
        preparation_id=new, complete_preparation=True,
    )
    assert client.data["conversations"][str(conv.id)]["context_preparation_id"] is None
    assert repository.list_active(owner_id=OWNER, conversation_id=conv.id) == [user, assistant]


def test_firestore_summary_repository_is_owner_scoped_append_only_and_maps_lazy_errors():
    from personal_ai.context.repositories import FirestoreSummaryRepository
    from personal_ai.evaluation.context import build_fixture, load_fixtures
    from tests.test_context import record
    client = FakeFirestoreClient()
    client.data["conversation_summaries"] = {}
    active, pending, _ = build_fixture(load_fixtures()[2])
    conv = Conversation(id=pending.conversation_id, owner_id=OWNER, title="Synthetic",
                        created_at=NOW, updated_at=NOW)
    FirestoreConversationRepository(client).create(conv)
    summaries = FirestoreSummaryRepository(client)
    summary = record(active[:2])
    summaries.create(summary)
    assert summaries.compatible(owner_id=OWNER, conversation_id=conv.id, active=active) == summary
    with pytest.raises(ResourceNotFoundError):
        summaries.compatible(owner_id="foreign", conversation_id=conv.id, active=active)
    with pytest.raises(ResourceNotFoundError):
        summaries.create(summary.model_copy(update={"owner_id": "foreign"}))
    for stage in ("build", "iteration"):
        client.fail_query_stage = stage
        with pytest.raises(StorageUnavailableError):
            summaries.compatible(owner_id=OWNER, conversation_id=conv.id, active=active)


@pytest.mark.parametrize('adapter', ['memory', 'firestore'])
@pytest.mark.parametrize('target_index', [0, 1])
def test_long_branch_replacement_uses_bounded_writes_and_preserves_audit(
    adapter, target_index, transactional_fake, monkeypatch,
):
    from uuid import uuid4

    from personal_ai.evaluation.context import build_fixture, load_fixtures
    from personal_ai.storage import InMemoryConversationRepository, InMemoryMessageRepository
    active, pending, _ = build_fixture({**load_fixtures()[0], 'turns': 300})
    conv = Conversation(id=pending.conversation_id, owner_id=OWNER, title='Long synthetic',
                        created_at=NOW, updated_at=NOW)
    writes = []
    if adapter == 'memory':
        conversations = InMemoryConversationRepository()
        conversations.create(conv)
        repository = InMemoryMessageRepository(conversations)
        for item in active:
            repository.create(item)
    else:
        client = FakeFirestoreClient()
        FirestoreConversationRepository(client).create(conv)
        repository = FirestoreMessageRepository(client)
        for item in active:
            client.data['messages'][str(item.id)] = _message_data(item)
        commit = client.commit
        def bounded_commit(items):
            assert len(items) <= 500
            writes.append(len(items))
            commit(items)
        monkeypatch.setattr(client, 'commit', bounded_commit)
    target = active[target_index]
    replacement = target.model_copy(update={
        'id': uuid4(), 'content': 'replacement', 'supersedes_message_id': target.id,
    })
    lease = uuid4()
    repository.prepare_message_turn(
        owner_id=OWNER, conversation_id=conv.id, expected_active_ids=[m.id for m in active],
        supersede_from_message_id=target.id, messages=(replacement,), updated_at=NOW,
        preparation_id=lease,
    )
    assert repository.list_active(owner_id=OWNER, conversation_id=conv.id) == [*active[:target_index], replacement]
    for item in (target, active[-1]):
        preserved = repository.get(owner_id=OWNER, conversation_id=conv.id, message_id=item.id)
        assert preserved.status is MessageStatus.SUPERSEDED
        assert preserved.content == item.content
        assert preserved.parent_message_id == item.parent_message_id
    assert repository.update_status(
        owner_id=OWNER, conversation_id=conv.id, message_id=active[-1].id,
        status=MessageStatus.FAILED, expected_status=MessageStatus.COMPLETED, updated_at=NOW,
    ) is None
    repository.release_preparation(owner_id=OWNER, conversation_id=conv.id, preparation_id=uuid4())
    from personal_ai.storage import ConversationConflictError
    with pytest.raises(ConversationConflictError):
        repository.prepare_message_turn(
            owner_id=OWNER, conversation_id=conv.id,
            expected_active_ids=[m.id for m in [*active[:target_index], replacement]],
            supersede_from_message_id=None, messages=(), updated_at=NOW, preparation_id=uuid4(),
        )
    repository.release_preparation(owner_id=OWNER, conversation_id=conv.id, preparation_id=lease)
    if writes:
        assert max(writes) == 3


def test_firestore_release_lease_is_owner_scoped_and_preserves_new_reservation(transactional_fake):
    from uuid import uuid4
    client = FakeFirestoreClient()
    conv = conversation()
    FirestoreConversationRepository(client).create(conv)
    repository = FirestoreMessageRepository(client)
    lease = uuid4()
    repository.prepare_message_turn(owner_id=OWNER, conversation_id=conv.id, expected_active_ids=[],
        supersede_from_message_id=None, messages=(), updated_at=NOW, preparation_id=lease)
    repository.release_preparation(owner_id=OWNER, conversation_id=conv.id, preparation_id=uuid4())
    assert client.data['conversations'][str(conv.id)]['context_preparation_id'] == str(lease)
    with pytest.raises(ResourceNotFoundError):
        repository.release_preparation(owner_id='foreign', conversation_id=conv.id, preparation_id=lease)
    repository.release_preparation(owner_id=OWNER, conversation_id=conv.id, preparation_id=lease)
    assert client.data['conversations'][str(conv.id)]['context_preparation_id'] is None
