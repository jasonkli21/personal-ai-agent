"""Postgres owner for the versioned, secret-free inference endpoint registry."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres import (
    PersistenceConflict,
    PostgresDatabase,
    PostgresPayloadRepository,
)
from personal_ai.routing.contracts import (
    EndpointProfile,
    EndpointRegistrySnapshot,
    compute_registry_version,
)
from personal_ai.routing.registry import EndpointRegistry

_OWNER_ID = "personal-ai-system"
_SCOPE = ApplicationScope(application_id="personal_ai")
_RECORD_ID = "endpoint-registry-v1"


class PostgresEndpointRegistryRepository:
    """CAS-persisted registry snapshots using the Phase 10 Postgres boundary."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def load(self) -> EndpointRegistrySnapshot | None:
        scope_id = PostgresPayloadRepository.scope_id(_OWNER_ID, _SCOPE)
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT registry_version,revision,payload FROM endpoint_registry_snapshots "
                "WHERE scope_id=%s AND record_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NULL",
                (scope_id, _RECORD_ID, _OWNER_ID, _SCOPE.application_id),
            ).fetchone()
        if row is None:
            return None
        registry_version, revision, payload = row
        snapshot = _decode_snapshot(payload)
        if snapshot.registry_version != registry_version or snapshot.revision != int(revision):
            raise RuntimeError("endpoint_registry_record_invalid")
        return snapshot

    def save(
        self,
        profiles: Sequence[EndpointProfile],
        *,
        expected_registry_version: str | None,
    ) -> EndpointRegistrySnapshot:
        profile_tuple = tuple(profiles)
        # Reuse the runtime invariants so direct repository writes cannot make
        # an over-limit or cross-account quota snapshot authoritative.
        EndpointRegistry(profile_tuple)
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            scope_id = _ensure_registry_namespace(connection)
            row = connection.execute(
                "SELECT registry_version,revision FROM endpoint_registry_snapshots "
                "WHERE scope_id=%s AND record_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NULL FOR UPDATE",
                (scope_id, _RECORD_ID, _OWNER_ID, _SCOPE.application_id),
            ).fetchone()
            if expected_registry_version is None:
                if row is not None:
                    raise PersistenceConflict("endpoint registry already initialized")
                snapshot = EndpointRegistrySnapshot(
                    revision=1,
                    registry_version=compute_registry_version(profile_tuple, revision=1),
                    profiles=profile_tuple,
                )
                payload = PostgresPayloadRepository._json(
                    snapshot.model_dump(mode="json")
                )
                connection.execute(
                    "INSERT INTO endpoint_registry_snapshots(record_id,scope_id,owner_id,"
                    "application_id,workspace_id,record_version,revision,registry_version,"
                    "created_at,updated_at,payload) "
                    "VALUES (%s,%s,%s,%s,NULL,1,%s,%s,%s,%s,%s::jsonb)",
                    (
                        _RECORD_ID, scope_id, _OWNER_ID, _SCOPE.application_id,
                        snapshot.revision, snapshot.registry_version, now, now, payload,
                    ),
                )
                return snapshot

            if row is None or row[0] != expected_registry_version:
                raise PersistenceConflict("endpoint registry revision changed")
            revision = int(row[1]) + 1
            snapshot = EndpointRegistrySnapshot(
                revision=revision,
                registry_version=compute_registry_version(profile_tuple, revision=revision),
                profiles=profile_tuple,
            )
            payload = PostgresPayloadRepository._json(snapshot.model_dump(mode="json"))
            cursor = connection.execute(
                "UPDATE endpoint_registry_snapshots SET revision=%s,registry_version=%s,"
                "updated_at=%s,payload=%s::jsonb WHERE scope_id=%s AND record_id=%s "
                "AND owner_id=%s AND application_id=%s AND workspace_id IS NULL "
                "AND revision=%s AND registry_version=%s",
                (
                    snapshot.revision, snapshot.registry_version, now, payload,
                    scope_id, _RECORD_ID, _OWNER_ID, _SCOPE.application_id,
                    int(row[1]), expected_registry_version,
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceConflict("endpoint registry revision changed")
            return snapshot


def _ensure_registry_namespace(connection: Any) -> str:
    scope_id = PostgresPayloadRepository.scope_id(_OWNER_ID, _SCOPE)
    connection.execute(
        "INSERT INTO scope_namespaces(scope_id,owner_id,application_id,workspace_id,scope_kind) "
        "VALUES (%s,%s,%s,NULL,'global') ON CONFLICT (scope_id) DO NOTHING",
        (scope_id, _OWNER_ID, _SCOPE.application_id),
    )
    row = connection.execute(
        "SELECT owner_id,application_id,workspace_id,scope_kind FROM scope_namespaces "
        "WHERE scope_id=%s",
        (scope_id,),
    ).fetchone()
    if row != (_OWNER_ID, _SCOPE.application_id, None, "global"):
        raise PersistenceConflict("endpoint registry scope namespace collision")
    return scope_id


def _decode_snapshot(payload: Any) -> EndpointRegistrySnapshot:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise RuntimeError("endpoint_registry_record_invalid") from error
    try:
        return EndpointRegistrySnapshot.model_validate(payload)
    except (TypeError, ValueError) as error:
        raise RuntimeError("endpoint_registry_record_invalid") from error
