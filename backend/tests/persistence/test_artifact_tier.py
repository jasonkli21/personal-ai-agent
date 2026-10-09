"""Opt-in real Postgres artifact metadata/CAS/fence checks; bodies stay fake."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event
from uuid import uuid4

import pytest

from personal_ai.artifacts.contracts import ArtifactBudgetExceeded, ArtifactUnavailable
from personal_ai.artifacts.local import InMemoryArtifactStore
from personal_ai.artifacts.service import ArtifactService
from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres import PostgresDatabase
from personal_ai.persistence.postgres_artifacts import PostgresArtifactMetadataRepository

pytestmark = pytest.mark.persistence_integration


@pytest.fixture
def database():
    dsn = os.environ.get("PERSISTENCE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set PERSISTENCE_TEST_POSTGRES_DSN for isolated local Postgres")
    database = PostgresDatabase(dsn, environment="test", min_size=1, max_size=4)
    database.migrate()
    try:
        yield database
    finally:
        database.close()


def test_metadata_body_separation_and_cas(database):
    repo = PostgresArtifactMetadataRepository(database)
    store = InMemoryArtifactStore()
    service = ArtifactService(repo, store)
    owner = f"artifact-test-{uuid4()}"
    ref = service.write(
        [{"score": 1}] * 100,
        owner_id=owner,
        scope=ApplicationScope(),
        kind="evaluation",
        identity=str(uuid4()),
        schema_version="test-v1",
        jsonl=True,
        required=True,
    )
    with database.connection() as connection:
        payload, size = connection.execute(
            "SELECT payload,octet_length(payload::text) FROM artifact_metadata WHERE artifact_id=%s",
            (ref.artifact_id,),
        ).fetchone()
    assert size < 8192 and "score" not in payload and "body" not in payload
    assert (
        service.read(ref.artifact_id, owner_id=owner, scope=ApplicationScope())
        == [{"score": 1}] * 100
    )
    assert service.delete(ref).status == "deleted"


def test_global_admission_is_atomic(database):
    today = datetime.now(UTC).date()
    with database.connection() as connection:
        row = connection.execute(
            "SELECT operations FROM artifact_storage_budgets WHERE budget_day=%s", (today,)
        ).fetchone()
    before = row[0] if row else 0
    repo = PostgresArtifactMetadataRepository(database, max_operations=before + 1)

    def reserve(_):
        try:
            repo.reserve(operations=1, byte_count=0)
            return True
        except ArtifactBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert sum(executor.map(reserve, range(8))) == 1


def test_store_rotation_admission_is_atomic_across_instances(database):
    barrier = Barrier(2)
    stores = [InMemoryArtifactStore(), InMemoryArtifactStore()]
    stores[0].store_id = "gcs:artifact-store-one"
    stores[1].store_id = "gcs:artifact-store-two"
    services = [
        ArtifactService(PostgresArtifactMetadataRepository(database), store) for store in stores
    ]
    owners = [f"artifact-test-{uuid4()}" for _ in services]

    def write(index):
        barrier.wait(timeout=5)
        try:
            return services[index].write(
                {"score": index}, owner_id=owners[index], scope=ApplicationScope(),
                kind="evaluation", identity=str(uuid4()), schema_version="test-v1",
                required=True,
            )
        except ArtifactUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, range(2)))

    assert sum(result is not None for result in results) == 1
    with database.connection() as connection:
        stored = connection.execute(
            "SELECT count(*),count(DISTINCT payload->>'store_id') FROM artifact_metadata "
            "WHERE owner_id=ANY(%s)",
            (owners,),
        ).fetchone()
    assert stored == (1, 1)
    assert sum(bool(store.objects) for store in stores) == 1


def test_durable_fence_survives_new_repository_instance(database, monkeypatch):
    repo = PostgresArtifactMetadataRepository(database)
    owner = f"artifact-test-{uuid4()}"
    store = InMemoryArtifactStore()
    service = ArtifactService(repo, store)
    ref = service.write(
        {"score": 1},
        owner_id=owner,
        scope=ApplicationScope(),
        kind="evaluation",
        identity=str(uuid4()),
        schema_version="test-v1",
        required=True,
    )
    put = store.put
    monkeypatch.setattr(store, "put", lambda *args: (_ for _ in ()).throw(OSError("offline")))
    pending = service.write(
        {"score": 2}, owner_id=owner, scope=ApplicationScope(), kind="evaluation",
        identity=str(uuid4()), schema_version="test-v1",
    )
    monkeypatch.setattr(store, "put", put)
    missing = service.write(
        {"score": 3}, owner_id=owner, scope=ApplicationScope(), kind="evaluation",
        identity=str(uuid4()), schema_version="test-v1", required=True,
    )
    missing = service._state(missing, "missing")
    assert pending is None
    repo.fence(owner)
    new = ArtifactService(PostgresArtifactMetadataRepository(database), store)
    with pytest.raises(ArtifactUnavailable):
        new.read(ref.artifact_id, owner_id=owner, scope=ApplicationScope())
    assert new.reconcile(owner_id=owner)["deleted"] == 3


def test_account_confirmation_fence_and_cancel_before_cleanup(database):
    from personal_ai.persistence.postgres_auth import PostgresAccountLifecycleRepository

    owner = f"artifact-test-{uuid4()}"
    lifecycle = PostgresAccountLifecycleRepository(database)
    request = lifecycle.create_deletion(
        owner_id=owner, idempotency_key=uuid4(), correlation_id="test"
    )
    lifecycle.transition_deletion(
        owner_id=owner, request_id=request["id"], action="confirm", correlation_id="test"
    )
    metadata = PostgresArtifactMetadataRepository(database)
    assert not metadata.active(owner)
    lifecycle.transition_deletion(
        owner_id=owner, request_id=request["id"], action="cancel", correlation_id="test"
    )
    assert metadata.active(owner)


def test_cancel_winning_owner_cleanup_claim_prevents_physical_delete(database):
    from personal_ai.persistence.postgres_auth import PostgresAccountLifecycleRepository

    owner = f"artifact-test-{uuid4()}"
    scope = ApplicationScope()
    lifecycle = PostgresAccountLifecycleRepository(database)
    metadata = PostgresArtifactMetadataRepository(database)
    store = InMemoryArtifactStore()
    service = ArtifactService(metadata, store)
    ref = service.write(
        {"score": 1}, owner_id=owner, scope=scope, kind="evaluation",
        identity=str(uuid4()), schema_version="test-v1", required=True,
    )
    request = lifecycle.create_deletion(
        owner_id=owner, idempotency_key=uuid4(), correlation_id="test"
    )
    lifecycle.transition_deletion(
        owner_id=owner, request_id=request["id"], action="confirm", correlation_id="test"
    )
    selected = Event()
    resume = Event()
    delete = service.delete

    def paused_delete(candidate, *, owner_deletion=False):
        if owner_deletion:
            selected.set()
            assert resume.wait(5)
        return delete(candidate, owner_deletion=owner_deletion)

    service.delete = paused_delete
    with ThreadPoolExecutor(max_workers=1) as executor:
        reconciliation = executor.submit(service.reconcile, limit=10, owner_id=owner)
        assert selected.wait(5)
        lifecycle.transition_deletion(
            owner_id=owner, request_id=request["id"], action="cancel", correlation_id="test"
        )
        resume.set()
        result = reconciliation.result(timeout=5)

    assert result["failed"] == 1
    assert metadata.active(owner)
    assert metadata.get(ref.artifact_id, owner_id=owner, scope=scope).status == "ready"
    assert store.read(ref.key, ref.generation, max_bytes=ref.compressed_bytes)


def test_owner_cleanup_claim_winning_cancellation_returns_conflict(database):
    from personal_ai.auth.account_data import AccountRequestConflict
    from personal_ai.persistence.postgres_auth import PostgresAccountLifecycleRepository

    owner = f"artifact-test-{uuid4()}"
    scope = ApplicationScope()
    lifecycle = PostgresAccountLifecycleRepository(database)
    metadata = PostgresArtifactMetadataRepository(database)
    store = InMemoryArtifactStore()
    service = ArtifactService(metadata, store)
    ref = service.write(
        {"score": 1}, owner_id=owner, scope=scope, kind="evaluation",
        identity=str(uuid4()), schema_version="test-v1", required=True,
    )
    request = lifecycle.create_deletion(
        owner_id=owner, idempotency_key=uuid4(), correlation_id="test"
    )
    lifecycle.transition_deletion(
        owner_id=owner, request_id=request["id"], action="confirm", correlation_id="test"
    )
    deleting = Event()
    resume = Event()
    delete = store.delete

    def paused_delete(key, generation):
        deleting.set()
        assert resume.wait(5)
        return delete(key, generation)

    store.delete = paused_delete
    with ThreadPoolExecutor(max_workers=1) as executor:
        reconciliation = executor.submit(service.reconcile, limit=10, owner_id=owner)
        assert deleting.wait(5)
        with pytest.raises(AccountRequestConflict):
            lifecycle.transition_deletion(
                owner_id=owner, request_id=request["id"], action="cancel", correlation_id="test"
            )
        assert metadata.get(ref.artifact_id, owner_id=owner, scope=scope).status == "deleting"
        resume.set()
        result = reconciliation.result(timeout=5)

    assert result["deleted"] == 1
    assert metadata.get(ref.artifact_id, owner_id=owner, scope=scope).status == "deleted"
    assert not store.objects
