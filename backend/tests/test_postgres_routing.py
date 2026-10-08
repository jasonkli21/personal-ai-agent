"""Deterministic contract checks for Phase 18's Postgres registry owner."""

import json
from contextlib import contextmanager

import pytest
from pydantic import ValidationError

from personal_ai.persistence.postgres_routing import PostgresEndpointRegistryRepository
from personal_ai.routing import (
    DataUsePolicy,
    EndpointProfile,
    EndpointRegistry,
    QuotaBucket,
    RegistryConflictError,
    RegistryPayloadTooLargeError,
    StrictFreeEligibilityAttestation,
)


def _profile(
    version: int = 1,
    *,
    model: str = "model-a",
    profile_id: str = "synthetic:account-a:key-a:model-a",
    account_scope_id: str = "account-a",
    structured_schema_ids: tuple[str, ...] = (),
    quota_buckets: tuple[QuotaBucket, ...] | None = None,
) -> EndpointProfile:
    return EndpointProfile(
        endpoint_profile_id=profile_id,
        profile_version=version,
        provider_id="synthetic",
        model_id=model,
        endpoint_id="synthetic-chat-v1",
        deployment_id="synthetic-deployment-a",
        credential_source="environment",
        credential_reference="env:SYNTHETIC_MODEL_KEY",
        credential_scope_id="credential-a",
        account_scope_id=account_scope_id,
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
        strict_free_attestation=StrictFreeEligibilityAttestation(
            endpoint_profile_id=profile_id,
            provider_id="synthetic",
            model_id=model,
            endpoint_id="synthetic-chat-v1",
            deployment_id="synthetic-deployment-a",
            account_scope_id=account_scope_id,
            credential_scope_id="credential-a",
            tier_id="free",
            reference="preflight:synthetic-v1",
            source="synthetic_test",
            zero_cost_verified=True,
            paid_overflow_excluded=True,
        ),
        data_use_policy=DataUsePolicy(
            status="approved", max_sensitivity="personal", policy_reference="policy:v1"
        ),
        structured_schema_ids=structured_schema_ids,
        serializer_id="synthetic-chat-v1",
        runtime_id="synthetic-runtime-v1",
        quota_membership="verified",
        quota_buckets=quota_buckets if quota_buckets is not None else (QuotaBucket(
            bucket_id=f"synthetic-{account_scope_id}-requests",
            authority_scope_id=account_scope_id,
            operations=frozenset({"bounded_generation"}),
            unit="requests",
            window_seconds=3600,
            source="provider_contract",
            confidence="verified",
            evidence_reference="quota:synthetic-v1",
        ),),
    )


class _Cursor:
    def __init__(self, row=None, rowcount=0, rows=None):
        self._row = row
        self.rowcount = rowcount
        self._rows = rows if rows is not None else ([] if row is None else [row])

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _MemoryConnection:
    def __init__(self):
        self.namespace = None
        self.registry = None
        self.profile_versions = {}
        self.hide_registry_on_load = False
        self.hide_registry_on_lock = False

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
            if "FOR UPDATE" in query and self.hide_registry_on_lock:
                self.hide_registry_on_lock = False
                return _Cursor()
            if "FOR UPDATE" not in query and self.hide_registry_on_load:
                self.hide_registry_on_load = False
                return _Cursor()
            if self.registry is None:
                return _Cursor()
            return _Cursor((
                self.registry["registry_version"], self.registry["revision"],
                self.registry["payload"],
            ))
        if query.startswith("SELECT endpoint_profile_id,last_profile_version"):
            return _Cursor(rows=[
                (profile_id, version)
                for profile_id, version in sorted(self.profile_versions.items())
            ])
        if query.startswith("INSERT INTO endpoint_registry_snapshots"):
            if self.registry is not None:
                return _Cursor()
            self.registry = {
                "revision": params[4], "registry_version": params[5],
                "payload": json.loads(params[8]),
            }
            return _Cursor(
                row=(self.registry["registry_version"], self.registry["revision"]),
                rowcount=1,
            )
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
        if query.startswith("INSERT INTO endpoint_profile_version_history"):
            profile_id, version = params[1], params[2]
            self.profile_versions[profile_id] = max(
                self.profile_versions.get(profile_id, 0), version
            )
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
    restored = EndpointRegistry(None, repository=repository)

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

    with pytest.raises(RegistryConflictError, match="endpoint registry revision changed"):
        repository.save((first,), expected_registry_version=old_version)


def test_postgres_registry_reloads_winning_snapshot_after_initialization_race():
    database = _MemoryDatabase()
    repository = PostgresEndpointRegistryRepository(database)
    initial = _profile()
    seeded = EndpointRegistry((initial,), repository=repository)
    database.connection_value.hide_registry_on_load = True
    database.connection_value.hide_registry_on_lock = True

    initialized = EndpointRegistry(None, repository=repository)

    assert initialized.snapshot == seeded.snapshot
    assert database.connection_value.registry["revision"] == 1


def test_postgres_profile_version_history_survives_removal_and_restart():
    database = _MemoryDatabase()
    repository = PostgresEndpointRegistryRepository(database)
    initial = _profile()
    registry = EndpointRegistry((initial,), repository=repository)
    removed = registry.remove(initial.endpoint_profile_id)
    restored = EndpointRegistry(None, repository=repository)

    assert restored.profiles == ()
    assert repository.load_profile_version_history()[initial.endpoint_profile_id] == 1
    with pytest.raises(RegistryConflictError, match="increase_after_removal"):
        repository.save((initial,), expected_registry_version=removed.registry_version)

    reconciled = EndpointRegistry((initial,), repository=repository)
    assert reconciled.profiles[0].profile_version == 2


def test_repository_revalidates_model_copies_and_rejects_oversize_before_database_writes():
    database = _MemoryDatabase()
    repository = PostgresEndpointRegistryRepository(database)
    invalid = _profile().model_copy(update={"credential_source": "secret_manager"})
    with pytest.raises(ValidationError, match="credential_reference_source_mismatch"):
        repository.save((invalid,), expected_registry_version=None)
    assert database.connection_value.namespace is None

    schemas = tuple(f"schema:{index}:" + "x" * 180 for index in range(128))
    profiles = tuple(
        _profile(
            profile_id=profile_id,
            account_scope_id=f"account-{index}",
            quota_buckets=(QuotaBucket(
                bucket_id=f"quota:{index}",
                authority_scope_id=f"account-{index}",
                operations=frozenset({"bounded_generation"}),
                unit="requests",
                window_seconds=60,
                source="provider_contract",
                confidence="verified",
                evidence_reference="quota:synthetic-v1",
            ),),
            structured_schema_ids=schemas,
        )
        for index, profile_id in enumerate(f"large-profile:{value}" for value in range(6))
    )
    with pytest.raises(RegistryPayloadTooLargeError, match="payload_too_large"):
        repository.save(profiles, expected_registry_version=None)
    assert database.connection_value.namespace is None


def test_phase18_migration_owns_one_bounded_system_snapshot():
    from pathlib import Path

    migration = Path(__file__).parents[1] / "src/personal_ai/persistence/migrations/016_endpoint_registry.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS endpoint_registry_snapshots" in sql
    assert "owner_id = 'personal-ai-system'" in sql
    assert "pg_column_size(payload) <= 262144" in sql
    assert "registry_version char(64)" in sql
