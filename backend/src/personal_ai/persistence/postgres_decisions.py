"""Postgres persistence for immutable entity, claim and decision snapshots."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from personal_ai.auth.scope import (
    ApplicationScope,
    current_application_scope,
    scope_matches,
    scope_normalized_dump,
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
from personal_ai.persistence.postgres import (
    PostgresDatabase,
    PostgresPayloadRepository,
    _ensure_namespace,
)
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError

_FAMILY_FOR_RECORD = {
    CanonicalEntity: "canonical_entities",
    EntityAlias: "entity_aliases",
    EntityClaim: "entity_claims",
    EntityMatch: "entity_matches",
    DecisionSnapshot: "decision_snapshots",
    EvidenceSnapshot: "decision_evidence_snapshots",
    CandidateEvaluation: "candidate_evaluations",
}


def _scope(record) -> ApplicationScope:
    return ApplicationScope(
        application_id=record.application_id, workspace_id=record.workspace_id
    )


def _data(record, *, owner_id: str | None = None) -> dict:
    value = record.model_dump(mode="json")
    if owner_id is not None:
        value["owner_id"] = owner_id
    return value


def _model(record_type, value):
    if record_type is CandidateEvaluation:
        value = {key: item for key, item in value.items() if key != "owner_id"}
    return record_type.model_validate(value)


def _insert(connection, record, *, family: str | None = None, owner_id: str | None = None):
    family = family or _FAMILY_FOR_RECORD[type(record)]
    owner_id = owner_id or record.owner_id
    scope = _scope(record)
    scope_id = _ensure_namespace(connection, owner_id, scope)
    record_id = str(record.id)
    value = _data(record, owner_id=owner_id if type(record) is CandidateEvaluation else None)
    created_at = getattr(record, "created_at", None)
    status = getattr(record, "status", None)
    connection.execute(
        f"INSERT INTO {family}(record_id,scope_id,owner_id,application_id,workspace_id,"
        "record_version,status,revision,created_at,payload) "
        "VALUES (%s,%s,%s,%s,%s,1,%s,1,COALESCE(%s,now()),%s::jsonb)",
        (
            record_id, scope_id, owner_id, scope.application_id, scope.workspace_id,
            status, created_at,
            PostgresPayloadRepository._json(value),
        ),
    )


class PostgresDecisionRepository:
    """Keep identity writes and the complete decision snapshot in one P transaction."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def list_entities(self, owner_id: str, entity_type: str, limit: int):
        if limit < 1 or limit > 500:
            raise ValueError("decision_entity_limit_invalid")
        scope = current_application_scope()
        owners = (owner_id, "*")
        scope_ids = tuple(PostgresPayloadRepository.scope_id(value, scope) for value in owners)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT owner_id,payload FROM canonical_entities WHERE scope_id=ANY(%s) "
                "AND owner_id=ANY(%s) AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND status='active' AND payload->>'entity_type'=%s "
                "ORDER BY record_id LIMIT %s",
                (list(scope_ids), list(owners), scope.application_id, scope.workspace_id,
                 entity_type, limit + 1),
            ).fetchall()
        records = []
        for _, payload in rows:
            entity = _model(CanonicalEntity, payload)
            if scope_matches(entity, scope) and (
                entity.owner_scope == "shared" or entity.owner_scope == f"owner:{owner_id}"
            ):
                records.append(entity)
        return tuple(records[: limit + 1])

    def list_aliases(self, owner_id: str, entity_ids: tuple[UUID, ...]):
        if not entity_ids:
            return ()
        scope = current_application_scope()
        scope_ids = [
            PostgresPayloadRepository.scope_id(value, scope) for value in (owner_id, "*")
        ]
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM entity_aliases WHERE scope_id=ANY(%s) "
                "AND owner_id=ANY(%s) AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND payload->>'entity_id'=ANY(%s) ORDER BY record_id",
                (
                    scope_ids, [owner_id, "*"], scope.application_id, scope.workspace_id,
                    [str(value) for value in entity_ids],
                ),
            ).fetchall()
        values = tuple(_model(EntityAlias, row[0]) for row in rows)
        return tuple(value for value in values if scope_matches(value, scope))

    def list_claims(
        self, owner_id: str, entity_ids: tuple[UUID, ...], attributes: tuple[str, ...] = (), limit: int = 500
    ):
        if limit < 1 or limit > 5000:
            raise ValueError("decision_claim_limit_invalid")
        if not entity_ids:
            return ()
        scope = current_application_scope()
        clauses = [
            "scope_id=%s", "owner_id=%s", "application_id=%s",
            "workspace_id IS NOT DISTINCT FROM %s", "payload->>'entity_id'=ANY(%s)",
        ]
        params: list = [
            PostgresPayloadRepository.scope_id(owner_id, scope), owner_id,
            scope.application_id, scope.workspace_id, [str(item) for item in entity_ids],
        ]
        if attributes:
            clauses.append("payload->>'attribute'=ANY(%s)")
            params.append(list(attributes))
        params.append(limit + 1)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM entity_claims WHERE " + " AND ".join(clauses)
                + " ORDER BY payload->>'entity_id',payload->>'attribute',record_id LIMIT %s",
                params,
            ).fetchall()
        return tuple(_model(EntityClaim, row[0]) for row in rows)

    def find_claims_by_evidence(self, owner_id: str, evidence_id: UUID, limit: int = 100):
        if not 1 <= limit <= 1000:
            raise ValueError("decision_claim_limit_invalid")
        scope = current_application_scope()
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT claim.payload FROM entity_claim_evidence link "
                "JOIN entity_claims claim ON claim.scope_id=link.scope_id "
                "AND claim.record_id=link.claim_id WHERE link.scope_id=%s AND link.owner_id=%s "
                "AND link.application_id=%s AND link.workspace_id IS NOT DISTINCT FROM %s "
                "AND link.evidence_id=%s ORDER BY link.claim_id LIMIT %s",
                (
                    PostgresPayloadRepository.scope_id(owner_id, scope), owner_id,
                    scope.application_id, scope.workspace_id, str(evidence_id), limit,
                ),
            ).fetchall()
        return tuple(_model(EntityClaim, row[0]) for row in rows)

    def create(self, result: DecisionResult) -> DecisionResult:
        result = scoped_record(result)
        decision = result.decision
        scope = _scope(decision)
        if len(result.entities) + len(result.aliases) + len(result.claims) + len(result.matches) + len(result.evaluations) + 2 > 450:
            raise DecisionError("decision_write_limit", 422)
        try:
            with self.database.transaction() as connection:
                scope_id = _ensure_namespace(connection, decision.owner_id, scope)
                row = connection.execute(
                    "SELECT payload FROM decision_snapshots WHERE scope_id=%s AND record_id=%s "
                    "AND owner_id=%s FOR UPDATE",
                    (scope_id, str(decision.id), decision.owner_id),
                ).fetchone()
                if row is not None:
                    old = DecisionSnapshot.model_validate(row[0])
                    if old.request_fingerprint != decision.request_fingerprint:
                        raise DecisionError("idempotency_conflict")
                    return self.get(decision.owner_id, decision.id)

                for entity in result.entities:
                    family = "canonical_entities"
                    current = connection.execute(
                        f"SELECT payload FROM {family} WHERE scope_id=%s AND record_id=%s FOR UPDATE",
                        (PostgresPayloadRepository.scope_id(entity.owner_id, scope), str(entity.id)),
                    ).fetchone()
                    if current is not None:
                        old = CanonicalEntity.model_validate(current[0])
                        if (
                            old.owner_id != entity.owner_id or old.entity_type != entity.entity_type
                            or old.identifiers != entity.identifiers
                        ):
                            raise DecisionError("entity_identity_conflict")
                for claim in result.claims:
                    current = connection.execute(
                        "SELECT payload FROM entity_claims WHERE scope_id=%s AND record_id=%s FOR UPDATE",
                        (PostgresPayloadRepository.scope_id(claim.owner_id, scope), str(claim.id)),
                    ).fetchone()
                    if current is not None and scope_normalized_dump(
                        EntityClaim.model_validate(current[0])
                    ) != scope_normalized_dump(claim):
                        raise DecisionError("claim_immutability_conflict")

                records: Iterable = (
                    *result.entities, *result.aliases, *result.claims, *result.matches,
                    *result.evaluations, decision, result.evidence_snapshot,
                )
                for record in records:
                    family = _FAMILY_FOR_RECORD[type(record)]
                    owner = decision.owner_id if isinstance(record, CandidateEvaluation) else record.owner_id
                    exists = connection.execute(
                        f"SELECT payload FROM {family} WHERE scope_id=%s AND record_id=%s FOR UPDATE",
                        (PostgresPayloadRepository.scope_id(owner, scope), str(record.id)),
                    ).fetchone()
                    if exists is None:
                        _insert(connection, record, owner_id=owner)
                    else:
                        old_payload = exists[0]
                        new_payload = _data(record, owner_id=owner if isinstance(record, CandidateEvaluation) else None)
                        if old_payload != new_payload:
                            if isinstance(record, EntityClaim):
                                raise DecisionError("claim_immutability_conflict")
                            raise DecisionError("decision_record_conflict")
                    if isinstance(record, EntityClaim):
                        for ref in record.evidence_refs:
                            connection.execute(
                                "INSERT INTO entity_claim_evidence(scope_id,owner_id,application_id,workspace_id,"
                                "evidence_id,entity_id,claim_id) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                                "ON CONFLICT DO NOTHING",
                                (
                                    PostgresPayloadRepository.scope_id(owner, scope), owner,
                                    scope.application_id, scope.workspace_id, str(ref.evidence_id),
                                    str(record.entity_id), str(record.id),
                                ),
                            )
        except Exception as error:
            if error.__class__.__name__ == "UniqueViolation":
                existing = self.get(decision.owner_id, decision.id)
                if existing.decision.request_fingerprint == decision.request_fingerprint:
                    return existing
            raise
        return result

    def get(self, owner_id: str, decision_id: UUID) -> DecisionResult:
        scope = current_application_scope()
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM decision_snapshots WHERE scope_id=%s AND record_id=%s "
                "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
                (scope_id, str(decision_id), owner_id, scope.application_id, scope.workspace_id),
            ).fetchone()
            if row is None:
                raise ResourceNotFoundError("decision not found")
            decision = DecisionSnapshot.model_validate(row[0])
            evidence_row = connection.execute(
                "SELECT payload FROM decision_evidence_snapshots WHERE scope_id=%s AND record_id=%s "
                "AND owner_id=%s",
                (scope_id, str(decision.evidence_snapshot_id), owner_id),
            ).fetchone()
            if evidence_row is None:
                raise StorageUnavailableError("decision evidence snapshot unavailable")
            evidence = EvidenceSnapshot.model_validate(evidence_row[0])
            eval_rows = connection.execute(
                "SELECT payload FROM candidate_evaluations WHERE scope_id=%s AND owner_id=%s "
                "AND payload->>'decision_id'=%s ORDER BY created_at,record_id",
                (scope_id, owner_id, str(decision_id)),
            ).fetchall()
            evaluations = tuple(_model(CandidateEvaluation, item[0]) for item in eval_rows)
            entities = []
            for entity_id in decision.candidate_ids:
                entity = self._get_record(
                    connection, "canonical_entities", CanonicalEntity, owner_id, scope,
                    entity_id, allow_shared=True,
                )
                entities.append(entity)
            claim_ids = sorted({claim_id for item in evaluations for claim_id in item.claim_ids}, key=str)
            claims = tuple(
                self._get_record(connection, "entity_claims", EntityClaim, owner_id, scope, item)
                for item in claim_ids
            )
            aliases = self._list_aliases(connection, owner_id, scope, tuple(item.id for item in entities))
            if decision.alias_ids is not None:
                expected = set(decision.alias_ids)
                aliases = tuple(item for item in aliases if item.id in expected)
                if {item.id for item in aliases} != expected:
                    raise StorageUnavailableError("decision alias unavailable")
            match_rows = connection.execute(
                "SELECT payload FROM entity_matches WHERE scope_id=%s AND owner_id=%s "
                "AND payload->>'decision_id'=%s ORDER BY created_at,record_id",
                (scope_id, owner_id, str(decision_id)),
            ).fetchall()
            matches = tuple(_model(EntityMatch, item[0]) for item in match_rows)
        if not scope_matches(decision, scope) or not scope_matches(evidence, scope):
            raise ResourceNotFoundError("decision not found")
        if any(item.entity_id not in decision.candidate_ids for item in evaluations):
            raise StorageUnavailableError("decision evaluation invalid")
        return DecisionResult(
            application_id=decision.application_id, workspace_id=decision.workspace_id,
            scope_version=decision.scope_version, decision=decision,
            recommendation=decision.recommendation, evidence_snapshot=evidence,
            entities=tuple(entities), claims=claims, aliases=aliases, matches=matches,
            evaluations=evaluations,
        )

    @staticmethod
    def _get_record(connection, family, record_type, owner_id, scope, record_id, *, allow_shared=False):
        owners = (owner_id, "*") if allow_shared else (owner_id,)
        scopes = [PostgresPayloadRepository.scope_id(value, scope) for value in owners]
        row = connection.execute(
            f"SELECT payload FROM {family} WHERE scope_id=ANY(%s) AND record_id=%s "
            "AND owner_id=ANY(%s) AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
            (scopes, str(record_id), list(owners), scope.application_id, scope.workspace_id),
        ).fetchone()
        if row is None:
            raise StorageUnavailableError("decision child record unavailable")
        record = _model(record_type, row[0])
        if not scope_matches(record, scope):
            raise ResourceNotFoundError("decision not found")
        return record

    @staticmethod
    def _list_aliases(connection, owner_id, scope, entity_ids):
        if not entity_ids:
            return ()
        owners = (owner_id, "*")
        scopes = [PostgresPayloadRepository.scope_id(value, scope) for value in owners]
        rows = connection.execute(
            "SELECT payload FROM entity_aliases WHERE scope_id=ANY(%s) AND owner_id=ANY(%s) "
            "AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
            "AND payload->>'entity_id'=ANY(%s) ORDER BY record_id",
            (scopes, list(owners), scope.application_id, scope.workspace_id,
             [str(item) for item in entity_ids]),
        ).fetchall()
        return tuple(_model(EntityAlias, row[0]) for row in rows)
