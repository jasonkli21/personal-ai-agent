"""Versioned contracts for thin, evidence-backed domain modules."""

import json
from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from personal_ai.decisions.contracts import (
    Constraint,
    DecisionCreateRequest,
    DecisionRecord,
    FeatureScore,
    PolicyVersions,
    Preference,
    ScopedDecisionRecord,
)
from personal_ai.entities.research import TypedValue


class DomainContractError(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)


class DomainField(DecisionRecord):
    """A registered display field; modules cannot introduce anonymous fields."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=100)
    label: str = Field(min_length=1, max_length=100)
    value_kinds: tuple[str, ...] = Field(min_length=1, max_length=10)
    mutable: bool = True
    required_for_recommendation: bool = False


class DomainRegistration(DecisionRecord):
    schema_version: Literal["domain-module-v1"] = "domain-module-v1"
    domain_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,40}$")
    supported_entity_types: tuple[str, ...] = Field(min_length=1, max_length=8)
    supported_constraints: tuple[str, ...] = Field(max_length=40)
    supported_features: tuple[str, ...] = Field(max_length=20)
    source_policy_version: str = Field(min_length=1, max_length=100)
    field_schema_version: str = Field(min_length=1, max_length=100)
    feature_policy_version: str = Field(min_length=1, max_length=100)
    fields: tuple[DomainField, ...] = Field(min_length=1, max_length=32)
    source_adapters: tuple[str, ...] = Field(min_length=1, max_length=12)
    privacy_policy: str = Field(min_length=1, max_length=500)
    retention_policy: str = Field(min_length=1, max_length=500)
    enabled: bool = False

    @model_validator(mode="after")
    def registration_is_unambiguous(self):
        for values in (
            self.supported_entity_types,
            self.supported_constraints,
            self.supported_features,
            self.source_adapters,
        ):
            if len(values) != len(set(values)):
                raise ValueError("domain registration values must be unique")
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("domain field names must be unique")
        if set(self.supported_features) - {field.key for field in self.fields}:
            raise ValueError("every domain feature must have a registered field")
        return self


class ProviderObservationExtension(ScopedDecisionRecord):
    """Provider identity and policy metadata attached to core evidence."""

    source_observation_id: UUID
    evidence_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,80}$")
    provider_object_id: str | None = Field(default=None, max_length=300)
    entity_kind: str = Field(min_length=1, max_length=100)
    adapter_version: str = Field(min_length=1, max_length=100)
    attribution: str = Field(min_length=1, max_length=500)
    policy_url: str | None = Field(default=None, max_length=2048)
    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    observed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def provider_source_is_valid(self):
        if self.expires_at <= self.observed_at:
            raise ValueError("invalid provider observation freshness")
        from personal_ai.search.policy import canonical_url

        if canonical_url(self.url) != self.url:
            raise ValueError("provider URL must be canonical and public")
        if self.policy_url is not None and canonical_url(self.policy_url) != self.policy_url:
            raise ValueError("provider policy URL must be canonical and public")
        return self


class DomainClaimExtension(ScopedDecisionRecord):
    """Typed domain vocabulary linked to an immutable Phase 6 claim."""

    claim_id: UUID
    domain_id: str
    attribute: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=100)
    typed_value: TypedValue
    original_value: str = Field(min_length=1, max_length=500)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=12)
    observed_at: datetime
    expires_at: datetime
    schema_version: Literal["domain-claim-v1"] = "domain-claim-v1"

    @model_validator(mode="after")
    def claim_is_fresh(self):
        if self.expires_at <= self.observed_at:
            raise ValueError("invalid domain claim freshness")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate domain claim evidence")
        return self


class ComparisonSource(ScopedDecisionRecord):
    evidence_id: UUID
    source_observation_id: UUID
    url: str
    title: str | None = None
    attribution: str | None = None
    policy_url: str | None = None
    observed_at: datetime
    expires_at: datetime


class ComparisonCell(ScopedDecisionRecord):
    field: str
    label: str
    value: str | None = None
    status: Literal["verified", "conflicting", "stale", "missing", "unverified", "derived"]
    note: str | None = Field(default=None, max_length=300)
    claim_ids: tuple[UUID, ...] = Field(default=(), max_length=40)
    sources: tuple[ComparisonSource, ...] = Field(default=(), max_length=24)


class DomainComparisonRow(ScopedDecisionRecord):
    candidate_id: UUID
    name: str = Field(min_length=1, max_length=300)
    eligible: bool
    selected: bool
    rank: int | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    exclusion_reasons: tuple[str, ...] = Field(default=(), max_length=30)
    cells: tuple[ComparisonCell, ...] = Field(max_length=32)
    features: tuple[FeatureScore, ...] = Field(default=(), max_length=20)


class DomainComparisonSnapshot(ScopedDecisionRecord):
    id: UUID
    decision_id: UUID
    owner_id: str
    domain_id: str
    candidate_ids: tuple[UUID, ...] = Field(max_length=24)
    field_schema_version: str
    feature_policy_version: str
    decision_policy_versions: PolicyVersions
    constraints: tuple[Constraint, ...] = Field(default=(), max_length=30)
    preferences: tuple[Preference, ...] = Field(default=(), max_length=20)
    rendered_at: datetime
    state: Literal["recommended", "eligible_unranked", "research_needed", "no_verified_match"]
    rows: tuple[DomainComparisonRow, ...] = Field(max_length=24)
    available_filters: tuple[str, ...] = Field(default=("eligible", "fresh", "conflicts"), max_length=12)

    @model_validator(mode="after")
    def snapshot_is_bounded(self):
        if self.candidate_ids != tuple(row.candidate_id for row in self.rows):
            raise ValueError("comparison rows must match candidate IDs")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("duplicate comparison candidate")
        return self


class DomainComparisonCreateRequest(DecisionRecord):
    schema_version: Literal["domain-comparison-v1"] = "domain-comparison-v1"
    decision: DecisionCreateRequest
    provider_observations: tuple[ProviderObservationExtension, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def evidence_extensions_match_request(self):
        ids = [item.source_observation_id for item in self.provider_observations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate provider observation")
        if self.decision.supplied_evidence:
            evidence = {item.evidence_id: item for item in self.decision.supplied_evidence}
            for extension in self.provider_observations:
                source = evidence.get(extension.evidence_id)
                if source is None or (
                    source.source_observation_id != extension.source_observation_id
                    or source.owner_id != extension.owner_id
                    or source.url != extension.url
                    or source.observed_at != extension.observed_at
                    or source.expires_at != extension.expires_at
                ):
                    raise ValueError("provider observation does not match supplied evidence")
        return self


class DomainLookupRequest(DecisionRecord):
    schema_version: Literal["domain-lookup-v1"] = "domain-lookup-v1"
    idempotency_key: UUID
    query: str = Field(min_length=1, max_length=300)
    constraints: tuple[Constraint, ...] = Field(default=(), max_length=30)
    preferences: tuple[Preference, ...] = Field(default=(), max_length=20)
    max_results: int = Field(default=8, ge=1, le=12)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value):
        value = " ".join(value.split())
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("invalid domain query")
        return value

    def fingerprint(self, owner_id: str, domain_id: str) -> str:
        """Hash normalized lookup inputs without retaining the submitted query."""
        payload = {
            "owner_id": owner_id,
            "domain_id": domain_id,
            "request": self.model_dump(mode="json", exclude={"idempotency_key"}),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode()).hexdigest()


class DomainLookupReservation(ScopedDecisionRecord):
    """Durable, fenced idempotency state for provider-backed lookups."""

    id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    domain_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,40}$")
    idempotency_key: UUID
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    fence_token: UUID
    state: Literal["reserved", "completed", "failed", "uncertain"] = "reserved"
    comparison_id: UUID | None = None
    failure_kind: Literal["provider", "contract"] | None = None
    failure_code: str | None = Field(default=None, min_length=1, max_length=100)
    failure_status: int | None = Field(default=None, ge=400, le=599)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def state_payload_is_consistent(self):
        has_failure = any((self.failure_kind, self.failure_code, self.failure_status))
        if self.state == "completed":
            if self.comparison_id is None or has_failure:
                raise ValueError("completed lookup requires only a comparison mapping")
        elif self.state == "failed":
            if self.comparison_id is not None or not all((self.failure_kind, self.failure_code, self.failure_status)):
                raise ValueError("failed lookup requires a safe failure result")
        elif self.state in {"reserved", "uncertain"} and (self.comparison_id is not None or has_failure):
            raise ValueError("active or uncertain lookup cannot expose a result")
        if self.updated_at < self.created_at:
            raise ValueError("invalid lookup reservation timestamps")
        return self


class DomainFixtureDescription(DecisionRecord):
    fixture_id: str = Field(pattern=r"^[a-z0-9-]{2,100}$")
    domain_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)


class DomainComparisonResult(ScopedDecisionRecord):
    schema_version: Literal["domain-comparison-v1"] = "domain-comparison-v1"
    registration: DomainRegistration
    comparison: DomainComparisonSnapshot
    provider_observations: tuple[ProviderObservationExtension, ...] = Field(max_length=24)
    domain_claims: tuple[DomainClaimExtension, ...] = Field(max_length=200)


class DomainComparisonLookupRequest(DecisionRecord):
    decision_id: UUID


class DomainInspection(DecisionRecord):
    schema_version: Literal["domain-inspection-v1"] = "domain-inspection-v1"
    comparison_id: UUID
    domain_id: str
    source_policy_version: str
    feature_policy_version: str
    provider_names: tuple[str, ...] = Field(default=(), max_length=12)
    observation_ids: tuple[UUID, ...] = Field(default=(), max_length=24)
    claim_ids: tuple[UUID, ...] = Field(default=(), max_length=200)
