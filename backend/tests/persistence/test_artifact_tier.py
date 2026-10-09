"""Opt-in real Postgres artifact metadata/CAS/fence checks; bodies stay fake."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
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


def test_durable_fence_survives_new_repository_instance(database):
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
    repo.fence(owner)
    new = ArtifactService(PostgresArtifactMetadataRepository(database), store)
    with pytest.raises(ArtifactUnavailable):
        new.read(ref.artifact_id, owner_id=owner, scope=ApplicationScope())
    assert new.reconcile(owner_id=owner)["deleted"] == 1


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
