"""Decision Firestore transaction and reconstruction tests without a live service."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from personal_ai.decisions.contracts import DecisionCreateRequest
from personal_ai.decisions.firestore import FirestoreDecisionRepository
from personal_ai.decisions.repositories import DecisionError
from personal_ai.entities.research import MoneyValue
from personal_ai.storage.errors import ResourceNotFoundError
from tests.test_decisions import evidence, make_service


class Snapshot:
    def __init__(self, data):
        self.exists = data is not None
        self._data = data

    def to_dict(self):
        return self._data


class Document:
    def __init__(self, collection, identifier):
        self.collection = collection
        self.identifier = identifier

    def get(self, **_):
        return Snapshot(self.collection.client.records.get((self.collection.name, self.identifier)))


class Query:
    def __init__(self, collection, filters=(), maximum=None):
        self.collection = collection
        self.filters = filters
        self.maximum = maximum

    def where(self, *, filter):
        return Query(self.collection, (*self.filters, filter), self.maximum)

    def limit(self, maximum):
        return Query(self.collection, self.filters, maximum)

    def stream(self, **_):
        docs = []
        for (collection_name, identifier), data in self.collection.client.records.items():
            if collection_name != self.collection.name:
                continue
            if all(self._matches(data, condition) for condition in self.filters):
                docs.append(Snapshot(data))
        return docs[: self.maximum]

    @staticmethod
    def _matches(data, condition):
        actual = data.get(condition.field_path)
        if condition.op_string == "==":
            return actual == condition.value
        if condition.op_string == "in":
            return actual in condition.value
        if condition.op_string == "array_contains":
            return condition.value in actual
        raise AssertionError(f"unexpected Firestore query operator {condition.op_string}")


class Collection:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def document(self, identifier):
        return Document(self, identifier)

    def where(self, *, filter):
        return Query(self, (filter,))


def repository_environment():
    client = MagicMock()
    client.records = {}
    client.collections = {}
    client._firestore_api.begin_transaction.return_value = SimpleNamespace(transaction=b"offline")
    transaction = client.transaction.return_value
    transaction._write_pbs = []

    def collection(name):
        client.collections.setdefault(name, Collection(client, name))
        return client.collections[name]

    client.collection.side_effect = collection

    def read(ref):
        data = client.records.get((ref.collection.name, ref.identifier))
        return iter([Snapshot(data)])

    transaction.get.side_effect = read
    transaction.create.side_effect = lambda ref, data: client.records.__setitem__(
        (ref.collection.name, ref.identifier), data
    )
    return FirestoreDecisionRepository(client), client, transaction


def decision_result():
    service = make_service()
    source = evidence("Tiny Widget costs $10.")
    request = DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(
            {
                "entity_type": "object",
                "canonical_name": "Tiny Widget",
                "claims": ({
                    "attribute": "price",
                    "typed_value": MoneyValue(amount=Decimal(10), currency="USD"),
                    "original_value": "$10",
                    "currency": "USD",
                    "evidence_ids": (source.evidence_id,),
                },),
            },
        ),
        supplied_evidence=(source,),
    )
    return service.create(request)


def test_firestore_decision_writes_snapshot_atomically_and_reconstructs_owner_scoped_result():
    repository, client, transaction = repository_environment()
    result = decision_result()

    assert repository.create(result) == result
    assert len(client.records) == (
        len(result.entities) + len(result.aliases) + len(result.claims)
        + len(result.matches) + len(result.evaluations) + 2
    )
    assert transaction.create.call_count == len(client.records)
    assert all("passage" not in value for value in client.records.values())

    replay = repository.create(result)
    assert replay == result
    assert repository.get("local", result.decision.id) == result
    with pytest.raises(ResourceNotFoundError):
        repository.get("another-owner", result.decision.id)


def test_firestore_decision_rejects_idempotency_conflict_before_writing():
    repository, _, transaction = repository_environment()
    result = decision_result()
    repository.create(result)
    transaction.create.reset_mock()

    changed_decision = result.decision.model_copy(update={"request_fingerprint": "f" * 64})
    changed = result.model_copy(update={"decision": changed_decision})
    with pytest.raises(DecisionError, match="idempotency_conflict"):
        repository.create(changed)
    transaction.create.assert_not_called()
