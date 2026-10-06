"""Owner-scoped storage for Phase 7 registration and comparison snapshots."""

from datetime import UTC, datetime
from threading import RLock
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.auth.scope import (
    scope_matches,
    scope_normalized_dump,
    scoped_identifier,
    scoped_record,
)
from personal_ai.domains.contracts import DomainComparisonResult, DomainLookupReservation
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError


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


class FirestoreDomainRepository:
    """Point-lookup persistence; no domain-specific entity or ranking store."""

    def __init__(self, client=None, *, project_id=None, emulator_host=None):
        from personal_ai.storage.firestore import _firestore_client

        self.client = client if client is not None else _firestore_client(project_id, emulator_host)
        self.registrations = self.client.collection("domain_registrations")
        self.claims = self.client.collection("domain_claim_extensions")
        self.observations = self.client.collection("provider_observations")
        self.comparisons = self.client.collection("domain_comparison_views")
        self.lookups = self.client.collection("domain_lookup_idempotency")

    @staticmethod
    def _run(operation):
        from google.api_core.exceptions import GoogleAPICallError, RetryError

        from personal_ai.storage.errors import StorageUnavailableError

        try:
            return operation()
        except (GoogleAPICallError, RetryError, OSError, TimeoutError) as error:
            raise StorageUnavailableError("domain storage unavailable") from error

    @staticmethod
    def _data(record):
        return record.model_dump(mode="json")

    def create(self, result):
        return self._persist(result)

    def complete_lookup(self, reservation_id, fence_token, result):
        return self._persist(result, reservation_id=reservation_id, fence_token=fence_token)

    def _persist(self, result, *, reservation_id=None, fence_token=None):
        from personal_ai.domains.contracts import DomainRegistration
        from personal_ai.storage.transactions import bounded_transaction

        result = scoped_record(result)
        snapshot = result.comparison
        comparison_ref = self.comparisons.document(scoped_identifier(snapshot.id))
        reservation_ref = self.lookups.document(scoped_identifier(reservation_id)) if reservation_id else None
        registration = result.registration
        registration_ref = self.registrations.document(str(uuid5(
            NAMESPACE_URL,
            f"domain-registration-v1:{registration.domain_id}:{registration.field_schema_version}:"
            f"{registration.feature_policy_version}:{registration.source_policy_version}",
        )))
        claim_refs = [
            (item, self.claims.document(scoped_identifier(uuid5(
                NAMESPACE_URL, f"domain-claim-v1:{item.domain_id}:{item.claim_id}"
            ))) )
            for item in result.domain_claims
        ]
        observation_refs = [
            (item, self.observations.document(scoped_identifier(item.source_observation_id)))
            for item in result.provider_observations
        ]

        def operation(transaction, timeout):
            current_reservation = None
            if reservation_ref is not None:
                current = next(transaction.get(reservation_ref), None)
                if current is None or not current.exists:
                    raise DomainRepositoryError("domain_lookup_reservation_missing")
                current_reservation = DomainLookupReservation.model_validate(current.to_dict())
                if (
                    current_reservation.owner_id != snapshot.owner_id
                    or current_reservation.domain_id != snapshot.domain_id
                    or not scope_matches(current_reservation)
                ):
                    raise DomainRepositoryError("domain_lookup_result_conflict")
                if current_reservation.state == "completed":
                    existing = next(transaction.get(comparison_ref), None)
                    if existing is None or not existing.exists:
                        raise DomainRepositoryError("domain_lookup_result_missing")
                    from personal_ai.domains.contracts import DomainComparisonResult

                    saved = DomainComparisonResult.model_validate(existing.to_dict())
                    if (
                        current_reservation.comparison_id != snapshot.id
                        or saved.comparison.owner_id != snapshot.owner_id
                        or saved.comparison.domain_id != snapshot.domain_id
                        or not scope_matches(saved)
                    ):
                        raise DomainRepositoryError("domain_lookup_result_conflict")
                    return saved
                if (
                    current_reservation.state != "reserved"
                    or current_reservation.fence_token != fence_token
                ):
                    raise DomainRepositoryError("domain_lookup_fence_lost")
            existing_snapshot = next(transaction.get(comparison_ref), None)
            existing_result = None
            if existing_snapshot is not None and existing_snapshot.exists:
                from personal_ai.domains.contracts import DomainComparisonResult

                existing = DomainComparisonResult.model_validate(existing_snapshot.to_dict())
                if (
                    existing.comparison.owner_id != snapshot.owner_id
                    or existing.comparison.domain_id != snapshot.domain_id
                    or existing.comparison.decision_id != snapshot.decision_id
                    or not scope_matches(existing)
                ):
                    raise DomainRepositoryError("domain_comparison_conflict")
                existing_result = existing

            record_refs = [(record, reference, next(transaction.get(reference), None))
                           for record, reference in [(result.registration, registration_ref), *claim_refs, *observation_refs]]
            # All transaction reads precede writes. Registration content is
            # versioned; runtime enablement is a separate gate.
            for record, reference, current in record_refs:
                if current is None or not current.exists:
                    continue
                data = current.to_dict()
                if reference == registration_ref:
                    old = DomainRegistration.model_validate(data)
                    old_static = old.model_copy(update={"enabled": record.enabled})
                    if old_static != record:
                        raise DomainRepositoryError("domain_registration_conflict")
                else:
                    comparable = dict(data)
                    comparable.pop("owner_id", None)
                    from personal_ai.domains.contracts import DomainClaimExtension

                    if isinstance(record, DomainClaimExtension):
                        old_claim = DomainClaimExtension.model_validate(comparable)
                        if not scope_matches(old_claim):
                            raise DomainRepositoryError("domain_comparison_conflict")
                        comparable = old_claim
                    if scope_normalized_dump(comparable) != scope_normalized_dump(self._data(record)):
                        raise DomainRepositoryError("domain_record_conflict")

            if not any(ref == registration_ref and current is not None and current.exists
                       for _, ref, current in record_refs):
                transaction.create(registration_ref, self._data(result.registration))
            for record, reference, current in record_refs:
                if reference == registration_ref or current is not None and current.exists:
                    continue
                data = self._data(record)
                if record in result.domain_claims:
                    data["owner_id"] = snapshot.owner_id
                transaction.create(reference, data)
            if existing_result is None:
                transaction.create(comparison_ref, self._data(result))
            saved = existing_result or result
            if reservation_ref is not None and current_reservation is not None:
                completed = _updated_reservation(
                    current_reservation,
                    state="completed",
                    comparison_id=saved.comparison.id,
                    updated_at=max(current_reservation.updated_at, saved.comparison.rendered_at),
                )
                transaction.set(reservation_ref, self._data(completed))
            return saved

        return self._run(lambda: bounded_transaction(self.client, operation))

    def reserve_lookup(self, reservation):
        from personal_ai.storage.transactions import bounded_transaction

        reservation = scoped_record(reservation)
        reference = self.lookups.document(scoped_identifier(reservation.id))

        def operation(transaction, timeout):
            del timeout
            snapshot = next(transaction.get(reference), None)
            if snapshot is not None and snapshot.exists:
                existing = DomainLookupReservation.model_validate(snapshot.to_dict())
                if (
                    existing.owner_id != reservation.owner_id
                    or existing.domain_id != reservation.domain_id
                    or existing.idempotency_key != reservation.idempotency_key
                    or not scope_matches(existing)
                ):
                    raise DomainRepositoryError("domain_lookup_reservation_conflict")
                return existing
            transaction.create(reference, self._data(reservation))
            return reservation

        try:
            return self._run(lambda: bounded_transaction(self.client, operation))
        except StorageUnavailableError:
            # A competing transaction may have won the create after our
            # initial read. Resolve the durable winner so callers fail closed
            # as in-progress instead of treating a normal fence race as outage.
            snapshot = self._run(lambda: reference.get(retry=None, timeout=5))
            if not snapshot.exists:
                raise
            existing = DomainLookupReservation.model_validate(snapshot.to_dict())
            if (
                existing.owner_id != reservation.owner_id
                or existing.domain_id != reservation.domain_id
                or existing.idempotency_key != reservation.idempotency_key
                or not scope_matches(existing)
            ):
                raise DomainRepositoryError("domain_lookup_reservation_conflict")
            return existing

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
        from personal_ai.storage.transactions import bounded_transaction

        reference = self.lookups.document(scoped_identifier(reservation_id))

        def operation(transaction, timeout):
            del timeout
            snapshot = next(transaction.get(reference), None)
            if snapshot is None or not snapshot.exists:
                raise DomainRepositoryError("domain_lookup_reservation_missing")
            current = DomainLookupReservation.model_validate(snapshot.to_dict())
            if not scope_matches(current):
                raise DomainRepositoryError("domain_lookup_reservation_missing")
            if current.fence_token != fence_token:
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
            transaction.set(reference, self._data(failed))
            return failed

        return self._run(lambda: bounded_transaction(self.client, operation))

    def get(self, owner_id: str, comparison_id: UUID) -> DomainComparisonResult:
        from personal_ai.domains.contracts import DomainComparisonResult

        def operation():
            document = self.comparisons.document(scoped_identifier(comparison_id)).get(retry=None, timeout=5)
            if not document.exists:
                raise ResourceNotFoundError("domain comparison not found")
            result = DomainComparisonResult.model_validate(document.to_dict())
            if result.comparison.owner_id != owner_id or not scope_matches(result):
                raise ResourceNotFoundError("domain comparison not found")
            return result

        return self._run(operation)
