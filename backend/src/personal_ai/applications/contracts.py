"""Typed, versioned metadata for registered applications and capabilities."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_ai.auth.scope import RequestScope

ApplicationId = str
Sensitivity = Literal["public", "personal", "sensitive", "restricted"]
CapabilityKind = Literal["context_provider", "tool"]
_APPLICATION_ID_PATTERN = r"^[a-z][a-z0-9_-]{1,40}$"
_CAPABILITY_ID_PATTERN = r"^[a-z][a-z0-9_.-]{1,80}$"


class ApplicationRegistryError(ValueError):
    """A clear, stable registration or lookup failure."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class SensitivityDefaults(BaseModel):
    """Default classifications for context source categories."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation: Sensitivity = "personal"
    memory: Sensitivity = "personal"
    domain_context: Sensitivity = "sensitive"
    client_context: Sensitivity = "personal"


class CrossApplicationDeclaration(BaseModel):
    """Declarative cross-app metadata; this contract never grants a data share."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["disabled", "declaration_only"] = "disabled"
    application_ids: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def declaration_is_consistent(self) -> "CrossApplicationDeclaration":
        if len(set(self.application_ids)) != len(self.application_ids):
            raise ValueError("cross_application_ids_must_be_unique")
        if any(not re.fullmatch(_APPLICATION_ID_PATTERN, item) for item in self.application_ids):
            raise ValueError("cross_application_id_invalid")
        if self.mode == "disabled" and self.application_ids:
            raise ValueError("disabled_cross_application_declaration_has_references")
        if self.mode == "declaration_only" and not self.application_ids:
            raise ValueError("cross_application_declaration_requires_references")
        return self


class ApplicationBudgetHints(BaseModel):
    """Optional advisory context budgets; these do not select a model/provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    context_tokens: int | None = Field(default=None, ge=1, le=128_000)
    memory_tokens: int | None = Field(default=None, ge=1, le=64_000)
    domain_context_tokens: int | None = Field(default=None, ge=1, le=64_000)

    @model_validator(mode="after")
    def child_budgets_fit_total(self) -> "ApplicationBudgetHints":
        children = [value for value in (self.memory_tokens, self.domain_context_tokens) if value]
        if self.context_tokens is not None and children and sum(children) > self.context_tokens:
            raise ValueError("application_budget_hints_exceed_context_budget")
        return self


class ApplicationDefinition(BaseModel):
    """A registered app's capabilities and defaults, separate from domain state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["application-definition-v1"] = "application-definition-v1"
    application_id: str = Field(pattern=_APPLICATION_ID_PATTERN, min_length=2, max_length=42)
    display_name: str = Field(min_length=1, max_length=100)
    workspace_kind: Literal["unsupported", "optional", "required"] = "optional"
    context_provider_ids: tuple[str, ...] = Field(default=(), max_length=16)
    tool_ids: tuple[str, ...] = Field(default=(), max_length=16)
    memory_namespace: str = Field(pattern=_APPLICATION_ID_PATTERN, min_length=2, max_length=42)
    sensitivity_defaults: SensitivityDefaults = Field(default_factory=SensitivityDefaults)
    cross_application: CrossApplicationDeclaration = Field(
        default_factory=CrossApplicationDeclaration
    )
    budget_hints: ApplicationBudgetHints = Field(default_factory=ApplicationBudgetHints)
    comparison_domain_ids: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def references_are_unambiguous(self) -> "ApplicationDefinition":
        for name, values in (
            ("context_provider_ids", self.context_provider_ids),
            ("tool_ids", self.tool_ids),
            ("comparison_domain_ids", self.comparison_domain_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name}_must_be_unique")
        for capability_id in (*self.context_provider_ids, *self.tool_ids):
            if not re.fullmatch(_CAPABILITY_ID_PATTERN, capability_id):
                raise ValueError("application_capability_id_invalid")
        for domain_id in self.comparison_domain_ids:
            if not re.fullmatch(r"^[a-z][a-z0-9-]{1,40}$", domain_id):
                raise ValueError("application_comparison_domain_id_invalid")
        if self.application_id in self.cross_application.application_ids:
            raise ValueError("application_cannot_declare_itself_cross_application")
        return self


class CapabilityRegistration(BaseModel):
    """Registry metadata for one context provider or tool implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["application-capability-v1"] = "application-capability-v1"
    capability_id: str = Field(pattern=_CAPABILITY_ID_PATTERN, min_length=2, max_length=81)
    kind: CapabilityKind
    available: bool = False
    unavailable_reason: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def availability_is_consistent(self) -> "CapabilityRegistration":
        if self.available and self.unavailable_reason is not None:
            raise ValueError("available_capability_has_unavailable_reason")
        if not self.available and self.unavailable_reason is None:
            raise ValueError("unavailable_capability_requires_reason")
        return self


class ApplicationContextRequest(BaseModel):
    """Resolved manifest metadata paired with the authenticated request scope."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    definition: ApplicationDefinition
    scope: RequestScope

    @model_validator(mode="after")
    def manifest_matches_scope(self) -> "ApplicationContextRequest":
        if self.definition.application_id != self.scope.application_id:
            raise ValueError("application_definition_scope_mismatch")
        if self.definition.workspace_kind == "unsupported" and self.scope.workspace_id is not None:
            raise ValueError("application_workspace_unsupported")
        if self.definition.workspace_kind == "required" and self.scope.workspace_id is None:
            raise ValueError("application_workspace_required")
        return self
