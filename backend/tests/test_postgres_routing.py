"""Deterministic contract checks for Phase 18's Postgres registry owner."""

import json
from contextlib import contextmanager

import pytest

from personal_ai.persistence.postgres import PersistenceConflict
from personal_ai.persistence.postgres_routing import PostgresEndpointRegistryRepository
from personal_ai.routing import (
    DataUsePolicy,
    EndpointProfile,
    EndpointRegistry,
    QuotaBucket,
)


def _profile(version: int = 1, *, model: str = "model-a") -> EndpointProfile:
    return EndpointProfile(
        endpoint_profile_id="synthetic:account-a:key-a:model-a",
        profile_version=version,
        provider_id="synthetic",
        model_id=model,
        endpoint_id="synthetic-chat-v1",
        deployment_id="synthetic-deployment-a",
        credential_source="environment",
        credential_reference="env:SYNTHETIC_MODEL_KEY",
        credential_scope_id="credential-a",
        account_scope_id="account-a",
        tier_id="free",
        tier_verified=True,
        execution_mode="STRICT_FREE",
        cost_class="VERIFIED_FREE",
        billing_owner="provider_account",
        enabled=True,
        strict_free_enabled=True,
        capabilities=frozenset({"bounded_generation"}),
        context_limit_tokens=4096,
        max_output_tokens=1024,
        data_use_policy=DataUsePolicy(
            status="approved", max_sensitivity="personal", policy_reference="policy:v1"
        ),
        serializer_id="synthetic-chat-v1",
        runtime_id="synthetic-runtime-v1",
        quota_membership="verified",
        quota_buckets=(QuotaBucket(
            bucket_id="synthetic-account-a-requests",
            authority_scope_id="account-a",
            operations=frozenset({"bounded_generation"}),
            unit="requests",
            window_seconds=3600,
            source="provider_contract",
            confidence="verified",
        ),),
    )


class _Cursor:
    def __init__(self, row=None, rowcount=0):
        self._row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self._row


class _MemoryConnection:
    def __init__(self):
        self.namespace = None
        self.registry = None

    def execute(self, query, params=None):
        query = " ".join(query.split())
        params = tuple(params or ())
        if query.startswith("INSERT INTO scope_namespaces"):
            if self.namespace is None:
                self.namespace = (params[0], params[1], params[2], None, "global")
            return _Cursor()
        if query.startswith("SELECT owner_id,application_id,workspace_id,scope_kind"):
            return _Cursor(self.namespace[1:] if self.namespace is not None else None)
        if query.startswith("SELECT registry_version,revision,payload"):
            if self.registry is None:
                return _Cursor()
            return _Cursor((
                self.registry["registry_version"], self.registry["revision"],
                self.registry["payload"],
            ))
        if query.startswith("SELECT registry_version,revision FROM"):
            if self.registry is None:
                return _Cursor()
            return _Cursor((self.registry["registry_version"], self.registry["revision"]))
        if query.startswith("INSERT INTO endpoint_registry_snapshots"):
            if self.registry is not None:
                raise RuntimeError("unique_violation")
            self.registry = {
                "revision": params[4], "registry_version": params[5],
                "payload": json.loads(params[8]),
            }
            return _Cursor(rowcount=1)
        if query.startswith("UPDATE endpoint_registry_snapshots"):
            if (
                self.registry is None
                or self.registry["revision"] != params[8]
                or self.registry["registry_version"] != params[9]
            ):
                return _Cursor(rowcount=0)
            self.registry = {
                "revision": params[0], "registry_version": params[1],
                "payload": json.loads(params[3]),
            }
            return _Cursor(rowcount=1)
        raise AssertionError(f"unhandled SQL in contract fixture: {query}")


class _MemoryDatabase:
    def __init__(self):
        self.connection_value = _MemoryConnection()

    @contextmanager
    def connection(self, **_kwargs):
        yield self.connection_value

    @contextmanager
    def transaction(self, **_kwargs):
        yield self.connection_value


def test_postgres_repository_seeds_updates_and_reloads_registry_snapshot():
    database = _MemoryDatabase()
    repository = PostgresEndpointRegistryRepository(database)
    initial = _profile()
    registry = EndpointRegistry((initial,), repository=repository)

    assert registry.snapshot.revision == 1
    assert repository.load() == registry.snapshot

    updated = initial.model_copy(update={"profile_version": 2, "context_limit_tokens": 2048})
    registry.upsert(updated)
    restored = EndpointRegistry((), repository=repository)

    assert restored.snapshot == registry.snapshot
    assert restored.snapshot.revision == 2
    assert restored.profiles[0].context_limit_tokens == 2048


def test_postgres_repository_rejects_stale_registry_compare_and_swap():
    database = _MemoryDatabase()
    repository = PostgresEndpointRegistryRepository(database)
    first = _profile()
    registry = EndpointRegistry((first,), repository=repository)
    old_version = registry.registry_version
    updated = first.model_copy(update={"profile_version": 2, "context_limit_tokens": 2048})
    registry.upsert(updated)

    with pytest.raises(PersistenceConflict, match="endpoint registry revision changed"):
        repository.save((first,), expected_registry_version=old_version)


def test_phase18_migration_owns_one_bounded_system_snapshot():
    from pathlib import Path

    migration = Path(__file__).parents[1] / "src/personal_ai/persistence/migrations/016_endpoint_registry.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS endpoint_registry_snapshots" in sql
    assert "owner_id = 'personal-ai-system'" in sql
    assert "pg_column_size(payload) <= 262144" in sql
    assert "registry_version char(64)" in sql
