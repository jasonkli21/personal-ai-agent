"""Task-aware routing contracts for the Phase 21 deterministic baseline.

These records contain only bounded decision facts. They deliberately have no
provider client, credential handle, prompt text, or executable fallback field.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_ai.routing.contracts import (
    CounterConfidence,
    EndpointCandidateRequirements,
    EndpointOperation,
    EndpointProfile,
    ExecutionMode,
)

MAX_ROUTING_DECISION_BYTES = 65_536
MAX_ROUTING_OUTCOME_BYTES = 2_048
MAX_ROUTING_OUTCOMES = 32
MAX_REPLAY_SECONDS = 90 * 24 * 60 * 60
_SAFE_ID = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._:/@+_-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONFIDENCE_RANK: dict[CounterConfidence, int] = {
    "unknown": 0,
    "estimated": 1,
    "reported": 2,
    "authoritative": 3,
}


def _safe_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError("routing_identity_invalid")
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("routing_timestamp_must_be_aware")
    return value.astimezone(UTC)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


TaskType = Literal[
    "chat",
    "summary",
    "extraction",
    "research_planning",
    "research_synthesis",
    "rewrite",
    "structured_generation",
    "embedding",
]


class QualityPolicy(_FrozenModel):
    """Task quality admission policy, independent of preference scoring."""

    mode: Literal["measured_floor", "unmeasured_baseline"] = "unmeasured_baseline"
    quality_profile_id: str | None = Field(default=None, max_length=200)
    quality_profile_version: int | None = Field(default=None, ge=1, le=2_147_483_647)
    minimum_score: float | None = Field(default=None, ge=0, le=1)
    minimum_coverage: float = Field(default=0, ge=0, le=1)
    max_age_seconds: int = Field(default=30 * 24 * 60 * 60, ge=1, le=MAX_REPLAY_SECONDS)

    @field_validator("quality_profile_id")
    @classmethod
    def valid_quality_profile(cls, value: str | None) -> str | None:
        return _safe_id(value) if value is not None else None

    @model_validator(mode="after")
    def validate_quality_policy(self) -> QualityPolicy:
        if self.mode == "measured_floor" and (
            self.quality_profile_id is None
            or self.quality_profile_version is None
            or self.minimum_score is None
            or self.minimum_coverage <= 0
        ):
            raise ValueError("measured_quality_floor_incomplete")
        return self


class EndpointPriority(_FrozenModel):
    endpoint_profile_id: str
    priority: int = Field(ge=-100_000, le=100_000)

    @field_validator("endpoint_profile_id")
    @classmethod
    def valid_endpoint_id(cls, value: str) -> str:
        return _safe_id(value)


class RoutingPreferences(_FrozenModel):
    """Optional score inputs. Hard quality floors are applied before these."""

    quality_weight: int = Field(default=0, ge=0, le=1_000_000)
    reliability_weight: int = Field(default=0, ge=0, le=1_000_000)
    latency_penalty_per_second: int = Field(default=0, ge=0, le=1_000_000)


class RoutingTaskProfile(_FrozenModel):
    """Versioned policy for a known operation; callers do not classify with an LLM."""

    task_id: str
    profile_id: str
    profile_version: int = Field(ge=1, le=2_147_483_647)
    task_type: TaskType
    required_capabilities: frozenset[EndpointOperation] = Field(min_length=1, max_length=6)
    quality: QualityPolicy = Field(default_factory=QualityPolicy)
    preferences: RoutingPreferences = Field(default_factory=RoutingPreferences)
    endpoint_priorities: tuple[EndpointPriority, ...] = Field(default=(), max_length=32)
    citation_policy: Literal["none", "source_links", "required"] = "none"
    validator_id: str | None = Field(default=None, max_length=200)
    validator_version: str | None = Field(default=None, max_length=100)
    escalation_allowed: bool = False
    cascade_allowed: bool = False
    allow_source_narrowing: bool = False
    max_physical_attempts: int = Field(default=1, ge=1, le=32)
    max_reselections: int = Field(default=0, ge=0, le=4)
    max_auxiliary_calls: int = Field(default=0, ge=0, le=16)
    deadline_ms: int = Field(default=30_000, ge=1, le=600_000)
    replay_retention_seconds: int = Field(default=MAX_REPLAY_SECONDS, ge=1, le=MAX_REPLAY_SECONDS)

    @field_validator("task_id", "profile_id", "validator_id")
    @classmethod
    def valid_task_identity(cls, value: str | None) -> str | None:
        return _safe_id(value) if value is not None else None

    @field_validator("validator_version")
    @classmethod
    def valid_validator_version(cls, value: str | None) -> str | None:
        return _safe_id(value) if value is not None else None

    @model_validator(mode="after")
    def validate_task_profile(self) -> RoutingTaskProfile:
        if (self.validator_id is None) != (self.validator_version is None):
            raise ValueError("routing_validator_identity_incomplete")
        if len({row.endpoint_profile_id for row in self.endpoint_priorities}) != len(
            self.endpoint_priorities
        ):
            raise ValueError("routing_endpoint_priority_duplicate")
        return self

    def priority_for(self, endpoint_profile_id: str) -> int:
        return next(
            (row.priority for row in self.endpoint_priorities
             if row.endpoint_profile_id == endpoint_profile_id),
            0,
        )


class RoutingRequestFacts(_FrozenModel):
    """Request metadata safe to retain for replay; contains no user text."""

    request_id: str
    run_id: str | None = None
    requirements: EndpointCandidateRequirements
    policy_version: str
    source_count: int | None = Field(default=None, ge=0, le=10_000)
    source_manifest_sha256: str | None = None
    prepared_context_tokens: int | None = Field(default=None, ge=0, le=2_000_000)
    count_source: str | None = Field(default=None, max_length=100)
    count_confidence: CounterConfidence = "unknown"
    excluded_endpoint_profile_ids: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("request_id", "run_id", "policy_version", "count_source")
    @classmethod
    def valid_request_ids(cls, value: str | None) -> str | None:
        return _safe_id(value) if value is not None else None

    @field_validator("source_manifest_sha256")
    @classmethod
    def valid_manifest_hash(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.fullmatch(value):
            raise ValueError("routing_manifest_hash_invalid")
        return value

    @field_validator("excluded_endpoint_profile_ids")
    @classmethod
    def valid_excluded_endpoints(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("routing_excluded_endpoint_duplicate")
        return tuple(_safe_id(value) for value in values)


class RuntimeCandidateFacts(_FrozenModel):
    """Decision-time authorization, credential, health, and exhaustion facts."""

    endpoint_profile_id: str
    endpoint_profile_version: int = Field(ge=1, le=2_147_483_647)
    authorization: Literal["authorized", "denied", "unknown"] = "unknown"
    authorization_reference: str | None = Field(default=None, max_length=500)
    credential_status: Literal["usable", "unusable", "unknown"] = "unknown"
    health_status: Literal["healthy", "degraded", "cooldown", "unknown"] = "unknown"
    health_reference: str | None = Field(default=None, max_length=500)
    observed_at: datetime
    fresh_until: datetime
    cooldown_until: datetime | None = None
    exhausted: bool | None = None

    @field_validator("endpoint_profile_id")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("authorization_reference", "health_reference")
    @classmethod
    def valid_reference(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("routing_evidence_reference_invalid")
        return value

    @field_validator("observed_at", "fresh_until", "cooldown_until")
    @classmethod
    def valid_runtime_time(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None

    @model_validator(mode="after")
    def require_authorization_reference(self) -> RuntimeCandidateFacts:
        if self.authorization == "authorized" and self.authorization_reference is None:
            raise ValueError("routing_authorization_requires_reference")
        if self.fresh_until <= self.observed_at:
            raise ValueError("routing_runtime_freshness_invalid")
        return self


class QualityEvidence(_FrozenModel):
    """Fresh task x endpoint measurement; it is admission evidence, not a guess."""

    task_profile_id: str
    task_profile_version: int = Field(ge=1, le=2_147_483_647)
    endpoint_profile_id: str
    endpoint_profile_version: int = Field(ge=1, le=2_147_483_647)
    quality_profile_id: str
    quality_profile_version: int = Field(ge=1, le=2_147_483_647)
    score: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)
    measured_at: datetime
    fresh_until: datetime
    evidence_reference: str = Field(min_length=1, max_length=500)

    @field_validator(
        "task_profile_id", "endpoint_profile_id", "quality_profile_id", "evidence_reference"
    )
    @classmethod
    def valid_quality_identity(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("measured_at", "fresh_until")
    @classmethod
    def valid_quality_timestamps(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def valid_quality_interval(self) -> QualityEvidence:
        if self.fresh_until <= self.measured_at:
            raise ValueError("routing_quality_freshness_invalid")
        return self


class RoutingSignals(_FrozenModel):
    """Optional bounded latency/reliability facts used only when configured."""

    endpoint_profile_id: str
    endpoint_profile_version: int = Field(ge=1, le=2_147_483_647)
    observed_at: datetime
    fresh_until: datetime
    latency_ms: int | None = Field(default=None, ge=0, le=600_000)
    reliability: float | None = Field(default=None, ge=0, le=1)
    evidence_reference: str = Field(min_length=1, max_length=500)

    @field_validator("endpoint_profile_id", "evidence_reference")
    @classmethod
    def valid_signal_identity(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("observed_at", "fresh_until")
    @classmethod
    def valid_signal_timestamps(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def valid_signal_interval(self) -> RoutingSignals:
        if self.fresh_until <= self.observed_at:
            raise ValueError("routing_signal_freshness_invalid")
        return self


class CandidateDecision(_FrozenModel):
    """Complete safe decision facts for a single considered endpoint."""

    profile: EndpointProfile
    eligible: bool
    rejection_reasons: tuple[str, ...] = Field(default=(), max_length=64)
    runtime_facts: RuntimeCandidateFacts | None = None
    quality_evidence: QualityEvidence | None = None
    routing_signals: RoutingSignals | None = None
    configured_priority: int = Field(default=0, ge=-100_000, le=100_000)

    @model_validator(mode="after")
    def consistent_candidate(self) -> CandidateDecision:
        if self.eligible != (not self.rejection_reasons):
            raise ValueError("routing_candidate_assessment_inconsistent")
        if self.eligible and self.runtime_facts is not None and (
            self.runtime_facts.endpoint_profile_id != self.profile.endpoint_profile_id
            or self.runtime_facts.endpoint_profile_version != self.profile.profile_version
        ):
            raise ValueError("routing_runtime_profile_identity_mismatch")
        if self.eligible and self.quality_evidence is not None and (
            self.quality_evidence.endpoint_profile_id != self.profile.endpoint_profile_id
            or self.quality_evidence.endpoint_profile_version != self.profile.profile_version
        ):
            raise ValueError("routing_quality_profile_identity_mismatch")
        if self.eligible and self.routing_signals is not None and (
            self.routing_signals.endpoint_profile_id != self.profile.endpoint_profile_id
            or self.routing_signals.endpoint_profile_version != self.profile.profile_version
        ):
            raise ValueError("routing_signal_profile_identity_mismatch")
        return self


class OverflowCandidateRef(_FrozenModel):
    """Compact identity and digest used when required replay facts exceed the bound."""

    endpoint_profile_id: str
    profile_version: int = Field(ge=1, le=2_147_483_647)
    profile_facts_sha256: str

    @field_validator("endpoint_profile_id")
    @classmethod
    def valid_overflow_id(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("profile_facts_sha256")
    @classmethod
    def valid_overflow_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("routing_profile_digest_invalid")
        return value


class RoutingStrategyCandidate(_FrozenModel):
    """A strategy-visible candidate, constructed only after all hard filters."""

    profile: EndpointProfile
    configured_priority: int
    quality_score: float | None = Field(default=None, ge=0, le=1)
    latency_ms: int | None = Field(default=None, ge=0, le=600_000)
    reliability: float | None = Field(default=None, ge=0, le=1)
    quality_evidence_reference: str | None = Field(default=None, max_length=500)
    signal_evidence_reference: str | None = Field(default=None, max_length=500)


class RoutingStrategyInput(_FrozenModel):
    """Pure data passed to interchangeable strategies; all candidates passed eligibility."""

    task: RoutingTaskProfile
    requirements: EndpointCandidateRequirements
    policy_version: str
    registry_version: str
    candidates: tuple[RoutingStrategyCandidate, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def validate_strategy_input(self) -> RoutingStrategyInput:
        ids = [row.profile.endpoint_profile_id for row in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("routing_strategy_candidate_duplicate")
        if self.requirements.execution_mode != "STRICT_FREE":
            raise ValueError("automatic_router_requires_strict_free")
        if not self.task.required_capabilities.issubset(self.requirements.required_capabilities):
            raise ValueError("routing_task_capability_requirement_mismatch")
        return self


class RankedCandidate(_FrozenModel):
    endpoint_profile_id: str
    profile_version: int = Field(ge=1, le=2_147_483_647)
    score: int = Field(ge=-2_147_483_648, le=2_147_483_647)
    reason_code: str = Field(min_length=1, max_length=100)

    @field_validator("endpoint_profile_id", "reason_code")
    @classmethod
    def valid_rank_item(cls, value: str) -> str:
        return _safe_id(value)


class RoutingStrategyResult(_FrozenModel):
    selected_endpoint_profile_id: str
    selected_profile_version: int = Field(ge=1, le=2_147_483_647)
    ranked_candidates: tuple[RankedCandidate, ...] = Field(max_length=32)
    strategy_id: str
    strategy_version: str
    strategy_implementation_sha256: str
    configuration_version: str
    configuration_sha256: str
    tie_break_version: str
    reason_code: str = Field(min_length=1, max_length=100)

    @field_validator(
        "selected_endpoint_profile_id", "strategy_id", "strategy_version",
        "configuration_version", "tie_break_version", "reason_code",
    )
    @classmethod
    def valid_strategy_identity(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("strategy_implementation_sha256", "configuration_sha256")
    @classmethod
    def valid_strategy_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("routing_strategy_digest_invalid")
        return value

    @model_validator(mode="after")
    def selected_is_top_ranked(self) -> RoutingStrategyResult:
        if not self.ranked_candidates:
            raise ValueError("routing_strategy_ranking_empty")
        first = self.ranked_candidates[0]
        if (
            first.endpoint_profile_id != self.selected_endpoint_profile_id
            or first.profile_version != self.selected_profile_version
        ):
            raise ValueError("routing_strategy_selection_not_top_ranked")
        identities = [row.endpoint_profile_id for row in self.ranked_candidates]
        if len(identities) != len(set(identities)):
            raise ValueError("routing_strategy_ranking_duplicate")
        return self


class RoutingStrategyIdentity(_FrozenModel):
    strategy_id: str
    strategy_version: str
    strategy_implementation_sha256: str
    configuration_version: str
    configuration_sha256: str
    tie_break_version: str

    @field_validator("strategy_id", "strategy_version", "configuration_version", "tie_break_version")
    @classmethod
    def valid_identity_field(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("strategy_implementation_sha256", "configuration_sha256")
    @classmethod
    def valid_identity_digest(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("routing_strategy_digest_invalid")
        return value


class PreparationIdentity(_FrozenModel):
    """Endpoint-specific prepared-input identity with no retained input text."""

    endpoint_profile_id: str
    endpoint_profile_version: int = Field(ge=1, le=2_147_483_647)
    serializer_id: str
    counter_id: str | None = None
    input_tokens: int = Field(ge=0, le=2_000_000)
    count_source: str
    count_confidence: CounterConfidence
    source_manifest_sha256: str
    prepared_input_sha256: str

    @field_validator(
        "endpoint_profile_id", "serializer_id", "counter_id", "count_source"
    )
    @classmethod
    def valid_preparation_id(cls, value: str | None) -> str | None:
        return _safe_id(value) if value is not None else None

    @field_validator("source_manifest_sha256", "prepared_input_sha256")
    @classmethod
    def valid_preparation_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("routing_preparation_hash_invalid")
        return value


class QuotaReservationRef(_FrozenModel):
    reservation_id: UUID
    buckets: tuple[tuple[str, int], ...] = Field(max_length=32)

    @field_validator("buckets")
    @classmethod
    def valid_reservation_buckets(cls, values: tuple[tuple[str, int], ...]):
        names = [name for name, _ in values]
        if len(set(names)) != len(names) or any(not _SAFE_ID.fullmatch(name) for name in names):
            raise ValueError("routing_reservation_bucket_invalid")
        if any(isinstance(amount, bool) or amount < 0 for _, amount in values):
            raise ValueError("routing_reservation_units_invalid")
        return values


class DispatchRevalidation(_FrozenModel):
    """Trusted orchestrator snapshot collected immediately before reservation."""

    endpoint_profile_id: str
    endpoint_profile_version: int = Field(ge=1, le=2_147_483_647)
    validated_at: datetime
    fresh_until: datetime
    policy_version: str
    authorization_current: bool
    authorization_reference: str = Field(min_length=1, max_length=500)
    credential_usable: bool
    health_status: Literal["healthy", "degraded", "cooldown", "unknown"]
    quota_not_exhausted: bool
    sources_authorized: bool
    source_permission_reference: str = Field(min_length=1, max_length=500)
    source_manifest_sha256: str
    source_set_narrowed: bool = False

    @field_validator(
        "endpoint_profile_id", "policy_version", "authorization_reference",
        "source_permission_reference",
    )
    @classmethod
    def valid_revalidation_identity(cls, value: str) -> str:
        return _safe_id(value)

    @field_validator("validated_at", "fresh_until")
    @classmethod
    def valid_revalidation_time(cls, value: datetime) -> datetime:
        return _aware(value)

    @field_validator("source_manifest_sha256")
    @classmethod
    def valid_revalidation_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("routing_manifest_hash_invalid")
        return value

    @model_validator(mode="after")
    def valid_revalidation_interval(self) -> DispatchRevalidation:
        if self.fresh_until <= self.validated_at:
            raise ValueError("routing_revalidation_freshness_invalid")
        return self


class ExecutionPlan(_FrozenModel):
    """One selected endpoint plan; advisory candidate references are never fallbacks."""

    schema_version: Literal["execution-plan-v1"] = "execution-plan-v1"
    state: Literal["preparing", "ready"] = "preparing"
    routing_decision_id: UUID
    parent_decision_id: UUID | None = None
    reselection_depth: int = Field(default=0, ge=0, le=4)
    task_id: str
    task_profile_id: str
    task_profile_version: int = Field(ge=1, le=2_147_483_647)
    selected_endpoint_profile_id: str
    selected_profile_version: int = Field(ge=1, le=2_147_483_647)
    reselection_candidate_refs: tuple[tuple[str, int], ...] = Field(max_length=31)
    execution_mode: ExecutionMode
    required_capabilities: frozenset[EndpointOperation] = Field(min_length=1, max_length=6)
    preparation: PreparationIdentity | None = None
    final_fit: bool | None = None
    reservation: QuotaReservationRef | None = None
    validator_id: str | None = None
    validator_version: str | None = None
    escalation_allowed: bool = False
    cascade_allowed: bool = False
    max_physical_attempts: int = Field(ge=1, le=32)
    max_reselections: int = Field(default=0, ge=0, le=4)
    max_auxiliary_calls: int = Field(ge=0, le=16)
    deadline_ms: int = Field(ge=1, le=600_000)
    input_tokens_bound: int = Field(ge=0, le=2_000_000)
    output_tokens_bound: int = Field(ge=0, le=1_000_000)
    registry_version: str
    policy_version: str
    strategy_id: str
    strategy_version: str
    strategy_reason_code: str

    @field_validator(
        "task_id", "task_profile_id", "selected_endpoint_profile_id", "registry_version",
        "policy_version", "strategy_id", "strategy_version", "strategy_reason_code",
        "validator_id", "validator_version",
    )
    @classmethod
    def valid_plan_identity(cls, value: str | None) -> str | None:
        return _safe_id(value) if value is not None else None

    @field_validator("reselection_candidate_refs")
    @classmethod
    def unique_reselection_refs(cls, values: tuple[tuple[str, int], ...]):
        ids = [endpoint_id for endpoint_id, _ in values]
        if len(set(ids)) != len(ids) or any(not _SAFE_ID.fullmatch(value) for value in ids):
            raise ValueError("execution_plan_reselection_reference_invalid")
        return values

    @model_validator(mode="after")
    def validate_plan_state(self) -> ExecutionPlan:
        if self.selected_endpoint_profile_id in {
            endpoint_id for endpoint_id, _ in self.reselection_candidate_refs
        }:
            raise ValueError("execution_plan_selected_endpoint_repeated")
        if self.reselection_depth > self.max_reselections:
            raise ValueError("execution_plan_reselection_budget_exceeded")
        if (self.validator_id is None) != (self.validator_version is None):
            raise ValueError("execution_plan_validator_identity_incomplete")
        if self.state == "preparing":
            if self.preparation is not None or self.final_fit is not None or self.reservation is not None:
                raise ValueError("provisional_execution_plan_has_final_facts")
        else:
            if self.preparation is None or self.final_fit is not True or self.reservation is None:
                raise ValueError("ready_execution_plan_requires_fit_and_reservation")
            if (
                self.preparation.endpoint_profile_id != self.selected_endpoint_profile_id
                or self.preparation.endpoint_profile_version != self.selected_profile_version
            ):
                raise ValueError("execution_plan_preparation_endpoint_mismatch")
            if self.preparation.input_tokens > self.input_tokens_bound:
                raise ValueError("execution_plan_prepared_input_exceeds_bound")
        return self


class RoutingDecisionObservation(_FrozenModel):
    """Immutable decision-time facts retained for bounded, privacy-safe replay."""

    schema_version: Literal["routing-decision-v1"] = "routing-decision-v1"
    routing_decision_id: UUID
    parent_decision_id: UUID | None = None
    root_decision_id: UUID
    reselection_depth: int = Field(default=0, ge=0, le=4)
    owner_id: str = Field(min_length=1, max_length=200)
    application_id: str = Field(min_length=2, max_length=42)
    workspace_id: str | None = Field(default=None, max_length=100)
    created_at: datetime
    replay_until: datetime
    request: RoutingRequestFacts
    task: RoutingTaskProfile
    registry_version: str
    policy_version: str
    strategy_identity: RoutingStrategyIdentity
    lifecycle_status: Literal["preparing", "no_route"]
    replay_completeness: Literal["complete", "incomplete"] = "complete"
    incomplete_reason: str | None = None
    candidates: tuple[CandidateDecision, ...] = Field(max_length=32)
    overflow_candidates: tuple[OverflowCandidateRef, ...] = Field(default=(), max_length=32)
    strategy_input: RoutingStrategyInput | None = None
    strategy_result: RoutingStrategyResult | None = None
    provisional_plan: ExecutionPlan | None = None
    no_route_reason: str | None = None

    @field_validator("created_at", "replay_until")
    @classmethod
    def valid_decision_timestamp(cls, value: datetime) -> datetime:
        return _aware(value)

    @field_validator(
        "owner_id", "application_id", "workspace_id", "registry_version",
        "policy_version", "no_route_reason", "incomplete_reason"
    )
    @classmethod
    def valid_observation_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) > 500 or value != value.strip():
            raise ValueError("routing_observation_identity_invalid")
        return value

    @model_validator(mode="after")
    def validate_replay_observation(self) -> RoutingDecisionObservation:
        if self.replay_until <= self.created_at:
            raise ValueError("routing_replay_horizon_invalid")
        if (self.replay_until - self.created_at).total_seconds() > MAX_REPLAY_SECONDS:
            raise ValueError("routing_replay_horizon_exceeds_limit")
        if self.parent_decision_id is None:
            if self.root_decision_id != self.routing_decision_id or self.reselection_depth != 0:
                raise ValueError("routing_root_decision_identity_invalid")
        elif (
            self.root_decision_id == self.routing_decision_id
            or self.reselection_depth < 1
            or self.reselection_depth > self.task.max_reselections
        ):
            raise ValueError("routing_reselection_lineage_invalid")
        ids = [row.profile.endpoint_profile_id for row in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("routing_observation_candidate_duplicate")
        if len({row.endpoint_profile_id for row in self.overflow_candidates}) != len(
            self.overflow_candidates
        ):
            raise ValueError("routing_observation_overflow_candidate_duplicate")
        if self.replay_completeness == "complete":
            if self.incomplete_reason is not None or self.overflow_candidates:
                raise ValueError("routing_observation_completeness_inconsistent")
        elif (
            self.incomplete_reason is None
            or self.overflow_candidates == ()
            or self.candidates
            or self.strategy_input is not None
            or self.strategy_result is not None
            or self.provisional_plan is not None
            or self.lifecycle_status != "no_route"
        ):
            raise ValueError("routing_observation_incomplete_record_invalid")
        if self.request.policy_version != self.policy_version:
            raise ValueError("routing_observation_policy_version_mismatch")
        if self.lifecycle_status == "preparing":
            if self.strategy_input is None or self.strategy_result is None or self.provisional_plan is None:
                raise ValueError("routing_preparing_observation_incomplete")
            if self.no_route_reason is not None:
                raise ValueError("routing_preparing_observation_has_no_route_reason")
            if self.provisional_plan.routing_decision_id != self.routing_decision_id:
                raise ValueError("routing_observation_plan_identity_mismatch")
            eligible_ids = {
                row.profile.endpoint_profile_id for row in self.candidates if row.eligible
            }
            strategy_ids = {
                row.profile.endpoint_profile_id for row in self.strategy_input.candidates
            }
            if eligible_ids != strategy_ids:
                raise ValueError("routing_strategy_input_widened_or_narrowed_eligibility")
            if self.strategy_result.selected_endpoint_profile_id not in eligible_ids:
                raise ValueError("routing_strategy_selected_ineligible_endpoint")
            if (
                self.strategy_input.registry_version != self.registry_version
                or self.strategy_input.policy_version != self.policy_version
                or self.strategy_input.task.profile_id != self.task.profile_id
                or self.strategy_input.task.profile_version != self.task.profile_version
            ):
                raise ValueError("routing_strategy_input_version_mismatch")
            profile_by_id = {
                row.profile.endpoint_profile_id: row.profile for row in self.candidates
            }
            if any(
                profile_by_id[row.profile.endpoint_profile_id] != row.profile
                for row in self.strategy_input.candidates
            ):
                raise ValueError("routing_strategy_candidate_profile_mismatch")
            if (
                self.provisional_plan.task_id != self.task.task_id
                or self.provisional_plan.task_profile_id != self.task.profile_id
                or self.provisional_plan.task_profile_version != self.task.profile_version
                or self.provisional_plan.registry_version != self.registry_version
                or self.provisional_plan.policy_version != self.policy_version
                or self.provisional_plan.parent_decision_id != self.parent_decision_id
                or self.provisional_plan.reselection_depth != self.reselection_depth
            ):
                raise ValueError("routing_observation_plan_facts_mismatch")
            if (
                self.strategy_result.strategy_id != self.strategy_identity.strategy_id
                or self.strategy_result.strategy_version != self.strategy_identity.strategy_version
                or self.strategy_result.strategy_implementation_sha256
                != self.strategy_identity.strategy_implementation_sha256
                or self.strategy_result.configuration_version
                != self.strategy_identity.configuration_version
                or self.strategy_result.configuration_sha256
                != self.strategy_identity.configuration_sha256
                or self.strategy_result.tie_break_version != self.strategy_identity.tie_break_version
            ):
                raise ValueError("routing_strategy_identity_mismatch")
        elif self.no_route_reason is None or self.provisional_plan is not None:
            raise ValueError("routing_no_route_observation_invalid")
        encoded = self.model_dump_json().encode("utf-8")
        if len(encoded) > MAX_ROUTING_DECISION_BYTES:
            raise ValueError("routing_decision_payload_too_large")
        return self

    @property
    def facts_sha256(self) -> str:
        encoded = self.model_dump_json().encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class RoutingDecisionEvent(_FrozenModel):
    """Append-only bounded outcome or lifecycle update for a decision."""

    event_type: Literal[
        "decision_preparing",
        "decision_no_route",
        "preparation_completed",
        "preparation_failed",
        "reservation_succeeded",
        "reservation_failed",
        "dispatch_started",
        "dispatch_completed",
        "dispatch_failed",
        "reselection_linked",
        "replay_unavailable",
    ]
    occurred_at: datetime
    reason_code: str | None = Field(default=None, max_length=100)
    endpoint_profile_id: str | None = Field(default=None, max_length=200)
    invocation_id: UUID | None = None
    attempt_id: UUID | None = None
    evaluation_run_id: UUID | None = None
    linked_decision_id: UUID | None = None
    preparation: PreparationIdentity | None = None
    reservation_id: UUID | None = None
    outcome_code: str | None = Field(default=None, max_length=100)
    dispatch_revalidation: DispatchRevalidation | None = None

    @field_validator("occurred_at")
    @classmethod
    def valid_event_time(cls, value: datetime) -> datetime:
        return _aware(value)

    @field_validator("reason_code", "endpoint_profile_id", "outcome_code")
    @classmethod
    def valid_event_code(cls, value: str | None) -> str | None:
        return _safe_id(value) if value is not None else None

    @model_validator(mode="after")
    def bound_event(self) -> RoutingDecisionEvent:
        if len(self.model_dump_json().encode("utf-8")) > MAX_ROUTING_OUTCOME_BYTES:
            raise ValueError("routing_outcome_payload_too_large")
        return self


class RoutingDecisionRecord(_FrozenModel):
    observation: RoutingDecisionObservation
    events: tuple[RoutingDecisionEvent, ...] = Field(max_length=MAX_ROUTING_OUTCOMES)

    @model_validator(mode="after")
    def bound_events(self) -> RoutingDecisionRecord:
        encoded = json.dumps(
            [event.model_dump(mode="json") for event in self.events],
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > MAX_ROUTING_DECISION_BYTES:
            raise ValueError("routing_outcomes_payload_too_large")
        return self
