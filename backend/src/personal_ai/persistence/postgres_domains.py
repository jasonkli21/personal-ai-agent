"""Postgres ownership for domain registrations, result snapshots and lookup fences."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.auth.scope import (
    ApplicationScope,
    current_application_scope,
    scope_matches,
    scoped_record,
)
from personal_ai.domains.contracts import (
    DomainClaimExtension,
    DomainComparisonResult,
    DomainLookupReservation,
    DomainRegistration,
)
from personal_ai.domains.repositories import DomainRepositoryError, _updated_reservation
from personal_ai.persistence.postgres import (
    PostgresDatabase,
    PostgresPayloadRepository,
    _ensure_namespace,
)
from personal_ai.storage.errors import ResourceNotFoundError


def _scope(record):
    return ApplicationScope(application_id=record.application_id, workspace_id=record.workspace_id)


def _dump(record):
    return PostgresPayloadRepository._json(record.model_dump(mode="json"))


def _registration_key(record: DomainRegistration):
    return (
        record.domain_id, record.field_schema_version,
        record.feature_policy_version, record.source_policy_version,
    )


def _claim_record_id(record: DomainClaimExtension):
    return str(uuid5(NAMESPACE_URL, f"domain-claim-v1:{record.domain_id}:{record.claim_id}"))


def _register(connection, owner_id, scope):
    return _ensure_namespace(connection, owner_id, scope)


def _put_child(connection, table, record, *, owner_id, record_id):
    scope = _scope(record)
    scope_id = _register(connection, owner_id, scope)
    value = record.model_dump(mode="json")
    current = connection.execute(
        f"SELECT payload FROM {table} WHERE scope_id=%s AND record_id=%s FOR UPDATE",
        (scope_id, record_id),
    ).fetchone()
    if current is not None:
        old_value = current[0]
        if table == "domain_claim_extensions":
            old_value.pop("owner_id", None)
        if old_value != value:
            raise DomainRepositoryError("domain_record_conflict")
        return
    connection.execute(
        f"INSERT INTO {table}(record_id,scope_id,owner_id,application_id,workspace_id,"
        "record_version,status,revision,created_at,expires_at,payload) "
        "VALUES (%s,%s,%s,%s,%s,1,'active',1,%s,%s,%s::jsonb)",
        (
            record_id, scope_id, owner_id, scope.application_id, scope.workspace_id,
            getattr(record, "observed_at", getattr(record, "rendered_at", datetime.now(UTC))),
            getattr(record, "expires_at", None), _dump(record),
        ),
    )


class PostgresDomainRepository:
    """Preserve the registration and result transaction groups in P."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    @staticmethod
    def _read_reservation(connection, owner_id, scope, reservation_id, *, lock=False):
        suffix = " FOR UPDATE" if lock else ""
        row = connection.execute(
            "SELECT payload,revision FROM domain_lookup_idempotency WHERE scope_id=%s "
            "AND record_id=%s AND owner_id=%s AND application_id=%s "
            "AND workspace_id IS NOT DISTINCT FROM %s" + suffix,
            (
                PostgresPayloadRepository.scope_id(owner_id, scope), str(reservation_id),
                owner_id, scope.application_id, scope.workspace_id,
            ),
        ).fetchone()
        return None if row is None else (DomainLookupReservation.model_validate(row[0]), row[1])

    def create(self, result: DomainComparisonResult):
        return self._persist(scoped_record(result))

    def get(self, owner_id: str, comparison_id: UUID):
        scope = current_application_scope()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM domain_comparison_views WHERE scope_id=%s AND record_id=%s "
                "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
                (
                    PostgresPayloadRepository.scope_id(owner_id, scope), str(comparison_id),
                    owner_id, scope.application_id, scope.workspace_id,
                ),
            ).fetchone()
        if row is None:
            raise ResourceNotFoundError("domain comparison not found")
        result = DomainComparisonResult.model_validate(row[0])
        if result.comparison.owner_id != owner_id or not scope_matches(result, scope):
            raise ResourceNotFoundError("domain comparison not found")
        return result

    def reserve_lookup(self, reservation: DomainLookupReservation):
        reservation = scoped_record(reservation)
        scope = _scope(reservation)
        scope_id = PostgresPayloadRepository.scope_id(reservation.owner_id, scope)
        try:
            with self.database.transaction() as connection:
                _register(connection, reservation.owner_id, scope)
                current = self._read_reservation(
                    connection, reservation.owner_id, scope, reservation.id, lock=True
                )
                if current is not None:
                    old = current[0]
                    if (
                        old.owner_id != reservation.owner_id
                        or old.domain_id != reservation.domain_id
                        or old.idempotency_key != reservation.idempotency_key
                        or not scope_matches(old, scope)
                    ):
                        raise DomainRepositoryError("domain_lookup_reservation_conflict")
                    return old
                connection.execute(
                    "INSERT INTO domain_lookup_idempotency(record_id,scope_id,owner_id,application_id,"
                    "workspace_id,record_version,status,revision,created_at,updated_at,idempotency_key,payload) "
                    "VALUES (%s,%s,%s,%s,%s,1,%s,1,%s,%s,%s,%s::jsonb)",
                    (
                        str(reservation.id), scope_id, reservation.owner_id, scope.application_id,
                        scope.workspace_id, reservation.state, reservation.created_at,
                        reservation.updated_at, str(reservation.idempotency_key), _dump(reservation),
                    ),
                )
        except Exception as error:
            if error.__class__.__name__ != "UniqueViolation":
                raise
            with self.database.connection() as connection:
                current = self._read_reservation(
                    connection, reservation.owner_id, scope, reservation.id
                )
            if current is None:
                raise DomainRepositoryError("domain_lookup_reservation_conflict") from error
            old = current[0]
            if (
                old.owner_id != reservation.owner_id or old.domain_id != reservation.domain_id
                or old.idempotency_key != reservation.idempotency_key
                or not scope_matches(old, scope)
            ):
                raise DomainRepositoryError("domain_lookup_reservation_conflict") from error
            return old
        return reservation

    def fail_lookup(
        self, reservation_id, fence_token, *, state, failure_kind=None,
        failure_code=None, failure_status=None,
    ):
        scope = current_application_scope()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload,revision,scope_id FROM domain_lookup_idempotency "
                "WHERE record_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s FOR UPDATE",
                (str(reservation_id), scope.application_id, scope.workspace_id),
            ).fetchone()
            if row is None:
                raise DomainRepositoryError("domain_lookup_reservation_missing")
            current = DomainLookupReservation.model_validate(row[0])
            revision = row[1]
            if not scope_matches(current, scope):
                raise DomainRepositoryError("domain_lookup_reservation_missing")
            if current.fence_token != fence_token:
                raise DomainRepositoryError("domain_lookup_fence_lost")
            if current.state != "reserved":
                return current
            failed = _updated_reservation(
                current, state=state, failure_kind=failure_kind,
                failure_code=failure_code, failure_status=failure_status,
                updated_at=max(current.updated_at, datetime.now(UTC)),
            )
            connection.execute(
                "UPDATE domain_lookup_idempotency SET payload=%s::jsonb,status=%s,updated_at=%s,revision=revision+1 "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                (
                    _dump(failed), failed.state, failed.updated_at,
                    row[2],
                    str(reservation_id), revision,
                ),
            )
        return failed

    def complete_lookup(self, reservation_id, fence_token, result: DomainComparisonResult):
        return self._persist(
            scoped_record(result), reservation_id=reservation_id, fence_token=fence_token
        )

    def _persist(self, result, *, reservation_id=None, fence_token=None):
        snapshot, scope = result.comparison, _scope(result.comparison)
        owner_id = snapshot.owner_id
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        with self.database.transaction() as connection:
            _register(connection, owner_id, scope)
            current_reservation = None
            reservation_revision = None
            if reservation_id is not None:
                found = self._read_reservation(
                    connection, owner_id, scope, reservation_id, lock=True
                )
                if found is None:
                    raise DomainRepositoryError("domain_lookup_reservation_missing")
                current_reservation, reservation_revision = found
                if current_reservation.domain_id != snapshot.domain_id:
                    raise DomainRepositoryError("domain_lookup_result_conflict")
                if current_reservation.state == "completed":
                    if current_reservation.comparison_id != snapshot.id:
                        raise DomainRepositoryError("domain_lookup_result_conflict")
                    row = connection.execute(
                        "SELECT payload FROM domain_comparison_views WHERE scope_id=%s AND record_id=%s",
                        (scope_id, str(snapshot.id)),
                    ).fetchone()
                    if row is None:
                        raise DomainRepositoryError("domain_lookup_result_missing")
                    return DomainComparisonResult.model_validate(row[0])
                if current_reservation.state != "reserved" or current_reservation.fence_token != fence_token:
                    raise DomainRepositoryError("domain_lookup_fence_lost")

            existing = connection.execute(
                "SELECT payload FROM domain_comparison_views WHERE scope_id=%s AND record_id=%s "
                "AND owner_id=%s FOR UPDATE",
                (scope_id, str(snapshot.id), owner_id),
            ).fetchone()
            if existing is not None:
                old_result = DomainComparisonResult.model_validate(existing[0])
                if (
                    old_result.comparison.owner_id != owner_id
                    or old_result.comparison.domain_id != snapshot.domain_id
                    or old_result.comparison.decision_id != snapshot.decision_id
                ):
                    raise DomainRepositoryError("domain_comparison_conflict")
                saved = old_result
            else:
                registration = result.registration
                module_id, module_version, policy_version, source_policy = _registration_key(registration)
                row = connection.execute(
                    "SELECT payload,enabled FROM domain_registrations WHERE module_id=%s "
                    "AND module_version=%s AND policy_version=%s FOR UPDATE",
                    (module_id, module_version, f"{policy_version}:{source_policy}"),
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO domain_registrations(module_id,module_version,policy_version,enabled,payload) "
                        "VALUES (%s,%s,%s,%s,%s::jsonb)",
                        (module_id, module_version, f"{policy_version}:{source_policy}", registration.enabled, _dump(registration)),
                    )
                else:
                    old = DomainRegistration.model_validate(row[0])
                    if old.model_copy(update={"enabled": registration.enabled}) != registration:
                        raise DomainRepositoryError("domain_registration_conflict")
                for record in result.domain_claims:
                    _put_child(
                        connection, "domain_claim_extensions", record, owner_id=owner_id,
                        record_id=_claim_record_id(record),
                    )
                for record in result.provider_observations:
                    _put_child(
                        connection, "provider_observations", record, owner_id=owner_id,
                        record_id=str(record.source_observation_id),
                    )
                connection.execute(
                    "INSERT INTO domain_comparison_views(record_id,scope_id,owner_id,application_id,"
                    "workspace_id,record_version,status,revision,created_at,payload) "
                    "VALUES (%s,%s,%s,%s,%s,1,'completed',1,%s,%s::jsonb)",
                    (
                        str(snapshot.id), scope_id, owner_id, scope.application_id, scope.workspace_id,
                        snapshot.rendered_at, _dump(result),
                    ),
                )
                saved = result
            if current_reservation is not None:
                completed = _updated_reservation(
                    current_reservation, state="completed", comparison_id=saved.comparison.id,
                    updated_at=max(current_reservation.updated_at, saved.comparison.rendered_at),
                )
                connection.execute(
                    "UPDATE domain_lookup_idempotency SET payload=%s::jsonb,status='completed',updated_at=%s,"
                    "revision=revision+1 WHERE scope_id=%s AND record_id=%s AND revision=%s",
                    (_dump(completed), completed.updated_at, scope_id, str(reservation_id), reservation_revision),
                )
        return saved
