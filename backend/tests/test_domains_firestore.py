"""Firestore domain transaction contracts exercised with an offline client fake."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from personal_ai.decisions.repositories import InMemoryDecisionRepository
from personal_ai.domains.contracts import DomainLookupReservation
from personal_ai.domains.fixtures import fixture_registry
from personal_ai.domains.repositories import (
    DomainRepositoryError,
    FirestoreDomainRepository,
    InMemoryDomainRepository,
)
from personal_ai.domains.service import DomainService
from personal_ai.settings import Settings
from tests.test_decisions_firestore import Collection, Snapshot


def firestore_domain_repository():
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

    def read(reference):
        data = client.records.get((reference.collection.name, reference.identifier))
        return iter([Snapshot(data)])

    def write(reference, data):
        client.records[(reference.collection.name, reference.identifier)] = data

    transaction.get.side_effect = read
    transaction.create.side_effect = write
    transaction.set.side_effect = write
    return FirestoreDomainRepository(client), client, transaction


def lookup_result():
    fixture = next(item for item in fixture_registry() if item.fixture_id == "travel-research-needed")
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        decision_enabled=True,
        travel_enabled=True,
    )
    service = DomainService(
        settings,
        InMemoryDecisionRepository(),
        InMemoryDomainRepository(),
        owner_id="local",
        clock=lambda: datetime(2026, 10, 2, 12, tzinfo=UTC),
    )
    return service.create("travel", fixture.request)


def reservation():
    now = datetime(2026, 10, 2, 12, tzinfo=UTC)
    return DomainLookupReservation(
        id=uuid4(),
        owner_id="local",
        domain_id="travel",
        idempotency_key=uuid4(),
        request_fingerprint="a" * 64,
        fence_token=uuid4(),
        created_at=now,
        updated_at=now,
    )


def test_firestore_completion_atomically_maps_lookup_to_owner_scoped_comparison():
    repository, client, _ = firestore_domain_repository()
    lookup = reservation()
    result = lookup_result()
    assert repository.reserve_lookup(lookup) == lookup

    saved = repository.complete_lookup(lookup.id, lookup.fence_token, result)
    assert saved == result
    stored = DomainLookupReservation.model_validate(
        client.records[("domain_lookup_idempotency", str(lookup.id))]
    )
    assert stored.state == "completed"
    assert stored.comparison_id == result.comparison.id
    assert repository.get("local", result.comparison.id) == result

    replay = repository.reserve_lookup(lookup.model_copy(update={"fence_token": uuid4()}))
    assert replay == stored
    assert repository.get("local", replay.comparison_id) == result


def test_firestore_completion_rejects_a_stale_fence_without_writing_a_comparison():
    repository, client, transaction = firestore_domain_repository()
    lookup = reservation()
    result = lookup_result()
    repository.reserve_lookup(lookup)
    transaction.create.reset_mock()
    transaction.set.reset_mock()

    with pytest.raises(DomainRepositoryError, match="domain_lookup_fence_lost"):
        repository.complete_lookup(lookup.id, uuid4(), result)

    assert ("domain_comparison_views", str(result.comparison.id)) not in client.records
    assert transaction.create.call_count == 0
    assert transaction.set.call_count == 0


def test_firestore_completion_rejects_cross_owner_result_mapping():
    repository, client, transaction = firestore_domain_repository()
    lookup = reservation().model_copy(update={"owner_id": "another-owner"})
    result = lookup_result()
    repository.reserve_lookup(lookup)
    transaction.create.reset_mock()
    transaction.set.reset_mock()

    with pytest.raises(DomainRepositoryError, match="domain_lookup_result_conflict"):
        repository.complete_lookup(lookup.id, lookup.fence_token, result)

    assert ("domain_comparison_views", str(result.comparison.id)) not in client.records
    assert transaction.create.call_count == 0
    assert transaction.set.call_count == 0


def test_firestore_preserves_prior_registration_when_feature_policy_changes():
    repository, client, _ = firestore_domain_repository()
    result = lookup_result()
    old = result.registration.model_copy(update={"feature_policy_version": "travel-features-v1"})
    client.records[("domain_registrations", "travel")] = old.model_dump(mode="json")

    assert repository.create(result) == result
    registrations = [data for (collection, _), data in client.records.items()
                     if collection == "domain_registrations"]
    assert {item["feature_policy_version"] for item in registrations} == {
        "travel-features-v1", "travel-features-v2",
    }
