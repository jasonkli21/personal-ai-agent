"""Owner-scoped idempotency and fenced result storage for booking extraction."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from threading import RLock
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ConfigDict, Field

from personal_ai.auth.scope import (
    STANDALONE_APPLICATION_ID,
    ApplicationScopedRecord,
    current_application_scope,
    scope_matches,
    scoped_record,
)
from personal_ai.booking_extractions.contracts import BookingExtractionResult
from personal_ai.storage.errors import ResourceNotFoundError

RESULT_RETENTION = timedelta(days=7)


class ExtractionError(RuntimeError):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code, self.status = code, status
        super().__init__(code)


def extraction_id_for(owner_id: str, key: UUID) -> UUID:
    scope = current_application_scope()
    namespace = (
        "" if scope.application_id == STANDALONE_APPLICATION_ID and scope.workspace_id is None
        else f":{scope.application_id}:{scope.workspace_id or ''}"
    )
    return uuid5(NAMESPACE_URL, f"booking-document-extraction-v1:{owner_id}{namespace}:{key}")


class ExtractionRecord(ApplicationScopedRecord):
    model_config = ConfigDict(extra="forbid", frozen=True)
    extraction_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    idempotency_key: UUID
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: str
    created_at: datetime
    execution_deadline: datetime
    expires_at: datetime
    retained_until: datetime
    result: BookingExtractionResult | None = None


class BookingExtractionRepository(Protocol):
    def begin(
        self,
        *,
        owner_id: str,
        key: UUID,
        fingerprint: str,
        source_sha256: str,
        now: datetime,
        execution_deadline: datetime,
        timeout_seconds: float = 5,
        deadline: float | None = None,
    ) -> tuple[ExtractionRecord, bool]: ...
    def complete(
        self, record: ExtractionRecord, result: BookingExtractionResult,
        timeout_seconds: float = 5, deadline: float | None = None,
    ) -> ExtractionRecord: ...
    def get(self, owner_id: str, extraction_id: UUID) -> ExtractionRecord: ...
    def get_by_key(self, owner_id: str, key: UUID) -> ExtractionRecord: ...
    def delete(self, owner_id: str, extraction_id: UUID) -> ExtractionRecord: ...
    def delete_by_key(
        self, owner_id: str, key: UUID, source_sha256: str, now: datetime
    ) -> ExtractionRecord: ...
    def purge_expired(self, now: datetime, *, limit: int) -> int: ...


def _new(
    owner_id: str,
    key: UUID,
    fingerprint: str,
    source_sha256: str,
    now: datetime,
    deadline: datetime,
) -> ExtractionRecord:
    return scoped_record(ExtractionRecord(
        extraction_id=extraction_id_for(owner_id, key),
        owner_id=owner_id,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        source_sha256=source_sha256,
        state="running",
        created_at=now,
        execution_deadline=deadline,
        expires_at=now + RESULT_RETENTION,
        retained_until=now + RESULT_RETENTION,
    ))


def _check(old: ExtractionRecord, owner_id: str, fingerprint: str, source_sha256: str) -> None:
    if old.owner_id != owner_id or not scope_matches(old):
        raise ResourceNotFoundError("extraction not found")
    if old.state == "deleted":
        if old.source_sha256 != source_sha256:
            raise ExtractionError("idempotency_conflict")
        return
    if old.request_fingerprint != fingerprint:
        raise ExtractionError("idempotency_conflict")


def _deleted(record: ExtractionRecord) -> ExtractionRecord:
    result = BookingExtractionResult(
        extraction_id=record.extraction_id,
        idempotency_key=record.idempotency_key,
        source_sha256=record.source_sha256,
        state="deleted",
        candidates=(),
        created_at=record.created_at,
        expires_at=record.expires_at,
    )
    return record.model_copy(update={"state": "deleted", "result": result})


class InMemoryBookingExtractionRepository:
    def __init__(self) -> None:
        self._records: dict[UUID, ExtractionRecord] = {}
        self._lock = RLock()

    def begin(
        self, *, owner_id, key, fingerprint, source_sha256, now, execution_deadline,
        timeout_seconds=5, deadline=None,
    ):
        extraction_id = extraction_id_for(owner_id, key)
        with self._lock:
            old = self._records.get(extraction_id)
            if old is not None:
                _check(old, owner_id, fingerprint, source_sha256)
                return old, False
            record = _new(owner_id, key, fingerprint, source_sha256, now, execution_deadline)
            self._records[extraction_id] = record
            return record, True

    def complete(self, record, result, timeout_seconds=5, deadline=None):
        with self._lock:
            old = self._records.get(record.extraction_id)
            if old is None or old.owner_id != record.owner_id or not scope_matches(old):
                raise ResourceNotFoundError("extraction not found")
            if old.state != "running" or old.request_fingerprint != record.request_fingerprint:
                raise ExtractionError("extraction_conflict")
            updated = old.model_copy(update={"state": result.state, "result": result})
            self._records[old.extraction_id] = updated
            return updated

    def get(self, owner_id, extraction_id):
        with self._lock:
            record = self._records.get(extraction_id)
            if record is None or record.owner_id != owner_id or not scope_matches(record):
                raise ResourceNotFoundError("extraction not found")
            return record

    def get_by_key(self, owner_id, key):
        return self.get(owner_id, extraction_id_for(owner_id, key))

    def delete(self, owner_id, extraction_id):
        with self._lock:
            record = self._records.get(extraction_id)
            if record is None or record.owner_id != owner_id or not scope_matches(record):
                raise ResourceNotFoundError("extraction not found")
            updated = _deleted(record)
            self._records[record.extraction_id] = updated
            return updated

    def delete_by_key(self, owner_id, key, source_sha256, now):
        extraction_id = extraction_id_for(owner_id, key)
        with self._lock:
            record = self._records.get(extraction_id)
            if record is None:
                fingerprint = sha256(f"deleted:{key}:{source_sha256}".encode()).hexdigest()
                record = _new(owner_id, key, fingerprint, source_sha256, now, now)
            elif (record.owner_id != owner_id or record.source_sha256 != source_sha256
                  or not scope_matches(record)):
                raise ExtractionError("idempotency_conflict")
            updated = _deleted(record)
            self._records[extraction_id] = updated
            return updated

    def purge_expired(self, now, *, limit):
        removed = 0
        with self._lock:
            for extraction_id, record in list(self._records.items()):
                if removed >= limit:
                    break
                if (not scope_matches(record) or record.state != "completed"
                        or record.expires_at > now or record.result is None):
                    continue
                expired_result = record.result.model_copy(
                    update={"state": "expired", "candidates": ()}
                )
                self._records[extraction_id] = record.model_copy(
                    update={"state": "expired", "result": expired_result}
                )
                removed += 1
        return removed
