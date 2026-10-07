"""Postgres adapters for bounded proposal and booking-result aggregates."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from uuid import UUID

from personal_ai.auth.scope import (
    ApplicationScope,
    current_application_scope,
    scope_matches,
)
from personal_ai.booking_extractions.contracts import BookingExtractionResult
from personal_ai.booking_extractions.repositories import (
    ExtractionError,
    ExtractionRecord,
    extraction_id_for,
)
from personal_ai.booking_extractions.repositories import (
    _check as _check_extraction,
)
from personal_ai.booking_extractions.repositories import (
    _deleted as _deleted_extraction,
)
from personal_ai.booking_extractions.repositories import (
    _new as _new_extraction,
)
from personal_ai.itinerary_proposals.contracts import (
    ItineraryProposalRequest,
    ItineraryProposalResult,
    ProposalError,
)
from personal_ai.itinerary_proposals.repositories import (
    ProposalRecord,
    _check_replay,
    _new_record,
)
from personal_ai.persistence.postgres import (
    PostgresDatabase,
    PostgresPayloadRepository,
    _ensure_namespace,
)
from personal_ai.storage.errors import ResourceNotFoundError


def _scope(record) -> ApplicationScope:
    return ApplicationScope(application_id=record.application_id, workspace_id=record.workspace_id)


def _json(record):
    return PostgresPayloadRepository._json(record.model_dump(mode="json"))


def _select(connection, family, owner_id, scope, record_id, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    row = connection.execute(
        f"SELECT payload,revision FROM {family} WHERE scope_id=%s AND record_id=%s "
        "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s" + suffix,
        (
            PostgresPayloadRepository.scope_id(owner_id, scope), str(record_id), owner_id,
            scope.application_id, scope.workspace_id,
        ),
    ).fetchone()
    return None if row is None else (row[0], int(row[1]))


def _insert(connection, family, record, *, record_id, idempotency_key=None):
    scope, owner_id = _scope(record), record.owner_id
    scope_id = _ensure_namespace(connection, owner_id, scope)
    connection.execute(
        f"INSERT INTO {family}(record_id,scope_id,owner_id,application_id,workspace_id,"
        "record_version,status,revision,created_at,expires_at,idempotency_key,payload) "
        "VALUES (%s,%s,%s,%s,%s,1,%s,1,%s,%s,%s,%s::jsonb)",
        (
            str(record_id), scope_id, owner_id, scope.application_id, scope.workspace_id,
            record.state, record.created_at, getattr(record, "retained_until", getattr(record, "expires_at", None)),
            idempotency_key, _json(record),
        ),
    )


class PostgresItineraryProposalRepository:
    """Conditional proposal begin/complete operations with the 48h replay window."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def begin(
        self, *, owner_id: str, request: ItineraryProposalRequest,
        request_fingerprint: str, now: datetime, execution_deadline: datetime,
        timeout_seconds: float = 5, deadline: float | None = None,
    ) -> tuple[ProposalRecord, bool]:
        record = _new_record(owner_id, request, request_fingerprint, now, execution_deadline)
        scope = _scope(record)
        with self.database.transaction(timeout_seconds=timeout_seconds, deadline=deadline) as connection:
            _ensure_namespace(connection, owner_id, scope)
            current = _select(
                connection, "itinerary_proposals", owner_id, scope, record.proposal_id, lock=True
            )
            if current is not None:
                old = ProposalRecord.model_validate(current[0])
                _check_replay(old, owner_id, request_fingerprint, now)
                if old.retained_until > now:
                    return old, False
                connection.execute(
                    "UPDATE itinerary_proposals SET payload=%s::jsonb,status=%s,revision=revision+1,"
                    "created_at=%s,expires_at=%s,updated_at=now() WHERE scope_id=%s AND record_id=%s AND revision=%s",
                    (
                        _json(record), record.state, record.created_at, record.retained_until,
                        PostgresPayloadRepository.scope_id(owner_id, scope), str(record.proposal_id), current[1],
                    ),
                )
                return record, True
            _insert(
                connection, "itinerary_proposals", record, record_id=record.proposal_id,
                idempotency_key=str(request.idempotency_key),
            )
        return record, True

    def complete(
        self, record: ProposalRecord, result: ItineraryProposalResult,
        timeout_seconds: float = 5, deadline: float | None = None,
    ) -> ProposalRecord:
        scope = _scope(record)
        with self.database.transaction(timeout_seconds=timeout_seconds, deadline=deadline) as connection:
            current = _select(
                connection, "itinerary_proposals", record.owner_id, scope, record.proposal_id, lock=True
            )
            if current is None:
                raise ResourceNotFoundError("proposal not found")
            old = ProposalRecord.model_validate(current[0])
            if (
                old.state != "running" or old.request_fingerprint != record.request_fingerprint
                or old.created_at != record.created_at or result.proposal_id != old.proposal_id
                or result.created_at != old.created_at or result.state == "running"
            ):
                raise ProposalError("proposal_conflict", 409)
            updated = old.model_copy(update={"state": result.state, "result": result})
            cursor = connection.execute(
                "UPDATE itinerary_proposals SET payload=%s::jsonb,status=%s,revision=revision+1 "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s AND status='running'",
                (
                    _json(updated), updated.state, PostgresPayloadRepository.scope_id(record.owner_id, scope),
                    str(record.proposal_id), current[1],
                ),
            )
            if cursor.rowcount != 1:
                raise ProposalError("proposal_conflict", 409)
        return updated

    def get(self, owner_id: str, proposal_id: UUID) -> ProposalRecord:
        scope = current_application_scope()
        with self.database.connection() as connection:
            current = _select(connection, "itinerary_proposals", owner_id, scope, proposal_id)
        if current is None:
            raise ResourceNotFoundError("proposal not found")
        record = ProposalRecord.model_validate(current[0])
        if record.owner_id != owner_id or not scope_matches(record, scope):
            raise ResourceNotFoundError("proposal not found")
        return record


class PostgresBookingExtractionRepository:
    """Replay-safe extraction result and deletion tombstone storage."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def begin(
        self, *, owner_id, key, fingerprint, source_sha256, now, execution_deadline,
        timeout_seconds=5, deadline=None,
    ):
        record = _new_extraction(owner_id, key, fingerprint, source_sha256, now, execution_deadline)
        scope = _scope(record)
        try:
            with self.database.transaction(timeout_seconds=timeout_seconds, deadline=deadline) as connection:
                _ensure_namespace(connection, owner_id, scope)
                current = _select(
                    connection, "booking_document_extractions", owner_id, scope,
                    record.extraction_id, lock=True,
                )
                if current is not None:
                    old = ExtractionRecord.model_validate(current[0])
                    _check_extraction(old, owner_id, fingerprint, source_sha256)
                    return old, False
                _insert(
                    connection, "booking_document_extractions", record,
                    record_id=record.extraction_id, idempotency_key=str(key),
                )
        except Exception as error:
            if error.__class__.__name__ != "UniqueViolation":
                raise
            replay = self.get_by_key(owner_id, key, timeout_seconds=timeout_seconds, deadline=deadline)
            try:
                _check_extraction(replay, owner_id, fingerprint, source_sha256)
            except ExtractionError as conflict:
                raise conflict from error
            return replay, False
        return record, True

    def complete(
        self, record: ExtractionRecord, result: BookingExtractionResult,
        timeout_seconds=5, deadline=None,
    ):
        scope = _scope(record)
        with self.database.transaction(timeout_seconds=timeout_seconds, deadline=deadline) as connection:
            current = _select(
                connection, "booking_document_extractions", record.owner_id, scope,
                record.extraction_id, lock=True,
            )
            if current is None:
                raise ResourceNotFoundError("extraction not found")
            old = ExtractionRecord.model_validate(current[0])
            if old.state != "running" or old.request_fingerprint != record.request_fingerprint:
                raise ExtractionError("extraction_conflict")
            updated = old.model_copy(update={"state": result.state, "result": result})
            cursor = connection.execute(
                "UPDATE booking_document_extractions SET payload=%s::jsonb,status=%s,revision=revision+1 "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s AND status='running'",
                (
                    _json(updated), updated.state,
                    PostgresPayloadRepository.scope_id(record.owner_id, scope),
                    str(record.extraction_id), current[1],
                ),
            )
            if cursor.rowcount != 1:
                raise ExtractionError("extraction_conflict")
        return updated

    def get(self, owner_id, extraction_id, *, timeout_seconds=None, deadline=None):
        scope = current_application_scope()
        with self.database.connection(timeout_seconds=timeout_seconds, deadline=deadline) as connection:
            current = _select(
                connection, "booking_document_extractions", owner_id, scope, extraction_id
            )
        if current is None:
            raise ResourceNotFoundError("extraction not found")
        record = ExtractionRecord.model_validate(current[0])
        if record.owner_id != owner_id or not scope_matches(record, scope):
            raise ResourceNotFoundError("extraction not found")
        return record

    def get_by_key(self, owner_id, key, timeout_seconds=None, deadline=None):
        return self.get(
            owner_id, extraction_id_for(owner_id, key),
            timeout_seconds=timeout_seconds, deadline=deadline,
        )

    def delete(self, owner_id, extraction_id):
        record = self.get(owner_id, extraction_id)
        scope = _scope(record)
        updated = _deleted_extraction(record)
        with self.database.transaction() as connection:
            current = _select(
                connection, "booking_document_extractions", owner_id, scope, extraction_id, lock=True
            )
            if current is None:
                raise ResourceNotFoundError("extraction not found")
            connection.execute(
                "UPDATE booking_document_extractions SET payload=%s::jsonb,status='deleted',revision=revision+1 "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                (_json(updated), PostgresPayloadRepository.scope_id(owner_id, scope), str(extraction_id), current[1]),
            )
        return updated

    def delete_by_key(self, owner_id, key, source_sha256, now):
        try:
            record = self.get_by_key(owner_id, key)
        except ResourceNotFoundError:
            fingerprint = sha256(f"deleted:{key}:{source_sha256}".encode()).hexdigest()
            record = _new_extraction(owner_id, key, fingerprint, source_sha256, now, now)
            record = _deleted_extraction(record)
            try:
                with self.database.transaction() as connection:
                    _insert(
                        connection, "booking_document_extractions", record,
                        record_id=record.extraction_id, idempotency_key=str(key),
                    )
            except Exception as error:
                if error.__class__.__name__ != "UniqueViolation":
                    raise
                return self.delete_by_key(owner_id, key, source_sha256, now)
            return record
        if record.source_sha256 != source_sha256:
            raise ExtractionError("idempotency_conflict")
        return self.delete(owner_id, record.extraction_id)

    def purge_expired(self, now, *, limit):
        if not 1 <= limit <= 500:
            raise ValueError("cleanup limit must be between one and 500")
        scope = current_application_scope()
        with self.database.connection() as connection:
            candidates = connection.execute(
                "SELECT owner_id,record_id,payload,revision FROM booking_document_extractions "
                "WHERE application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND status='completed' AND expires_at<=%s "
                "ORDER BY expires_at,record_id LIMIT %s",
                (scope.application_id, scope.workspace_id, now, limit),
            ).fetchall()
        count = 0
        for owner_id, record_id, value, revision in candidates:
            record = ExtractionRecord.model_validate(value)
            if record.expires_at > now or record.result is None:
                continue
            expired = record.result.model_copy(update={"state": "expired", "candidates": ()})
            updated = record.model_copy(update={"state": "expired", "result": expired})
            with self.database.transaction() as connection:
                row = connection.execute(
                    "SELECT payload,revision FROM booking_document_extractions WHERE scope_id=%s "
                    "AND record_id=%s AND owner_id=%s AND application_id=%s "
                    "AND workspace_id IS NOT DISTINCT FROM %s FOR UPDATE",
                    (
                        PostgresPayloadRepository.scope_id(owner_id, scope), record_id, owner_id,
                        scope.application_id, scope.workspace_id,
                    ),
                ).fetchone()
                if row is None:
                    continue
                old = ExtractionRecord.model_validate(row[0])
                if old.state != "completed" or old.expires_at > now or old.result is None:
                    continue
                connection.execute(
                    "UPDATE booking_document_extractions SET payload=%s::jsonb,status='expired',revision=revision+1 "
                    "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                    (
                        _json(updated), PostgresPayloadRepository.scope_id(owner_id, scope),
                        record_id, row[1],
                    ),
                )
                count += 1
        return count
