"""Versioned neutral inputs and persisted outputs for decision support."""

from datetime import datetime
from hashlib import sha256
from math import isfinite
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from personal_ai.entities.research import (
    CanonicalEntity,
    DecisionRecord,
    EntityAlias,
    EntityClaim,
    EntityMatch,
    EvidenceReference,
    TypedValue,
)


class SuppliedEvidence(DecisionRecord):
    """Evidence supplied without a Phase 5 session; still requires attribution."""

    evidence_id: UUID
    source_observation_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    origin: Literal["supplied"] = "supplied"
    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    observed_at: datetime
    expires_at: datetime
    expiry_policy: Literal["supplied"] = "supplied"
    content_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    passage: str = Field(min_length=1, max_length=1200, exclude=True)

    @model_validator(mode="after")
    def source_is_valid(self):
        # Reuse Phase 5's public URL policy at this untrusted input boundary.
        from personal_ai.search.policy import canonical_url

        if self.expires_at <= self.observed_at:
            raise ValueError("invalid source freshness")
        if canonical_url(self.url) != self.url:
            raise ValueError("source URL must be canonical and public")
        if " ".join(self.passage.split()) == "":
            raise ValueError("empty evidence passage")
        if sha256(" ".join(self.passage.split()).encode()).hexdigest() != self.content_fingerprint:
            raise ValueError("evidence fingerprint mismatch")
        return self

    def reference(self) -> EvidenceReference:
        return EvidenceReference.model_validate(
            self.model_dump(exclude={"passage"})
        )


class ClaimProposal(DecisionRecord):
    attribute: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")
    typed_value: TypedValue
    original_value: str = Field(min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=30)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=12)
    scope: str | None = Field(default=None, max_length=100)


class Candidate(DecisionRecord):
    entity_type: Literal["object", "place", "organization", "other"]
    canonical_name: str = Field(min_length=1, max_length=300)
    identifiers: dict[str, str] = Field(default_factory=dict, max_length=12)
    aliases: tuple[str, ...] = Field(default=(), max_length=8)
    claims: tuple[ClaimProposal, ...] = Field(default=(), max_length=20)

    @field_validator("canonical_name", "aliases")
    @classmethod
    def safe_text(cls, value):
        values = (value,) if isinstance(value, str) else value
        if any(not item.strip() or any(ord(char) < 32 for char in item) for item in values):
            raise ValueError("invalid candidate text")
        return value


# The request boundary calls these proposals; once provenance and identity are
# validated the same neutral record is a decision candidate.
CandidateProposal = Candidate


ConstraintOperator = Literal[
    "exact", "maximum", "minimum", "range", "set", "geospatial", "date_window", "availability"
]


class Constraint(DecisionRecord):
    id: UUID
    attribute: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")
    operator: ConstraintOperator
    value: TypedValue | None = None
    upper_value: TypedValue | None = None
    allowed_values: tuple[TypedValue, ...] = Field(default=(), max_length=20)
    radius_km: float | None = Field(default=None, gt=0, le=20_000)
    required: bool = True
    missing_policy: Literal["fail_closed", "allow_unknown"] = "fail_closed"
    source: Literal["user", "system"] = "user"
    source_record_id: str | None = Field(default=None, max_length=200)
    scope: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def operator_shape(self):
        if self.required and self.missing_policy != "fail_closed":
            raise ValueError("required constraints must fail closed")
        if (
            self.operator in {"exact", "maximum", "minimum", "availability", "geospatial", "date_window"}
            and self.value is None
        ):
            raise ValueError("constraint value required")
        if self.operator == "range":
            if self.value is None or self.upper_value is None:
                raise ValueError("range requires two values")
        elif self.upper_value is not None:
            raise ValueError("upper_value is only valid for range")
        if self.operator == "set" and not self.allowed_values:
            raise ValueError("set constraint requires values")
        if self.operator != "set" and self.allowed_values:
            raise ValueError("allowed_values is only valid for set")
        if self.operator == "geospatial":
            if not isinstance(self.value, dict) and getattr(self.value, "kind", None) != "location":
                raise ValueError("geospatial constraint requires a location")
            if self.radius_km is None:
                raise ValueError("geospatial constraint requires a radius")
        elif self.radius_km is not None:
            raise ValueError("radius_km is only valid for geospatial")
        if self.operator == "date_window" and getattr(self.value, "kind", None) != "date_window":
            raise ValueError("date-window constraint requires a date window")
        if self.operator == "availability" and getattr(self.value, "kind", None) != "availability":
            raise ValueError("availability constraint requires an availability value")
        return self


class Preference(DecisionRecord):
    attribute: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")
    target: TypedValue
    weight: float = Field(default=1, ge=0, le=1)
    source: Literal["user"] = "user"
    scope: str | None = Field(default=None, max_length=100)


class DecisionCreateRequest(DecisionRecord):
    schema_version: Literal["decision-v1"] = "decision-v1"
    idempotency_key: UUID
    research_session_id: UUID | None = None
    candidates: tuple[Candidate, ...] = Field(default=(), max_length=24)
    constraints: tuple[Constraint, ...] = Field(default=(), max_length=30)
    preferences: tuple[Preference, ...] = Field(default=(), max_length=20)
    supplied_evidence: tuple[SuppliedEvidence, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def evidence_path_is_clear(self):
        if self.research_session_id and self.supplied_evidence:
            raise ValueError("choose one evidence source path")
        if not self.research_session_id and not self.supplied_evidence and any(
            candidate.claims for candidate in self.candidates
        ):
            raise ValueError("claims require explicit evidence")
        ids = [item.evidence_id for item in self.supplied_evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence id")
        attributes = {
            item.attribute for item in self.constraints
        } | {item.attribute for item in self.preferences}
        if len(attributes) > 30:
            raise ValueError("too many distinct comparison attributes")
        constraint_ids = [item.id for item in self.constraints]
        if len(constraint_ids) != len(set(constraint_ids)):
            raise ValueError("duplicate constraint id")
        return self

    def fingerprint(self, owner_id: str) -> str:
        from hashlib import sha256

        data = self.model_dump(mode="json", exclude={"idempotency_key", "supplied_evidence"})
        supplied = [
            {**item.reference().model_dump(mode="json"), "passage": item.passage}
            for item in self.supplied_evidence
        ]
        payload = {"owner_id": owner_id, "request": data, "supplied_evidence": supplied}
        import json

        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EvidenceSnapshot(DecisionRecord):
    id: UUID
    decision_id: UUID
    owner_id: str
    evidence_refs: tuple[EvidenceReference, ...] = Field(max_length=250)
    policy_version: Literal["evidence-snapshot-v1"] = "evidence-snapshot-v1"
    created_at: datetime

    @model_validator(mode="after")
    def evidence_is_owner_scoped(self):
        if any(ref.owner_id != self.owner_id for ref in self.evidence_refs):
            raise ValueError("foreign owner evidence reference")
        source_pairs = {
            (ref.evidence_id, ref.source_observation_id) for ref in self.evidence_refs
        }
        if len(source_pairs) != len(self.evidence_refs):
            raise ValueError("duplicate source reference")
        return self


class RankingPolicy(DecisionRecord):
    policy_version: Literal["rank-v1"] = "rank-v1"
    feature_weights: dict[str, float]
    normalization: Literal["weighted_mean-v1"] = "weighted_mean-v1"
    tie_breakers: tuple[Literal["score_desc", "normalized_name_asc", "entity_id_asc"], ...] = (
        "score_desc",
        "normalized_name_asc",
        "entity_id_asc",
    )

    @field_validator("feature_weights")
    @classmethod
    def bounded_finite_weights(cls, value):
        if any(not isfinite(weight) or weight < 0 or weight > 1 for weight in value.values()):
            raise ValueError("ranking feature weights must be finite and bounded")
        return value


class PolicyVersions(DecisionRecord):
    identity: Literal["identity-v1"] = "identity-v1"
    # Keep v1 readable so persisted historical snapshots retain their policy.
    resolution: Literal["resolve-v1", "resolve-v2"] = "resolve-v2"
    claim_verification: Literal["claim-verification-v1", "claim-verification-v2"] = "claim-verification-v1"
    constraints: Literal["constraint-v1"] = "constraint-v1"
    ranking: Literal["rank-v1"] = "rank-v1"
    # Optional, additive Phase 7 feature policy. `rank-v1` remains the shared
    # hard-filter/soft-rank contract; this records a registered domain feature
    # extension used for that decision.
    domain_features: str | None = Field(default=None, max_length=100)
    evidence_snapshot: Literal["evidence-snapshot-v1"] = "evidence-snapshot-v1"
    entity_match_threshold: float = Field(ge=0, le=1)
    ranking_policy: RankingPolicy
    max_candidates: int = Field(ge=0, le=24)
    max_comparison_rows: int = Field(ge=0, le=24)


class Recommendation(DecisionRecord):
    status: Literal["recommended", "eligible_unranked", "research_needed", "no_verified_match"]
    selected_entity_id: UUID | None = None
    candidate_order: tuple[UUID, ...] = Field(default=(), max_length=24)
    supporting_claim_ids: tuple[UUID, ...] = Field(default=(), max_length=40)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=250)
    explanation_codes: tuple[str, ...] = Field(default=(), max_length=40)

    @model_validator(mode="after")
    def selection_has_provenance(self):
        if self.selected_entity_id is not None:
            if self.status != "recommended" or self.selected_entity_id not in self.candidate_order:
                raise ValueError("recommendation selection is inconsistent")
            if not self.supporting_claim_ids or not self.evidence_ids:
                raise ValueError("recommendation requires claim and evidence provenance")
        elif self.status == "recommended":
            raise ValueError("recommended state requires a selected entity")
        return self


class DecisionSnapshot(DecisionRecord):
    id: UUID
    owner_id: str
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    research_session_id: UUID | None = None
    constraint_set: tuple[Constraint, ...] = Field(max_length=30)
    preferences: tuple[Preference, ...] = Field(max_length=20)
    candidate_ids: tuple[UUID, ...] = Field(max_length=24)
    # Older snapshots did not record alias membership. New snapshots freeze it
    # so later identity evidence cannot change a historical decision response.
    alias_ids: tuple[UUID, ...] | None = Field(default=None, max_length=192)
    evidence_snapshot_id: UUID
    policy_versions: PolicyVersions
    recommendation: Recommendation
    state: Literal["recommended", "eligible_unranked", "research_needed", "no_verified_match"]
    selected_entity_id: UUID | None = None
    created_at: datetime

    @model_validator(mode="after")
    def state_and_selection(self):
        if self.selected_entity_id is not None and self.selected_entity_id not in self.candidate_ids:
            raise ValueError("selection must reference a candidate")
        if (self.state == "recommended") != (self.selected_entity_id is not None):
            raise ValueError("recommendation state and selection disagree")
        if (
            self.recommendation.status != self.state
            or self.recommendation.selected_entity_id != self.selected_entity_id
        ):
            raise ValueError("snapshot recommendation does not match decision state")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("duplicate candidate entity")
        if self.alias_ids is not None and len(set(self.alias_ids)) != len(self.alias_ids):
            raise ValueError("duplicate decision alias")
        return self


class AttributeStatus(DecisionRecord):
    attribute: str
    scope: str | None = None
    status: Literal["verified", "conflicting", "stale", "missing", "unverified"]
    claim_ids: tuple[UUID, ...] = Field(default=(), max_length=40)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=250)
    reason: str = Field(min_length=1, max_length=100)


class ConstraintOutcome(DecisionRecord):
    constraint_id: UUID
    attribute: str
    outcome: Literal["pass", "fail", "unknown"]
    reason: str = Field(min_length=1, max_length=100)
    claim_ids: tuple[UUID, ...] = Field(default=(), max_length=40)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=250)


class FeatureScore(DecisionRecord):
    name: str
    value: float | None = Field(ge=0, le=1)
    weight: float = Field(ge=0, le=1)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=250)
    missing_treatment: Literal["zero", "omit"] = "zero"


class CandidateEvaluation(DecisionRecord):
    id: UUID
    decision_id: UUID
    entity_id: UUID
    identity_outcome: Literal["matched", "review", "no_match"] = "no_match"
    identity_confidence: float = Field(default=0, ge=0, le=1)
    identity_candidate_entity_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    claim_ids: tuple[UUID, ...] = Field(default=(), max_length=40)
    eligibility: bool
    attribute_statuses: tuple[AttributeStatus, ...] = Field(default=(), max_length=40)
    constraint_outcomes: tuple[ConstraintOutcome, ...] = Field(default=(), max_length=30)
    feature_values: tuple[FeatureScore, ...] = Field(default=(), max_length=30)
    score: float | None = Field(default=None, ge=0, le=1)
    rank: int | None = Field(default=None, ge=1)
    exclusion_reasons: tuple[str, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def eligibility_and_rank(self):
        if self.eligibility and self.exclusion_reasons:
            raise ValueError("eligible candidate cannot have exclusion reasons")
        if not self.eligibility and self.rank is not None:
            raise ValueError("ineligible candidate cannot be ranked")
        if self.eligibility and self.identity_outcome == "review":
            raise ValueError("ambiguous identity cannot be eligible")
        return self


class DecisionResult(DecisionRecord):
    schema_version: Literal["decision-v1"] = "decision-v1"
    decision: DecisionSnapshot
    recommendation: Recommendation
    evidence_snapshot: EvidenceSnapshot
    entities: tuple[CanonicalEntity, ...]
    claims: tuple[EntityClaim, ...]
    aliases: tuple[EntityAlias, ...]
    matches: tuple[EntityMatch, ...]
    evaluations: tuple[CandidateEvaluation, ...]

    @model_validator(mode="after")
    def provenance_is_closed(self):
        entity_ids = {entity.id for entity in self.entities}
        if entity_ids != set(self.decision.candidate_ids):
            raise ValueError("decision entities do not match candidate ids")
        if self.evidence_snapshot.id != self.decision.evidence_snapshot_id:
            raise ValueError("evidence snapshot reference mismatch")
        if self.evidence_snapshot.owner_id != self.decision.owner_id:
            raise ValueError("evidence snapshot owner mismatch")
        if (
            self.recommendation.status != self.decision.state
            or self.recommendation.selected_entity_id != self.decision.selected_entity_id
            or self.recommendation != self.decision.recommendation
        ):
            raise ValueError("recommendation does not match persisted decision")
        if any(
            entity.owner_scope != "shared" and entity.owner_id != self.decision.owner_id
            for entity in self.entities
        ):
            raise ValueError("foreign owner entity")
        evidence_source_pairs = {
            (ref.evidence_id, ref.source_observation_id)
            for ref in self.evidence_snapshot.evidence_refs
        }
        claims_by_id = {claim.id: claim for claim in self.claims}
        for claim in self.claims:
            if claim.owner_id != self.decision.owner_id or claim.entity_id not in entity_ids or any(
                (ref.evidence_id, ref.source_observation_id) not in evidence_source_pairs
                for ref in claim.evidence_refs
            ):
                raise ValueError("claim provenance is not in the decision snapshot")
        if any(
            alias.entity_id not in entity_ids
            or (
                alias.owner_id != self.decision.owner_id
                and not (
                    alias.owner_id == "*"
                    and next(entity for entity in self.entities if entity.id == alias.entity_id).owner_scope == "shared"
                )
            )
            for alias in self.aliases
        ):
            raise ValueError("alias provenance is not owner-scoped")
        if self.decision.alias_ids is not None and {alias.id for alias in self.aliases} != set(self.decision.alias_ids):
            raise ValueError("aliases do not match the decision snapshot")
        if any(
            evaluation.entity_id not in entity_ids
            or any(claim_id not in claims_by_id for claim_id in evaluation.claim_ids)
            for evaluation in self.evaluations
        ):
            raise ValueError("candidate evaluation has unknown provenance")
        if {evaluation.entity_id for evaluation in self.evaluations} != entity_ids:
            raise ValueError("every candidate requires one evaluation")
        if (
            len(set(self.recommendation.candidate_order)) != len(self.recommendation.candidate_order)
            or not set(self.recommendation.candidate_order).issubset(entity_ids)
        ):
            raise ValueError("recommendation order has an unknown candidate")
        if self.decision.selected_entity_id is not None:
            evaluation = next(
                item for item in self.evaluations
                if item.entity_id == self.decision.selected_entity_id
            )
            if not evaluation.eligibility or not evaluation.claim_ids or not any(
                claims_by_id[claim_id].evidence_refs for claim_id in evaluation.claim_ids
            ):
                raise ValueError("recommendation requires eligible claim and evidence provenance")
            if (
                self.recommendation.candidate_order[0] != evaluation.entity_id
                or not set(self.recommendation.supporting_claim_ids).issubset(evaluation.claim_ids)
                or not self.recommendation.supporting_claim_ids
            ):
                raise ValueError("recommendation omits selected candidate provenance")
            claim_evidence_ids = {
                ref.evidence_id
                for claim_id in self.recommendation.supporting_claim_ids
                for ref in claims_by_id[claim_id].evidence_refs
            }
            if claim_evidence_ids != set(self.recommendation.evidence_ids):
                raise ValueError("recommendation evidence provenance does not match its claims")
        if any(
            match.owner_id != self.decision.owner_id or match.decision_id != self.decision.id
            for match in self.matches
        ):
            raise ValueError("foreign owner entity match")
        return self


class DecisionInspection(DecisionRecord):
    schema_version: Literal["decision-inspection-v1"] = "decision-inspection-v1"
    decision_id: UUID
    state: str
    policy_versions: PolicyVersions
    selected_entity_id: UUID | None
    selected: tuple[CandidateEvaluation, ...]
    excluded: tuple[CandidateEvaluation, ...]
    matches: tuple[EntityMatch, ...]
    evidence_refs: tuple[EvidenceReference, ...]
