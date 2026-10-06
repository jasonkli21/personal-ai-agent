"""Provider-neutral contracts and deterministic policies for experimental memory."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from personal_ai.auth.scope import ApplicationScopedRecord
from personal_ai.memory.contracts import DerivedMemory, LifecycleEventType, Memory, ScoredMemory

Actor = Literal["system", "developer_test"]
RetrievalStatus = Literal["active", "superseded", "forgotten"]
JobType = Literal["consolidation", "maintenance"]
JobStatus = Literal["pending", "leased", "retry", "completed", "terminal"]


class MemoryLifecycleEvent(ApplicationScopedRecord):
    """Immutable, replay-safe record of one lifecycle decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    memory_id: UUID
    event_type: LifecycleEventType
    reason_code: str = Field(min_length=1, max_length=100)
    policy_version: str = Field(min_length=1, max_length=100)
    actor: Actor = "system"
    occurred_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=300)
    related_memory_ids: tuple[UUID, ...] = Field(default_factory=tuple, max_length=8)
    job_id: UUID | None = None
    expected_state_version: int = Field(ge=0)
    schema_version: Literal[1] = 1

    @field_validator("occurred_at")
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_invalid")
        return value.astimezone(UTC)


class MemoryLifecycleState(ApplicationScopedRecord):
    """Rebuildable owner-scoped projection; source Memory documents stay immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    retrieval_status: RetrievalStatus = "active"
    effective_status_at: datetime | None = None
    superseded_by_memory_id: UUID | None = None
    consolidated_into_memory_ids: tuple[UUID, ...] = Field(default_factory=tuple, max_length=8)
    last_retrieved_at: datetime | None = None
    retrieval_count: int = Field(default=0, ge=0)
    state_version: int = Field(default=0, ge=0)
    importance: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    importance_policy_version: str | None = None
    last_event_id: UUID | None = None

    @field_validator("effective_status_at", "last_retrieved_at")
    @classmethod
    def utc(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamp_invalid")
            return value.astimezone(UTC)
        return value


class MemoryLifecycleOutcome(ApplicationScopedRecord):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["applied", "replayed", "conflict"]
    state: MemoryLifecycleState | None = None
    event_id: UUID | None = None
    reason: str | None = None


class MemoryJob(ApplicationScopedRecord):
    """Durable work intent. Pub/Sub messages contain only ID and schema version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    job_type: JobType
    candidate_memory_ids: tuple[UUID, ...] = Field(max_length=4)
    policy_version: str = Field(min_length=1, max_length=100)
    policy_snapshot: dict[str, float | str | int]
    status: JobStatus = "pending"
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, gt=0, le=10)
    lease_expires_at: datetime | None = None
    lease_token: UUID | None = None
    lease_generation: int = Field(default=0, ge=0)
    idempotency_key: str = Field(min_length=1, max_length=300)
    publish_pending: bool = True
    retry_reason: str | None = Field(default=None, max_length=100)
    next_attempt_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    schema_version: Literal[1] = 1

    @field_validator("lease_expires_at", "next_attempt_at", "created_at", "updated_at")
    @classmethod
    def utc(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamp_invalid")
            return value.astimezone(UTC)
        return value

    @model_validator(mode="after")
    def lease_shape(self):
        if self.status == "leased" and (self.lease_expires_at is None or self.lease_token is None):
            raise ValueError("lease_invalid")
        if len(set(self.candidate_memory_ids)) != len(self.candidate_memory_ids):
            raise ValueError("job_source_duplicate")
        return self


@dataclass(frozen=True)
class ScorePolicy:
    version: str = "score-v1"
    similarity_weight: float = 0.50
    importance_weight: float = 0.15
    recency_weight: float = 0.15
    frequency_weight: float = 0.10
    confidence_weight: float = 0.10
    half_life_days: float = 90

    def __post_init__(self):
        weights = self.weights
        if self.version != "score-v1" or any(not math.isfinite(weight) or not 0 <= weight <= 1 for weight in weights):
            raise ValueError("score_policy_invalid")
        if sum(weights) <= 0 or not math.isfinite(self.half_life_days) or self.half_life_days <= 0:
            raise ValueError("score_policy_invalid")

    @property
    def weights(self) -> tuple[float, ...]:
        return (
            self.similarity_weight,
            self.importance_weight,
            self.recency_weight,
            self.frequency_weight,
            self.confidence_weight,
        )

    @property
    def identity(self) -> str:
        payload = json.dumps(
            {
                "version": self.version,
                "weights": self.weights,
                "half_life_days": self.half_life_days,
                "normalization": "positive-weight-sum-v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class MemoryScore:
    memory_id: UUID
    score: float | None
    similarity: float | None
    importance: float | None
    recency: float | None
    frequency: float | None
    confidence: float | None
    policy_version: str
    reason: str | None = None


IMPORTANCE_BY_TYPE = {
    "explicit_correction": 1.0,
    "preference": 0.8,
    "semantic_summary": 0.6,
    "episodic_observation": 0.4,
}


def score_memory(
    candidate: ScoredMemory,
    state: MemoryLifecycleState,
    policy: ScorePolicy,
    *,
    now: datetime,
) -> MemoryScore:
    """Compute the versioned bounded weighted score without reading memory text."""
    memory = candidate.memory
    similarity = float(candidate.similarity)
    if not math.isfinite(similarity):
        return MemoryScore(
            memory.id, None, None, None, None, None, None, policy.version, "similarity_invalid"
        )
    similarity = min(1.0, max(0.0, similarity))
    if state.importance_policy_version not in (None, "score-v1"):
        return MemoryScore(memory.id, None, similarity, None, None, None, None,
                           policy.version, "importance_policy_invalid")
    importance = state.importance
    if importance is None:
        importance = IMPORTANCE_BY_TYPE.get(memory.memory_type)
    if isinstance(memory, DerivedMemory):
        importance = min(importance or 0, memory.importance)
    effective = memory.effective_at
    age_days = max(0.0, (now.astimezone(UTC) - effective.astimezone(UTC)).total_seconds() / 86400)
    recency = 2 ** (-age_days / policy.half_life_days)
    frequency = min(state.retrieval_count / 10, 1.0)
    confidence = memory.confidence
    inputs = (similarity, importance, recency, frequency, confidence)
    if any(
        value is None or not math.isfinite(float(value)) or not 0 <= float(value) <= 1
        for value in inputs
    ):
        return MemoryScore(
            memory.id,
            None,
            similarity,
            importance,
            recency,
            frequency,
            confidence,
            policy.version,
            "score_input_invalid",
        )
    denominator = sum(policy.weights)
    score = (
        sum(value * weight for value, weight in zip(inputs, policy.weights, strict=True))
        / denominator
    )
    return MemoryScore(
        memory.id, score, similarity, importance, recency, frequency, confidence, policy.version
    )


def transition(state: MemoryLifecycleState, event: MemoryLifecycleEvent) -> MemoryLifecycleState:
    """Apply one validated transition to a projection, or raise a safe reason code."""
    if event.owner_id != state.owner_id or event.memory_id != state.memory_id:
        raise ValueError("owner_or_memory_mismatch")
    if event.expected_state_version != state.state_version:
        raise ValueError("state_version_conflict")
    changes: dict[str, object] = {
        "state_version": state.state_version + 1,
        "effective_status_at": event.occurred_at,
        "last_event_id": event.id,
    }
    if event.event_type == "consolidated":
        changes["consolidated_into_memory_ids"] = tuple(
            sorted(set(state.consolidated_into_memory_ids) | set(event.related_memory_ids), key=str)
        )
    elif event.event_type == "retrieved":
        changes["retrieval_count"] = state.retrieval_count + 1
        changes["last_retrieved_at"] = event.occurred_at
        changes["effective_status_at"] = state.effective_status_at
    elif event.event_type == "superseded":
        if (
            state.retrieval_status != "active"
            or len(event.related_memory_ids) != 1
            or event.related_memory_ids[0] == state.memory_id
        ):
            raise ValueError("transition_invalid")
        changes["retrieval_status"] = "superseded"
        changes["superseded_by_memory_id"] = event.related_memory_ids[0]
    elif event.event_type == "forgotten":
        if state.retrieval_status != "active":
            raise ValueError("transition_invalid")
        changes["retrieval_status"] = "forgotten"
    elif event.event_type == "reactivated":
        if state.retrieval_status == "active" or state.superseded_by_memory_id is not None:
            raise ValueError("transition_invalid")
        changes["retrieval_status"] = "active"
        changes["effective_status_at"] = event.occurred_at
    elif event.event_type == "review_required":
        changes["effective_status_at"] = state.effective_status_at
    else:
        raise ValueError("event_type_invalid")
    return MemoryLifecycleState.model_validate({**state.model_dump(), **changes})


class MemoryLifecycleRepository(Protocol):
    def get_state(self, *, owner_id: str, memory_id: UUID) -> MemoryLifecycleState: ...
    def list_events(self, *, owner_id: str, memory_id: UUID, limit: int = 50): ...
    def find_event(self, *, owner_id: str, memory_id: UUID, idempotency_key: str): ...
    def apply_event(
        self,
        event: MemoryLifecycleEvent,
        *,
        completed_assistant_id: UUID | None = None,
        job: MemoryJob | None = None,
        lease_token: UUID | None = None,
    ) -> MemoryLifecycleOutcome: ...
    def create_job(self, job: MemoryJob) -> tuple[MemoryJob, bool]: ...
    def get_job(self, *, owner_id: str, job_id: UUID) -> MemoryJob: ...
    def get_job_by_id(self, *, job_id: UUID) -> MemoryJob: ...
    def claim_job(self, *, owner_id: str, job_id: UUID, now: datetime, lease_seconds: int): ...
    def complete_job(self, job: MemoryJob, *, token: UUID, now: datetime): ...
    def fail_job(
        self, job: MemoryJob, *, token: UUID, now: datetime, reason: str, retryable: bool
    ): ...
    def dependencies(self, *, owner_id: str, memory_id: UUID, limit: int = 100): ...
    def discover_related(self, *, owner_id: str, memory_id: UUID, limit: int = 4): ...
    def discover_forgetting_candidates(
        self, *, owner_id: str, older_than: datetime, limit: int = 4
    ): ...
    def discover_maintenance_candidates(self, *, owner_id: str, limit: int = 4): ...


MemoryRecord = Memory | DerivedMemory
