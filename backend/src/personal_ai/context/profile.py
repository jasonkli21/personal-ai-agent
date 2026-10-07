"""Owner-wide AI preferences and their explicit application-sharing policy."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from threading import RLock
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_ai.auth.scope import RequestScope
from personal_ai.context.providers import (
    ContextItem,
    ContextOperationSpec,
    ContextPermissionDependency,
    ContextProviderError,
    ContextProviderInputs,
    ContextProviderSpec,
    ContextSelection,
    ContextSourceReference,
)

ProfileField = Literal["preferred_units", "locale", "response_style", "answer_length"]
_FIELD_VALUES = {
    "preferred_units": {"metric", "imperial"},
    "response_style": {"concise", "balanced", "detailed"},
    "answer_length": {"short", "standard", "expanded"},
}


class GlobalProfileFieldUpdate(BaseModel):
    """One explicit user-set value and the applications allowed to receive it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: ProfileField
    value: str = Field(min_length=1, max_length=100)
    shared_with_applications: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("shared_with_applications")
    @classmethod
    def sharing_is_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("profile_sharing_applications_must_be_unique")
        return value

    @model_validator(mode="after")
    def field_value_matches_vocabulary(self) -> GlobalProfileFieldUpdate:
        if self.field == "locale":
            import re

            if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,4}", self.value):
                raise ValueError("profile_locale_invalid")
        elif self.value not in _FIELD_VALUES[self.field]:
            raise ValueError("profile_value_invalid")
        if any(not item or len(item) > 42 for item in self.shared_with_applications):
            raise ValueError("profile_sharing_application_invalid")
        return self


class GlobalProfileFieldRecord(GlobalProfileFieldUpdate):
    """Persisted value with unambiguous user-set provenance."""

    set_by: Literal["user"] = "user"
    set_at: datetime

    @field_validator("set_at")
    @classmethod
    def timestamp_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("profile_timestamp_timezone_required")
        return value.astimezone(UTC)


class GlobalProfile(BaseModel):
    """Sparse AI-owned profile; it never contains domain-owned records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["global-profile-v1"] = "global-profile-v1"
    owner_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=0)
    fields: tuple[GlobalProfileFieldRecord, ...] = Field(default=(), max_length=4)
    updated_at: datetime | None = None

    @field_validator("updated_at")
    @classmethod
    def updated_timestamp_is_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("profile_timestamp_timezone_required")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def sparse_fields_are_unique(self) -> GlobalProfile:
        names = [item.field for item in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("profile_fields_must_be_unique")
        if (self.revision == 0) != (self.updated_at is None):
            raise ValueError("profile_revision_timestamp_mismatch")
        return self


class GlobalProfileUpdate(BaseModel):
    """Partial owner-authenticated profile update; no inferred values are accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fields: tuple[GlobalProfileFieldUpdate, ...] = Field(default=(), max_length=4)
    remove_fields: tuple[ProfileField, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def update_is_unambiguous(self) -> GlobalProfileUpdate:
        names = [item.field for item in self.fields]
        if len(names) != len(set(names)) or len(self.remove_fields) != len(set(self.remove_fields)):
            raise ValueError("profile_update_fields_must_be_unique")
        if set(names) & set(self.remove_fields):
            raise ValueError("profile_update_fields_conflict")
        if not names and not self.remove_fields:
            raise ValueError("profile_update_empty")
        return self


class GlobalProfileContextField(BaseModel):
    """Only the value selected for this application, without other share targets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: ProfileField
    value: str
    set_by: Literal["user"]
    set_at: datetime


class GlobalProfileRepository(Protocol):
    """Owner-only profile storage, with filtered sharing reads for providers."""

    def get(self, owner_id: str) -> GlobalProfile: ...
    def update(self, owner_id: str, update: GlobalProfileUpdate) -> GlobalProfile: ...
    def shared_fields(
        self,
        owner_id: str,
        application_id: str,
        fields: Sequence[ProfileField],
        *,
        deadline: float | None = None,
    ) -> tuple[tuple[int, GlobalProfileFieldRecord], ...]: ...


class InMemoryGlobalProfileRepository:
    """Deterministic profile repository for tests and offline fixtures."""

    def __init__(self, *, clock=None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self.records: dict[str, GlobalProfile] = {}
        self._lock = RLock()

    def get(self, owner_id: str) -> GlobalProfile:
        with self._lock:
            return self.records.get(
                owner_id,
                GlobalProfile(owner_id=owner_id, revision=0, fields=(), updated_at=None),
            )

    def update(self, owner_id: str, update: GlobalProfileUpdate) -> GlobalProfile:
        now = self._clock().astimezone(UTC)
        with self._lock:
            current = self.records.get(owner_id)
            fields = {item.field: item for item in current.fields} if current else {}
            for name in update.remove_fields:
                fields.pop(name, None)
            for item in update.fields:
                fields[item.field] = GlobalProfileFieldRecord(
                    **item.model_dump(), set_by="user", set_at=now
                )
            candidate = GlobalProfile(
                owner_id=owner_id,
                revision=(current.revision if current else 0) + 1,
                fields=tuple(fields[key] for key in sorted(fields)),
                updated_at=now,
            )
            self.records[owner_id] = candidate
            return candidate

    def shared_fields(self, owner_id, application_id, fields, *, deadline=None):
        del deadline
        allowed = set(fields)
        with self._lock:
            profile = self.records.get(owner_id)
            if profile is None:
                return ()
            return tuple(
                (profile.revision, item)
                for item in profile.fields
                if item.field in allowed and application_id in item.shared_with_applications
            )


class GlobalProfileContextProvider:
    spec = ContextProviderSpec(
        provider_id="global_profile",
        source_class="global_profile",
        source_version="global-profile-context-v1",
        operations=(
            ContextOperationSpec(
                operation="profile",
                allowed_fields=("preferred_units", "locale", "response_style", "answer_length"),
                results_per_field=True,
                maximum_results=4,
                maximum_bytes=16_384,
                maximum_timeout_seconds=2,
            ),
        ),
        maximum_items_per_call=4,
    )

    def __init__(self, repository: GlobalProfileRepository, inputs: ContextProviderInputs) -> None:
        self.repository = repository
        self.inputs = inputs

    def validate_selection(self, selection: ContextSelection, inputs: ContextProviderInputs):
        del selection
        if inputs.scope != self.inputs.scope:
            raise ContextProviderError("context_provider_scope_mismatch")

    def fetch(self, selection: ContextSelection, scope: RequestScope, *, deadline: float):
        fields = self.repository.shared_fields(
            scope.owner_id,
            scope.application_id,
            tuple(selection.fields),
            deadline=deadline,
        )
        by_field = {item.field: (revision, item) for revision, item in fields}
        bounded = tuple(
            by_field[name]
            for name in selection.fields
            if name in by_field
        )[: selection.max_results]
        return tuple(
            ContextItem(
                source_class="global_profile",
                provider_id=self.spec.provider_id,
                source_id="owner-global-profile",
                source_version=f"global-profile-v1:{revision}",
                item_id=item.field,
                owner_id=scope.owner_id,
                application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                authority="user_asserted",
                observed_at=item.set_at,
                sensitivity="personal",
                source_refs=(
                    ContextSourceReference(
                        kind="record", reference_id=f"global-profile:{scope.owner_id}:{item.field}"
                    ),
                ),
                permission_dependencies=(
                    ContextPermissionDependency(
                        permission_id=f"global_profile_share:{item.field}:{scope.application_id}",
                        version="global-profile-v1",
                        purpose="user-authorized field sharing",
                    ),
                ),
                payload=GlobalProfileContextField(
                    field=item.field,
                    value=item.value,
                    set_by=item.set_by,
                    set_at=item.set_at,
                ),
            )
            for revision, item in bounded
        )


class GlobalProfileContextProviderFactory:
    spec = GlobalProfileContextProvider.spec

    def __init__(self, repository: GlobalProfileRepository) -> None:
        self.repository = repository

    def create(self, inputs: ContextProviderInputs) -> GlobalProfileContextProvider:
        return GlobalProfileContextProvider(self.repository, inputs)
