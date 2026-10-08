"""Deterministic application and capability registration."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Protocol

from personal_ai.applications.contracts import (
    ApplicationContextPolicy,
    ApplicationDefinition,
    ApplicationRegistryError,
    CapabilityKind,
    CapabilityRegistration,
    ContextFieldPolicy,
    ContextOperationPolicy,
    ContextProviderPolicy,
)

SHARED_CONTEXT_PROVIDER_IDS = (
    "conversation_history",
    "ai_memory",
    "external_research",
    "global_profile",
    "client_context",
)


class _ComparisonModule(Protocol):
    registration: object


class ApplicationNotRegisteredError(ApplicationRegistryError):
    def __init__(self, application_id: str) -> None:
        self.application_id = application_id
        super().__init__("application_not_registered")


@dataclass(frozen=True, slots=True)
class RegisteredApplication:
    """An app manifest composed with its referenced capability metadata."""

    definition: ApplicationDefinition
    context_providers: tuple[CapabilityRegistration, ...]
    tools: tuple[CapabilityRegistration, ...]
    comparison_modules: tuple[_ComparisonModule, ...]


class ApplicationRegistry:
    """Immutable-by-interface manifest registry, independently constructible in tests."""

    def __init__(
        self,
        definitions: Iterable[ApplicationDefinition],
        capabilities: Iterable[CapabilityRegistration] = (),
        *,
        comparison_modules: Mapping[str, _ComparisonModule] | None = None,
    ) -> None:
        definition_by_id: dict[str, ApplicationDefinition] = {}
        for definition in definitions:
            if definition.application_id in definition_by_id:
                raise ApplicationRegistryError(
                    "application_definition_duplicate",
                    f"Duplicate application definition: {definition.application_id}",
                )
            definition_by_id[definition.application_id] = definition

        capability_values = list(capabilities)
        registered_ids = {item.capability_id for item in capability_values}
        if "conversation_history" not in registered_ids:
            capability_values.append(
                CapabilityRegistration(
                    capability_id="conversation_history",
                    kind="context_provider",
                    available=True,
                )
            )
        if "ai_memory" not in registered_ids:
            capability_values.append(
                CapabilityRegistration(
                    capability_id="ai_memory",
                    kind="context_provider",
                    available=True,
                    feature_gate="memory_enabled",
                )
            )
        if "global_profile" not in registered_ids:
            capability_values.append(
                CapabilityRegistration(
                    capability_id="global_profile",
                    kind="context_provider",
                    available=True,
                )
            )
        if "external_research" not in registered_ids:
            capability_values.append(
                CapabilityRegistration(
                    capability_id="external_research",
                    kind="context_provider",
                    available=True,
                )
            )
        if "client_context" not in registered_ids:
            capability_values.append(
                CapabilityRegistration(
                    capability_id="client_context",
                    kind="context_provider",
                    available=True,
                )
            )

        capability_by_key: dict[tuple[CapabilityKind, str], CapabilityRegistration] = {}
        capability_ids: set[str] = set()
        for capability in capability_values:
            key = (capability.kind, capability.capability_id)
            if capability.capability_id in capability_ids:
                raise ApplicationRegistryError(
                    "application_capability_duplicate",
                    f"Duplicate capability registration: {capability.capability_id}",
                )
            capability_ids.add(capability.capability_id)
            capability_by_key[key] = capability

        comparison_modules = dict(comparison_modules or {})
        for domain_id, module in comparison_modules.items():
            if getattr(module.registration, "domain_id", None) != domain_id:
                raise ApplicationRegistryError("comparison_module_identity_mismatch")

        registrations: dict[str, RegisteredApplication] = {}
        for definition in definition_by_id.values():
            app_providers = self._resolve_capabilities(
                definition, "context_provider", definition.context_provider_ids, capability_by_key
            )
            shared_providers = self._resolve_capabilities(
                definition,
                "context_provider",
                SHARED_CONTEXT_PROVIDER_IDS,
                capability_by_key,
            )
            providers = shared_providers + tuple(
                provider for provider in app_providers
                if provider.capability_id not in SHARED_CONTEXT_PROVIDER_IDS
            )
            tools = self._resolve_capabilities(
                definition, "tool", definition.tool_ids, capability_by_key
            )
            missing_domains = set(definition.comparison_domain_ids) - set(comparison_modules)
            if missing_domains:
                missing = ", ".join(sorted(missing_domains))
                raise ApplicationRegistryError(
                    "application_comparison_domain_unknown",
                    f"Application {definition.application_id} references unknown comparison domain(s): {missing}",
                )
            registrations[definition.application_id] = RegisteredApplication(
                definition=definition,
                context_providers=providers,
                tools=tools,
                comparison_modules=tuple(
                    comparison_modules[domain_id]
                    for domain_id in definition.comparison_domain_ids
                ),
            )

        for definition in definition_by_id.values():
            unknown_cross_app_ids = (
                set(definition.cross_application.application_ids) - set(definition_by_id)
            )
            if unknown_cross_app_ids:
                missing = ", ".join(sorted(unknown_cross_app_ids))
                raise ApplicationRegistryError(
                    "application_cross_reference_unknown",
                    f"Application {definition.application_id} references unregistered application(s): {missing}",
                )

        self._registrations = MappingProxyType(registrations)
        self._capabilities = MappingProxyType(capability_by_key)

    @staticmethod
    def _resolve_capabilities(
        definition: ApplicationDefinition,
        kind: CapabilityKind,
        capability_ids: tuple[str, ...],
        available: Mapping[tuple[CapabilityKind, str], CapabilityRegistration],
    ) -> tuple[CapabilityRegistration, ...]:
        resolved = []
        for capability_id in capability_ids:
            capability = available.get((kind, capability_id))
            if capability is None:
                raise ApplicationRegistryError(
                    "application_capability_unknown",
                    f"Application {definition.application_id} references unknown {kind}: {capability_id}",
                )
            resolved.append(capability)
        return tuple(resolved)

    @property
    def application_ids(self) -> frozenset[str]:
        return frozenset(self._registrations)

    def get(self, application_id: str) -> ApplicationDefinition:
        try:
            return self._registrations[application_id].definition
        except KeyError as error:
            raise ApplicationNotRegisteredError(application_id) from error

    def registration(self, application_id: str) -> RegisteredApplication:
        try:
            return self._registrations[application_id]
        except KeyError as error:
            raise ApplicationNotRegisteredError(application_id) from error

    def capability(
        self, application_id: str, capability_id: str, *, kind: CapabilityKind
    ) -> CapabilityRegistration:
        registration = self.registration(application_id)
        declared_ids = (
            tuple(provider.capability_id for provider in registration.context_providers)
            if kind == "context_provider"
            else tuple(tool.capability_id for tool in registration.tools)
        )
        if capability_id not in declared_ids:
            raise ApplicationRegistryError("application_capability_not_declared")
        return self._capabilities[(kind, capability_id)]


def _capability(
    capability_id: str,
    kind: CapabilityKind,
    *,
    available: bool = False,
    feature_gate: str | None = None,
    reason: str = "application_integration_not_implemented",
) -> CapabilityRegistration:
    return CapabilityRegistration(
        capability_id=capability_id,
        kind=kind,
        available=available,
        feature_gate=feature_gate,
        unavailable_reason=None if available else reason,
    )


def _domain_context_policy(
    version: str, declarations: tuple[ContextProviderPolicy, ...]
) -> ApplicationContextPolicy:
    """Compose explicit app-owned source rules with shared context policies."""
    shared = ApplicationContextPolicy()
    return ApplicationContextPolicy(
        version=version,
        provider_policies=(*shared.provider_policies, *declarations),
        maximum_model_sensitivity=shared.maximum_model_sensitivity,
        cross_application="deny",
    )


def _field_policy(
    name: str, *, sensitivity: str = "sensitive", model_disclosure: bool = True
) -> ContextFieldPolicy:
    return ContextFieldPolicy(
        field=name, sensitivity=sensitivity, model_disclosure=model_disclosure
    )


def _operation_policy(
    operation: str,
    fields: tuple[str, ...],
    *,
    restricted_fields: tuple[str, ...] = (),
) -> ContextOperationPolicy:
    return ContextOperationPolicy(
        operation=operation,
        fields=tuple(
            _field_policy(
                field,
                sensitivity="restricted" if field in restricted_fields else "sensitive",
                model_disclosure=field not in restricted_fields,
            )
            for field in fields
        ),
        sensitivity="sensitive",
    )


@lru_cache(maxsize=1)
def default_application_registry() -> ApplicationRegistry:
    """Build initial manifests with common chat context and comparison modules."""
    from personal_ai.domains.registry import registry as domain_registry

    comparison_modules = domain_registry()
    capabilities = (
        _capability("conversation_history", "context_provider", available=True),
        _capability(
            "ai_memory",
            "context_provider",
            available=True,
            feature_gate="memory_enabled",
        ),
        _capability("global_profile", "context_provider", available=True),
        _capability("client_context", "context_provider", available=True),
        _capability("external_research", "context_provider", available=True),
        _capability("travel.trip_context", "context_provider"),
        _capability("travel.research_context", "context_provider"),
        _capability("travel.itinerary_action", "tool", reason="travel_actions_unavailable"),
        _capability("shopping.product_context", "context_provider"),
        _capability("shopping.catalog_search", "context_provider"),
        _capability("shopping.product_action", "tool", reason="shopping_actions_unavailable"),
        _capability("finance.account_context", "context_provider"),
        _capability("finance.portfolio_context", "context_provider"),
        _capability("finance.account_action", "tool", reason="finance_actions_unavailable"),
        _capability("health.profile_context", "context_provider"),
        _capability("health.history_context", "context_provider"),
        _capability("health.record_action", "tool", reason="health_actions_unavailable"),
    )
    return ApplicationRegistry(
        (
            ApplicationDefinition(
                application_id="personal_ai",
                display_name="Personal AI",
                workspace_kind="optional",
                memory_namespace="personal_ai",
            ),
            ApplicationDefinition(
                application_id="travel",
                display_name="Travel",
                workspace_kind="optional",
                context_provider_ids=("travel.trip_context", "travel.research_context"),
                tool_ids=("travel.itinerary_action",),
                memory_namespace="travel",
                sensitivity_defaults={
                    "conversation": "personal",
                    "memory": "personal",
                    "domain_context": "sensitive",
                    "client_context": "personal",
                },
                context_policy=_domain_context_policy(
                    "travel-context-policy-v1",
                    (
                        ContextProviderPolicy(
                            provider_id="travel.trip_context",
                            operations=(_operation_policy(
                                "current",
                                ("city", "start_date", "end_date", "payment_details"),
                                restricted_fields=("payment_details",),
                            ),),
                        ),
                        ContextProviderPolicy(
                            provider_id="travel.research_context",
                            operations=(_operation_policy(
                                "search", ("passage", "observed_at", "expires_at")
                            ),),
                        ),
                    ),
                ),
                comparison_domain_ids=("travel",),
            ),
            ApplicationDefinition(
                application_id="shopping",
                display_name="Shopping",
                workspace_kind="optional",
                context_provider_ids=("shopping.product_context", "shopping.catalog_search"),
                tool_ids=("shopping.product_action",),
                memory_namespace="shopping",
                sensitivity_defaults={
                    "conversation": "personal",
                    "memory": "personal",
                    "domain_context": "sensitive",
                    "client_context": "personal",
                },
                context_policy=_domain_context_policy(
                    "shopping-context-policy-v1",
                    (
                        ContextProviderPolicy(
                            provider_id="shopping.product_context",
                            operations=(_operation_policy(
                                "current", ("product_name", "price", "tax_id"),
                                restricted_fields=("tax_id",),
                            ),),
                        ),
                        ContextProviderPolicy(
                            provider_id="shopping.catalog_search",
                            operations=(_operation_policy(
                                "search", ("product_name", "price", "tax_id"),
                                restricted_fields=("tax_id",),
                            ),),
                        ),
                    ),
                ),
                comparison_domain_ids=("shopping",),
            ),
            ApplicationDefinition(
                application_id="finance",
                display_name="Finance",
                workspace_kind="optional",
                context_provider_ids=("finance.account_context", "finance.portfolio_context"),
                tool_ids=("finance.account_action",),
                memory_namespace="finance",
                sensitivity_defaults={
                    "conversation": "sensitive",
                    "memory": "sensitive",
                    "domain_context": "restricted",
                    "client_context": "sensitive",
                },
                context_policy=_domain_context_policy(
                    "finance-context-policy-v1",
                    (
                        ContextProviderPolicy(
                            provider_id="finance.account_context",
                            operations=(_operation_policy(
                                "current", ("balance", "currency", "tax_id"),
                                restricted_fields=("tax_id",),
                            ),),
                        ),
                        ContextProviderPolicy(
                            provider_id="finance.portfolio_context",
                            operations=(_operation_policy(
                                "current", ("ticker", "shares", "market_value", "tax_id"),
                                restricted_fields=("tax_id",),
                            ),),
                        ),
                    ),
                ),
            ),
            ApplicationDefinition(
                application_id="health",
                display_name="Health",
                workspace_kind="optional",
                context_provider_ids=("health.profile_context", "health.history_context"),
                tool_ids=("health.record_action",),
                memory_namespace="health",
                sensitivity_defaults={
                    "conversation": "sensitive",
                    "memory": "sensitive",
                    "domain_context": "restricted",
                    "client_context": "sensitive",
                },
                context_policy=_domain_context_policy(
                    "health-context-policy-v1",
                    (
                        ContextProviderPolicy(
                            provider_id="health.profile_context",
                            operations=(
                                _operation_policy(
                                    "profile", ("medication_name", "dose", "diagnosis"),
                                    restricted_fields=("diagnosis",),
                                ),
                                _operation_policy(
                                    "current", ("medication_name", "dose", "diagnosis"),
                                    restricted_fields=("diagnosis",),
                                ),
                            ),
                        ),
                        ContextProviderPolicy(
                            provider_id="health.history_context",
                            operations=(_operation_policy(
                                "history",
                                ("medication_name", "dose", "observed_at", "diagnosis"),
                                restricted_fields=("diagnosis",),
                            ),),
                        ),
                    ),
                ),
            ),
        ),
        capabilities,
        comparison_modules=comparison_modules,
    )


def application_registry_for(request) -> ApplicationRegistry:
    """Use an app-injected registry when present, otherwise the built-in registry."""
    try:
        configured = getattr(request.app.state, "application_registry", None)
    except (AttributeError, RuntimeError):
        configured = None
    return configured or default_application_registry()
