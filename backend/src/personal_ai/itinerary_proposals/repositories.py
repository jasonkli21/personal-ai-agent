"""Owner-scoped idempotency and immutable result storage for travel proposals."""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import RLock
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from google.api_core.exceptions import GoogleAPICallError, RetryError
from pydantic import BaseModel, ConfigDict, Field

from personal_ai.itinerary_proposals.contracts import (
    ItineraryProposalRequest,
    ItineraryProposalResult,
    ProposalError,
)
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError
from personal_ai.storage.firestore import _firestore_client
from personal_ai.storage.transactions import bounded_transaction

MAX_RESULT_LIFETIME = timedelta(hours=24)
IDEMPOTENCY_RETENTION = timedelta(hours=48)


def proposal_id_for(owner_id: str, idempotency_key: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"itinerary-proposal-v1:{owner_id}:{idempotency_key}")


class ProposalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: str
    trip_handle: str
    created_at: datetime
    execution_deadline: datetime
    proposal_expires_at: datetime
    retained_until: datetime
    result: ItineraryProposalResult | None = None


class ItineraryProposalRepository(Protocol):
    def begin(
        self,
        *,
        owner_id: str,
        request: ItineraryProposalRequest,
        request_fingerprint: str,
        now: datetime,
        execution_deadline: datetime,
    ) -> tuple[ProposalRecord, bool]: ...

    def complete(
        self, record: ProposalRecord, result: ItineraryProposalResult
    ) -> ProposalRecord: ...

    def get(self, owner_id: str, proposal_id: UUID) -> ProposalRecord: ...


def _new_record(owner_id, request, request_fingerprint, now, execution_deadline):
    return ProposalRecord(
        proposal_id=proposal_id_for(owner_id, request.idempotency_key),
        owner_id=owner_id,
        request_fingerprint=request_fingerprint,
        state="running",
        trip_handle=request.context.trip_handle,
        created_at=now,
        execution_deadline=execution_deadline,
        proposal_expires_at=now + MAX_RESULT_LIFETIME,
        retained_until=now + IDEMPOTENCY_RETENTION,
    )


def _check_replay(old: ProposalRecord, owner_id: str, fingerprint: str, now: datetime) -> None:
    if old.owner_id != owner_id:
        raise ResourceNotFoundError("proposal not found")
    if old.retained_until <= now:
        return
    if old.request_fingerprint != fingerprint:
        raise ProposalError("idempotency_conflict", 409)


class InMemoryItineraryProposalRepository:
    """Process-local deterministic repository for tests and local fake demos."""

    def __init__(self) -> None:
        self._records: dict[UUID, ProposalRecord] = {}
        self._lock = RLock()

    def begin(
        self,
        *,
        owner_id: str,
        request: ItineraryProposalRequest,
        request_fingerprint: str,
        now: datetime,
        execution_deadline: datetime,
    ) -> tuple[ProposalRecord, bool]:
        proposal_id = proposal_id_for(owner_id, request.idempotency_key)
        with self._lock:
            old = self._records.get(proposal_id)
            if old is not None:
                _check_replay(old, owner_id, request_fingerprint, now)
                if old.retained_until > now:
                    return old, False
            record = _new_record(owner_id, request, request_fingerprint, now, execution_deadline)
            self._records[proposal_id] = record
            return record, True

    def complete(self, record: ProposalRecord, result: ItineraryProposalResult) -> ProposalRecord:
        with self._lock:
            old = self._records.get(record.proposal_id)
            if old is None or old.owner_id != record.owner_id:
                raise ResourceNotFoundError("proposal not found")
            if old.state != "running" or old.request_fingerprint != record.request_fingerprint:
                raise ProposalError("proposal_conflict", 409)
            if result.proposal_id != old.proposal_id or result.created_at != old.created_at:
                raise ProposalError("proposal_conflict", 409)
            if result.state == "running":
                raise ProposalError("proposal_conflict", 409)
            completed = old.model_copy(update={"state": result.state, "result": result})
            self._records[old.proposal_id] = completed
            return completed

    def get(self, owner_id: str, proposal_id: UUID) -> ProposalRecord:
        with self._lock:
            old = self._records.get(proposal_id)
            if old is None or old.owner_id != owner_id:
                raise ResourceNotFoundError("proposal not found")
            return old


class FirestoreItineraryProposalRepository:
    """Single-document transaction boundary; no travel database is accessed."""

    def __init__(self, client=None, *, project_id=None, emulator_host=None):
        self.client = client if client is not None else _firestore_client(project_id, emulator_host)
        self.proposals = self.client.collection("itinerary_proposals")

    @staticmethod
    def _data(record: ProposalRecord) -> dict:
        data = record.model_dump(mode="json")
        # Native Firestore timestamp is required by its TTL policy.
        data["retained_until"] = record.retained_until
        return data

    @staticmethod
    def _decode(snapshot, owner_id: str) -> ProposalRecord:
        if not snapshot.exists:
            raise ResourceNotFoundError("proposal not found")
        record = ProposalRecord.model_validate(snapshot.to_dict())
        if record.owner_id != owner_id:
            raise ResourceNotFoundError("proposal not found")
        return record

    @staticmethod
    def _storage_call(operation):
        try:
            return operation()
        except (GoogleAPICallError, RetryError, OSError, ValueError) as error:
            raise StorageUnavailableError("proposal storage unavailable") from error

    def begin(
        self,
        *,
        owner_id: str,
        request: ItineraryProposalRequest,
        request_fingerprint: str,
        now: datetime,
        execution_deadline: datetime,
    ) -> tuple[ProposalRecord, bool]:
        record = _new_record(owner_id, request, request_fingerprint, now, execution_deadline)

        def operation(transaction, timeout):
            ref = self.proposals.document(str(record.proposal_id))
            snapshot = ref.get(transaction=transaction, retry=None, timeout=timeout())
            if snapshot.exists:
                old = self._decode(snapshot, owner_id)
                _check_replay(old, owner_id, request_fingerprint, now)
                if old.retained_until > now:
                    return old, False
            transaction.set(ref, self._data(record))
            return record, True

        return self._storage_call(lambda: bounded_transaction(self.client, operation))

    def complete(self, record: ProposalRecord, result: ItineraryProposalResult) -> ProposalRecord:
        def operation(transaction, timeout):
            ref = self.proposals.document(str(record.proposal_id))
            snapshot = ref.get(transaction=transaction, retry=None, timeout=timeout())
            old = self._decode(snapshot, record.owner_id)
            if (
                old.state != "running"
                or old.request_fingerprint != record.request_fingerprint
                or old.created_at != record.created_at
                or result.proposal_id != old.proposal_id
                or result.created_at != old.created_at
                or result.state == "running"
            ):
                raise ProposalError("proposal_conflict", 409)
            completed = old.model_copy(update={"state": result.state, "result": result})
            transaction.set(ref, self._data(completed))
            return completed

        return self._storage_call(lambda: bounded_transaction(self.client, operation))

    def get(self, owner_id: str, proposal_id: UUID) -> ProposalRecord:
        return self._storage_call(
            lambda: self._decode(
                self.proposals.document(str(proposal_id)).get(retry=None, timeout=5), owner_id
            )
        )
