"""Bounded, privacy-safe contracts for cross-endpoint task evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_ai.routing.contracts import CounterConfidence, EndpointRef
from personal_ai.routing.phase21 import EvaluationQualityGate, QualityEvidence

_SAFE_ID = r"^[A-Za-z0-9@][A-Za-z0-9._:/@+_-]{0,199}$"
_REVISION = r"^[0-9a-f]{7,64}(-working-tree)?$"


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class EvaluationMessage(FrozenContract):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


class ExpectedClaim(FrozenContract):
    claim_id: str = Field(pattern=_SAFE_ID)
    value: str = Field(min_length=1, max_length=500)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=8)


class OutputSchema(FrozenContract):
    required_fields: tuple[str, ...] = Field(min_length=1, max_length=32)
    field_types: dict[str, Literal["string", "number", "integer", "array", "object", "boolean"]]

    @model_validator(mode="after")
    def schema_is_coherent(self):
        if len(set(self.required_fields)) != len(self.required_fields):
            raise ValueError("evaluation_schema_duplicate_field")
        if not set(self.required_fields).issubset(self.field_types):
            raise ValueError("evaluation_schema_field_type_missing")
        return self


class HardConstraint(FrozenContract):
    path: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    operator: Literal["lte", "gte", "equals", "not_equals", "not_contains"]
    value: str | float | int | bool

    @model_validator(mode="after")
    def comparison_value_matches_operator(self):
        if self.operator in {"lte", "gte"} and (
            not isinstance(self.value, (int, float)) or isinstance(self.value, bool)
        ):
            raise ValueError("evaluation_constraint_numeric_value_required")
        if self.operator == "not_contains" and not isinstance(self.value, str):
            raise ValueError("evaluation_constraint_string_value_required")
        return self


class EvaluationFixture(FrozenContract):
    """Synthetic input and deterministic rubric; fixture text is never persisted."""

    fixture_id: str = Field(pattern=_SAFE_ID)
    data_classification: Literal["synthetic_public"]
    task_profile_id: str = Field(pattern=_SAFE_ID)
    task_profile_version: int = Field(ge=1, le=2_147_483_647)
    policy_version: str = Field(pattern=_SAFE_ID)
    messages: tuple[EvaluationMessage, ...] = Field(min_length=1, max_length=8)
    source_ids: tuple[str, ...] = Field(default=(), max_length=32)
    expected_claims: tuple[ExpectedClaim, ...] = Field(default=(), max_length=32)
    required_terms: tuple[str, ...] = Field(default=(), max_length=32)
    forbidden_literals: tuple[str, ...] = Field(default=(), max_length=32)
    output_schema_id: str = Field(pattern=_SAFE_ID)
    output_schema: OutputSchema
    hard_constraints: tuple[HardConstraint, ...] = Field(default=(), max_length=16)
    held_out: bool = True
    reference_output: dict[str, object]

    @field_validator("source_ids", "required_terms", "forbidden_literals")
    @classmethod
    def values_are_unique_and_bounded(cls, values):
        if len(set(values)) != len(values) or any(not value or len(value) > 200 for value in values):
            raise ValueError("evaluation_fixture_values_invalid")
        return values

    @model_validator(mode="after")
    def fixture_is_safe(self):
        if not self.held_out:
            raise ValueError("evaluation_fixture_must_be_held_out")
        if any(claim.source_ids and not set(claim.source_ids).issubset(self.source_ids)
               for claim in self.expected_claims):
            raise ValueError("evaluation_fixture_claim_source_invalid")
        if len({claim.claim_id for claim in self.expected_claims}) != len(self.expected_claims):
            raise ValueError("evaluation_fixture_claim_duplicate")
        if len(str(self.reference_output).encode("utf-8")) > 16_384:
            raise ValueError("evaluation_fixture_reference_output_too_large")
        return self

    @property
    def case_identity_sha256(self) -> str:
        import hashlib
        import json

        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class EvaluationMetrics(FrozenContract):
    schema_validity: float = Field(ge=0, le=1)
    citation_precision: float = Field(ge=0, le=1)
    citation_coverage: float = Field(ge=0, le=1)
    provenance: float = Field(ge=0, le=1)
    answer_support: float = Field(ge=0, le=1)
    answer_relevance: float = Field(ge=0, le=1)
    hard_constraint_satisfaction: float = Field(ge=0, le=1)
    privacy: float = Field(ge=0, le=1)
    overall_score: float = Field(ge=0, le=1)
    hard_boundaries_passed: bool
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    usage_confidence: Literal["exact", "derived", "configured", "unknown"] = "unknown"
    latency_ms: int | None = Field(default=None, ge=0, le=600_000)
    quota_units: tuple[tuple[str, int], ...] = Field(default=(), max_length=16)
    quota_confidence: Literal["exact", "derived", "configured", "unknown"] = "unknown"


class EvaluationCaseSummary(FrozenContract):
    evaluation_run_id: UUID
    fixture_id: str = Field(pattern=_SAFE_ID)
    task_profile_id: str = Field(pattern=_SAFE_ID)
    task_profile_version: int = Field(ge=1, le=2_147_483_647)
    endpoint: EndpointRef
    provider_id: str = Field(pattern=_SAFE_ID)
    model_id: str = Field(pattern=_SAFE_ID)
    account_scope_id: str | None = None
    credential_scope_id: str | None = None
    serializer_id: str = Field(pattern=_SAFE_ID)
    runtime_id: str = Field(pattern=_SAFE_ID)
    counter_id: str | None = None
    counter_confidence: CounterConfidence = "unknown"
    endpoint_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str = Field(pattern=_SAFE_ID)
    tested_revision: str = Field(pattern=_REVISION)
    status: Literal["measured", "not_run", "failed", "synthetic_baseline"]
    reason: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:+/-]{1,100}$")
    routing_decision_id: UUID | None = None
    invocation_id: UUID | None = None
    attempt_id: UUID | None = None
    artifact_id: UUID | None = None
    single_provider_baseline: bool = False
    deterministic_strategy_baseline: bool = False
    deterministic_strategy_rank: int | None = Field(default=None, ge=1, le=32)
    deterministic_strategy_score: int | None = Field(default=None, ge=-2_147_483_648, le=2_147_483_647)
    metrics: EvaluationMetrics | None = None
    measured_at: datetime

    @field_validator("measured_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluation_timestamp_must_be_aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def case_status_is_consistent(self):
        if (self.status in {"measured", "synthetic_baseline"}) != (self.metrics is not None):
            raise ValueError("evaluation_case_metrics_status_mismatch")
        if self.status == "measured" and (
            self.routing_decision_id is None or self.invocation_id is None or self.attempt_id is None
        ):
            raise ValueError("evaluation_case_dispatch_identity_missing")
        return self


class EvaluationRunSummary(FrozenContract):
    schema_version: Literal[1] = 1
    evaluation_run_id: UUID
    task_profile_id: str = Field(pattern=_SAFE_ID)
    task_profile_version: int = Field(ge=1, le=2_147_483_647)
    task_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal["synthetic", "live"]
    status: Literal["completed", "partial", "failed", "offline_baseline"]
    tested_revision: str = Field(pattern=_REVISION)
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str = Field(pattern=_SAFE_ID)
    fixture_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    total_cases: int = Field(ge=1, le=10_000)
    measured_cases: int = Field(ge=0, le=10_000)
    synthetic_cases: int = Field(ge=0, le=10_000)
    skipped_cases: int = Field(ge=0, le=10_000)
    failed_cases: int = Field(ge=0, le=10_000)
    single_provider_baseline_endpoint_profile_id: str | None = None
    deterministic_strategy_id: str = Field(pattern=_SAFE_ID)
    deterministic_strategy_version: str = Field(pattern=_SAFE_ID)
    deterministic_baseline_endpoint_profile_ids: tuple[str, ...] = Field(default=(), max_length=128)
    created_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def counts_and_timestamps_are_coherent(self):
        if (
            self.measured_cases + self.synthetic_cases + self.skipped_cases + self.failed_cases
            != self.total_cases
        ):
            raise ValueError("evaluation_run_case_counts_invalid")
        if (
            self.synthetic_cases and self.source != "synthetic"
        ) or (
            self.measured_cases and self.source != "live"
        ):
            raise ValueError("evaluation_run_source_counts_invalid")
        if self.status == "offline_baseline" and (
            self.source != "synthetic"
            or self.synthetic_cases != self.total_cases
            or self.skipped_cases
            or self.failed_cases
        ):
            raise ValueError("evaluation_run_offline_status_invalid")
        if self.status == "completed" and (
            self.source != "live"
            or self.measured_cases != self.total_cases
            or self.skipped_cases
            or self.failed_cases
        ):
            raise ValueError("evaluation_run_completed_status_invalid")
        if (
            self.created_at.tzinfo is None
            or self.created_at.utcoffset() is None
            or self.completed_at.tzinfo is None
            or self.completed_at.utcoffset() is None
        ):
            raise ValueError("evaluation_timestamp_must_be_aware")
        if self.completed_at < self.created_at:
            raise ValueError("evaluation_run_time_invalid")
        return self


class QualityProfile(FrozenContract):
    """Endpoint-specific immutable measurement with an explicit publication state."""

    quality_evidence_id: UUID
    quality_evidence_version: int = Field(ge=1, le=2_147_483_647)
    evaluation_run_id: UUID
    quality_profile_id: str = Field(pattern=_SAFE_ID)
    quality_profile_version: int = Field(ge=1, le=2_147_483_647)
    task_profile_id: str = Field(pattern=_SAFE_ID)
    task_profile_version: int = Field(ge=1, le=2_147_483_647)
    endpoint: EndpointRef
    provider_id: str = Field(pattern=_SAFE_ID)
    model_id: str = Field(pattern=_SAFE_ID)
    account_scope_id: str | None = None
    credential_scope_id: str | None = None
    endpoint_id: str = Field(pattern=_SAFE_ID)
    deployment_id: str = Field(pattern=_SAFE_ID)
    serializer_id: str = Field(pattern=_SAFE_ID)
    runtime_id: str = Field(pattern=_SAFE_ID)
    counter_id: str | None = None
    counter_confidence: CounterConfidence = "unknown"
    policy_version: str = Field(pattern=_SAFE_ID)
    endpoint_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_identity_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scoring_policy_id: str = Field(pattern=_SAFE_ID)
    scoring_policy_version: int = Field(ge=1, le=2_147_483_647)
    minimum_score: float = Field(ge=0, le=1)
    minimum_coverage: float = Field(gt=0, le=1)
    minimum_confidence: float = Field(ge=0, le=1)
    minimum_samples: int = Field(ge=1, le=100_000)
    minimum_benefit: float = Field(ge=0, le=1)
    max_age_seconds: int = Field(ge=1, le=7_776_000)
    tested_revision: str = Field(pattern=_REVISION)
    fixture_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    sample_count: int = Field(ge=1, le=100_000)
    coverage: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    hard_boundaries_passed: bool
    mean_metrics: dict[str, float] = Field(max_length=16)
    measured_at: datetime
    fresh_until: datetime
    status: Literal["unpromoted", "qualified", "rejected"] = "unpromoted"
    revision: int = Field(default=1, ge=1)
    baseline_evidence_id: UUID | None = None
    promotion_minimum_benefit: float | None = Field(default=None, ge=0, le=1)

    @field_validator("measured_at", "fresh_until")
    @classmethod
    def profile_timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("quality_profile_timestamp_must_be_aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def profile_identity_and_metric_bounds(self):
        if self.fresh_until <= self.measured_at:
            raise ValueError("quality_profile_freshness_invalid")
        if any(not key or len(key) > 80 or not 0 <= value <= 1 for key, value in self.mean_metrics.items()):
            raise ValueError("quality_profile_metric_invalid")
        if self.status == "qualified" and (
            self.baseline_evidence_id is None or self.promotion_minimum_benefit is None
        ):
            raise ValueError("quality_profile_promotion_proof_missing")
        if self.status == "qualified" and (
            self.sample_count < self.minimum_samples
            or self.coverage < self.minimum_coverage
            or self.score < self.minimum_score
            or self.confidence < self.minimum_confidence
            or not self.hard_boundaries_passed
            or self.promotion_minimum_benefit < self.minimum_benefit
        ):
            raise ValueError("quality_profile_threshold_not_met")
        return self

    def as_routing_evidence(self) -> QualityEvidence:
        if self.status != "qualified":
            raise ValueError("quality_profile_not_qualified")
        return QualityEvidence(
            quality_evidence_id=self.quality_evidence_id,
            quality_evidence_version=self.quality_evidence_version,
            task_profile_id=self.task_profile_id,
            task_profile_version=self.task_profile_version,
            endpoint_profile_id=self.endpoint.endpoint_profile_id,
            endpoint_profile_version=self.endpoint.profile_version,
            provider_id=self.provider_id,
            model_id=self.model_id,
            endpoint_id=self.endpoint_id,
            deployment_id=self.deployment_id,
            account_scope_id=self.account_scope_id,
            credential_scope_id=self.credential_scope_id,
            serializer_id=self.serializer_id,
            runtime_id=self.runtime_id,
            counter_id=self.counter_id,
            counter_confidence=self.counter_confidence,
            quality_profile_id=self.quality_profile_id,
            quality_profile_version=self.quality_profile_version,
            policy_version=self.policy_version,
            endpoint_configuration_sha256=self.endpoint_configuration_sha256,
            task_configuration_sha256=self.task_configuration_sha256,
            quality_identity_sha256=self.quality_identity_sha256,
            scoring_policy_id=self.scoring_policy_id,
            scoring_policy_version=self.scoring_policy_version,
            tested_revision=self.tested_revision,
            score=self.score,
            coverage=self.coverage,
            confidence=self.confidence,
            sample_count=self.sample_count,
            measured_at=self.measured_at,
            fresh_until=self.fresh_until,
            evidence_reference=f"quality-profile:{self.quality_evidence_id}:{self.quality_evidence_version}",
        )


class EvaluationRunStart(FrozenContract):
    evaluation_run_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    application_id: str = Field(min_length=2, max_length=42)
    workspace_id: str | None = Field(default=None, max_length=100)
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tested_revision: str = Field(pattern=_REVISION)
    policy_version: str = Field(pattern=_SAFE_ID)
    task_profile_id: str = Field(pattern=_SAFE_ID)
    task_profile_version: int = Field(ge=1, le=2_147_483_647)
    task_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal["synthetic", "live"]
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    expected_cases: int = Field(ge=1, le=10_000)
    created_at: datetime
    gate_bindings: tuple[EvaluationQualityGate, ...] = Field(min_length=1, max_length=10_000)

    @field_validator("created_at")
    @classmethod
    def start_timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluation_timestamp_must_be_aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def run_case_bindings_are_unique(self):
        identities = [
            (
                gate.fixture_id,
                gate.endpoint.endpoint_profile_id,
                gate.endpoint.profile_version,
            )
            for gate in self.gate_bindings
        ]
        if (
            len(identities) != len(set(identities))
            or len(identities) != self.expected_cases
            or any(
                gate.evaluation_run_id != self.evaluation_run_id
                or gate.policy_version != self.policy_version
                or gate.task_profile_id != self.task_profile_id
                or gate.task_profile_version != self.task_profile_version
                or gate.task_configuration_sha256 != self.task_configuration_sha256
                or gate.mode != self.source
                for gate in self.gate_bindings
            )
        ):
            raise ValueError("evaluation_run_case_bindings_invalid")
        return self


class QualityProfileChange(FrozenContract):
    quality_evidence_id: UUID
    expected_revision: int = Field(ge=1)
    profile: QualityProfile
