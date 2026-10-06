"""Application manifests and their deterministic registry."""

from personal_ai.applications.contracts import (
    ApplicationBudgetHints,
    ApplicationContextRequest,
    ApplicationDefinition,
    ApplicationRegistryError,
    CapabilityRegistration,
    CrossApplicationDeclaration,
    SensitivityDefaults,
)
from personal_ai.applications.registry import (
    ApplicationNotRegisteredError,
    ApplicationRegistry,
    application_registry_for,
    default_application_registry,
)

__all__ = [
    "ApplicationBudgetHints",
    "ApplicationContextRequest",
    "ApplicationDefinition",
    "ApplicationNotRegisteredError",
    "ApplicationRegistry",
    "ApplicationRegistryError",
    "CapabilityRegistration",
    "CrossApplicationDeclaration",
    "SensitivityDefaults",
    "application_registry_for",
    "default_application_registry",
]
