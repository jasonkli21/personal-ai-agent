"""Owner-scoped idempotency and immutable result storage for travel proposals."""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import RLock
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ConfigDict, Field

from personal_ai.auth.scope import (
    STANDALONE_APPLICATION_ID,
    ApplicationScopedRecord,
    current_application_scope,
    scope_matches,
    scoped_record,
)
from personal_ai.itinerary_proposals.contracts import (
    ItineraryProposalRequest,
    ItineraryProposalResult,
    ProposalError,
)
from personal_ai.storage.errors import ResourceNotFoundError

MAX_RESULT_LIFETIME = timedelta(hours=24)
IDEMPOTENCY_RETENTION = timedelta(hours=48)


def proposal_id_for(owner_id: str, idempotency_key: UUID) -> UUID:
    scope = current_application_scope()
    namespace = (
        "" if scope.application_id == STANDALONE_APPLICATION_ID and scope.workspace_id is None
        else f":{scope.application_id}:{scope.workspace_id or ''}"
    )
    return uuid5(NAMESPACE_URL, f"itinerary-proposal-v1:{owner_id}{namespace}:{idempotency_key}")


class ProposalRecord(ApplicationScopedRecord):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: str
    trip_handle: str
    support_mode: Literal["context_only", "research_evidence"]
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
        timeout_seconds: float = 5,
        deadline: float | None = None,
    ) -> tuple[ProposalRecord, bool]: ...

    def complete(
        self,
        record: ProposalRecord,
        result: ItineraryProposalResult,
        timeout_seconds: float = 5,
        deadline: float | None = None,
    ) -> ProposalRecord: ...

    def get(self, owner_id: str, proposal_id: UUID) -> ProposalRecord: ...


def _new_record(owner_id, request, request_fingerprint, now, execution_deadline):
    return scoped_record(ProposalRecord(
        proposal_id=proposal_id_for(owner_id, request.idempotency_key),
        owner_id=owner_id,
        request_fingerprint=request_fingerprint,
        state="running",
        trip_handle=request.context.trip_handle,
        support_mode=("research_evidence" if request.research_session_ids else "context_only"),
        created_at=now,
        execution_deadline=execution_deadline,
        proposal_expires_at=now + MAX_RESULT_LIFETIME,
        retained_until=now + IDEMPOTENCY_RETENTION,
    ))


def _check_replay(old: ProposalRecord, owner_id: str, fingerprint: str, now: datetime) -> None:
    if old.owner_id != owner_id or not scope_matches(old):
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
        timeout_seconds: float = 5,
        deadline: float | None = None,
    ) -> tuple[ProposalRecord, bool]:
        del timeout_seconds, deadline
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

    def complete(
        self,
        record: ProposalRecord,
        result: ItineraryProposalResult,
        timeout_seconds: float = 5,
        deadline: float | None = None,
    ) -> ProposalRecord:
        del timeout_seconds, deadline
        with self._lock:
            old = self._records.get(record.proposal_id)
            if old is None or old.owner_id != record.owner_id or not scope_matches(old):
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
            if old is None or old.owner_id != owner_id or not scope_matches(old):
                raise ResourceNotFoundError("proposal not found")
            return old
