"""Decision Firestore transaction and reconstruction tests without a live service."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from personal_ai.decisions.contracts import DecisionCreateRequest
from personal_ai.decisions.firestore import FirestoreDecisionRepository
from personal_ai.decisions.repositories import DecisionError, InMemoryDecisionRepository
from personal_ai.entities.research import EntityAlias, MoneyValue, TextValue
from personal_ai.storage.errors import ResourceNotFoundError
from tests.test_decisions import evidence, make_service


class Snapshot:
    def __init__(self, data, identifier=None):
        self.exists = data is not None
        self._data = data
        self.id = identifier

    def to_dict(self):
        return self._data


class Document:
    def __init__(self, collection, identifier):
        self.collection = collection
        self.identifier = identifier

    def get(self, **_):
        return Snapshot(
            self.collection.client.records.get((self.collection.name, self.identifier)),
            self.identifier,
        )


class Query:
    def __init__(self, collection, filters=(), maximum=None, ordering=None, after=None):
        self.collection = collection
        self.filters = filters
        self.maximum = maximum
        self.ordering = ordering
        self.after = after

    def where(self, *, filter):
        return Query(self.collection, (*self.filters, filter), self.maximum, self.ordering, self.after)

    def limit(self, maximum):
        return Query(self.collection, self.filters, maximum, self.ordering, self.after)

    def order_by(self, field, *, direction=None):
        return Query(self.collection, self.filters, self.maximum, (field, direction), self.after)

    def start_after(self, snapshot):
        return Query(self.collection, self.filters, self.maximum, self.ordering, snapshot.id)

    def stream(self, **_):
        docs = []
        for (collection_name, identifier), data in self.collection.client.records.items():
            if collection_name != self.collection.name:
                continue
            if all(self._matches(data, condition) for condition in self.filters):
                docs.append(Snapshot(data, identifier))
        if self.ordering:
            field, direction = self.ordering
            docs.sort(
                key=lambda item: item.id if field == "__name__" else item.to_dict().get(field),
                reverse=direction == "DESCENDING",
            )
        if self.after is not None:
            index = next((i for i, item in enumerate(docs) if item.id == self.after), None)
            docs = docs[index + 1:] if index is not None else []
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


def test_firestore_historical_decision_does_not_gain_aliases_from_later_evidence():
    repository, client, _ = repository_environment()
    result = decision_result()
    repository.create(result)
    assert result.decision.alias_ids == ()
    later_alias = EntityAlias(
        id=uuid4(), entity_id=result.entities[0].id, owner_id="local",
        normalized_alias="later alias", source_evidence_ids=(uuid4(),),
        created_at=result.decision.created_at,
    )
    client.records[("entity_aliases", str(later_alias.id))] = later_alias.model_dump(mode="json")
    assert repository.get("local", result.decision.id) == result


def test_firestore_claim_attribute_filter_finds_relevant_record_past_unrelated_prefix():
    repository, client, _ = repository_environment()
    result = decision_result()
    entity_id = result.entities[0].id
    base_claim = result.claims[0]
    for index in range(501):
        unrelated = base_claim.model_copy(update={
            "id": uuid4(), "attribute": "color", "typed_value": TextValue(value="blue"),
            "original_value": "blue",
        })
        client.records[("entity_claims", str(unrelated.id))] = unrelated.model_dump(mode="json")
    relevant = next(claim for claim in result.claims if claim.attribute == "price")
    client.records[("entity_claims", str(relevant.id))] = relevant.model_dump(mode="json")

    fetched = repository.list_claims("local", (entity_id,), ("price",), limit=5)
    assert tuple(item.id for item in fetched) == (relevant.id,)

    fake = InMemoryDecisionRepository()
    fake.claims = {
        uuid4(): base_claim.model_copy(update={
            "attribute": "color", "typed_value": TextValue(value="blue"), "original_value": "blue",
        })
        for _ in range(501)
    }
    fake.claims[relevant.id] = relevant
    assert fake.list_claims("local", (entity_id,), ("price",), limit=5) == (relevant,)


def test_standalone_entity_limit_is_applied_after_scope_filtering():
    repository, client, _ = repository_environment()
    result = decision_result()
    standalone = result.entities[0].model_copy(update={
        "id": uuid4(), "application_id": "personal_ai", "workspace_id": None,
        "scope_version": 2,
    })
    for index in range(120):
        foreign = standalone.model_copy(update={
            "id": uuid4(), "canonical_name": f"Foreign {index}",
            "application_id": "travel", "scope_version": 2,
        })
        client.records[("canonical_entities", f"a-{index:03}")] = foreign.model_dump(mode="json")
    client.records[("canonical_entities", "z-standalone")] = standalone.model_dump(mode="json")

    assert repository.list_entities("local", "object", limit=1) == (standalone,)


def test_firestore_alias_reads_batch_entity_ids_and_preserve_all_owner_scoped_aliases(monkeypatch):
    repository, client, _ = repository_environment()
    result = decision_result()
    entity_ids = tuple(uuid4() for _ in range(31))
    expected = []
    for index, entity_id in enumerate(entity_ids):
        for owner in ("local", "*", "other"):
            alias = EntityAlias(
                id=uuid4(), entity_id=entity_id, owner_id=owner,
                normalized_alias=f"alias {index}", created_at=result.decision.created_at,
            )
            client.records[("entity_aliases", str(alias.id))] = alias.model_dump(mode="json")
            if owner != "other":
                expected.append(alias)
    calls = []
    stream = Query.stream

    def counted_stream(self, **kwargs):
        calls.append(kwargs)
        return stream(self, **kwargs)

    monkeypatch.setattr(Query, "stream", counted_stream)
    assert repository.list_aliases("local", entity_ids) == tuple(sorted(expected, key=lambda alias: str(alias.id)))
    assert len(calls) == 4  # Two ownership scopes, two bounded groups of IDs.
    assert all(call["retry"] is None and 0 < call["timeout"] <= 5 for call in calls)
