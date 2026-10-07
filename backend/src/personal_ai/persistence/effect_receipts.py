"""Narrow Postgres arbitration for cross-store memory effects.

The same unique receipt row arbitrates effect application and abort recovery.
An `applied` receipt is inserted before the effect writes in the transaction but
is not visible until those writes commit. Recovery's `aborted` insert races on
the same unique key, so it either observes the committed effect or wins after an
apply rollback. There is no externally visible `applying` lease to expire.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres import (
    PersistenceConflict,
    PostgresDatabase,
    _ensure_namespace,
)


@dataclass(frozen=True)
class EffectReceipt:
    operation_id: str
    attempt_id: str
    fingerprint: str
    outcome: str
    result_refs: dict[str, Any]
    execution_deadline: datetime
    created_at: datetime


class PostgresEffectReceiptRepository:
    """Arbitrate one scoped attempt and its knowledge writes atomically."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def apply(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        operation_id: str,
        attempt_id: str,
        fingerprint: str,
        execution_deadline: datetime,
        effect: Callable[[Any], dict[str, Any]],
    ) -> tuple[EffectReceipt, bool]:
        deadline = _utc(execution_deadline)
        now = datetime.now(UTC)
        scope_id = PostgresDatabaseScope.scope_id(owner_id, scope)
        with self.database.transaction() as connection:
            _ensure_namespace(connection, owner_id, scope)
            inserted = connection.execute(
                "INSERT INTO memory_lifecycle_operations "
                "(scope_id,owner_id,application_id,workspace_id,operation_id,attempt_id,"
                "fingerprint,outcome,result_refs,execution_deadline) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'applied','{}'::jsonb,%s) "
                "ON CONFLICT (scope_id,operation_id,attempt_id) DO NOTHING RETURNING operation_id",
                (
                    scope_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                    operation_id,
                    attempt_id,
                    fingerprint,
                    deadline,
                ),
            ).fetchone()
            if inserted is None:
                receipt = self._read_locked(
                    connection, scope_id, operation_id, attempt_id
                )
                self._validate_identity(receipt, fingerprint)
                if receipt.outcome == "aborted":
                    raise PersistenceConflict("memory effect attempt was aborted")
                return receipt, False
            if now >= deadline or datetime.now(UTC) >= deadline:
                raise PersistenceConflict("memory effect deadline expired")
            result_refs = effect(connection)
            if not isinstance(result_refs, dict):
                raise TypeError("effect result references must be an object")
            connection.execute(
                "UPDATE memory_lifecycle_operations SET result_refs=%s::jsonb "
                "WHERE scope_id=%s AND operation_id=%s AND attempt_id=%s",
                (
                    PostgresPayloadRepositoryJson.dumps(result_refs),
                    scope_id,
                    operation_id,
                    attempt_id,
                ),
            )
            receipt = self._read_locked(connection, scope_id, operation_id, attempt_id)
            return receipt, True

    def abort_if_unresolved(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        operation_id: str,
        attempt_id: str,
        fingerprint: str,
        execution_deadline: datetime,
    ) -> EffectReceipt:
        """Serialize abort against any old apply; absence alone never authorizes release."""
        scope_id = PostgresDatabaseScope.scope_id(owner_id, scope)
        with self.database.transaction() as connection:
            _ensure_namespace(connection, owner_id, scope)
            connection.execute(
                "INSERT INTO memory_lifecycle_operations "
                "(scope_id,owner_id,application_id,workspace_id,operation_id,attempt_id,"
                "fingerprint,outcome,result_refs,execution_deadline) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'aborted','{}'::jsonb,%s) "
                "ON CONFLICT (scope_id,operation_id,attempt_id) DO NOTHING",
                (
                    scope_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                    operation_id,
                    attempt_id,
                    fingerprint,
                    _utc(execution_deadline),
                ),
            )
            receipt = self._read_locked(connection, scope_id, operation_id, attempt_id)
            self._validate_identity(receipt, fingerprint)
            return receipt

    def get(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        operation_id: str,
        attempt_id: str,
    ) -> EffectReceipt | None:
        scope_id = PostgresDatabaseScope.scope_id(owner_id, scope)
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT operation_id,attempt_id,fingerprint,outcome,result_refs,"
                "execution_deadline,created_at FROM memory_lifecycle_operations "
                "WHERE scope_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND operation_id=%s AND attempt_id=%s",
                (
                    scope_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                    operation_id,
                    attempt_id,
                ),
            ).fetchone()
        return None if row is None else _receipt(row)

    @staticmethod
    def _read_locked(connection, scope_id, operation_id, attempt_id) -> EffectReceipt:
        row = connection.execute(
            "SELECT operation_id,attempt_id,fingerprint,outcome,result_refs,"
            "execution_deadline,created_at FROM memory_lifecycle_operations "
            "WHERE scope_id=%s AND operation_id=%s AND attempt_id=%s FOR UPDATE",
            (scope_id, operation_id, attempt_id),
        ).fetchone()
        if row is None:  # unique arbitration guarantees a row or transaction failure
            raise PersistenceConflict("effect receipt unavailable")
        return _receipt(row)

    @staticmethod
    def _validate_identity(receipt: EffectReceipt, fingerprint: str) -> None:
        if receipt.fingerprint != fingerprint:
            raise PersistenceConflict("effect identity fingerprint conflict")


class PostgresDatabaseScope:
    @staticmethod
    def scope_id(owner_id: str, scope: ApplicationScope) -> str:
        from personal_ai.persistence.postgres import PostgresPayloadRepository

        return PostgresPayloadRepository.scope_id(owner_id, scope)


class PostgresPayloadRepositoryJson:
    @staticmethod
    def dumps(value: dict[str, Any]) -> str:
        import json

        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > 16_384:
            raise ValueError("effect_result_too_large")
        return serialized


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp_invalid")
    return value.astimezone(UTC)


def _receipt(row) -> EffectReceipt:
    return EffectReceipt(
        operation_id=row[0],
        attempt_id=row[1],
        fingerprint=row[2].strip(),
        outcome=row[3],
        result_refs=row[4],
        execution_deadline=row[5],
        created_at=row[6],
    )
