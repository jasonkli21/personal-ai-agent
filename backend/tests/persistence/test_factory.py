from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from personal_ai.persistence.factory import (
    PostgresDynamoPersistenceFactory,
    close_persistence_clients,
    persistence_factory,
)


@pytest.fixture(autouse=True)
def clear_shared_factories():
    close_persistence_clients()
    yield
    close_persistence_clients()


def _settings(**updates):
    defaults = {
        "app_environment": "test",
        "p10_cloud_adapters_configured": False,
        "persistence_local_postgres_dsn": SecretStr("postgresql://local/db"),
        "persistence_local_dynamodb_endpoint": "http://127.0.0.1:8000",
        "p10_neon_runtime_dsn": SecretStr(""),
        "p10_neon_pool_max_size": 4,
        "p10_dynamodb_region": "us-east-1",
        "p10_dynamodb_table_name": "personal-ai-runtime-v1",
        "p10_dynamodb_role_arn": "arn:aws:iam::123456789012:role/personal-ai-runtime",
        "p10_dynamodb_identity_token_audience": "https://example.test/aws-role",
    }
    defaults.update(updates)
    return SimpleNamespace(**defaults)


def test_local_factory_uses_explicit_local_stores_and_is_shared(monkeypatch):
    calls = []

    class Database:
        def __init__(self, dsn, *, environment):
            calls.append(("postgres", dsn, environment))

        def close(self):
            calls.append(("close-postgres",))

    class Table:
        def __init__(self, endpoint, *, table_name, region):
            calls.append(("dynamodb", endpoint, table_name, region))

        def close(self):
            calls.append(("close-dynamodb",))

    monkeypatch.setattr("personal_ai.persistence.postgres.PostgresDatabase", Database)
    monkeypatch.setattr("personal_ai.persistence.dynamodb.DynamoDBRuntimeTable", Table)
    settings = _settings()

    factory = persistence_factory(settings)

    assert isinstance(factory, PostgresDynamoPersistenceFactory)
    assert persistence_factory(settings) is factory
    assert calls == [
        ("postgres", "postgresql://local/db", "test"),
        ("dynamodb", "http://127.0.0.1:8000", "personal-ai-runtime-v1", "us-east-1"),
    ]
    close_persistence_clients()
    assert calls[-2:] == [("close-postgres",), ("close-dynamodb",)]


def test_deployed_factory_uses_neon_and_federated_dynamodb(monkeypatch):
    calls = []

    class Database:
        def __init__(self, dsn, *, environment, max_size):
            calls.append(("neon", dsn, environment, max_size))

        def close(self):
            calls.append(("close-neon",))

    class Table:
        def __init__(self, config):
            calls.append(("federated-dynamodb", config))

        def close(self):
            calls.append(("close-federated-dynamodb",))

    monkeypatch.setattr("personal_ai.persistence.neon.NeonRuntimeDatabase", Database)
    monkeypatch.setattr(
        "personal_ai.persistence.dynamodb_cloud.FederatedDynamoDBRuntimeTable", Table
    )
    settings = _settings(
        app_environment="production",
        p10_cloud_adapters_configured=True,
        p10_neon_runtime_dsn=SecretStr(
            "postgresql://runtime:secret@ep-example-pooler.us-east-1.aws.neon.tech/db"
        ),
        p10_neon_pool_max_size=3,
    )

    factory = persistence_factory(settings)

    assert isinstance(factory, PostgresDynamoPersistenceFactory)
    assert calls[0] == (
        "neon",
        "postgresql://runtime:secret@ep-example-pooler.us-east-1.aws.neon.tech/db",
        "production",
        3,
    )
    assert calls[1][0] == "federated-dynamodb"
    assert calls[1][1].table_name == "personal-ai-runtime-v1"
    assert calls[1][1].role_arn.endswith(":role/personal-ai-runtime")


@pytest.mark.parametrize(
    ("environment", "configured", "message"),
    [
        ("staging", False, "deployed_polyglot_persistence_required"),
        ("local", True, "cloud_persistence_requires_deployed_environment"),
    ],
)
def test_factory_rejects_missing_or_misplaced_cloud_configuration(
    environment, configured, message
):
    with pytest.raises(RuntimeError, match=message):
        persistence_factory(
            _settings(
                app_environment=environment,
                p10_cloud_adapters_configured=configured,
            )
        )
