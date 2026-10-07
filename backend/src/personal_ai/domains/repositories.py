"""Owner-scoped storage for Phase 7 registration and comparison snapshots."""

from datetime import UTC, datetime
from threading import RLock
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.auth.scope import (
    scope_matches,
    scoped_record,
)
from personal_ai.domains.contracts import DomainComparisonResult, DomainLookupReservation
from personal_ai.storage.errors import ResourceNotFoundError


class DomainRepositoryError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class DomainRepository(Protocol):
    def create(self, result: DomainComparisonResult) -> DomainComparisonResult: ...

    def get(self, owner_id: str, comparison_id: UUID) -> DomainComparisonResult: ...

    def reserve_lookup(self, reservation: DomainLookupReservation) -> DomainLookupReservation: ...

    def fail_lookup(
        self,
        reservation_id: UUID,
        fence_token: UUID,
        *,
        state: Literal["failed", "uncertain"],
        failure_kind: str | None = None,
        failure_code: str | None = None,
        failure_status: int | None = None,
    ) -> DomainLookupReservation: ...

    def complete_lookup(
        self,
        reservation_id: UUID,
        fence_token: UUID,
        result: DomainComparisonResult,
    ) -> DomainComparisonResult: ...


def lookup_reservation_id(owner_id: str, domain_id: str, idempotency_key: UUID) -> UUID:
    from personal_ai.auth.scope import STANDALONE_APPLICATION_ID, current_application_scope

    scope = current_application_scope()
    namespace = (
        "" if scope.application_id == STANDALONE_APPLICATION_ID and scope.workspace_id is None
        else f":{scope.application_id}:{scope.workspace_id or ''}"
    )
    return uuid5(NAMESPACE_URL, f"domain-lookup-v1:{owner_id}{namespace}:{domain_id}:{idempotency_key}")


def _updated_reservation(reservation: DomainLookupReservation, **updates):
    values = reservation.model_dump()
    values.update(updates)
    return DomainLookupReservation.model_validate(values)


class InMemoryDomainRepository:
    """Deterministic owner-isolated domain repository used by fixtures and tests."""

    def __init__(self):
        self.results: dict[UUID, DomainComparisonResult] = {}
        self.lookups: dict[UUID, DomainLookupReservation] = {}
        self.lock = RLock()

    def create(self, result):
        result = scoped_record(result)
        with self.lock:
            existing = self.results.get(result.comparison.id)
            if existing is not None:
                if not scope_matches(existing):
                    raise ResourceNotFoundError("domain comparison not found")
                if (
                    existing.comparison.owner_id != result.comparison.owner_id
                    or existing.comparison.domain_id != result.comparison.domain_id
                    or existing.comparison.decision_id != result.comparison.decision_id
                ):
                    raise DomainRepositoryError("domain_comparison_conflict")
                return existing
            self.results[result.comparison.id] = result
            return result

    def get(self, owner_id, comparison_id):
        with self.lock:
            result = self.results.get(comparison_id)
            if result is None or result.comparison.owner_id != owner_id or not scope_matches(result):
                raise ResourceNotFoundError("domain comparison not found")
            return result

    def reserve_lookup(self, reservation):
        reservation = scoped_record(reservation)
        with self.lock:
            existing = self.lookups.get(reservation.id)
            if existing is not None:
                if not scope_matches(existing):
                    raise DomainRepositoryError("domain_lookup_reservation_conflict")
                if (
                    existing.owner_id != reservation.owner_id
                    or existing.domain_id != reservation.domain_id
                    or existing.idempotency_key != reservation.idempotency_key
                ):
                    raise DomainRepositoryError("domain_lookup_reservation_conflict")
                return existing
            self.lookups[reservation.id] = reservation
            return reservation

    def fail_lookup(
        self,
        reservation_id,
        fence_token,
        *,
        state: Literal["failed", "uncertain"],
        failure_kind=None,
        failure_code=None,
        failure_status=None,
    ):
        with self.lock:
            current = self.lookups.get(reservation_id)
            if current is None or not scope_matches(current) or current.fence_token != fence_token:
                raise DomainRepositoryError("domain_lookup_fence_lost")
            if current.state != "reserved":
                return current
            failed = _updated_reservation(
                current,
                state=state,
                failure_kind=failure_kind,
                failure_code=failure_code,
                failure_status=failure_status,
                updated_at=max(current.updated_at, datetime.now(UTC)),
            )
            self.lookups[reservation_id] = failed
            return failed

    def complete_lookup(self, reservation_id, fence_token, result):
        with self.lock:
            current = self.lookups.get(reservation_id)
            if current is None or not scope_matches(current):
                raise DomainRepositoryError("domain_lookup_reservation_missing")
            if (
                current.owner_id != result.comparison.owner_id
                or current.domain_id != result.comparison.domain_id
            ):
                raise DomainRepositoryError("domain_lookup_result_conflict")
            if current.state == "completed":
                if current.comparison_id != result.comparison.id:
                    raise DomainRepositoryError("domain_lookup_result_conflict")
                return self.get(result.comparison.owner_id, current.comparison_id)
            if current.state != "reserved" or current.fence_token != fence_token:
                raise DomainRepositoryError("domain_lookup_fence_lost")
            saved = self.create(result)
            self.lookups[reservation_id] = _updated_reservation(
                current,
                state="completed",
                comparison_id=saved.comparison.id,
                updated_at=max(current.updated_at, saved.comparison.rendered_at),
            )
            return saved
