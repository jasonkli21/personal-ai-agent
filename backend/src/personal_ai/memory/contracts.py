"""Immutable, provider-neutral durable user knowledge and workflow outcomes."""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_ai.entities import Message

MemoryType = Literal[
    "preference", "episodic_observation", "semantic_summary", "explicit_correction"
]

LifecycleEventType = Literal[
    "consolidated", "superseded", "forgotten", "reactivated", "retrieved", "review_required"
]


def normalize(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip().casefold()


def vector(values: Sequence[float], dimensions: int) -> tuple[float, ...]:
    if len(values) != dimensions or any(
        isinstance(v, bool) or not math.isfinite(v) for v in values
    ):
        raise ValueError("embedding_invalid")
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("embedding_invalid")
    return tuple(v / norm for v in values)


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    memory_type: MemoryType
    content: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    source_message_ids: tuple[UUID, ...] = Field(min_length=1, max_length=2)
    effective_at: datetime | None = None
    rationale_code: Literal[
        "user_preference", "user_experience", "user_generalization", "user_correction"
    ]

    @field_validator("effective_at")
    @classmethod
    def utc(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamp_invalid")
            return value.astimezone(UTC)
        return value


class Memory(MemoryCandidate):
    id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    normalized_content: str = Field(min_length=1, max_length=1000)
    status: Literal["active", "rejected"] = "active"
    source_conversation_id: UUID
    source_turn_id: UUID
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    effective_at: datetime
    created_at: datetime
    embedding: tuple[float, ...]
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_dimensions: int = Field(gt=0, le=2048)
    schema_version: Literal[1] = 1

    @field_validator("embedding", mode="before")
    @classmethod
    def numeric_vector(cls, values):
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values):
            raise ValueError("embedding_invalid")
        return values

    @field_validator("observed_at", "created_at")
    @classmethod
    def timestamps(cls, value):
        return cls.utc(value)

    @model_validator(mode="after")
    def valid(self):
        if self.normalized_content != normalize(self.content) or not self.normalized_content:
            raise ValueError("content_invalid")
        vector(self.embedding, self.embedding_dimensions)
        if len(set(self.source_message_ids)) != len(self.source_message_ids):
            raise ValueError("source_invalid")
        return self


class DerivedMemorySource(BaseModel):
    """Original v1 source record references for a multi-conversation derivation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: UUID
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_conversation_id: UUID
    source_turn_id: UUID
    source_message_ids: tuple[UUID, ...] = Field(min_length=1, max_length=2)
    excerpt: str = Field(min_length=1, max_length=1000)


class DerivedMemory(BaseModel):
    """Explicit schema for a bounded multi-source, extractive memory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    memory_type: Literal["preference", "semantic_summary"]
    content: str = Field(min_length=1, max_length=1000)
    normalized_content: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    importance: float = Field(ge=0, le=1, allow_inf_nan=False)
    effective_at: datetime
    created_at: datetime
    embedding: tuple[float, ...]
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_dimensions: int = Field(gt=0, le=2048)
    source_memory_ids: tuple[UUID, ...] = Field(min_length=2, max_length=4)
    sources: tuple[DerivedMemorySource, ...] = Field(min_length=2, max_length=4)
    source_set_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    derivation_policy_version: str = Field(min_length=1, max_length=100)
    rationale_code: Literal["repeated_explicit_preference", "compatible_episode_history"]
    schema_version: Literal[2] = 2

    @field_validator("embedding", mode="before")
    @classmethod
    def numeric_vector(cls, values):
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values):
            raise ValueError("embedding_invalid")
        return values

    @field_validator("effective_at", "created_at")
    @classmethod
    def timestamps(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_invalid")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid(self):
        if self.normalized_content != normalize(self.content) or not self.normalized_content:
            raise ValueError("content_invalid")
        if tuple(source.memory_id for source in self.sources) != self.source_memory_ids:
            raise ValueError("source_invalid")
        if len(set(self.source_memory_ids)) != len(self.source_memory_ids):
            raise ValueError("source_invalid")
        if any(normalize(source.excerpt) not in normalize(self.content) for source in self.sources):
            raise ValueError("source_coverage_invalid")
        vector(self.embedding, self.embedding_dimensions)
        return self


def identity(owner: str, fingerprint: str, candidate: MemoryCandidate) -> UUID:
    key = sha256(
        (
            owner
            + "\0"
            + fingerprint
            + "\0"
            + candidate.memory_type
            + "\0"
            + normalize(candidate.content)
        ).encode()
    ).hexdigest()
    return uuid5(NAMESPACE_URL, "personal-ai-memory:" + key)


@dataclass(frozen=True)
class ScoredMemory:
    memory: Memory | DerivedMemory
    similarity: float


@dataclass(frozen=True)
class RetrievalResult:
    candidates: tuple[ScoredMemory, ...] = ()
    selected: tuple[ScoredMemory, ...] = ()
    excluded: tuple[tuple[UUID, str], ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractionResult:
    created: tuple[UUID, ...] = ()
    skipped: tuple[UUID, ...] = ()
    reasons: tuple[str, ...] = ()


class Embedder(Protocol):
    def embed(
        self, texts: Sequence[str], *, query: bool = False, timeout: float | None = None
    ) -> Sequence[tuple[float, ...]]: ...


class MemoryExtractor(Protocol):
    def extract(
        self, source_turn: Sequence[Message], *, timeout: float
    ) -> Sequence[MemoryCandidate]: ...


class MemoryRepository(Protocol):
    def create(self, memory: Memory, *, timeout: float = 5) -> tuple[Memory, bool]: ...
    def get(self, *, owner_id: str, memory_id: UUID, timeout: float = 5) -> Memory: ...
    def search(
        self,
        *,
        owner_id: str,
        embedding: Sequence[float],
        model: str,
        dimensions: int,
        limit: int,
        timeout: float = 5,
    ) -> Sequence[ScoredMemory]: ...
