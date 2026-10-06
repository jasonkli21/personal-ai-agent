"""Application manifest validation, composition, and scoped consumer contracts."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai.applications.contracts import (
    ApplicationBudgetHints,
    ApplicationContextRequest,
    ApplicationDefinition,
    ApplicationRegistryError,
    CapabilityRegistration,
    CrossApplicationDeclaration,
)
from personal_ai.applications.registry import (
    ApplicationNotRegisteredError,
    ApplicationRegistry,
    default_application_registry,
)
from personal_ai.auth.scope import RequestScope
from personal_ai.context import ContextAssembler
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import Message, MessageRole, MessageStatus
from personal_ai.settings import Settings


def _definition(application_id: str = "synthetic", **updates) -> ApplicationDefinition:
    return ApplicationDefinition(
        application_id=application_id,
        display_name=application_id.title(),
        memory_namespace=application_id,
        **updates,
    )


def test_default_registry_registers_initial_manifests_and_unavailable_stubs() -> None:
    registry = default_application_registry()

    assert registry.application_ids == {
        "personal_ai", "travel", "shopping", "finance", "health"
    }
    assert registry.get("personal_ai").context_provider_ids == (
        "conversation_history", "ai_memory"
    )
    assert registry.capability(
        "personal_ai", "conversation_history", kind="context_provider"
    ).available
    assert not registry.capability("personal_ai", "ai_memory", kind="context_provider").available
    for application_id in ("travel", "shopping", "finance", "health"):
        registration = registry.registration(application_id)
        assert registration.definition.cross_application.mode == "disabled"
        assert registration.context_providers
        assert registration.tools
        assert all(not provider.available for provider in registration.context_providers)
        assert all(not tool.available for tool in registration.tools)
    assert registry.registration("travel").comparison_modules[0].registration.domain_id == "travel"
    assert registry.registration("shopping").comparison_modules[0].registration.domain_id == "shopping"


def test_unknown_application_fails_with_a_stable_registry_error() -> None:
    with pytest.raises(ApplicationNotRegisteredError) as error:
        default_application_registry().get("not_registered")

    assert error.value.code == "application_not_registered"


def test_duplicate_applications_and_unknown_references_fail_before_registration() -> None:
    provider = CapabilityRegistration(
        capability_id="synthetic.context",
        kind="context_provider",
        available=True,
    )
    definition = _definition(context_provider_ids=(provider.capability_id,))

    with pytest.raises(ApplicationRegistryError, match="Duplicate application definition"):
        ApplicationRegistry((definition, definition), (provider,))
    with pytest.raises(ApplicationRegistryError, match="unknown context_provider"):
        ApplicationRegistry((definition,), ())


def test_capability_kind_and_unavailable_state_are_validated() -> None:
    definition = _definition(context_provider_ids=("synthetic.context",))
    wrong_kind = CapabilityRegistration(
        capability_id="synthetic.context",
        kind="tool",
        available=True,
    )
    with pytest.raises(ApplicationRegistryError, match="unknown context_provider"):
        ApplicationRegistry((definition,), (wrong_kind,))

    with pytest.raises(ValidationError, match="unavailable_capability_requires_reason"):
        CapabilityRegistration(capability_id="synthetic.context", kind="context_provider")

    provider = CapabilityRegistration(
        capability_id="synthetic.provider",
        kind="context_provider",
        available=True,
    )
    definition = _definition(context_provider_ids=(provider.capability_id,))
    duplicate_id = CapabilityRegistration(
        capability_id=provider.capability_id, kind="tool", available=True
    )
    with pytest.raises(ApplicationRegistryError, match="Duplicate capability registration"):
        ApplicationRegistry((definition,), (provider, duplicate_id))


def test_schema_policy_and_budget_contradictions_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _definition(schema_version="application-definition-v99")
    with pytest.raises(ValidationError, match="disabled_cross_application_declaration_has_references"):
        CrossApplicationDeclaration(mode="disabled", application_ids=("travel",))
    with pytest.raises(ValidationError, match="application_budget_hints_exceed_context_budget"):
        ApplicationBudgetHints(context_tokens=100, memory_tokens=60, domain_context_tokens=50)


def test_cross_application_and_comparison_references_are_resolved() -> None:
    alpha = _definition(
        "alpha",
        cross_application=CrossApplicationDeclaration(
            mode="declaration_only", application_ids=("beta",)
        ),
    )
    beta = _definition("beta")
    with pytest.raises(ApplicationRegistryError, match="unregistered application"):
        ApplicationRegistry((alpha,))
    with pytest.raises(ApplicationRegistryError, match="unknown comparison domain"):
        ApplicationRegistry((_definition(comparison_domain_ids=("missing-domain",)),))
    assert ApplicationRegistry((alpha, beta)).get("alpha").cross_application.mode == "declaration_only"


def test_workspace_support_is_enforced_by_the_scoped_application_contract() -> None:
    scope = RequestScope(
        owner_id="owner-1",
        request_id="request-1",
        application_id="synthetic",
        workspace_id="team-a",
    )
    with pytest.raises(ValidationError, match="application_workspace_unsupported"):
        ApplicationContextRequest(
            definition=_definition(workspace_kind="unsupported"), scope=scope
        )
    required_scope = RequestScope(
        owner_id="owner-1", request_id="request-2", application_id="synthetic"
    )
    with pytest.raises(ValidationError, match="application_workspace_required"):
        ApplicationContextRequest(
            definition=_definition(workspace_kind="required"), scope=required_scope
        )


def test_synthetic_application_flows_into_context_without_application_branching() -> None:
    provider = CapabilityRegistration(
        capability_id="synthetic.context",
        kind="context_provider",
        available=True,
    )
    definition = _definition(context_provider_ids=(provider.capability_id,))
    registry = ApplicationRegistry((definition,), (provider,))
    scope = RequestScope(
        owner_id="owner-1", request_id="request-1", application_id="synthetic"
    )
    context_request = ApplicationContextRequest(
        definition=registry.get("synthetic"), scope=scope
    )
    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id=scope.owner_id,
        role=MessageRole.USER,
        content="hello",
        status=MessageStatus.COMPLETED,
        created_at=datetime.now(UTC),
        application_id="synthetic",
        workspace_id=None,
        scope_version=2,
    )

    assembled = ContextAssembler(
        Settings(ai_provider="fake", ai_model="fake-model"), FakeTokenCounter()
    ).assemble((), pending, refresh=False, application_context=context_request)

    assert assembled.messages[-1].content == "hello"
    assert context_request.definition.memory_namespace == "synthetic"
    assert registry.capability(
        "synthetic", "synthetic.context", kind="context_provider"
    ).available
