"""Exercise Firestore serialization, transaction deadlines and bounded indexed search."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import ServiceUnavailable
from google.cloud.firestore_v1.vector import Vector

from personal_ai.evaluation.memory import build_fixture, load_fixtures
from personal_ai.memory.fake import FakeMemoryExtractor
from personal_ai.memory.repositories import FirestoreMemoryRepository
from personal_ai.memory.services import MemoryExtractionService
from personal_ai.storage.errors import ConversationConflictError, StorageUnavailableError


def seeded():
    settings, conversations, messages, repo, turns, candidates, _, embedder = build_fixture(
        load_fixtures()[0]
    )
    MemoryExtractionService(
        settings, repo, messages, FakeMemoryExtractor(candidates), embedder
    ).run(turns[0][1])
    return next(iter(repo.records.values())), conversations, turns


def snapshot(data):
    return SimpleNamespace(exists=data is not None, to_dict=lambda: data)


def test_firestore_create_atomic_source_check_idempotency_and_rpc_deadline():
    memory, conversations, turns = seeded()
    client = MagicMock()
    api = client._firestore_api
    api.begin_transaction.return_value = SimpleNamespace(transaction=b"offline")
    transaction = client.transaction.return_value
    transaction.id = b"offline"
    transaction._write_pbs = []
    records = {
        ("memories", str(memory.id)): None,
        ("conversations", str(memory.source_conversation_id)): next(
            iter(conversations._conversations.values())
        ).model_dump(mode="json"),
        **{("messages", str(m.id)): m.model_dump(mode="json") for m in turns[0]},
    }
    refs = {}

    def collection(name):
        result = MagicMock()

        def document(identifier):
            ref = refs.setdefault((name, identifier), MagicMock())
            ref.get.side_effect = lambda **kwargs: snapshot(records.get((name, identifier)))
            return ref

        result.document.side_effect = document
        return result

    client.collection.side_effect = collection
    repository = FirestoreMemoryRepository(client)
    assert repository.create(memory, timeout=2) == (memory, True)
    assert transaction.create.call_count == 1
    data = transaction.create.call_args.args[1]
    assert isinstance(data["embedding"], Vector)
    assert data["source_turn_id"] == str(turns[0][1].id)
    for method in (api.begin_transaction, api.commit):
        assert method.call_args.kwargs["retry"] is None
        assert 0 < method.call_args.kwargs["timeout"] <= 2
    records[("memories", str(memory.id))] = data
    transaction.create.reset_mock()
    assert repository.create(memory)[1] is False
    transaction.create.assert_not_called()
    records[("memories", str(memory.id))] = None
    records[("messages", str(turns[0][0].id))]["status"] = "superseded"
    with pytest.raises(ConversationConflictError):
        repository.create(memory)
    api.rollback.assert_called_once()
    transaction.create.assert_not_called()


def test_firestore_owner_status_model_prefilters_vector_limit_and_safe_failures():
    memory, _, _ = seeded()
    client = MagicMock()
    collection = client.collection.return_value
    collection.where.return_value = collection
    nearest = collection.find_nearest.return_value
    data = memory.model_dump(mode="json")
    data["embedding"] = Vector(memory.embedding)
    data["vector_distance"] = 0.02
    nearest.stream.return_value = [snapshot(data)]
    repository = FirestoreMemoryRepository(client)
    result = repository.search(
        owner_id="local", embedding=[1, 0, 0], model="fake-v1", dimensions=3, limit=10
    )
    assert result[0].memory == memory
    assert result[0].similarity == 0.98
    filters = [call.kwargs["filter"] for call in collection.where.call_args_list]
    assert [(f.field_path, f.value) for f in filters] == [
        ("owner_id", "local"),
        ("status", "active"),
        ("embedding_model", "fake-v1"),
        ("embedding_dimensions", 3),
    ]
    assert collection.find_nearest.call_args.kwargs["limit"] == 10
    assert nearest.stream.call_args.kwargs["retry"] is None
    nearest.stream.side_effect = ServiceUnavailable("private storage message")
    with pytest.raises(StorageUnavailableError) as caught:
        repository.search(
            owner_id="local", embedding=[1, 0, 0], model="fake-v1", dimensions=3, limit=10
        )
    assert "private" not in str(caught.value)


def test_firestore_memory_create_rejects_cyclic_source_ancestry_before_commit():
    memory, conversations, turns = seeded()
    client = MagicMock()
    client._firestore_api.begin_transaction.return_value = SimpleNamespace(transaction=b"offline")
    transaction = client.transaction.return_value
    transaction.id = b"offline"
    transaction._write_pbs = []
    user, assistant = turns[0]
    records = {
        ("memories", str(memory.id)): None,
        ("conversations", str(memory.source_conversation_id)): next(
            iter(conversations._conversations.values())
        ).model_dump(mode="json"),
        ("messages", str(user.id)): {
            **user.model_dump(mode="json"), "parent_message_id": str(user.id),
        },
        ("messages", str(assistant.id)): assistant.model_dump(mode="json"),
    }

    def collection(name):
        result = MagicMock()

        def document(identifier):
            reference = MagicMock()
            reference.get.side_effect = lambda **_: snapshot(records.get((name, identifier)))
            return reference

        result.document.side_effect = document
        return result

    client.collection.side_effect = collection
    repository = FirestoreMemoryRepository(client)
    with pytest.raises(ConversationConflictError, match="ancestry invalid"):
        repository.create(memory)
    transaction.create.assert_not_called()
    client._firestore_api.commit.assert_not_called()
    client._firestore_api.rollback.assert_called_once()
