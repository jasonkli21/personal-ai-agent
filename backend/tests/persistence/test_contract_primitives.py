"""Backend-neutral persistence invariants that do not require local services."""


from datetime import UTC, datetime
from uuid import uuid4

import pytest

from personal_ai.auth.scope import ApplicationScope
from personal_ai.memory.lifecycle import MemoryJob
from personal_ai.persistence.dynamodb import (
    DynamoDBLocalClient,
    DynamoDBMemoryJobRepository,
    _namespace,
)
from personal_ai.persistence.postgres import PostgresDatabase, PostgresPayloadRepository


def test_postgres_scope_id_is_unambiguous_and_null_workspace_is_distinct():
    standalone = ApplicationScope(application_id="personal_ai", workspace_id=None)
    empty_workspace = ApplicationScope(application_id="personal_ai", workspace_id="x")
    assert PostgresPayloadRepository.scope_id("ab", standalone) != (
        PostgresPayloadRepository.scope_id("a", standalone)
    )
    assert PostgresPayloadRepository.scope_id("owner", standalone) != (
        PostgresPayloadRepository.scope_id("owner", empty_workspace)
    )


def test_dynamodb_namespace_is_collision_safe_and_scope_presence_aware():
    assert _namespace(ApplicationScope(application_id="app", workspace_id=None), "a#b") != (
        _namespace(ApplicationScope(application_id="app", workspace_id="b"), "a")
    )
    assert _namespace(ApplicationScope(application_id="app", workspace_id=None), "owner") != (
        _namespace(ApplicationScope(application_id="app", workspace_id="workspace"), "owner")
    )


@pytest.mark.parametrize(
    "dsn,environment",
    [
        ("postgresql://user:pass@db.example.com:5432/app", "local"),
        ("postgresql://user:pass@localhost:5432/app", "production"),
    ],
)
def test_postgres_local_endpoint_policy_rejects_wrong_target(dsn, environment):
    with pytest.raises(ValueError):
        PostgresDatabase(dsn, environment=environment)


def test_dynamodb_client_requires_an_explicit_local_endpoint():
    for endpoint in ("", "https://localhost:8000", "http://dynamodb.us-east-1.amazonaws.com:8000"):
        with pytest.raises(ValueError):
            DynamoDBLocalClient(endpoint)


def test_job_publication_removal_preserves_canonical_job_id():
    class CapturingTable:
        operations = None

        def transact(self, operations):
            self.operations = operations

    now = datetime.now(UTC)
    job = MemoryJob(
        id=uuid4(), owner_id="owner", job_type="maintenance", candidate_memory_ids=(),
        policy_version="score-v1", policy_snapshot={}, status="completed",
        publish_pending=False, idempotency_key="job-retention-test",
        created_at=now, updated_at=now,
    )
    table = CapturingTable()
    repository = DynamoDBMemoryJobRepository(table)

    assert repository._save_job(
        {"PK": "owner", "SK": "JOB", "owner_id": "owner"},
        job,
        4,
        remove_publication=True,
    ) == job

    update = table.operations[0]["Update"]
    expression = update["UpdateExpression"]
    set_clause, remove_clause = expression.split(" REMOVE ", maxsplit=1)
    assert "job_id=:jobid" in set_clause
    assert "job_id" not in remove_clause.split(",")
