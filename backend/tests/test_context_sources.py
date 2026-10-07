"""Phase 11 typed source admission and synthetic provider fixtures."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from personal_ai.applications.contracts import (
    ApplicationContextRequest,
    ApplicationDefinition,
    CapabilityRegistration,
)
from personal_ai.applications.registry import ApplicationRegistry, default_application_registry
from personal_ai.auth.scope import ApplicationScope, RequestScope
from personal_ai.context.adapters import (
    ClientContextProviderFactory,
    ConversationContextProviderFactory,
    MemoryContextProviderFactory,
    ResearchEvidenceContextProviderFactory,
    ToolResultProviderFactory,
    ToolResultSnapshot,
)
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.profile import (
    GlobalProfileContextProviderFactory,
    GlobalProfileFieldUpdate,
    GlobalProfileUpdate,
    InMemoryGlobalProfileRepository,
)
from personal_ai.context.providers import (
    ContextEntityReference,
    ContextItem,
    ContextOperationSpec,
    ContextPermissionDependency,
    ContextPreparationError,
    ContextProviderCoordinator,
    ContextProviderError,
    ContextProviderInputs,
    ContextProviderSpec,
    ContextSelection,
    ContextSourceReference,
    StaticContextProviderFactory,
)
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import Message, MessageRole, MessageStatus
from personal_ai.evidence.contracts import Evidence, SourceObservation
from personal_ai.memory.contracts import Memory, RetrievalResult, ScoredMemory
from personal_ai.settings import Settings

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


class SyntheticDomainPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    availability: str


class SyntheticContextProvider:
    spec = ContextProviderSpec(
        provider_id="synthetic.context",
        source_class="domain_current",
        source_version="synthetic-domain-v1",
        operations=(
            ContextOperationSpec(
                operation="current",
                allowed_fields=("name", "availability"),
                accepts_entity_refs=True,
                maximum_window_seconds=86_400,
                maximum_results=2,
                maximum_bytes=8_192,
                maximum_timeout_seconds=2,
            ),
        ),
        maximum_items_per_call=2,
    )

    def __init__(self, *, fail: str | None = None) -> None:
        self.fail = fail
        self.calls: list[tuple[tuple[str, ...], int, int]] = []

    def validate_selection(self, selection, inputs):
        assert inputs.scope.application_id == "synthetic"
        assert selection.operation == "current"

    def fetch(self, selection, scope, *, deadline):
        self.calls.append((selection.fields, selection.max_results, selection.max_bytes))
        if self.fail:
            raise ContextProviderError(self.fail)
        reference = ContextEntityReference(
            entity_type="stay",
            entity_id="fixture-stay-1",
            application_id=scope.application_id,
            workspace_id=scope.workspace_id,
        )
        return (
            ContextItem(
                source_class="domain_current",
                provider_id=self.spec.provider_id,
                source_id="synthetic-stays",
                source_version="fixture-7",
                item_id="stay-1",
                owner_id=scope.owner_id,
                application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                entity_refs=(reference,),
                authority="authoritative",
                observed_at=NOW,
                effective_at=NOW,
                expires_at=NOW + timedelta(days=1),
                sensitivity="sensitive",
                source_refs=(
                    ContextSourceReference(kind="record", reference_id="stay-1-v7"),
                ),
                permission_dependencies=(
                    ContextPermissionDependency(
                        permission_id="synthetic.read_stays",
                        version="v1",
                        purpose="read the selected synthetic stay",
                    ),
                ),
                payload=SyntheticDomainPayload(
                    name="Juniper House (synthetic)", availability="available"
                ),
            ),
        )


def synthetic_context(*provider_ids: str, tools=(), scope=None):
    definition = ApplicationDefinition(
        application_id="synthetic",
        display_name="Synthetic",
        memory_namespace="synthetic",
        context_provider_ids=provider_ids,
        tool_ids=tuple(item.capability_id for item in tools),
    )
    provider_capabilities = tuple(
        CapabilityRegistration(
            capability_id=provider_id,
            kind="context_provider",
            available=True,
        )
        for provider_id in provider_ids
    )
    registry = ApplicationRegistry((definition,), (*provider_capabilities, *tools))
    request_scope = scope or RequestScope(
        owner_id="owner-1", request_id="request-1", application_id="synthetic"
    )
    registration = registry.registration("synthetic")
    return ApplicationContextRequest(
        definition=definition,
        scope=request_scope,
        context_provider_capabilities=registration.context_providers,
        tool_capabilities=registration.tools,
    )


def selection(**updates):
    values = {
        "provider_id": "synthetic.context",
        "operation": "current",
        "fields": ("name", "availability"),
        "max_results": 1,
        "max_bytes": 4_096,
        "timeout_seconds": 1,
    }
    values.update(updates)
    return ContextSelection(**values)


def test_registered_synthetic_application_uses_shared_preparation_without_app_branching():
    context = synthetic_context("synthetic.context")
    provider = SyntheticContextProvider()
    coordinator = ContextProviderCoordinator(
        {"synthetic.context": StaticContextProviderFactory(provider)}
    )
    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id=context.scope.owner_id,
        role=MessageRole.USER,
        content="Find me a stay.",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
        application_id="synthetic",
    )

    assembled = ContextAssembler(
        Settings(ai_provider="fake", ai_model="fake-model"),
        FakeTokenCounter(),
        context_provider_coordinator=coordinator,
    ).assemble(
        (),
        pending,
        refresh=False,
        application_context=context,
        context_selections=(selection(),),
    )

    item = assembled.source_items[0]
    assert item.source_class == "domain_current"
    assert item.authority == "authoritative"
    assert item.sensitivity == "sensitive"
    assert item.expires_at == NOW + timedelta(days=1)
    assert item.source_refs[0].reference_id == "stay-1-v7"
    assert item.permission_dependencies[0].permission_id == "synthetic.read_stays"
    assert isinstance(item.payload, SyntheticDomainPayload)
    assert provider.calls == [(('name', 'availability'), 1, 4_096)]


def test_unknown_authority_and_timestamps_remain_explicit():
    class UnknownProvider(SyntheticContextProvider):
        spec = SyntheticContextProvider.spec.model_copy(
            update={"provider_id": "synthetic.unknown"}
        )

        def fetch(self, selection, scope, *, deadline):
            self.calls.append((selection.fields, selection.max_results, selection.max_bytes))
            return (
                ContextItem(
                    source_class="domain_current",
                    provider_id=self.spec.provider_id,
                    source_id="unknown-source",
                    source_version="v1",
                    item_id="unknown-1",
                    owner_id=scope.owner_id,
                    application_id=scope.application_id,
                    workspace_id=scope.workspace_id,
                    payload=SyntheticDomainPayload(name="Unknown", availability="unknown"),
                ),
            )

    context = synthetic_context("synthetic.unknown")
    provider = UnknownProvider()
    coordinator = ContextProviderCoordinator(
        {"synthetic.unknown": StaticContextProviderFactory(provider)}
    )
    result = coordinator.prepare(
        context,
        (selection(provider_id="synthetic.unknown"),),
        ContextProviderInputs(scope=context.scope, application_context=context),
    )
    assert result.items[0].authority == "unknown"
    assert result.items[0].observed_at is None
    assert result.items[0].effective_at is None
    assert result.items[0].expires_at is None


def test_invalid_cross_application_selection_denies_all_sources_before_any_call():
    context = synthetic_context("synthetic.context", "synthetic.second")
    provider = SyntheticContextProvider()
    second_calls = []
    second = SyntheticContextProvider()
    second.spec = second.spec.model_copy(update={"provider_id": "synthetic.second"})

    def second_fetch(request, scope, *, deadline):
        second_calls.append(True)
        return ()

    second.fetch = second_fetch
    coordinator = ContextProviderCoordinator(
        {
            "synthetic.context": StaticContextProviderFactory(provider),
            "synthetic.second": StaticContextProviderFactory(second),
        }
    )

    with pytest.raises(ContextPreparationError, match="context_cross_application_denied"):
        coordinator.prepare(
            context,
            (
                selection(provider_id="synthetic.second"),
                selection(
                    provider_id="synthetic.context",
                    target_scope=ApplicationScope(application_id="travel"),
                ),
            ),
            ContextProviderInputs(scope=context.scope),
        )

    assert provider.calls == []
    assert second_calls == []


@pytest.mark.parametrize(
    "changes,error_code",
    [
        ({"fields": ("unknown_field",)}, "context_fields_not_allowed"),
        ({"max_results": 3}, "context_result_limit_exceeded"),
        ({"max_bytes": 9_000}, "context_byte_limit_exceeded"),
        ({"timeout_seconds": 3}, "context_timeout_limit_exceeded"),
        (
            {
                "entity_refs": (
                    ContextEntityReference(
                        entity_type="stay",
                        entity_id="foreign",
                        application_id="travel",
                    ),
                )
            },
            "context_cross_application_denied",
        ),
        (
            {
                "window_start": NOW - timedelta(days=2),
                "window_end": NOW,
            },
            "context_time_window_exceeded",
        ),
    ],
)
def test_bounds_and_scope_are_rejected_before_source_call(changes, error_code):
    context = synthetic_context("synthetic.context")
    provider = SyntheticContextProvider()
    coordinator = ContextProviderCoordinator(
        {"synthetic.context": StaticContextProviderFactory(provider)}
    )
    with pytest.raises(ContextPreparationError, match=error_code):
        coordinator.prepare(
            context,
            (selection(**changes),),
            ContextProviderInputs(scope=context.scope),
        )
    assert provider.calls == []


def test_optional_failures_are_bounded_and_required_failure_stops_later_sources():
    context = synthetic_context("synthetic.context", "synthetic.later")
    failing = SyntheticContextProvider(fail="synthetic timeout")
    later = SyntheticContextProvider()
    later.spec = later.spec.model_copy(update={"provider_id": "synthetic.later"})
    # Keep the provider implementation's emitted identity aligned with its registration.
    later.fetch = lambda request, scope, *, deadline: ()
    coordinator = ContextProviderCoordinator(
        {
            "synthetic.context": StaticContextProviderFactory(failing),
            "synthetic.later": StaticContextProviderFactory(later),
        }
    )
    optional = coordinator.prepare(
        context,
        (selection(required=False),),
        ContextProviderInputs(scope=context.scope),
    )
    assert optional.failures[0].reason == "timeout"
    assert "synthetic timeout" not in str(optional.failures[0])

    with pytest.raises(ContextPreparationError, match="required_context_source_unavailable"):
        coordinator.prepare(
            context,
            (
                selection(provider_id="synthetic.later", required=False),
                selection(required=True),
            ),
            ContextProviderInputs(scope=context.scope),
        )
    assert later.calls == []


def test_profile_is_sparse_user_set_and_shared_per_field_before_disclosure():
    registry = default_application_registry()
    travel = registry.registration("travel")
    scope = RequestScope(owner_id="owner-1", request_id="request-1", application_id="travel")
    context = ApplicationContextRequest(
        definition=travel.definition,
        scope=scope,
        context_provider_capabilities=travel.context_providers,
        tool_capabilities=travel.tools,
    )
    repository = InMemoryGlobalProfileRepository(clock=lambda: NOW)
    assert repository.get("owner-1").fields == ()
    profile = repository.update(
        "owner-1",
        GlobalProfileUpdate(
            fields=(
                GlobalProfileFieldUpdate(
                    field="preferred_units",
                    value="metric",
                    shared_with_applications=("travel",),
                ),
                GlobalProfileFieldUpdate(field="locale", value="en-GB"),
            )
        ),
    )
    assert profile.revision == 1
    assert all(item.set_by == "user" and item.set_at == NOW for item in profile.fields)

    coordinator = ContextProviderCoordinator(
        {"global_profile": GlobalProfileContextProviderFactory(repository)}
    )
    result = coordinator.prepare(
        context,
        (
            ContextSelection(
                provider_id="global_profile",
                operation="profile",
                fields=("preferred_units", "locale"),
                max_results=2,
                max_bytes=4_096,
                timeout_seconds=1,
            ),
        ),
        ContextProviderInputs(scope=scope, application_context=context),
    )
    assert len(result.items) == 1
    assert result.items[0].source_class == "global_profile"
    assert result.items[0].authority == "user_asserted"
    assert result.items[0].item_id == "preferred_units"
    assert result.items[0].payload.value == "metric"
    assert "shared_with_applications" not in result.items[0].payload.model_dump()
    assert [item.field for _, item in repository.shared_fields(
        "owner-1", "travel", ("preferred_units", "locale")
    )] == ["preferred_units"]

    removed = repository.update(
        "owner-1", GlobalProfileUpdate(remove_fields=("preferred_units",))
    )
    assert [item.field for item in removed.fields] == ["locale"]
    assert removed.revision == 2


def test_client_context_is_non_authoritative_and_only_selected_fields_are_disclosed():
    scope = RequestScope(
        owner_id="owner-1",
        request_id="request-1",
        application_id="synthetic",
        client_context={"display_mode": "compact", "owner_id": "untrusted"},
    )
    context = synthetic_context(scope=scope)
    registration = default_application_registry().registration("personal_ai")
    # Use the built-in shared capability metadata with the synthetic scope/definition.
    context = context.model_copy(
        update={"context_provider_capabilities": registration.context_providers}
    )
    coordinator = ContextProviderCoordinator({"client_context": ClientContextProviderFactory()})
    result = coordinator.prepare(
        context,
        (
            ContextSelection(
                provider_id="client_context",
                operation="profile",
                fields=("display_mode",),
                max_results=1,
                max_bytes=4_096,
                timeout_seconds=0.1,
            ),
        ),
        ContextProviderInputs(scope=scope, application_context=context),
    )
    item = result.items[0]
    assert item.authority == "client_supplied"
    assert item.payload.key == "display_mode"
    assert item.payload.value == "compact"


def test_conversation_wrapper_projects_only_requested_fields_from_active_branch():
    registry = default_application_registry()
    application = registry.registration("personal_ai")
    scope = RequestScope(owner_id="local", request_id="request-1", application_id="personal_ai")
    context = ApplicationContextRequest(
        definition=application.definition,
        scope=scope,
        context_provider_capabilities=application.context_providers,
        tool_capabilities=application.tools,
    )
    message = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id="local",
        role=MessageRole.USER,
        content="private text",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
    )
    coordinator = ContextProviderCoordinator(
        {"conversation_history": ConversationContextProviderFactory()}
    )
    result = coordinator.prepare(
        context,
        (
            ContextSelection(
                provider_id="conversation_history",
                operation="history",
                fields=("role", "created_at", "id"),
                max_results=1,
                max_bytes=4_096,
                timeout_seconds=1,
            ),
        ),
        ContextProviderInputs(scope=scope, application_context=context, active_messages=(message,)),
    )
    assert result.items[0].payload.role == "user"
    assert result.items[0].payload.id == str(message.id)
    assert result.items[0].payload.content is None


def test_memory_wrapper_preserves_source_refs_without_disclosing_embeddings():
    registry = default_application_registry()
    application = registry.registration("personal_ai")
    scope = RequestScope(owner_id="local", request_id="request-1", application_id="personal_ai")
    context = ApplicationContextRequest(
        definition=application.definition,
        scope=scope,
        context_provider_capabilities=application.context_providers,
        tool_capabilities=application.tools,
    )
    source_message_id = uuid4()
    memory = Memory(
        id=uuid4(),
        owner_id="local",
        memory_type="preference",
        content="I prefer metric units.",
        confidence=0.9,
        source_message_ids=(source_message_id,),
        rationale_code="user_preference",
        normalized_content="i prefer metric units.",
        source_conversation_id=uuid4(),
        source_turn_id=uuid4(),
        source_fingerprint="a" * 64,
        observed_at=NOW,
        effective_at=NOW,
        created_at=NOW,
        embedding=(1.0, 0.0),
        embedding_model="fixture-v1",
        embedding_dimensions=2,
        application_id="personal_ai",
        workspace_id=None,
        scope_version=2,
    )
    coordinator = ContextProviderCoordinator(
        {"ai_memory": MemoryContextProviderFactory()},
        feature_flags={"memory_enabled": True},
    )
    result = coordinator.prepare(
        context,
        (
            ContextSelection(
                provider_id="ai_memory",
                operation="search",
                fields=("content", "memory_type", "effective_at"),
                max_results=1,
                max_bytes=8_192,
                timeout_seconds=1,
            ),
        ),
        ContextProviderInputs(
            scope=scope,
            application_context=context,
            retrieval=RetrievalResult(selected=(ScoredMemory(memory, 0.9),)),
        ),
    )
    item = result.items[0]
    assert item.source_class == "ai_memory"
    assert item.source_refs[0].reference_id == str(source_message_id)
    assert item.payload.content == "I prefer metric units."
    assert "embedding" not in item.payload.model_dump()


def test_research_wrapper_keeps_expiry_and_exact_source_attribution():
    registry = default_application_registry()
    application = registry.registration("personal_ai")
    scope = RequestScope(owner_id="local", request_id="request-1", application_id="personal_ai")
    context = ApplicationContextRequest(
        definition=application.definition,
        scope=scope,
        context_provider_capabilities=application.context_providers,
        tool_capabilities=application.tools,
    )
    passage = "Synthetic opening hours are 09:00 to 17:00."
    fingerprint = sha256(" ".join(passage.split()).encode()).hexdigest()
    session_id, query_id, observation_id, evidence_id = (uuid4() for _ in range(4))
    observation = SourceObservation(
        id=observation_id,
        session_id=session_id,
        query_id=query_id,
        owner_id="local",
        canonical_url="https://example.org/synthetic-hours",
        title="Synthetic hours",
        provider="fake",
        observed_at=NOW - timedelta(days=2),
        content_fingerprint=fingerprint,
        status="accepted",
        attempt_id=uuid4(),
    )
    evidence = Evidence(
        id=evidence_id,
        session_id=session_id,
        owner_id="local",
        source_observation_ids=(observation_id,),
        passage=passage,
        content_fingerprint=fingerprint,
        observed_at=NOW - timedelta(days=2),
        expires_at=NOW - timedelta(days=1),
        expiry_policy="current",
    )
    coordinator = ContextProviderCoordinator(
        {"external_research": ResearchEvidenceContextProviderFactory()}
    )
    result = coordinator.prepare(
        context,
        (
            ContextSelection(
                provider_id="external_research",
                operation="search",
                fields=("passage", "observed_at", "expires_at"),
                max_results=1,
                max_bytes=8_192,
                timeout_seconds=1,
            ),
        ),
        ContextProviderInputs(
            scope=scope,
            application_context=context,
            evidence_records=((evidence, (observation,)),),
        ),
    )
    item = result.items[0]
    assert item.authority == "external"
    assert item.expires_at == NOW - timedelta(days=1)
    assert item.payload.passage == passage
    assert item.source_refs[0].uri == "https://example.org/synthetic-hours"


def test_tool_results_require_registered_bounded_read_only_capability_and_typed_projection():
    tool = CapabilityRegistration(
        capability_id="synthetic.lookup",
        kind="tool",
        available=True,
        read_only_context=True,
        result_fields=("name", "status"),
        max_result_bytes=4_096,
    )
    context = synthetic_context(tools=(tool,))
    provider = ToolResultProviderFactory(
        tool,
        lambda payload, fields: SyntheticDomainPayload(
            name=payload.name if "name" in fields else "",
            availability=payload.availability if "status" in fields else "",
        ),
    )
    coordinator = ContextProviderCoordinator({"synthetic.lookup": provider})
    snapshot = ToolResultSnapshot(
        invocation_id="call-1",
        owner_id=context.scope.owner_id,
        application_id=context.scope.application_id,
        workspace_id=context.scope.workspace_id,
        payload=SyntheticDomainPayload(name="Fixture stay", availability="available"),
        observed_at=NOW,
    )
    result = coordinator.prepare(
        context,
        (
            ContextSelection(
                provider_id="synthetic.lookup",
                operation="current",
                fields=("name",),
                max_results=1,
                max_bytes=2_048,
                timeout_seconds=0.1,
            ),
        ),
        ContextProviderInputs(
            scope=context.scope,
            application_context=context,
            tool_results={"synthetic.lookup": snapshot},
        ),
    )
    assert result.items[0].source_class == "tool_result"
    assert result.items[0].source_refs[0].reference_id == "call-1"
    assert result.items[0].payload.result.name == "Fixture stay"
    assert result.items[0].payload.result.availability == ""

    non_read = tool.model_copy(
        update={"read_only_context": False, "result_fields": (), "max_result_bytes": None}
    )
    with pytest.raises(ContextPreparationError, match="context_tool_result_not_registered_read_only"):
        non_read_context = synthetic_context(tools=(non_read,))
        ContextProviderCoordinator({"synthetic.lookup": provider}).prepare(
            non_read_context,
            (
                ContextSelection(
                    provider_id="synthetic.lookup",
                    operation="current",
                    fields=("name",),
                    max_results=1,
                    max_bytes=2_048,
                    timeout_seconds=0.1,
                ),
            ),
            ContextProviderInputs(scope=non_read_context.scope),
        )
