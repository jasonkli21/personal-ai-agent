"""Owner-scoped decision persistence contracts and deterministic test fake."""

from threading import RLock
from typing import Protocol
from uuid import UUID

from personal_ai.auth.scope import scope_matches, scoped_record
from personal_ai.decisions.contracts import DecisionResult
from personal_ai.entities.research import CanonicalEntity, EntityAlias, EntityClaim
from personal_ai.storage.errors import ResourceNotFoundError


class DecisionError(Exception):
    """Safe decision operation error with a stable code and HTTP status."""

    def __init__(self, code: str, status: int = 409):
        self.code = code
        self.status = status
        super().__init__(code)


class DecisionRepository(Protocol):
    def list_entities(self, owner_id: str, entity_type: str, limit: int) -> tuple[CanonicalEntity, ...]: ...

    def list_aliases(self, owner_id: str, entity_ids: tuple[UUID, ...]) -> tuple[EntityAlias, ...]: ...

    def list_claims(
        self,
        owner_id: str,
        entity_ids: tuple[UUID, ...],
        attributes: tuple[str, ...] = (),
        limit: int = 500,
    ) -> tuple[EntityClaim, ...]: ...

    def find_claims_by_evidence(
        self, owner_id: str, evidence_id: UUID, limit: int = 100
    ) -> tuple[EntityClaim, ...]: ...

    def create(self, result: DecisionResult) -> DecisionResult: ...

    def get(self, owner_id: str, decision_id: UUID) -> DecisionResult: ...


class InMemoryDecisionRepository:
    """Deterministic, owner-isolated repository used by tests and evaluations."""

    def __init__(self):
        self.entities: dict[UUID, CanonicalEntity] = {}
        self.aliases: dict[UUID, EntityAlias] = {}
        self.claims: dict[UUID, EntityClaim] = {}
        self.evidence_entity_links: set[tuple[str, UUID, UUID, UUID]] = set()
        self.results: dict[UUID, DecisionResult] = {}
        self.lock = RLock()

    def list_entities(self, owner_id, entity_type, limit):
        with self.lock:
            matches = [
                entity for entity in self.entities.values()
                if scope_matches(entity)
                and entity.entity_type == entity_type
                and entity.status == "active"
                and entity.owner_scope in {f"owner:{owner_id}", "shared"}
            ]
            return tuple(sorted(matches, key=lambda entity: str(entity.id))[: limit + 1])

    def list_aliases(self, owner_id, entity_ids):
        with self.lock:
            allowed = set(entity_ids)
            return tuple(sorted((
                alias for alias in self.aliases.values()
                if scope_matches(alias) and alias.entity_id in allowed and alias.owner_id in {owner_id, "*"}
            ), key=lambda alias: str(alias.id)))

    def list_claims(self, owner_id, entity_ids, attributes=(), limit=500):
        with self.lock:
            allowed = set(entity_ids)
            matches = sorted((
                claim for claim in self.claims.values()
                if scope_matches(claim) and claim.entity_id in allowed and claim.owner_id == owner_id
                and (not attributes or claim.attribute in attributes)
            ), key=lambda claim: (str(claim.entity_id), claim.attribute, str(claim.id)))
            return tuple(matches[: limit + 1])

    def find_claims_by_evidence(self, owner_id, evidence_id, limit=100):
        with self.lock:
            return tuple(sorted((
                claim for claim in self.claims.values()
                if scope_matches(claim) and claim.owner_id == owner_id and evidence_id in claim.evidence_ids
            ), key=lambda claim: str(claim.id))[:limit])

    def create(self, result):
        result = scoped_record(result)
        with self.lock:
            decision = result.decision
            existing_result = self.results.get(decision.id)
            if existing_result:
                if not scope_matches(existing_result):
                    raise ResourceNotFoundError("decision not found")
                if existing_result.decision.request_fingerprint != decision.request_fingerprint:
                    raise DecisionError("idempotency_conflict")
                return existing_result
            for entity in result.entities:
                old_entity = self.entities.get(entity.id)
                if old_entity and (
                    old_entity.owner_id != entity.owner_id
                    or old_entity.entity_type != entity.entity_type
                    or any(old_entity.identifiers.get(key) != value for key, value in entity.identifiers.items())
                ):
                    raise DecisionError("entity_identity_conflict")
            for claim in result.claims:
                old_claim = self.claims.get(claim.id)
                if old_claim and old_claim != claim:
                    raise DecisionError("claim_immutability_conflict")
            for alias in result.aliases:
                old_alias = self.aliases.get(alias.id)
                if old_alias and old_alias != alias:
                    raise DecisionError("decision_record_conflict")
            for entity in result.entities:
                self.entities.setdefault(entity.id, entity)
            for alias in result.aliases:
                self.aliases.setdefault(alias.id, alias)
            for claim in result.claims:
                self.claims.setdefault(claim.id, claim)
                for evidence_id in claim.evidence_ids:
                    self.evidence_entity_links.add(
                        (claim.owner_id, evidence_id, claim.entity_id, claim.id)
                    )
            self.results[decision.id] = result
            return result

    def get(self, owner_id, decision_id):
        with self.lock:
            result = self.results.get(decision_id)
            if result is None or result.decision.owner_id != owner_id or not scope_matches(result):
                raise ResourceNotFoundError("decision not found")
            return result
