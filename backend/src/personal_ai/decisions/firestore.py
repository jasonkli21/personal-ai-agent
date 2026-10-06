"""Atomic immutable Firestore storage for entities, claims, and decisions."""

import time
from uuid import UUID

from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.cloud import firestore

from personal_ai.auth.scope import (
    scope_filtered_snapshots,
    scope_matches,
    scope_normalized_dump,
    scope_query,
    scoped_record,
)
from personal_ai.decisions.contracts import (
    CandidateEvaluation,
    DecisionResult,
    DecisionSnapshot,
    EvidenceSnapshot,
)
from personal_ai.decisions.repositories import DecisionError
from personal_ai.entities.research import CanonicalEntity, EntityAlias, EntityClaim, EntityMatch
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError
from personal_ai.storage.firestore import _firestore_client
from personal_ai.storage.transactions import bounded_transaction


class FirestoreDecisionRepository:
    """Owner-scoped Phase 6 records with append-only claims and decision snapshots."""

    def __init__(self, client=None, *, project_id=None, emulator_host=None):
        self.client = client if client is not None else _firestore_client(project_id, emulator_host)
        self.entities = self.client.collection("canonical_entities")
        self.aliases = self.client.collection("entity_aliases")
        self.claims = self.client.collection("entity_claims")
        self.matches = self.client.collection("entity_matches")
        self.decisions = self.client.collection("decision_snapshots")
        self.evidence_snapshots = self.client.collection("decision_evidence_snapshots")
        self.evaluations = self.client.collection("candidate_evaluations")

    @staticmethod
    def _run(operation):
        try:
            return operation()
        except (GoogleAPICallError, RetryError, OSError, TimeoutError) as error:
            raise StorageUnavailableError("decision storage unavailable") from error

    @staticmethod
    def _data(record):
        return record.model_dump(mode="json")

    def list_entities(self, owner_id, entity_type, limit):
        def operation():
            records = []
            for scope_owner in (owner_id, "*"):
                query = (
                    self.entities.where(filter=firestore.FieldFilter("owner_id", "==", scope_owner))
                    .where(filter=firestore.FieldFilter("entity_type", "==", entity_type))
                    .where(filter=firestore.FieldFilter("status", "==", "active"))
                )
                query = scope_query(query)
                records.extend(
                    entity for item in scope_filtered_snapshots(
                        query, limit=limit + 1, timeout=5
                    )
                    if scope_matches(entity := CanonicalEntity.model_validate(item.to_dict()))
                )
            return tuple(sorted({item.id: item for item in records}.values(), key=lambda item: str(item.id))[: limit + 1])

        return self._run(operation)

    def list_aliases(self, owner_id, entity_ids):
        def operation():
            aliases = []
            deadline = time.monotonic() + 5
            for offset in range(0, len(entity_ids), 30):
                group = [str(item) for item in entity_ids[offset:offset + 30]]
                for scope_owner in (owner_id, "*"):
                    query = (
                        self.aliases.where(filter=firestore.FieldFilter("owner_id", "==", scope_owner))
                        .where(filter=firestore.FieldFilter("entity_id", "in", group))
                    )
                    query = scope_query(query)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("decision alias query deadline exceeded")
                    values = tuple(
                        alias for item in scope_filtered_snapshots(
                            query, limit=100 * len(group) + 1, timeout=remaining
                        )
                        if scope_matches(alias := EntityAlias.model_validate(item.to_dict()))
                    )
                    if len(values) > 100 * len(group):
                        raise DecisionError("decision_alias_resolution_limit", 409)
                    aliases.extend(values)
            return tuple(sorted(aliases, key=lambda item: str(item.id)))

        return self._run(operation)

    def list_claims(self, owner_id, entity_ids, attributes=(), limit=500):
        def operation():
            records_by_id = {}
            ids = [str(item) for item in entity_ids]
            requested_attributes = tuple(sorted(set(attributes))) or (None,)
            deadline = time.monotonic() + 5
            for offset in range(0, len(ids), 30):
                group = ids[offset:offset + 30]
                for attribute in requested_attributes:
                    query = self.claims.where(
                        filter=firestore.FieldFilter("owner_id", "==", owner_id)
                    ).where(filter=firestore.FieldFilter("entity_id", "in", group))
                    if attribute is not None:
                        query = query.where(
                            filter=firestore.FieldFilter("attribute", "==", attribute)
                        )
                    query = scope_query(query)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("decision claim query deadline exceeded")
                    for item in scope_filtered_snapshots(
                        query, limit=limit + 1, timeout=remaining
                    ):
                        record = EntityClaim.model_validate(item.to_dict())
                        if scope_matches(record):
                            records_by_id[record.id] = record
                        if len(records_by_id) > limit:
                            return tuple(sorted(
                                records_by_id.values(),
                                key=lambda claim: (str(claim.entity_id), claim.attribute, str(claim.id)),
                            )[:limit + 1])
            return tuple(sorted(
                records_by_id.values(),
                key=lambda item: (str(item.entity_id), item.attribute, str(item.id)),
            ))

        return self._run(operation)

    def find_claims_by_evidence(self, owner_id, evidence_id, limit=100):
        def operation():
            query = (
                self.claims.where(filter=firestore.FieldFilter("owner_id", "==", owner_id))
                .where(filter=firestore.FieldFilter("evidence_ids", "array_contains", str(evidence_id)))
            )
            query = scope_query(query)
            return tuple(
                claim for item in scope_filtered_snapshots(
                    query, limit=limit, timeout=5
                )
                if scope_matches(claim := EntityClaim.model_validate(item.to_dict()))
            )

        return self._run(operation)

    def create(self, result: DecisionResult) -> DecisionResult:
        result = scoped_record(result)
        decision = result.decision
        snapshot_ref = self.decisions.document(str(decision.id))
        evidence_ref = self.evidence_snapshots.document(str(result.evidence_snapshot.id))

        records = []
        records.extend((self.entities, entity) for entity in result.entities)
        records.extend((self.aliases, alias) for alias in result.aliases)
        records.extend((self.claims, claim) for claim in result.claims)
        records.extend((self.matches, match) for match in result.matches)
        records.extend((self.evaluations, evaluation) for evaluation in result.evaluations)
        records.extend(((None, decision), (None, result.evidence_snapshot)))
        if len(records) > 450:
            raise DecisionError("decision_write_limit", 422)

        def operation(transaction, timeout):
            current = next(transaction.get(snapshot_ref), None)
            if current is not None and current.exists:
                old = DecisionSnapshot.model_validate(current.to_dict())
                if old.owner_id != decision.owner_id or not scope_matches(old):
                    raise ResourceNotFoundError("decision not found")
                if old.request_fingerprint != decision.request_fingerprint:
                    raise DecisionError("idempotency_conflict")
                return False

            references = []
            for collection, record in records:
                if collection is None:
                    ref = snapshot_ref if isinstance(record, DecisionSnapshot) else evidence_ref
                else:
                    ref = collection.document(str(record.id))
                references.append((collection, record, ref, next(transaction.get(ref), None)))

            # All reads are complete before the first write. Entities and claims
            # are append-only; the snapshot and its evaluations commit together.
            for collection, record, ref, current_record in references:
                if current_record is None or not current_record.exists:
                    data = self._data(record)
                    if isinstance(record, CandidateEvaluation):
                        data["owner_id"] = decision.owner_id
                    transaction.create(ref, data)
                    continue
                data = current_record.to_dict()
                if isinstance(record, CanonicalEntity):
                    old = CanonicalEntity.model_validate(data)
                    if (
                        old.owner_id != record.owner_id
                        or old.entity_type != record.entity_type
                        or old.identifiers != record.identifiers
                    ):
                        raise DecisionError("entity_identity_conflict")
                elif collection is self.claims:
                    old_claim = EntityClaim.model_validate(data)
                    if not scope_matches(old_claim):
                        raise ResourceNotFoundError("decision not found")
                    if scope_normalized_dump(old_claim) != scope_normalized_dump(record):
                        raise DecisionError("claim_immutability_conflict")
                else:
                    if data != self._data(record):
                        raise DecisionError("decision_record_conflict")
            return True

        created = self._run(lambda: bounded_transaction(self.client, operation))
        if not created:
            return self.get(decision.owner_id, decision.id)
        return result

    def get(self, owner_id: str, decision_id: UUID) -> DecisionResult:
        def operation():
            snapshot = self.decisions.document(str(decision_id)).get(retry=None, timeout=5)
            if not snapshot.exists:
                raise ResourceNotFoundError("decision not found")
            decision = DecisionSnapshot.model_validate(snapshot.to_dict())
            if decision.owner_id != owner_id or not scope_matches(decision):
                raise ResourceNotFoundError("decision not found")

            evidence_snapshot_doc = self.evidence_snapshots.document(
                str(decision.evidence_snapshot_id)
            ).get(retry=None, timeout=5)
            if not evidence_snapshot_doc.exists:
                raise StorageUnavailableError("decision evidence snapshot unavailable")
            evidence_snapshot = EvidenceSnapshot.model_validate(evidence_snapshot_doc.to_dict())
            if not scope_matches(evidence_snapshot):
                raise ResourceNotFoundError("decision not found")

            eval_query = self.evaluations.where(
                filter=firestore.FieldFilter("decision_id", "==", str(decision_id))
            ).limit(24)
            evaluations = []
            for item in scope_query(eval_query).stream(retry=None, timeout=5):
                data = item.to_dict()
                data.pop("owner_id", None)
                evaluation = CandidateEvaluation.model_validate(data)
                if scope_matches(evaluation):
                    evaluations.append(evaluation)
            evaluations = tuple(evaluations)
            if any(item.entity_id not in decision.candidate_ids for item in evaluations):
                raise StorageUnavailableError("decision evaluation invalid")

            entities = []
            for entity_id in decision.candidate_ids:
                entity_doc = self.entities.document(str(entity_id)).get(retry=None, timeout=5)
                if not entity_doc.exists:
                    raise StorageUnavailableError("decision entity unavailable")
                entity = CanonicalEntity.model_validate(entity_doc.to_dict())
                if ((entity.owner_scope != "shared" and entity.owner_id != owner_id)
                        or not scope_matches(entity)):
                    raise ResourceNotFoundError("decision not found")
                entities.append(entity)

            claim_ids = sorted({claim_id for item in evaluations for claim_id in item.claim_ids}, key=str)
            claims = []
            for claim_id in claim_ids:
                claim_doc = self.claims.document(str(claim_id)).get(retry=None, timeout=5)
                if not claim_doc.exists:
                    raise StorageUnavailableError("decision claim unavailable")
                claim = EntityClaim.model_validate(claim_doc.to_dict())
                if claim.owner_id != owner_id or not scope_matches(claim):
                    raise ResourceNotFoundError("decision not found")
                claims.append(claim)

            entity_ids = tuple(entity.id for entity in entities)
            aliases = self.list_aliases(owner_id, entity_ids)
            if decision.alias_ids is not None:
                recorded_alias_ids = set(decision.alias_ids)
                aliases = tuple(alias for alias in aliases if alias.id in recorded_alias_ids)
                if {alias.id for alias in aliases} != recorded_alias_ids:
                    raise StorageUnavailableError("decision alias unavailable")
            match_query = self.matches.where(
                filter=firestore.FieldFilter("owner_id", "==", owner_id)
            ).where(filter=firestore.FieldFilter("decision_id", "==", str(decision_id))).limit(24)
            match_query = scope_query(match_query)
            matches = tuple(
                match for item in match_query.stream(retry=None, timeout=5)
                if scope_matches(match := EntityMatch.model_validate(item.to_dict()))
            )
            return DecisionResult(
                application_id=decision.application_id,
                workspace_id=decision.workspace_id,
                scope_version=decision.scope_version,
                decision=decision,
                recommendation=decision.recommendation,
                evidence_snapshot=evidence_snapshot,
                entities=tuple(entities),
                claims=tuple(claims),
                aliases=aliases,
                matches=matches,
                evaluations=evaluations,
            )

        return self._run(operation)
