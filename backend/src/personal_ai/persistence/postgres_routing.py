"""Postgres owner for the versioned, secret-free inference endpoint registry."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres import (
    PostgresDatabase,
    PostgresPayloadRepository,
)
from personal_ai.routing.contracts import (
    EndpointProfile,
    EndpointRegistrySnapshot,
    compute_registry_version,
)
from personal_ai.routing.registry import (
    MAX_ENDPOINT_REGISTRY_JSON_BYTES,
    EndpointRegistry,
    RegistryConflictError,
    RegistryPayloadTooLargeError,
)

_OWNER_ID = "personal-ai-system"
_SCOPE = ApplicationScope(application_id="personal_ai")
_RECORD_ID = "endpoint-registry-v1"


class PostgresEndpointRegistryRepository:
    """CAS-persisted registry snapshots using the Phase 10 Postgres boundary."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def load(self) -> EndpointRegistrySnapshot | None:
        with self.database.connection() as connection:
            return self.load_from_connection(connection)

    def load_from_connection(self, connection, *, lock: bool = False):
        """Read a registry snapshot in the caller's admission transaction."""
        scope_id = PostgresPayloadRepository.scope_id(_OWNER_ID, _SCOPE)
        lock_clause = " FOR SHARE" if lock else ""
        row = connection.execute(
            "SELECT registry_version,revision,payload FROM endpoint_registry_snapshots "
            "WHERE scope_id=%s AND record_id=%s AND owner_id=%s "
            "AND application_id=%s AND workspace_id IS NULL" + lock_clause,
            (scope_id, _RECORD_ID, _OWNER_ID, _SCOPE.application_id),
        ).fetchone()
        if row is None:
            return None
        registry_version, revision, payload = row
        snapshot = _decode_snapshot(payload)
        if snapshot.registry_version != registry_version or snapshot.revision != int(revision):
            raise RuntimeError("endpoint_registry_record_invalid")
        return snapshot

    def load_profile_version_history(self) -> dict[str, int]:
        scope_id = PostgresPayloadRepository.scope_id(_OWNER_ID, _SCOPE)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT endpoint_profile_id,last_profile_version "
                "FROM endpoint_profile_version_history WHERE scope_id=%s",
                (scope_id,),
            ).fetchall()
        return {profile_id: int(version) for profile_id, version in rows}

    def save(
        self,
        profiles: Sequence[EndpointProfile],
        *,
        expected_registry_version: str | None,
    ) -> EndpointRegistrySnapshot:
        profile_tuple = EndpointRegistry(profiles).profiles
        # Reuse the runtime invariants so direct repository writes cannot make
        # an over-limit or cross-account quota snapshot authoritative.
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            scope_id = _ensure_registry_namespace(connection)
            row = connection.execute(
                "SELECT registry_version,revision,payload FROM endpoint_registry_snapshots "
                "WHERE scope_id=%s AND record_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NULL FOR UPDATE",
                (scope_id, _RECORD_ID, _OWNER_ID, _SCOPE.application_id),
            ).fetchone()
            previous = _decode_snapshot(row[2]) if row is not None else None
            history = _load_profile_version_history(connection, scope_id)
            if expected_registry_version is None:
                if row is not None:
                    raise RegistryConflictError("endpoint registry already initialized")
                _validate_profile_version_changes(profile_tuple, (), history)
                snapshot = EndpointRegistrySnapshot(
                    revision=1,
                    registry_version=compute_registry_version(profile_tuple, revision=1),
                    profiles=profile_tuple,
                )
                _ensure_payload_fits(snapshot)
                payload = PostgresPayloadRepository._json(
                    snapshot.model_dump(mode="json")
                )
                inserted = connection.execute(
                    "INSERT INTO endpoint_registry_snapshots(record_id,scope_id,owner_id,"
                    "application_id,workspace_id,record_version,revision,registry_version,"
                    "created_at,updated_at,payload) VALUES "
                    "(%s,%s,%s,%s,NULL,1,%s,%s,%s,%s,%s::jsonb) "
                    "ON CONFLICT (scope_id,record_id) DO NOTHING "
                    "RETURNING registry_version,revision",
                    (
                        _RECORD_ID, scope_id, _OWNER_ID, _SCOPE.application_id,
                        snapshot.revision, snapshot.registry_version, now, now, payload,
                    ),
                )
                if inserted.fetchone() is None:
                    raise RegistryConflictError("endpoint registry initialization raced")
                _write_profile_version_history(
                    connection, scope_id, profile_tuple, history
                )
                return snapshot

            if row is None or row[0] != expected_registry_version:
                raise RegistryConflictError("endpoint registry revision changed")
            if previous is None:
                raise RuntimeError("endpoint_registry_record_invalid")
            _validate_profile_version_changes(profile_tuple, previous.profiles, history)
            revision = int(row[1]) + 1
            snapshot = EndpointRegistrySnapshot(
                revision=revision,
                registry_version=compute_registry_version(profile_tuple, revision=revision),
                profiles=profile_tuple,
            )
            _ensure_payload_fits(snapshot)
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
                raise RegistryConflictError("endpoint registry revision changed")
            _write_profile_version_history(
                connection, scope_id, previous.profiles, history
            )
            _write_profile_version_history(
                connection, scope_id, profile_tuple, history
            )
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
        raise RegistryConflictError("endpoint registry scope namespace collision")
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


def _load_profile_version_history(connection: Any, scope_id: str) -> dict[str, int]:
    rows = connection.execute(
        "SELECT endpoint_profile_id,last_profile_version "
        "FROM endpoint_profile_version_history WHERE scope_id=%s "
        "ORDER BY endpoint_profile_id FOR UPDATE",
        (scope_id,),
    ).fetchall()
    return {profile_id: int(version) for profile_id, version in rows}


def _validate_profile_version_changes(
    profiles: Sequence[EndpointProfile],
    previous_profiles: Sequence[EndpointProfile],
    history: dict[str, int],
) -> None:
    previous = {profile.endpoint_profile_id: profile for profile in previous_profiles}
    for profile in profiles:
        old = previous.get(profile.endpoint_profile_id)
        if old is not None:
            last_version = history.get(profile.endpoint_profile_id, old.profile_version)
            if last_version != old.profile_version:
                raise RegistryConflictError("endpoint_profile_version_history_mismatch")
            if profile.profile_version < old.profile_version:
                raise RegistryConflictError("endpoint_profile_version_must_increase")
            if profile.profile_version == old.profile_version and profile != old:
                raise RegistryConflictError("endpoint_profile_version_must_increase")
            continue
        if profile.profile_version <= history.get(profile.endpoint_profile_id, 0):
            raise RegistryConflictError(
                "endpoint_profile_version_must_increase_after_removal"
            )


def _write_profile_version_history(
    connection: Any,
    scope_id: str,
    profiles: Sequence[EndpointProfile],
    existing: dict[str, int],
) -> None:
    for profile in profiles:
        prior = existing.get(profile.endpoint_profile_id, 0)
        version = max(prior, profile.profile_version)
        connection.execute(
            "INSERT INTO endpoint_profile_version_history "
            "(scope_id,endpoint_profile_id,last_profile_version,updated_at) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT (scope_id,endpoint_profile_id) "
            "DO UPDATE SET last_profile_version=GREATEST("
            "endpoint_profile_version_history.last_profile_version,EXCLUDED.last_profile_version), "
            "updated_at=EXCLUDED.updated_at",
            (scope_id, profile.endpoint_profile_id, version, datetime.now(UTC)),
        )
        existing[profile.endpoint_profile_id] = version


def _ensure_payload_fits(snapshot: EndpointRegistrySnapshot) -> None:
    # The application uses a 128 KiB compact JSON limit, leaving substantial
    # room for PostgreSQL jsonb's structural overhead under migration 016's
    # 256 KiB stored-payload constraint.
    if len(snapshot.model_dump_json().encode("utf-8")) > MAX_ENDPOINT_REGISTRY_JSON_BYTES:
        raise RegistryPayloadTooLargeError("endpoint_registry_payload_too_large")
