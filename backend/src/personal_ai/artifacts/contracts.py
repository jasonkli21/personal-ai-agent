"""Service-owned keys and bounded, secret-free artifact references."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_ai.auth.scope import ApplicationScope

ArtifactKind = Literal["context_trace", "routing_trace", "evaluation", "export", "debug_replay"]
ArtifactStatus = Literal["pending", "ready", "missing", "deleting", "deleted"]
MAX_RAW_BYTES = 8 * 1024 * 1024
MAX_COMPRESSED_BYTES = 1024 * 1024
MAX_REF_BYTES = 8192


class ArtifactUnavailable(RuntimeError):
    """An artifact is unauthorized, incomplete, expired or corrupt."""


class ArtifactConflict(ArtifactUnavailable):
    """Immutable identity or lifecycle revision conflicts."""


class ArtifactBudgetExceeded(ArtifactUnavailable):
    """A byte, operation, object or retention ceiling denies work."""


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    scope: ApplicationScope
    kind: ArtifactKind
    identity: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    # These IDs join authoritative records; they never duplicate admission state.
    routing_decision_id: UUID | None = None
    invocation_id: UUID | None = None
    evaluation_run_id: UUID | None = None
    cascade_run_id: UUID | None = None
    key: str = Field(pattern=r"^artifacts/v1/[0-9a-f]{64}/[0-9a-f-]{36}\.jsonl?\.gz$")
    store_id: str = Field(
        default="memory:local", pattern=r"^(memory:local|gcs:[a-z0-9][a-z0-9._-]{1,61}[a-z0-9])$"
    )
    generation: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,29}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compressed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compressed_bytes: int = Field(ge=1, le=MAX_COMPRESSED_BYTES)
    uncompressed_bytes: int = Field(ge=1, le=MAX_RAW_BYTES)
    sensitivity: Literal["public", "personal", "sensitive", "restricted"] = "personal"
    grant_dependencies: tuple[str, ...] = Field(default=(), max_length=32)
    schema_version: str = Field(min_length=1, max_length=100)
    content_type: Literal["application/json", "application/x-ndjson"]
    compression: Literal["gzip"] = "gzip"
    created_at: datetime
    expires_at: datetime
    source_rights_until: datetime | None = None
    status: ArtifactStatus = "pending"
    revision: int = Field(default=1, ge=1)
    # Numeric summaries only: no arbitrary text/blob escape hatch.
    summary: dict[str, int | bool] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def bounded(self):
        for value in (self.created_at, self.expires_at, self.source_rights_until):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("artifact_timezone_required")
        namespace = hashlib.sha256(
            json.dumps(
                [self.owner_id, self.scope.application_id, self.scope.workspace_id],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        extension = "jsonl" if self.content_type == "application/x-ndjson" else "json"
        if self.key != f"artifacts/v1/{namespace}/{self.artifact_id}.{extension}.gz":
            raise ValueError("artifact_key_scope_invalid")
        lifetime = (self.expires_at - self.created_at).total_seconds()
        if not 0 < lifetime <= 90 * 86400:
            raise ValueError("artifact_retention_invalid")
        if self.source_rights_until is not None and self.expires_at > self.source_rights_until:
            raise ValueError("artifact_source_rights_expiry")
        if self.status == "ready" and self.generation is None:
            raise ValueError("artifact_ready_generation_required")
        if any(not item or len(item) > 100 for item in self.grant_dependencies):
            raise ValueError("artifact_dependencies_invalid")
        if any(not key.isidentifier() or len(key) > 64 for key in self.summary):
            raise ValueError("artifact_summary_invalid")
        if (
            len(json.dumps(self.model_dump(mode="json"), ensure_ascii=False).encode())
            > MAX_REF_BYTES
        ):
            raise ValueError("artifact_reference_too_large")
        return self

    def available_at(self, now: datetime) -> bool:
        return self.status == "ready" and now.astimezone(UTC) < self.expires_at


class ArtifactStore(Protocol):
    """Private immutable bodies. Implementations accept server-generated keys only."""

    store_id: str

    def put(self, key: str, body: bytes) -> str: ...
    def generation(self, key: str) -> str | None: ...
    def read(self, key: str, generation: str, *, max_bytes: int) -> bytes: ...
    def delete(self, key: str, generation: str) -> None: ...


class ArtifactMetadataRepository(Protocol):
    def begin(self, ref: ArtifactRef) -> ArtifactRef: ...
    def begin_reserved(
        self,
        ref: ArtifactRef,
        *,
        operations: int,
        byte_count: int,
        objects: int = 0,
        read_bytes: int = 0,
    ) -> ArtifactRef: ...
    def get(self, artifact_id: UUID, *, owner_id: str, scope: ApplicationScope) -> ArtifactRef: ...
    def update(self, ref: ArtifactRef, *, expected_revision: int) -> ArtifactRef: ...
    def claim_owner_deletion(self, ref: ArtifactRef) -> ArtifactRef: ...
    def batch(self, *, limit: int, owner_id: str | None = None) -> tuple[ArtifactRef, ...]: ...
    def reserve(
        self, *, operations: int, byte_count: int, objects: int = 0, read_bytes: int = 0
    ) -> None: ...
    def active(self, owner_id: str) -> bool: ...
    def fence(self, owner_id: str) -> None: ...
    def observations(self) -> dict: ...
    def assert_store_compatible(self, store_id: str) -> None: ...


def validate_transition(previous: ArtifactRef, updated: ArtifactRef):
    mutable = {"status", "generation", "revision"}
    if previous.model_dump(exclude=mutable) != updated.model_dump(exclude=mutable):
        raise ArtifactConflict("artifact_immutable_metadata")
    allowed = {
        "pending": {"ready", "missing", "deleting"},
        "ready": {"missing", "deleting"},
        "missing": {"missing", "ready", "deleting"},
        "deleting": {"deleted"},
        "deleted": set(),
    }
    if updated.status not in allowed[previous.status]:
        raise ArtifactConflict("artifact_state_transition")
    if previous.generation is not None and previous.generation != updated.generation:
        raise ArtifactConflict("artifact_generation_immutable")


def same_publication_identity(previous: ArtifactRef, proposed: ArtifactRef) -> bool:
    """Compare immutable content while allowing concurrent writers' creation clocks to differ."""
    variable = {"status", "revision", "generation", "created_at", "expires_at"}
    return previous.model_dump(exclude=variable) == proposed.model_dump(exclude=variable)
