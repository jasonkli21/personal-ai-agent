"""Task-aware routing contracts for the Phase 21 deterministic baseline.

These records contain only bounded decision facts. They deliberately have no
provider client, credential handle, prompt text, or executable fallback field.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_ai.routing.contracts import (
    CounterConfidence,
    EndpointCandidateRequirements,
    EndpointOperation,
    EndpointRef,
)

MAX_ROUTING_DECISION_BYTES = 65_536
MAX_ROUTING_OUTCOME_BYTES = 16_384
MAX_ROUTING_OUTCOMES = 128
MAX_ROUTING_EVENTS_BYTES = MAX_ROUTING_OUTCOMES * MAX_ROUTING_OUTCOME_BYTES
MAX_ROUTING_TERMINAL_EVENT_BYTES = 1_024
MAX_ROUTING_SOURCE_REFERENCES = 64
MAX_REPLAY_SECONDS = 90 * 24 * 60 * 60
_SAFE_ID = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._:/@+_-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONFIDENCE_RANK: dict[CounterConfidence, int] = {
    "unknown": 0,
    "estimated": 1,
    "reported": 2,
    "authoritative": 3,
}
_SENSITIVITY_RANK = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3}


def source_reference_manifest_sha256(references: tuple[str, ...]) -> str:
    """Hash a canonical set of opaque, per-source digests for subset checks."""
    normalized = tuple(sorted(set(references)))
    return hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError("routing_identity_invalid")
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("routing_timestamp_must_be_aware")
    return value.astimezone(UTC)


def reselection_requirements_preserved(parent, child) -> bool:
    """Return true when child routing facts preserve or tighten root policy."""

    def narrower(parent_value, child_value):
        return parent_value is None or (child_value is not None and child_value <= parent_value)

    if (
        child.execution_mode != parent.execution_mode
        or child.automatic != parent.automatic
        or _SENSITIVITY_RANK[child.sensitivity] < _SENSITIVITY_RANK[parent.sensitivity]
        or not parent.required_capabilities.issubset(child.required_capabilities)
        or not narrower(parent.input_tokens, child.input_tokens)
        or not narrower(parent.output_tokens, child.output_tokens)
        or not narrower(parent.search_query_chars, child.search_query_chars)
        or not narrower(parent.search_results, child.search_results)
        or (
            parent.embedding_dimensions is not None
            and child.embedding_dimensions != parent.embedding_dimensions
        )
        or (
            parent.structured_schema_id is not None
            and child.structured_schema_id != parent.structured_schema_id
        )
    ):
        return False
    if parent.count is not None:
        if child.count is None:
            return False
        if (
            _CONFIDENCE_RANK[child.count.minimum_confidence]
            < _CONFIDENCE_RANK[parent.count.minimum_confidence]
        ):
            return False
        if (
            parent.count.structured_schema_id is not None
            and child.count.structured_schema_id != parent.count.structured_schema_id
        ):
            return False
    return True


def sources_allowed(decision: RoutingDecision, sources: tuple[str, ...]) -> bool:
    return sources == decision.request.source_reference_sha256s or (
        decision.task.allow_source_narrowing
        and set(sources).issubset(decision.request.source_reference_sha256s)
    )


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
            (
                row.priority
                for row in self.endpoint_priorities
                if row.endpoint_profile_id == endpoint_profile_id
            ),
            0,
        )


class RoutingRequestFacts(_FrozenModel):
    """Request metadata safe to retain for replay; contains no user text."""

    request_id: str
    run_id: str | None = None
    requirements: EndpointCandidateRequirements
    policy_version: str
    source_reference_sha256s: tuple[str, ...] = Field(
        default=(), max_length=MAX_ROUTING_SOURCE_REFERENCES
    )
    prepared_context_tokens: int | None = Field(default=None, ge=0, le=2_000_000)
    count_source: str | None = Field(default=None, max_length=100)
    count_confidence: CounterConfidence = "unknown"
    excluded_endpoint_profile_ids: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("request_id", "run_id", "policy_version", "count_source")
    @classmethod
    def valid_request_ids(cls, value: str | None) -> str | None:
        return _safe_id(value) if value is not None else None

    @field_validator("source_reference_sha256s")
    @classmethod
    def valid_source_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _SHA256.fullmatch(value) for value in values):
            raise ValueError("routing_source_reference_digest_invalid")
        return tuple(sorted(set(values)))

    @field_validator("excluded_endpoint_profile_ids")
    @classmethod
    def valid_excluded_endpoints(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("routing_excluded_endpoint_duplicate")
        return tuple(_safe_id(value) for value in values)

    @property
    def source_count(self):
        return len(self.source_reference_sha256s)

    @property
    def source_manifest_sha256(self):
        return source_reference_manifest_sha256(self.source_reference_sha256s)


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


class StrategyRef(_FrozenModel):
    strategy_id: str
    semantic_version: str
    artifact_id: str

    @field_validator("strategy_id", "semantic_version", "artifact_id")
    @classmethod
    def safe(cls, value):
        return _safe_id(value)


class StrategyCandidate(_FrozenModel):
    endpoint: EndpointRef
    configured_priority: int = Field(default=0, ge=-100_000, le=100_000)
    quality_score: float | None = Field(default=None, ge=0, le=1)
    latency_ms: int | None = Field(default=None, ge=0, le=600_000)
    reliability: float | None = Field(default=None, ge=0, le=1)


class CandidateFact(StrategyCandidate):
    """Immutable admission/score evidence, never runtime authority."""

    rejection_reasons: tuple[str, ...] = Field(default=(), max_length=64)
    evidence_references: tuple[str, ...] = Field(default=(), max_length=4)
    quality_valid_until: datetime | None = None

    @field_validator("evidence_references", "rejection_reasons")
    @classmethod
    def safe_codes(cls, values):
        return tuple(_safe_id(v) for v in values)

    @field_validator("quality_valid_until")
    @classmethod
    def timestamp(cls, value):
        return _aware(value) if value is not None else None

    @property
    def eligible(self):
        return not self.rejection_reasons

    def strategy_view(self):
        return StrategyCandidate(
            **{name: getattr(self, name) for name in StrategyCandidate.model_fields}
        )


class StrategyView(_FrozenModel):
    preferences: RoutingPreferences
    candidates: tuple[StrategyCandidate, ...] = Field(max_length=32)


class RankedCandidate(_FrozenModel):
    endpoint: EndpointRef
    score: int = Field(ge=-2_147_483_648, le=2_147_483_647)
    reason_code: str = Field(pattern=r"^[A-Za-z0-9._:+/-]{1,100}$")


class RoutingDecision(_FrozenModel):
    schema_version: Literal[2] = 2
    routing_decision_id: UUID
    root_decision_id: UUID
    parent_decision_id: UUID | None = None
    reselection_depth: int = Field(default=0, ge=0, le=4)
    owner_id: str = Field(min_length=1, max_length=200)
    application_id: str = Field(min_length=2, max_length=42)
    workspace_id: str | None = Field(default=None, max_length=100)
    created_at: datetime
    root_deadline_at: datetime
    replay_until: datetime
    request: RoutingRequestFacts
    task: RoutingTaskProfile
    strategy: StrategyRef
    registry_version: str = Field(max_length=100)
    candidates: tuple[CandidateFact, ...] = Field(default=(), max_length=32)
    ranking: tuple[RankedCandidate, ...] = Field(default=(), max_length=32)
    no_route_reason: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:+/-]{1,100}$")

    @field_validator("created_at", "root_deadline_at", "replay_until")
    @classmethod
    def timestamp(cls, value):
        return _aware(value)

    @model_validator(mode="after")
    def coherent(self):
        if (
            not self.request.requirements.automatic
            or self.request.requirements.execution_mode != "STRICT_FREE"
        ):
            raise ValueError("automatic_router_requires_strict_free")
        if not self.task.required_capabilities.issubset(
            self.request.requirements.required_capabilities
        ):
            raise ValueError("routing_task_capability_requirement_mismatch")
        if (
            not self.created_at
            < self.replay_until
            <= self.created_at + timedelta(seconds=self.task.replay_retention_seconds)
        ):
            raise ValueError("routing_replay_horizon_invalid")
        if self.parent_decision_id is None:
            if self.root_decision_id != self.routing_decision_id or self.reselection_depth:
                raise ValueError("routing_root_identity_invalid")
            if self.root_deadline_at != self.created_at + timedelta(
                milliseconds=self.task.deadline_ms
            ):
                raise ValueError("routing_root_deadline_invalid")
        elif (
            self.root_decision_id == self.routing_decision_id
            or not 1 <= self.reselection_depth <= self.task.max_reselections
        ):
            raise ValueError("routing_reselection_lineage_invalid")
        ids = [c.endpoint.endpoint_profile_id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("routing_candidate_duplicate")
        ranked = [r.endpoint for r in self.ranking]
        eligible = [c.endpoint for c in self.candidates if c.eligible]
        if (
            len(ranked) != len({(r.endpoint_profile_id, r.profile_version) for r in ranked})
            or any(r not in eligible for r in ranked)
            or (ranked and set(ranked) != set(eligible))
        ):
            raise ValueError("routing_strategy_ranked_ineligible_endpoint")
        if (self.no_route_reason is None) != bool(self.ranking):
            raise ValueError("routing_selection_invalid")
        if self.ranking and self.root_deadline_at <= self.created_at:
            raise ValueError("routing_root_deadline_invalid")
        if len(self.model_dump_json().encode()) > MAX_ROUTING_DECISION_BYTES:
            raise ValueError("routing_decision_payload_too_large")
        return self

    @property
    def selected(self) -> EndpointRef | None:
        return self.ranking[0].endpoint if self.ranking else None

    def strategy_view(self):
        return StrategyView(
            preferences=self.task.preferences,
            candidates=tuple(c.strategy_view() for c in self.candidates if c.eligible),
        )


class PreparationIdentity(_FrozenModel):
    endpoint: EndpointRef
    serializer_id: str
    counter_id: str | None = None
    input_tokens: int = Field(ge=0, le=2_000_000)
    count_source: str
    count_confidence: CounterConfidence
    source_reference_sha256s: tuple[str, ...] = Field(default=(), max_length=64)
    prepared_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prepared_at: datetime

    @field_validator("serializer_id", "counter_id", "count_source")
    @classmethod
    def safe(cls, value):
        return _safe_id(value) if value is not None else None

    @field_validator("source_reference_sha256s")
    @classmethod
    def sources(cls, values):
        return RoutingRequestFacts.valid_source_references(values)

    @field_validator("prepared_at")
    @classmethod
    def timestamp(cls, value):
        return _aware(value)


class AuthorizationEvidence(_FrozenModel):
    """A trusted authority's short-lived observation; not supplied to finalize."""

    reference: str
    checked_at: datetime
    valid_until: datetime

    @field_validator("reference")
    @classmethod
    def safe(cls, value):
        return _safe_id(value)

    @field_validator("checked_at", "valid_until")
    @classmethod
    def timestamp(cls, value):
        return _aware(value)


class DispatchPermit(_FrozenModel):
    """Committed authorization receipt. Must be claimed once before provider IO."""

    decision_id: UUID
    invocation_id: UUID
    attempt_id: UUID
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def timestamp(cls, value):
        return _aware(value)


RoutingStatus = Literal[
    "selected", "no_route", "failed", "authorized", "dispatched", "closed", "reselected"
]


class RoutingEvent(_FrozenModel):
    event_id: UUID = Field(default_factory=uuid4)
    kind: Literal[
        "selected",
        "no_route",
        "failed",
        "authorized",
        "dispatched",
        "closed",
        "auxiliary",
        "reselected",
    ]
    occurred_at: datetime
    reason: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:+/-]{1,100}$")
    authorization_reference: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9@][A-Za-z0-9._:/@+_-]{0,199}$"
    )
    attempt_id: UUID | None = None
    linked_decision_id: UUID | None = None
    preparation: PreparationIdentity | None = None
    permit: DispatchPermit | None = None

    @field_validator("occurred_at")
    @classmethod
    def timestamp(cls, value):
        return _aware(value)

    @model_validator(mode="after")
    def bounded(self):
        if len(self.model_dump_json().encode()) > MAX_ROUTING_OUTCOME_BYTES:
            raise ValueError("routing_event_payload_too_large")
        if self.kind == "authorized" and (
            self.permit is None
            or self.preparation is None
            or self.authorization_reference is None
            or self.attempt_id != self.permit.attempt_id
        ):
            raise ValueError("routing_authorization_event_incomplete")
        if self.kind == "dispatched" and (
            self.attempt_id is None or self.authorization_reference is None
        ):
            raise ValueError("routing_dispatch_event_incomplete")
        if self.kind != "authorized" and (self.permit is not None or self.preparation is not None):
            raise ValueError("routing_event_unexpected_preparation_or_permit")
        if self.kind == "reselected" and self.linked_decision_id is None:
            raise ValueError("routing_reselection_event_incomplete")
        return self


def transition(status: RoutingStatus, kind: str) -> RoutingStatus:
    allowed = {
        "selected": {"failed", "authorized", "auxiliary"},
        "failed": {"authorized", "reselected"},
        "authorized": {"dispatched", "failed"},
        "dispatched": {"failed", "closed"},
        "no_route": {"closed"},
        "reselected": set(),
        "closed": set(),
    }
    if kind not in allowed[status]:
        raise ValueError("routing_lifecycle_transition_invalid")
    return status if kind == "auxiliary" else kind


class RoutingRecord(_FrozenModel):
    decision: RoutingDecision
    status: RoutingStatus
    events: tuple[RoutingEvent, ...] = Field(min_length=1, max_length=MAX_ROUTING_OUTCOMES)

    def ensure_append_capacity(self, *, event_count: int, event_bytes: int) -> None:
        """Fail before authorizing work if its required lifecycle cannot be stored."""
        if event_count < 0 or event_bytes < 0:
            raise ValueError("routing_event_capacity_invalid")
        if len(self.events) + event_count > MAX_ROUTING_OUTCOMES:
            raise ValueError("routing_event_capacity_exhausted")
        current_bytes = sum(len(event.model_dump_json().encode("utf-8")) for event in self.events)
        if current_bytes + event_bytes > MAX_ROUTING_EVENTS_BYTES:
            raise ValueError("routing_events_payload_too_large")

    @model_validator(mode="after")
    def coherent(self):
        expected = "selected" if self.decision.selected else "no_route"
        if (
            self.events[0].kind != expected
            or self.events[0].occurred_at != self.decision.created_at
        ):
            raise ValueError("routing_initial_event_invalid")
        previous_time = self.decision.created_at
        ids = set()
        receipt = None
        for i, event in enumerate(self.events):
            if event.event_id in ids or event.occurred_at < previous_time:
                raise ValueError("routing_event_order_invalid")
            ids.add(event.event_id)
            previous_time = event.occurred_at
            if event.permit and event.permit.decision_id != self.decision.routing_decision_id:
                raise ValueError("routing_permit_decision_mismatch")
            if event.preparation and event.preparation.endpoint != self.decision.selected:
                raise ValueError("routing_preparation_endpoint_mismatch")
            if event.kind == "authorized":
                receipt = event.permit
                if not event.occurred_at < receipt.expires_at <= self.decision.root_deadline_at:
                    raise ValueError("routing_permit_expiry_invalid")
            if event.kind == "dispatched" and (
                receipt is None
                or event.attempt_id != receipt.attempt_id
                or event.occurred_at >= receipt.expires_at
            ):
                raise ValueError("routing_dispatch_receipt_mismatch")
            if i:
                expected = transition(expected, event.kind)
        if sum(len(e.model_dump_json().encode("utf-8")) for e in self.events) > MAX_ROUTING_EVENTS_BYTES:
            raise ValueError("routing_events_payload_too_large")
        if expected != self.status:
            raise ValueError("routing_materialized_status_invalid")
        return self
