"""Backend-neutral persistence invariants that do not require local services."""


import pytest

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.dynamodb import DynamoDBLocalClient, _namespace
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
