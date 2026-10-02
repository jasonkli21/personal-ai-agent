"""Owner-scoped storage for Phase 7 registration and comparison snapshots."""

from threading import RLock
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.domains.contracts import DomainComparisonResult
from personal_ai.storage.errors import ResourceNotFoundError


class DomainRepositoryError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class DomainRepository(Protocol):
    def create(self, result: DomainComparisonResult) -> DomainComparisonResult: ...

    def get(self, owner_id: str, comparison_id: UUID) -> DomainComparisonResult: ...


class InMemoryDomainRepository:
    """Deterministic owner-isolated domain repository used by fixtures and tests."""

    def __init__(self):
        self.results: dict[UUID, DomainComparisonResult] = {}
        self.lock = RLock()

    def create(self, result):
        with self.lock:
            existing = self.results.get(result.comparison.id)
            if existing is not None:
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
            if result is None or result.comparison.owner_id != owner_id:
                raise ResourceNotFoundError("domain comparison not found")
            return result


class FirestoreDomainRepository:
    """Point-lookup persistence; no domain-specific entity or ranking store."""

    def __init__(self, client=None, *, project_id=None, emulator_host=None):
        from personal_ai.storage.firestore import _firestore_client

        self.client = client if client is not None else _firestore_client(project_id, emulator_host)
        self.registrations = self.client.collection("domain_registrations")
        self.claims = self.client.collection("domain_claim_extensions")
        self.observations = self.client.collection("provider_observations")
        self.comparisons = self.client.collection("domain_comparison_views")

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
        from personal_ai.domains.contracts import DomainRegistration
        from personal_ai.storage.transactions import bounded_transaction

        snapshot = result.comparison
        comparison_ref = self.comparisons.document(str(snapshot.id))
        registration_ref = self.registrations.document(result.registration.domain_id)
        claim_refs = [
            (item, self.claims.document(str(uuid5(
                NAMESPACE_URL, f"domain-claim-v1:{item.domain_id}:{item.claim_id}"
            ))) )
            for item in result.domain_claims
        ]
        observation_refs = [
            (item, self.observations.document(str(item.source_observation_id)))
            for item in result.provider_observations
        ]

        def operation(transaction, timeout):
            del timeout
            existing_snapshot = next(transaction.get(comparison_ref), None)
            if existing_snapshot is not None and existing_snapshot.exists:
                from personal_ai.domains.contracts import DomainComparisonResult

                existing = DomainComparisonResult.model_validate(existing_snapshot.to_dict())
                if (
                    existing.comparison.owner_id != snapshot.owner_id
                    or existing.comparison.domain_id != snapshot.domain_id
                    or existing.comparison.decision_id != snapshot.decision_id
                ):
                    raise DomainRepositoryError("domain_comparison_conflict")
                return False

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
                elif data != self._data(record):
                    raise DomainRepositoryError("domain_record_conflict")

            if not any(ref == registration_ref and current is not None and current.exists
                       for _, ref, current in record_refs):
                transaction.create(registration_ref, self._data(result.registration))
            for record, reference, current in record_refs:
                if reference == registration_ref or current is not None and current.exists:
                    continue
                transaction.create(reference, self._data(record))
            transaction.create(comparison_ref, self._data(result))
            return True

        created = self._run(lambda: bounded_transaction(self.client, operation))
        if not created:
            return self.get(snapshot.owner_id, snapshot.id)
        return result

    def get(self, owner_id: str, comparison_id: UUID) -> DomainComparisonResult:
        from personal_ai.domains.contracts import DomainComparisonResult

        def operation():
            document = self.comparisons.document(str(comparison_id)).get(retry=None, timeout=5)
            if not document.exists:
                raise ResourceNotFoundError("domain comparison not found")
            result = DomainComparisonResult.model_validate(document.to_dict())
            if result.comparison.owner_id != owner_id:
                raise ResourceNotFoundError("domain comparison not found")
            return result

        return self._run(operation)
