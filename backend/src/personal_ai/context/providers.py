"""Typed, bounded context-source contracts and provider admission.

Provider implementations own their storage details. The coordinator resolves
only capabilities registered for the authenticated application and validates
the complete selection set before it lets any provider run.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from personal_ai.applications.contracts import (
    ApplicationContextRequest,
    CapabilityRegistration,
)
from personal_ai.auth.scope import ApplicationScope, RequestScope
from personal_ai.memory.contracts import RetrievalResult

ContextSourceClass = Literal[
    "global_profile",
    "domain_profile",
    "domain_current",
    "domain_history",
    "ai_memory",
    "conversation",
    "external_research",
    "tool_result",
    "client_context",
]
ContextOperation = Literal["profile", "current", "entity", "history", "search"]
ContextAuthority = Literal[
    "authoritative", "user_asserted", "derived", "external", "client_supplied", "unknown"
]
ContextSensitivity = Literal["public", "personal", "sensitive", "restricted", "unknown"]
CapabilityKind = Literal["context_provider", "tool"]

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class ContextEntityReference(BaseModel):
    """An exact entity reference that keeps its application/workspace scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_type: str = Field(min_length=1, max_length=80)
    entity_id: str = Field(min_length=1, max_length=200)
    application_id: str = Field(min_length=2, max_length=42)
    workspace_id: str | None = Field(default=None, max_length=100)


class ContextSourceReference(BaseModel):
    """A stable pointer to the source record or external observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["record", "conversation_message", "evidence", "url", "tool_invocation"]
    reference_id: str = Field(min_length=1, max_length=512)
    uri: str | None = Field(default=None, max_length=2048)
    fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ContextPermissionDependency(BaseModel):
    """Permission or capability identity required to disclose an item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    permission_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=160)


class ContextFieldSensitivity(BaseModel):
    """Sensitivity assigned to one field in the disclosed typed payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    sensitivity: ContextSensitivity


class ContextItem(BaseModel, Generic[PayloadT]):
    """Normalized metadata around a domain-typed payload.

    Unknown authority and timestamps remain explicit ``unknown``/``None``;
    source references and permission dependencies are never synthesized.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    source_class: ContextSourceClass
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,80}$")
    source_id: str = Field(min_length=1, max_length=200)
    source_version: str = Field(min_length=1, max_length=100)
    item_id: str = Field(min_length=1, max_length=200)
    owner_id: str = Field(min_length=1, max_length=200)
    application_id: str = Field(min_length=2, max_length=42)
    workspace_id: str | None = Field(default=None, max_length=100)
    entity_refs: tuple[ContextEntityReference, ...] = Field(default=(), max_length=32)
    authority: ContextAuthority = "unknown"
    observed_at: datetime | None = None
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    sensitivity: ContextSensitivity = "unknown"
    source_refs: tuple[ContextSourceReference, ...] = Field(default=(), max_length=200)
    represented_item_ids: tuple[str, ...] = Field(default=(), max_length=32)
    permission_dependencies: tuple[ContextPermissionDependency, ...] = Field(
        default=(), max_length=16
    )
    selected_operation: ContextOperation | None = Field(default=None, exclude=True)
    field_sensitivity: tuple[ContextFieldSensitivity, ...] = Field(default=(), max_length=32)
    payload: PayloadT

    @field_validator("payload", mode="before")
    @classmethod
    def payload_is_typed(cls, value: Any) -> Any:
        if not isinstance(value, BaseModel):
            raise TypeError("context_payload_must_be_typed")
        return value

    @field_validator("observed_at", "effective_at", "expires_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("context_timestamp_timezone_required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def references_are_unambiguous(self) -> ContextItem[PayloadT]:
        if not self.source_refs:
            raise ValueError("context_source_refs_required")
        if (
            self.observed_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.observed_at
        ):
            raise ValueError("context_expiry_must_follow_observation")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("context_source_refs_must_be_unique")
        if len(set(self.entity_refs)) != len(self.entity_refs):
            raise ValueError("context_entity_refs_must_be_unique")
        if len(set(self.represented_item_ids)) != len(self.represented_item_ids):
            raise ValueError("context_represented_item_ids_must_be_unique")
        if self.represented_item_ids and (
            self.source_class != "ai_memory"
            or self.provider_id != "ai_memory"
            or self.authority != "derived"
            or getattr(self.payload, "record_kind", None) != "derived_memory"
            or self.item_id in self.represented_item_ids
        ):
            raise ValueError("context_represented_items_require_derived_memory")
        if self.source_class in {"external_research", "client_context"} and (
            self.authority == "authoritative"
        ):
            raise ValueError("context_source_authority_ceiling")
        fields = [item.field for item in self.field_sensitivity]
        if len(fields) != len(set(fields)):
            raise ValueError("context_field_sensitivity_must_be_unique")
        payload_fields = set(type(self.payload).model_fields)
        if set(fields) - payload_fields:
            raise ValueError("context_field_sensitivity_outside_payload")
        disclosed_fields = set(self.payload.model_dump(exclude_none=True))
        if disclosed_fields - payload_fields:
            raise ValueError("context_payload_projection_invalid")
        missing_labels = disclosed_fields - set(fields)
        if missing_labels:
            # Field labels default to the conservative item-level classification;
            # providers can be more precise for mixed-sensitivity projections.
            expanded = (*self.field_sensitivity, *(
                ContextFieldSensitivity(field=name, sensitivity=self.sensitivity)
                for name in sorted(missing_labels)
            ))
            if len(expanded) > 32:
                raise ValueError("context_field_sensitivity_limit_exceeded")
            object.__setattr__(self, "field_sensitivity", expanded)
            fields.extend(sorted(missing_labels))
        sensitivity_rank = {
            "public": 0,
            "personal": 1,
            "sensitive": 2,
            "restricted": 3,
            "unknown": 4,
        }
        if self.field_sensitivity and sensitivity_rank[self.sensitivity] < max(
            sensitivity_rank[item.sensitivity] for item in self.field_sensitivity
        ):
            raise ValueError("context_aggregate_sensitivity_understated")
        return self


class ContextSelection(BaseModel):
    """A bounded, explicit source operation selected before retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,80}$")
    operation: ContextOperation
    fields: tuple[str, ...] = Field(default=(), max_length=32)
    entity_refs: tuple[ContextEntityReference, ...] = Field(default=(), max_length=16)
    window_start: datetime | None = None
    window_end: datetime | None = None
    max_results: int = Field(default=10, ge=1, le=50)
    max_bytes: int = Field(default=16_384, ge=1, le=65_536)
    max_tokens: int | None = Field(default=None, ge=1, le=128_000)
    timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    required: bool = False
    target_scope: ApplicationScope | None = None

    @field_validator("window_start", "window_end")
    @classmethod
    def window_timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("context_window_timezone_required")
        return value.astimezone(UTC)

    @field_validator("fields")
    @classmethod
    def fields_are_unique_and_named(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        import re

        if len(values) != len(set(values)) or any(
            not re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", value) for value in values
        ):
            raise ValueError("context_fields_invalid")
        return values

    @model_validator(mode="after")
    def window_is_complete(self) -> ContextSelection:
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("context_window_incomplete")
        if self.window_start is not None and self.window_end <= self.window_start:
            raise ValueError("context_window_invalid")
        if len(set(self.entity_refs)) != len(self.entity_refs):
            raise ValueError("context_entity_refs_must_be_unique")
        return self


class ContextOperationSpec(BaseModel):
    """Provider-specific admission limits for one advertised operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: ContextOperation
    allowed_fields: tuple[str, ...] = Field(default=(), max_length=32)
    dynamic_fields: bool = False
    fields_required: bool = True
    results_per_field: bool = False
    accepts_entity_refs: bool = False
    requires_time_window: bool = False
    maximum_window_seconds: int = Field(default=0, ge=0, le=31_536_000)
    maximum_results: int = Field(default=10, ge=1, le=50)
    maximum_bytes: int = Field(default=16_384, ge=1, le=65_536)
    maximum_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    @model_validator(mode="after")
    def operation_limits_are_consistent(self) -> ContextOperationSpec:
        if len(set(self.allowed_fields)) != len(self.allowed_fields):
            raise ValueError("context_operation_fields_must_be_unique")
        if self.dynamic_fields and self.allowed_fields:
            raise ValueError("context_dynamic_fields_cannot_have_static_fields")
        if self.results_per_field and (self.dynamic_fields or not self.fields_required):
            raise ValueError("context_results_per_field_requires_static_fields")
        if self.results_per_field and len(self.allowed_fields) > self.maximum_results:
            raise ValueError("context_results_per_field_exceeds_result_limit")
        if self.requires_time_window and self.maximum_window_seconds < 1:
            raise ValueError("context_time_window_bound_required")
        return self


class ContextProviderSpec(BaseModel):
    """The source identity, class, capability kind, and supported operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,80}$")
    source_class: ContextSourceClass
    source_version: str = Field(min_length=1, max_length=100)
    capability_kind: CapabilityKind = "context_provider"
    operations: tuple[ContextOperationSpec, ...] = Field(min_length=1, max_length=5)
    maximum_items_per_call: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def operations_are_unique(self) -> ContextProviderSpec:
        names = [item.operation for item in self.operations]
        if len(names) != len(set(names)):
            raise ValueError("context_provider_operations_must_be_unique")
        if (self.capability_kind == "tool") != (self.source_class == "tool_result"):
            raise ValueError("context_provider_tool_source_class_mismatch")
        return self

    def operation(self, name: ContextOperation) -> ContextOperationSpec | None:
        return next((item for item in self.operations if item.operation == name), None)


class ContextProviderFailure(BaseModel):
    """A bounded, safe result for an optional source that could not answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str
    operation: ContextOperation
    reason: Literal[
        "unavailable", "timeout", "unsupported_operation", "source_failed", "empty",
        "summary_provenance_limit", "summary_response_limit",
    ]


class ContextProviderResult(BaseModel):
    """Normalized response containing domain-typed items and safe failure reasons."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    items: tuple[ContextItem[Any], ...] = Field(default=(), max_length=100)
    failures: tuple[ContextProviderFailure, ...] = Field(default=(), max_length=16)


class ContextProviderError(RuntimeError):
    """Safe provider error. The message contains only its stable error code."""

    def __init__(self, code: str = "context_provider_unavailable") -> None:
        self.code = code
        super().__init__(code)


def tool_result_projection_is_valid(
    projected: Any, selected_fields: Sequence[str]
) -> bool:
    """Return whether a typed tool payload contains only its selected fields."""
    if not isinstance(projected, BaseModel):
        return False
    values = projected.model_dump(mode="python", exclude_none=False)
    return set(selected_fields).issubset(type(projected).model_fields) and not any(
        value is not None
        for field, value in values.items()
        if field not in selected_fields
    )


class ContextPreparationError(RuntimeError):
    """Context cannot be prepared without a required, admitted source."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ContextProviderInputs:
    """Already-authorized snapshots available to adapters for this one turn."""

    scope: RequestScope
    application_context: ApplicationContextRequest | None = None
    active_messages: tuple[Any, ...] = ()
    summary: Any | None = None
    retrieval: RetrievalResult | None = None
    evidence_records: tuple[Any, ...] = ()
    tool_results: Mapping[str, Any] | None = None


class ContextProvider(Protocol):
    """A single bounded source operation implementation.

    ``fetch`` receives an absolute monotonic deadline. Providers must treat it
    as a cooperative contract and pass the remaining budget to blocking
    dependencies. The synchronous coordinator cannot cancel a non-cooperative
    call; it detects and reports an overrun after that call returns.
    """

    spec: ContextProviderSpec

    def validate_selection(
        self, selection: ContextSelection, inputs: ContextProviderInputs
    ) -> None: ...

    def fetch(
        self, selection: ContextSelection, scope: RequestScope, *, deadline: float
    ) -> Sequence[ContextItem[Any]] | ContextProviderResult: ...


class ContextProviderFactory(Protocol):
    """Build a request-bound provider from data already loaded by its owner."""

    spec: ContextProviderSpec

    def create(self, inputs: ContextProviderInputs) -> ContextProvider: ...


class StaticContextProviderFactory:
    """Convenience factory for deterministic or synthetic provider instances."""

    def __init__(self, provider: ContextProvider) -> None:
        self.spec = provider.spec
        self._provider = provider

    def create(self, inputs: ContextProviderInputs) -> ContextProvider:
        del inputs
        return self._provider


class ContextProviderCoordinator:
    """Resolve registered providers and enforce bounds before any source call."""

    MAX_SELECTIONS = 16
    MAX_TOTAL_ITEMS = 100
    MAX_TOTAL_BYTES = 131_072

    def __init__(
        self,
        providers: Mapping[str, ContextProviderFactory | ContextProvider],
        *,
        feature_flags: Mapping[str, bool] | None = None,
    ) -> None:
        self._providers = dict(providers)
        self._feature_flags = dict(feature_flags or {})
        for provider_id, provider in self._providers.items():
            if provider_id != provider.spec.provider_id:
                raise ValueError("context_provider_identity_mismatch")
            try:
                ContextProviderSpec.model_validate(provider.spec.model_dump())
            except ValidationError as error:
                raise ValueError("context_provider_spec_invalid") from error

    def _factory(self, provider_id: str):
        return self._providers.get(provider_id)

    def planning_capability(self, context: ApplicationContextRequest, provider_id: str):
        """Describe whether a registered provider can be planned for this request.

        The returned state is advisory. ``prepare`` repeats registration,
        availability, scope, operation, and bound checks before retrieval.
        """
        from personal_ai.context.planner import ContextPlanningCapability

        capability = next(
            (
                item
                for item in context.context_provider_capabilities
                if item.capability_id == provider_id
            ),
            None,
        )
        if capability is None or capability.kind != "context_provider":
            return ContextPlanningCapability(status="not_registered")
        factory = self._factory(provider_id)
        if factory is None:
            return ContextPlanningCapability(status="unavailable")
        if not capability.is_enabled(self._feature_flags):
            return ContextPlanningCapability(status="disabled")
        try:
            spec = ContextProviderSpec.model_validate(factory.spec.model_dump())
        except ValidationError:
            return ContextPlanningCapability(status="unavailable")
        if spec.capability_kind != "context_provider":
            return ContextPlanningCapability(status="unavailable")
        return ContextPlanningCapability(status="available", spec=spec)

    @staticmethod
    def _preflight_failure(selection: ContextSelection, error: Exception) -> str:
        if isinstance(error, ContextPreparationError):
            raise error
        if isinstance(error, TimeoutError):
            reason = "timeout"
            required_code = "required_context_source_timeout"
        elif isinstance(error, ContextProviderError):
            reason = "timeout" if error.code.endswith("timeout") else "unavailable"
            required_code = (
                "required_context_source_timeout"
                if reason == "timeout"
                else "required_context_source_unavailable"
            )
        else:
            reason = "source_failed"
            required_code = "required_context_source_failed"
        if selection.required:
            raise ContextPreparationError(required_code) from error
        return reason

    @staticmethod
    def _capability(
        context: ApplicationContextRequest,
        provider_id: str,
        kind: CapabilityKind,
    ) -> CapabilityRegistration:
        values = (
            context.context_provider_capabilities
            if kind == "context_provider"
            else context.tool_capabilities
        )
        found = next((value for value in values if value.capability_id == provider_id), None)
        if found is None or found.kind != kind:
            raise ContextPreparationError("context_provider_not_registered")
        return found

    def prepare(
        self,
        context: ApplicationContextRequest,
        selections: Sequence[ContextSelection],
        inputs: ContextProviderInputs,
        *,
        deadline: float | None = None,
    ) -> ContextProviderResult:
        if len(selections) > self.MAX_SELECTIONS:
            raise ContextPreparationError("context_selection_limit_exceeded")
        if inputs.scope != context.scope:
            raise ContextPreparationError("context_provider_scope_mismatch")

        expected_scope = ApplicationScope(
            application_id=context.scope.application_id,
            workspace_id=context.scope.workspace_id,
        )
        # Scope denial is universal. Resolve it across the full selection set
        # before optional availability or supported-operation checks.
        for selection in selections:
            target_scope = selection.target_scope or expected_scope
            if target_scope != expected_scope or any(
                reference.application_id != expected_scope.application_id
                or reference.workspace_id != expected_scope.workspace_id
                for reference in selection.entity_refs
            ):
                raise ContextPreparationError("context_cross_application_denied")

        # Build and validate the entire plan first. A denied selection cannot
        # cause a partial set of unrelated providers to run.
        planned: list[tuple[ContextSelection, ContextProvider | None, str | None]] = []
        seen: set[tuple[str, str]] = set()
        for selection in selections:
            if deadline is not None and monotonic() >= deadline:
                raise ContextPreparationError("context_preparation_timeout")
            key = (selection.provider_id, selection.operation)
            if key in seen:
                raise ContextPreparationError("context_selection_duplicate")
            seen.add(key)
            factory = self._factory(selection.provider_id)
            if factory is None:
                registered = any(
                    item.capability_id == selection.provider_id
                    for item in (
                        *context.context_provider_capabilities,
                        *context.tool_capabilities,
                    )
                )
                if not registered:
                    raise ContextPreparationError("context_provider_not_registered")
                if selection.required:
                    raise ContextPreparationError("required_context_source_unavailable")
                planned.append((selection, None, "unavailable"))
                continue
            try:
                spec = ContextProviderSpec.model_validate(factory.spec.model_dump())
            except ValidationError as error:
                raise ContextPreparationError("context_provider_spec_invalid") from error
            capability = self._capability(context, selection.provider_id, spec.capability_kind)
            if spec.capability_kind == "tool" and (
                not capability.read_only_context
                or capability.max_result_bytes is None
                or any(
                    not set(operation.allowed_fields).issubset(capability.result_fields)
                    or operation.maximum_bytes > capability.max_result_bytes
                    for operation in spec.operations
                )
            ):
                raise ContextPreparationError("context_tool_result_not_registered_read_only")
            if not capability.is_enabled(self._feature_flags):
                reason = "unavailable"
                if selection.required:
                    raise ContextPreparationError("required_context_source_unavailable")
                planned.append((selection, None, reason))
                continue
            operation = spec.operation(selection.operation)
            if operation is None:
                if selection.required:
                    raise ContextPreparationError("required_context_operation_unsupported")
                planned.append((selection, None, "unsupported_operation"))
                continue
            if selection.fields:
                if not operation.dynamic_fields and not set(selection.fields).issubset(
                    operation.allowed_fields
                ):
                    raise ContextPreparationError("context_fields_not_allowed")
            elif operation.fields_required:
                raise ContextPreparationError("context_fields_required")
            if selection.entity_refs and not operation.accepts_entity_refs:
                raise ContextPreparationError("context_entity_scope_not_supported")
            if operation.requires_time_window and selection.window_start is None:
                raise ContextPreparationError("context_time_window_required")
            if selection.window_start is not None:
                assert selection.window_end is not None
                if operation.maximum_window_seconds < 1 or (
                    selection.window_end - selection.window_start
                ).total_seconds() > operation.maximum_window_seconds:
                    raise ContextPreparationError("context_time_window_exceeded")
            if selection.max_results > operation.maximum_results:
                raise ContextPreparationError("context_result_limit_exceeded")
            if selection.max_bytes > operation.maximum_bytes:
                raise ContextPreparationError("context_byte_limit_exceeded")
            if selection.timeout_seconds > operation.maximum_timeout_seconds:
                raise ContextPreparationError("context_timeout_limit_exceeded")
            if not spec.maximum_items_per_call:
                raise ContextPreparationError("context_provider_bounds_invalid")
            try:
                provider = factory.create(inputs) if hasattr(factory, "create") else factory
            except ContextPreparationError:
                raise
            except ContextProviderError as error:
                planned.append((selection, None, self._preflight_failure(selection, error)))
                continue
            except TimeoutError as error:
                planned.append((selection, None, self._preflight_failure(selection, error)))
                continue
            except Exception as error:  # noqa: BLE001 - optional dependency failures are bounded
                planned.append((selection, None, self._preflight_failure(selection, error)))
                continue
            if provider.spec != spec:
                raise ContextPreparationError("context_provider_identity_mismatch")
            try:
                provider.validate_selection(selection, inputs)
            except ContextPreparationError:
                raise
            except ContextProviderError as error:
                planned.append((selection, None, self._preflight_failure(selection, error)))
                continue
            except TimeoutError as error:
                planned.append((selection, None, self._preflight_failure(selection, error)))
                continue
            except Exception as error:  # noqa: BLE001 - optional dependency failures are bounded
                planned.append((selection, None, self._preflight_failure(selection, error)))
                continue
            planned.append((selection, provider, None))

        # Required sources run first. A required-source failure prevents later
        # optional sources from being read.
        planned.sort(key=lambda row: not row[0].required)
        items: list[ContextItem[Any]] = []
        failures: list[ContextProviderFailure] = []
        total_bytes = 0
        for selection, provider, preflight_failure in planned:
            if deadline is not None and monotonic() >= deadline:
                raise ContextPreparationError("context_preparation_timeout")
            if preflight_failure:
                failures.append(
                    ContextProviderFailure(
                        provider_id=selection.provider_id,
                        operation=selection.operation,
                        reason=preflight_failure,
                    )
                )
                continue
            assert provider is not None
            source_deadline = monotonic() + selection.timeout_seconds
            if deadline is not None:
                source_deadline = min(source_deadline, deadline)
            try:
                fetched = provider.fetch(selection, context.scope, deadline=source_deadline)
                if isinstance(fetched, ContextProviderResult):
                    records = fetched.items
                    provider_failures = fetched.failures
                    if any(
                        item.provider_id != selection.provider_id
                        or item.operation != selection.operation
                        for item in provider_failures
                    ):
                        raise ContextPreparationError("context_provider_failure_identity_mismatch")
                else:
                    records = tuple(fetched)
                    provider_failures = ()
                if monotonic() >= source_deadline:
                    if deadline is not None and source_deadline == deadline:
                        raise ContextPreparationError("context_preparation_timeout")
                    raise TimeoutError("context source timed out")
                if len(records) > min(selection.max_results, provider.spec.maximum_items_per_call):
                    raise ContextPreparationError("context_provider_result_limit_exceeded")
                call_bytes = 0
                for item in records:
                    if not isinstance(item, ContextItem) or not isinstance(item.payload, BaseModel):
                        raise ContextPreparationError("context_provider_item_invalid")
                    if not item.source_refs:
                        raise ContextPreparationError("context_provider_provenance_missing")
                    if provider.spec.capability_kind == "tool" and not tool_result_projection_is_valid(
                        getattr(item.payload, "result", None), selection.fields
                    ):
                        raise ContextPreparationError(
                            "context_provider_tool_projection_violation"
                        )
                    if item.source_class in {"external_research", "client_context"} and (
                        item.authority == "authoritative"
                    ):
                        raise ContextPreparationError("context_provider_authority_violation")
                    if (
                        item.provider_id != provider.spec.provider_id
                        or item.source_class != provider.spec.source_class
                        or item.owner_id != context.scope.owner_id
                        or item.application_id != context.scope.application_id
                        or item.workspace_id != context.scope.workspace_id
                    ):
                        raise ContextPreparationError("context_provider_scope_violation")
                    if any(
                        reference.application_id != context.scope.application_id
                        or reference.workspace_id != context.scope.workspace_id
                        for reference in item.entity_refs
                    ):
                        raise ContextPreparationError("context_provider_entity_scope_violation")
                    if selection.entity_refs and any(
                        reference not in selection.entity_refs
                        for reference in item.entity_refs
                    ):
                        raise ContextPreparationError("context_provider_entity_selection_violation")
                    encoded_size = len(item.model_dump_json().encode("utf-8"))
                    call_bytes += encoded_size
                if call_bytes > selection.max_bytes:
                    raise ContextPreparationError("context_provider_response_too_large")
                total_bytes += call_bytes
                if len(items) + len(records) > self.MAX_TOTAL_ITEMS:
                    raise ContextPreparationError("context_response_item_limit_exceeded")
                if total_bytes > self.MAX_TOTAL_BYTES:
                    raise ContextPreparationError("context_response_byte_limit_exceeded")
                if selection.required and provider_failures:
                    reason = provider_failures[0].reason
                    code = (
                        "required_context_source_empty"
                        if reason == "empty"
                        else "required_context_source_failed"
                    )
                    raise ContextPreparationError(code)
                items.extend(
                    item.model_copy(update={"selected_operation": selection.operation})
                    for item in records
                )
                failures.extend(provider_failures)
                if not records and not provider_failures:
                    if selection.required:
                        raise ContextPreparationError("required_context_source_empty")
                    failures.append(
                        ContextProviderFailure(
                            provider_id=selection.provider_id,
                            operation=selection.operation,
                            reason="empty",
                        )
                    )
            except ContextPreparationError:
                raise
            except TimeoutError as error:
                if selection.required:
                    raise ContextPreparationError("required_context_source_timeout") from error
                failures.append(
                    ContextProviderFailure(
                        provider_id=selection.provider_id,
                        operation=selection.operation,
                        reason="timeout",
                    )
                )
            except ContextProviderError as error:
                if selection.required:
                    raise ContextPreparationError("required_context_source_unavailable") from error
                reason = "timeout" if error.code.endswith("timeout") else "unavailable"
                failures.append(
                    ContextProviderFailure(
                        provider_id=selection.provider_id,
                        operation=selection.operation,
                        reason=reason,
                    )
                )
            except Exception as error:
                if selection.required:
                    raise ContextPreparationError("required_context_source_failed") from error
                failures.append(
                    ContextProviderFailure(
                        provider_id=selection.provider_id,
                        operation=selection.operation,
                        reason="source_failed",
                    )
                )
        if deadline is not None and monotonic() >= deadline:
            raise ContextPreparationError("context_preparation_timeout")
        return ContextProviderResult(items=tuple(items), failures=tuple(failures))


class FixedContextProviderFactory:
    """Build one request-bound provider using a small adapter callback."""

    def __init__(
        self,
        spec: ContextProviderSpec,
        build: Callable[[ContextProviderInputs], ContextProvider],
    ) -> None:
        self.spec = spec
        self._build = build

    def create(self, inputs: ContextProviderInputs) -> ContextProvider:
        return self._build(inputs)
