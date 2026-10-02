"""Versioned immutable observations and expiring evidence, never user memory."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ResearchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator(
        "created_at",
        "updated_at",
        "observed_at",
        "expires_at",
        "started_at",
        "completed_at",
        "executed_at",
        "published_at",
        "execution_deadline",
        check_fields=False,
    )
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value.astimezone(UTC)


class SearchQuery(ResearchRecord):
    id: UUID
    session_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    normalized_query: str = Field(min_length=1, max_length=500)
    rationale_code: Literal["question", "terminology"] = "question"
    sequence: int = Field(ge=0, le=2)
    state: Literal["planned", "completed", "failed"] = "planned"
    created_at: datetime
    executed_at: datetime | None = None


class AdapterAttempt(ResearchRecord):
    id: UUID
    session_id: UUID
    query_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    adapter: Literal["fake", "brave"]
    idempotency_key: str = Field(min_length=1, max_length=200)
    attempt_number: int = Field(ge=1, le=3)
    status: Literal["started", "completed", "failed"]
    parent_attempt_id: UUID | None = None
    started_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=80)


class SourceObservation(ResearchRecord):
    id: UUID
    session_id: UUID
    query_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    canonical_url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    provider: Literal["fake", "brave"]
    observed_at: datetime
    published_at: datetime | None = None
    content_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    status: Literal["accepted", "empty", "unsafe", "oversized", "stale"]
    attempt_id: UUID

    @model_validator(mode="after")
    def safe_source(self):
        from personal_ai.search.policy import canonical_url

        if self.status == "accepted" and (
            canonical_url(self.canonical_url) != self.canonical_url or not self.content_fingerprint
        ):
            raise ValueError("invalid attribution")
        return self


class Evidence(ResearchRecord):
    id: UUID
    session_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    source_observation_ids: tuple[UUID, ...] = Field(min_length=1, max_length=12)
    passage: str = Field(min_length=1, max_length=1200)
    content_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: datetime
    expires_at: datetime
    expiry_policy: Literal["general", "current"]
    extraction_version: Literal["snippet-v1"] = "snippet-v1"
    status: Literal["eligible"] = "eligible"
    near_duplicate_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def expiry(self):
        if self.expires_at <= self.observed_at or not self.passage.strip():
            raise ValueError("invalid evidence")
        expected = sha256(" ".join(self.passage.split()).encode()).hexdigest()
        if self.content_fingerprint != expected or len(set(self.source_observation_ids)) != len(
            self.source_observation_ids
        ):
            raise ValueError("invalid content provenance")
        return self


class EvidenceSelection(ResearchRecord):
    id: UUID
    session_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    evidence_ids: tuple[UUID, ...] = Field(max_length=12)
    excluded: dict[str, str]
    scores: dict[str, dict[str, float]]
    selector_policy_version: Literal["select-v1"] = "select-v1"
    token_count: int = Field(ge=0)
    counter_kind: Literal["provider", "estimated"]
    created_at: datetime
