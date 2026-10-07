"""Phase 11 typed source admission and synthetic provider fixtures."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import monotonic
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from personal_ai.applications.contracts import (
    ApplicationContextRequest,
    ApplicationDefinition,
    CapabilityRegistration,
)
from personal_ai.applications.registry import ApplicationRegistry, default_application_registry
from personal_ai.auth.scope import ApplicationScope, RequestScope
from personal_ai.context.adapters import (
    BuiltInContextPermissionRevalidator,
    ClientContextProviderFactory,
    ConversationContextProvider,
    ConversationContextProviderFactory,
    MemoryContextProviderFactory,
    ResearchEvidenceContextProviderFactory,
    ToolResultProviderFactory,
    ToolResultSnapshot,
)
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.contracts import ContextError
from personal_ai.context.inspection import ContextInspector
from personal_ai.context.planner import ContextPlanner
from personal_ai.context.profile import (
    GlobalProfileContextProviderFactory,
    GlobalProfileFieldUpdate,
    GlobalProfileUpdate,
    InMemoryGlobalProfileRepository,
)
from personal_ai.context.providers import (
    ContextEntityReference,
    ContextFieldSensitivity,
    ContextItem,
    ContextOperationSpec,
    ContextPermissionDependency,
    ContextPreparationError,
    ContextProviderCoordinator,
    ContextProviderError,
    ContextProviderFailure,
    ContextProviderInputs,
    ContextProviderResult,
    ContextProviderSpec,
    ContextSelection,
    ContextSourceReference,
    StaticContextProviderFactory,
)
from personal_ai.context.repositories import InMemorySummaryRepository
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import Message, MessageRole, MessageStatus
from personal_ai.evidence.contracts import Evidence, SourceObservation
from personal_ai.memory.contracts import (
    DerivedMemory,
    DerivedMemorySource,
    Memory,
    RetrievalResult,
    ScoredMemory,
    normalize,
)
from personal_ai.settings import Settings

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


class SyntheticDomainPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = None
    availability: str | None = None


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
                sensitivity=("sensitive" if "availability" in selection.fields else "personal"),
                field_sensitivity=tuple(
                    ContextFieldSensitivity(field=field, sensitivity=sensitivity)
                    for field, sensitivity in (
                        ("name", "personal"),
                        ("availability", "sensitive"),
                    )
                    if field in selection.fields
                ),
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
                    name="Juniper House (synthetic)" if "name" in selection.fields else None,
                    availability="available" if "availability" in selection.fields else None,
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


def _memory_record(scope, *, content="I prefer metric units.", status="active"):
    source_message_id = uuid4()
    return Memory(
        id=uuid4(),
        owner_id=scope.owner_id,
        memory_type="preference",
        content=content,
        confidence=0.9,
        source_message_ids=(source_message_id,),
        rationale_code="user_preference",
        normalized_content=normalize(content),
        status=status,
        source_conversation_id=uuid4(),
        source_turn_id=uuid4(),
        source_fingerprint=sha256(str(source_message_id).encode()).hexdigest(),
        observed_at=NOW,
        effective_at=NOW,
        created_at=NOW,
        embedding=(1.0, 0.0),
        embedding_model="fixture-v1",
        embedding_dimensions=2,
        application_id=scope.application_id,
        workspace_id=scope.workspace_id,
        scope_version=2,
    )


def _derived_memory_record(scope):
    memory_ids = (UUID(int=21), UUID(int=22))
    sources = tuple(
        DerivedMemorySource(
            memory_id=identifier,
            source_fingerprint=f"{index:x}" * 64,
            source_conversation_id=UUID(int=31 + index),
            source_turn_id=UUID(int=41 + index),
            source_message_ids=(UUID(int=51 + index),),
            excerpt="I like tea",
        )
        for index, identifier in enumerate(memory_ids, start=1)
    )
    namespace = [] if scope.application_id == "personal_ai" and scope.workspace_id is None else [
        scope.application_id,
        scope.workspace_id or "",
    ]
    identity_key = sha256(
        "\0".join(
            [scope.owner_id, *namespace, "extractive-v1"]
            + [f"{item.memory_id}:{item.source_fingerprint}" for item in sources]
        ).encode()
    ).hexdigest()
    content = "Historical personal context from repeated user statements:\nI like tea\nI like tea"
    return DerivedMemory(
        id=uuid5(NAMESPACE_URL, "personal-ai-derived-memory:" + identity_key),
        owner_id=scope.owner_id,
        application_id=scope.application_id,
        workspace_id=scope.workspace_id,
        memory_type="preference",
        content=content,
        normalized_content=normalize(content),
        confidence=0.8,
        importance=0.7,
        effective_at=NOW,
        created_at=NOW,
        embedding=(1.0, 0.0),
        embedding_model="fixture-v1",
        embedding_dimensions=2,
        source_memory_ids=memory_ids,
        sources=sources,
        source_set_identity=identity_key,
        derivation_policy_version="extractive-v1",
        rationale_code="repeated_explicit_preference",
    )


def _conversation_history(count: int, *, summary_content="Historical summary"):
    conversation_id = uuid4()
    messages = []
    for index in range(count // 2):
        user = Message(
            id=uuid4(),
            conversation_id=conversation_id,
            owner_id="local",
            role=MessageRole.USER,
            content=f"question {index}",
            status=MessageStatus.COMPLETED,
            created_at=NOW + timedelta(seconds=index * 2),
            application_id="personal_ai",
        )
        assistant = Message(
            id=uuid4(),
            conversation_id=conversation_id,
            owner_id="local",
            role=MessageRole.ASSISTANT,
            content=f"answer {index}",
            status=MessageStatus.COMPLETED,
            parent_message_id=user.id,
            created_at=NOW + timedelta(seconds=index * 2 + 1),
            application_id="personal_ai",
        )
        messages.extend((user, assistant))
    if count % 2:
        messages.append(
            Message(
                id=uuid4(),
                conversation_id=conversation_id,
                owner_id="local",
                role=MessageRole.USER,
                content="one more question",
                status=MessageStatus.COMPLETED,
                created_at=NOW + timedelta(seconds=count),
                application_id="personal_ai",
            )
        )
    from personal_ai.context.contracts import ConversationSummary, fingerprint

    active = tuple(messages)
    ids = tuple(message.id for message in active)
    summary = ConversationSummary(
        id=uuid4(),
        conversation_id=conversation_id,
        owner_id="local",
        application_id="personal_ai",
        workspace_id=None,
        content=summary_content,
        source_message_ids=ids,
        source_fingerprint=fingerprint(active),
        coverage_message_ids=ids,
        coverage_fingerprint=fingerprint(active, include_state=True),
        covers_through_message_id=ids[-1],
        source_token_count=100,
        summary_token_count=10,
        model="fixture",
        created_at=NOW,
    )
    return active, summary


def _research_case(scope, *, observation_overrides=(), source_ids_override=None):
    session_id = uuid4()
    passage = "A bounded synthetic evidence passage."
    fingerprint = sha256(" ".join(passage.split()).encode()).hexdigest()
    observations = []
    for index in range(len(observation_overrides) or 1):
        overrides = dict(observation_overrides[index]) if observation_overrides else {}
        observations.append(
            SourceObservation(
                id=overrides.pop("id", uuid4()),
                session_id=overrides.pop("session_id", session_id),
                query_id=uuid4(),
                owner_id=overrides.pop("owner_id", scope.owner_id),
                application_id=overrides.pop("application_id", scope.application_id),
                workspace_id=overrides.pop("workspace_id", scope.workspace_id),
                canonical_url=overrides.pop("canonical_url", f"https://example.org/source-{index}"),
                title="Synthetic source",
                provider="fake",
                observed_at=NOW,
                content_fingerprint=overrides.pop("content_fingerprint", fingerprint),
                status=overrides.pop("status", "accepted"),
                attempt_id=uuid4(),
                **overrides,
            )
        )
    observation_ids = tuple(item.id for item in observations)
    evidence_ids = (
        tuple(source_ids_override)
        if source_ids_override is not None
        else observation_ids
    )
    evidence = Evidence(
        id=uuid4(),
        session_id=session_id,
        owner_id=scope.owner_id,
        application_id=scope.application_id,
        workspace_id=scope.workspace_id,
        source_observation_ids=evidence_ids,
        passage=passage,
        content_fingerprint=fingerprint,
        observed_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(days=1),
        expiry_policy="current",
    )
    return evidence, tuple(observations)


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
    source_report = next(
        row for row in assembled.manifest.items if row.item_id == "stay-1"
    )
    assert not source_report.injected
    assert source_report.omission_reason == "permission_unverified"
    assert "Juniper House (synthetic)" not in "\n".join(
        message.content for message in assembled.messages
    )


def test_assembler_rechecks_grants_and_injects_typed_source_with_actual_manifest(caplog):
    caplog.set_level("DEBUG", logger="personal_ai.context.assembler")
    context = synthetic_context("synthetic.context")
    provider = SyntheticContextProvider()
    coordinator = ContextProviderCoordinator(
        {"synthetic.context": StaticContextProviderFactory(provider)}
    )

    class CurrentPermission:
        def is_current(self, dependency):
            return dependency.permission_id == "synthetic.read_stays" and dependency.version == "v1"

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
        permission_revalidator=CurrentPermission(),
    ).assemble(
        (),
        pending,
        refresh=False,
        application_context=context,
        context_selections=(selection(),),
    )

    assert any("Juniper House (synthetic)" in message.content for message in assembled.messages)
    assert assembled.manifest.actual_build
    assert assembled.manifest.effective_sensitivity == "sensitive"
    injected = [item for item in assembled.manifest.items if item.injected]
    assert [item.item_id for item in injected] == ["stay-1"]
    assert injected[0].authority == "authoritative"
    assert injected[0].source_reference_count == 1
    assert injected[0].source_version == "fixture-7"
    assert assembled.manifest.selected_message_ids == (str(pending.id),)
    assert str(pending.id) in caplog.text
    assert '"source_version":"fixture-7"' in "\n".join(
        message.content for message in assembled.messages
    )
    assert "Juniper House (synthetic)" not in caplog.text


def test_typed_source_expiring_during_counting_is_removed_or_rejected():
    context = synthetic_context("synthetic.context")
    expiry = NOW + timedelta(seconds=1)

    class ExpiringProvider(SyntheticContextProvider):
        def fetch(self, request, scope, *, deadline):
            del deadline
            return (
                ContextItem(
                    source_class="domain_current",
                    provider_id=self.spec.provider_id,
                    source_id="expiring-source",
                    source_version="expiring-v1",
                    item_id="typed-expires-during-count",
                    owner_id=scope.owner_id,
                    application_id=scope.application_id,
                    workspace_id=scope.workspace_id,
                    authority="authoritative",
                    observed_at=NOW,
                    expires_at=expiry,
                    sensitivity="personal",
                    source_refs=(ContextSourceReference(kind="record", reference_id="expiring-source"),),
                    payload=SyntheticDomainPayload(name="typed expires during count"),
                ),
            )

    class AdvancingCounter(FakeTokenCounter):
        def __init__(self, clock_value):
            self.clock_value = clock_value

        def count(self, messages):
            result = super().count(messages)
            if any("typed expires during count" in message.content for message in messages):
                self.clock_value[0] = NOW + timedelta(seconds=2)
            return result

    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id=context.scope.owner_id,
        role=MessageRole.USER,
        content="Use current context.",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
        application_id="synthetic",
    )
    coordinator = ContextProviderCoordinator(
        {"synthetic.context": StaticContextProviderFactory(ExpiringProvider())}
    )
    clock_value = [NOW]
    assembled = ContextAssembler(
        Settings(ai_provider="fake", ai_model="fake-model"),
        AdvancingCounter(clock_value),
        context_provider_coordinator=coordinator,
    ).assemble(
        (),
        pending,
        refresh=False,
        application_context=context,
        context_selections=(selection(),),
        clock=lambda: clock_value[0],
    )
    report = assembled.manifest.items[0]
    assert not report.injected
    assert report.omission_reason == "expired"
    assert all("typed expires during count" not in message.content for message in assembled.messages)

    clock_value[0] = NOW
    with pytest.raises(ContextError, match="context_source_unavailable"):
        ContextAssembler(
            Settings(ai_provider="fake", ai_model="fake-model"),
            AdvancingCounter(clock_value),
            context_provider_coordinator=coordinator,
        ).assemble(
            (),
            pending,
            refresh=False,
            application_context=context,
            context_selections=(selection(required=True),),
            clock=lambda: clock_value[0],
        )


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
                    source_refs=(
                        ContextSourceReference(kind="record", reference_id="unknown-source-v1"),
                    ),
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


def test_context_payload_requires_a_typed_model_at_construction_and_normalization():
    context = synthetic_context("synthetic.context")
    with pytest.raises(TypeError, match="context_payload_must_be_typed"):
        ContextItem(
            source_class="domain_current",
            provider_id="synthetic.context",
            source_id="source-1",
            source_version="v1",
            item_id="item-1",
            owner_id=context.scope.owner_id,
            application_id=context.scope.application_id,
            payload={"untyped": "data"},
        )

    class ForgedProvider(SyntheticContextProvider):
        def fetch(self, selection, scope, *, deadline):
            del selection, deadline
            item = ContextItem.model_construct(
                source_class="domain_current",
                provider_id=self.spec.provider_id,
                source_id="source-1",
                source_version="v1",
                item_id="item-1",
                owner_id=scope.owner_id,
                application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                entity_refs=(),
                authority="unknown",
                observed_at=None,
                effective_at=None,
                expires_at=None,
                sensitivity="unknown",
                source_refs=(),
                permission_dependencies=(),
                field_sensitivity=(),
                payload={"untyped": "data"},
            )
            return (item,)

    provider = ForgedProvider()
    with pytest.raises(ContextPreparationError, match="context_provider_item_invalid"):
        ContextProviderCoordinator(
            {"synthetic.context": StaticContextProviderFactory(provider)}
        ).prepare(
            context,
            (selection(),),
            ContextProviderInputs(scope=context.scope),
        )


def test_context_items_require_real_provenance_at_construction_and_result_boundary():
    context = synthetic_context("synthetic.context")
    with pytest.raises(ValidationError, match="context_source_refs_required"):
        ContextItem(
            source_class="domain_current",
            provider_id="synthetic.context",
            source_id="source-1",
            source_version="v1",
            item_id="item-1",
            owner_id=context.scope.owner_id,
            application_id=context.scope.application_id,
            payload=SyntheticDomainPayload(name="fixture"),
        )

    class ForgedMissingProvenanceProvider(SyntheticContextProvider):
        def fetch(self, selection, scope, *, deadline):
            del selection, deadline
            return (
                ContextItem.model_construct(
                    source_class="domain_current",
                    provider_id=self.spec.provider_id,
                    source_id="source-1",
                    source_version="v1",
                    item_id="item-1",
                    owner_id=scope.owner_id,
                    application_id=scope.application_id,
                    workspace_id=scope.workspace_id,
                    entity_refs=(),
                    authority="unknown",
                    observed_at=None,
                    effective_at=None,
                    expires_at=None,
                    sensitivity="unknown",
                    source_refs=(),
                    permission_dependencies=(),
                    field_sensitivity=(),
                    payload=SyntheticDomainPayload(name="fixture"),
                ),
            )

    with pytest.raises(ContextPreparationError, match="context_provider_provenance_missing"):
        ContextProviderCoordinator(
            {"synthetic.context": StaticContextProviderFactory(ForgedMissingProvenanceProvider())}
        ).prepare(
            context,
            (selection(),),
            ContextProviderInputs(scope=context.scope),
        )


def test_returned_entity_references_must_match_explicit_selection():
    context = synthetic_context("synthetic.context")
    requested = ContextEntityReference(
        entity_type="stay",
        entity_id="fixture-stay-1",
        application_id="synthetic",
    )
    additional_requested = ContextEntityReference(
        entity_type="stay",
        entity_id="fixture-stay-2",
        application_id="synthetic",
    )
    provider = SyntheticContextProvider()
    coordinator = ContextProviderCoordinator(
        {"synthetic.context": StaticContextProviderFactory(provider)}
    )
    result = coordinator.prepare(
        context,
        (selection(entity_refs=(requested, additional_requested)),),
        ContextProviderInputs(scope=context.scope),
    )
    assert result.items[0].entity_refs == (requested,)

    unrelated = ContextEntityReference(
        entity_type="stay",
        entity_id="unrelated-stay",
        application_id="synthetic",
    )

    class UnrelatedEntityProvider(SyntheticContextProvider):
        def fetch(self, request, scope, *, deadline):
            item = super().fetch(request, scope, deadline=deadline)[0]
            return (item.model_copy(update={"entity_refs": (unrelated,)}),)

    with pytest.raises(
        ContextPreparationError,
        match="context_provider_entity_selection_violation",
    ):
        ContextProviderCoordinator(
            {"synthetic.context": StaticContextProviderFactory(UnrelatedEntityProvider())}
        ).prepare(
            context,
            (selection(entity_refs=(requested,), required=True),),
            ContextProviderInputs(scope=context.scope),
        )


@pytest.mark.parametrize(
    "source_class,capability_kind",
    [("domain_current", "tool"), ("tool_result", "context_provider")],
)
def test_provider_spec_rejects_contradictory_tool_source_class(
    source_class, capability_kind
):
    with pytest.raises(ValidationError, match="context_provider_tool_source_class_mismatch"):
        ContextProviderSpec(
            provider_id="synthetic.invalid",
            source_class=source_class,
            source_version="v1",
            capability_kind=capability_kind,
            operations=(ContextOperationSpec(operation="current", fields_required=False),),
        )


@pytest.mark.parametrize("source_class", ["external_research", "client_context"])
def test_untrusted_source_classes_cannot_claim_authoritative_state(source_class):
    provider_id = "synthetic.untrusted"
    context = synthetic_context(provider_id)
    spec = SyntheticContextProvider.spec.model_copy(
        update={"provider_id": provider_id, "source_class": source_class}
    )

    class ForgedAuthorityProvider(SyntheticContextProvider):
        def __init__(self):
            super().__init__()
            self.spec = spec

        def fetch(self, selection, scope, *, deadline):
            del selection, deadline
            return (
                ContextItem.model_construct(
                    source_class=source_class,
                    provider_id=provider_id,
                    source_id="source-1",
                    source_version="v1",
                    item_id="item-1",
                    owner_id=scope.owner_id,
                    application_id=scope.application_id,
                    workspace_id=scope.workspace_id,
                    entity_refs=(),
                    authority="authoritative",
                    observed_at=None,
                    effective_at=None,
                    expires_at=None,
                    sensitivity="unknown",
                    source_refs=(ContextSourceReference(kind="record", reference_id="source-1"),),
                    permission_dependencies=(),
                    field_sensitivity=(),
                    payload=SyntheticDomainPayload(name="fixture"),
                ),
            )

    provider = ForgedAuthorityProvider()
    with pytest.raises(ContextPreparationError, match="context_provider_authority_violation"):
        ContextProviderCoordinator(
            {provider_id: StaticContextProviderFactory(provider)}
        ).prepare(
            context,
            (selection(provider_id=provider_id),),
            ContextProviderInputs(scope=context.scope),
        )


def test_field_sensitivity_tracks_the_disclosed_projection_and_unknowns_are_explicit():
    context = synthetic_context("synthetic.context")
    provider = SyntheticContextProvider()
    result = ContextProviderCoordinator(
        {"synthetic.context": StaticContextProviderFactory(provider)}
    ).prepare(
        context,
        (selection(fields=("name",)),),
        ContextProviderInputs(scope=context.scope),
    )
    item = result.items[0]
    assert item.sensitivity == "personal"
    assert [(value.field, value.sensitivity) for value in item.field_sensitivity] == [
        ("name", "personal")
    ]
    assert item.payload.name == "Juniper House (synthetic)"
    assert item.payload.availability is None

    class MixedSensitivityPayload(BaseModel):
        public_summary: str | None = None
        personal_name: str | None = None
        restricted_value: str | None = None
        omitted_value: str | None = None

    mixed = ContextItem(
        source_class="domain_current",
        provider_id="synthetic.context",
        source_id="source-mixed",
        source_version="v1",
        item_id="item-mixed",
        owner_id=context.scope.owner_id,
        application_id=context.scope.application_id,
        sensitivity="restricted",
        source_refs=(ContextSourceReference(kind="record", reference_id="source-mixed"),),
        field_sensitivity=(
            ContextFieldSensitivity(field="public_summary", sensitivity="public"),
            ContextFieldSensitivity(field="personal_name", sensitivity="personal"),
            ContextFieldSensitivity(field="restricted_value", sensitivity="restricted"),
        ),
        payload=MixedSensitivityPayload(
            public_summary="synthetic",
            personal_name="owner",
            restricted_value="private fixture",
        ),
    )
    assert {item.field for item in mixed.field_sensitivity} == {
        "public_summary", "personal_name", "restricted_value"
    }
    assert "omitted_value" not in {item.field for item in mixed.field_sensitivity}

    unknown = ContextItem(
        source_class="domain_current",
        provider_id="synthetic.context",
        source_id="source-1",
        source_version="v1",
        item_id="item-1",
        owner_id=context.scope.owner_id,
        application_id=context.scope.application_id,
        sensitivity="unknown",
        source_refs=(ContextSourceReference(kind="record", reference_id="source-1"),),
        field_sensitivity=(ContextFieldSensitivity(field="name", sensitivity="unknown"),),
        payload=SyntheticDomainPayload(name="fixture"),
    )
    assert unknown.field_sensitivity[0].sensitivity == "unknown"
    with pytest.raises(ValidationError, match="context_field_sensitivity_outside_payload"):
        ContextItem(
            source_class="domain_current",
            provider_id="synthetic.context",
            source_id="source-1",
            source_version="v1",
            item_id="item-1",
            owner_id=context.scope.owner_id,
            application_id=context.scope.application_id,
            sensitivity="personal",
            source_refs=(ContextSourceReference(kind="record", reference_id="source-1"),),
            field_sensitivity=(ContextFieldSensitivity(field="secret", sensitivity="restricted"),),
            payload=SyntheticDomainPayload(name="fixture"),
        )
    with pytest.raises(ValidationError):
        ContextFieldSensitivity.model_validate({"field": "name", "sensitivity": "secret"})
    with pytest.raises(ValidationError, match="context_aggregate_sensitivity_understated"):
        ContextItem(
            source_class="domain_current",
            provider_id="synthetic.context",
            source_id="source-1",
            source_version="v1",
            item_id="item-1",
            owner_id=context.scope.owner_id,
            application_id=context.scope.application_id,
            sensitivity="personal",
            source_refs=(ContextSourceReference(kind="record", reference_id="source-1"),),
            field_sensitivity=(ContextFieldSensitivity(field="name", sensitivity="restricted"),),
            payload=SyntheticDomainPayload(name="fixture"),
        )


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


@pytest.mark.parametrize("unavailable_kind", ["missing", "disabled", "unsupported"])
@pytest.mark.parametrize("foreign_scope", ["target", "entity"])
def test_universal_scope_denial_precedes_provider_availability(
    unavailable_kind, foreign_scope
):
    unavailable_id = f"synthetic.{unavailable_kind}"
    context = synthetic_context(unavailable_id, "synthetic.context")
    provider = SyntheticContextProvider()
    unavailable = SyntheticContextProvider()
    unavailable.spec = unavailable.spec.model_copy(update={"provider_id": unavailable_id})
    feature_flags = None
    if unavailable_kind == "disabled":
        capabilities = tuple(
            capability.model_copy(update={"feature_gate": "memory_enabled"})
            if capability.capability_id == unavailable_id
            else capability
            for capability in context.context_provider_capabilities
        )
        context = context.model_copy(update={"context_provider_capabilities": capabilities})
        feature_flags = {"memory_enabled": False}
    factories = {"synthetic.context": StaticContextProviderFactory(provider)}
    if unavailable_kind != "missing":
        factories[unavailable_id] = StaticContextProviderFactory(unavailable)
    coordinator = ContextProviderCoordinator(factories, feature_flags=feature_flags)
    foreign = ContextEntityReference(
        entity_type="stay", entity_id="foreign", application_id="travel"
    )
    unavailable_selection = ContextSelection(
        provider_id=unavailable_id,
        operation="history" if unavailable_kind == "unsupported" else "current",
        fields=("name", "availability"),
        entity_refs=(foreign,) if foreign_scope == "entity" else (),
        target_scope=(
            ApplicationScope(application_id="travel") if foreign_scope == "target" else None
        ),
        max_results=1,
        max_bytes=4_096,
        timeout_seconds=1,
    )
    with pytest.raises(ContextPreparationError, match="context_cross_application_denied"):
        coordinator.prepare(
            context,
            (unavailable_selection, selection(provider_id="synthetic.context")),
            ContextProviderInputs(scope=context.scope),
        )
    assert provider.calls == []
    assert unavailable.calls == []


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
    assert optional.failures[0].operation == "current"
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


def test_provider_failure_identifies_the_operation_that_failed():
    context = synthetic_context("synthetic.context")
    current = SyntheticContextProvider.spec.operation("current")
    assert current is not None
    history = ContextOperationSpec(
        operation="history",
        allowed_fields=("name", "availability"),
        maximum_results=2,
        maximum_bytes=8_192,
        maximum_timeout_seconds=2,
    )
    spec = SyntheticContextProvider.spec.model_copy(
        update={"operations": (current, history)}
    )

    class MultiOperationProvider(SyntheticContextProvider):
        def __init__(self):
            super().__init__()
            self.spec = spec

        def validate_selection(self, request, inputs):
            del inputs
            assert request.operation in {"current", "history"}

        def fetch(self, request, scope, *, deadline):
            if request.operation == "history":
                return ContextProviderResult(
                    failures=(
                        ContextProviderFailure(
                            provider_id=self.spec.provider_id,
                            operation="history",
                            reason="source_failed",
                        ),
                    )
                )
            return SyntheticContextProvider.fetch(self, request, scope, deadline=deadline)

    result = ContextProviderCoordinator(
        {"synthetic.context": StaticContextProviderFactory(MultiOperationProvider())}
    ).prepare(
        context,
        (selection(), selection(operation="history")),
        ContextProviderInputs(scope=context.scope),
    )
    assert len(result.items) == 1
    assert len(result.failures) == 1
    assert result.failures[0].provider_id == "synthetic.context"
    assert result.failures[0].operation == "history"
    assert result.failures[0].reason == "source_failed"


@pytest.mark.parametrize(
    "optional_issue,expected_reason",
    [
        ("expired", "expired"),
        ("permission", "permission_unverified"),
        ("budget", "source_budget"),
    ],
)
def test_required_operation_does_not_make_sibling_provider_operations_required(
    optional_issue, expected_reason
):
    context = synthetic_context("synthetic.context")
    current_spec = SyntheticContextProvider.spec.operation("current")
    assert current_spec is not None
    history_spec = ContextOperationSpec(
        operation="history",
        allowed_fields=("name",),
        maximum_results=2,
        maximum_bytes=8_192,
        maximum_timeout_seconds=2,
    )
    spec = SyntheticContextProvider.spec.model_copy(
        update={"operations": (current_spec, history_spec), "maximum_items_per_call": 2}
    )

    class MultiOperationProvider:
        def __init__(self):
            self.spec = spec

        def validate_selection(self, request, inputs):
            del inputs
            assert request.operation in {"current", "history"}

        def fetch(self, request, scope, *, deadline):
            del deadline
            if request.operation == "current":
                values = (("current-1", "required current value", NOW + timedelta(days=1)),)
            else:
                expiry = (
                    NOW - timedelta(days=1)
                    if optional_issue == "expired"
                    else NOW + timedelta(days=1)
                )
                name = (
                    "oversized " * 100 if optional_issue == "budget" else "optional history value"
                )
                values = (("history-1", name, expiry),)
            rows = []
            for item_id, name, expires_at in values:
                dependencies = (
                    (
                        ContextPermissionDependency(
                            permission_id="synthetic.optional_history",
                            version="v1",
                            purpose="read optional history",
                        ),
                    )
                    if optional_issue == "permission" and request.operation == "history"
                    else ()
                )
                rows.append(
                    ContextItem(
                        source_class="domain_current",
                        provider_id=self.spec.provider_id,
                        source_id=request.operation,
                        source_version="multi-operation-v1",
                        item_id=item_id,
                        owner_id=scope.owner_id,
                        application_id=scope.application_id,
                        workspace_id=scope.workspace_id,
                        authority="authoritative",
                        observed_at=NOW - timedelta(days=2) if expires_at < NOW else NOW,
                        expires_at=expires_at,
                        sensitivity="personal",
                        source_refs=(ContextSourceReference(kind="record", reference_id=item_id),),
                        permission_dependencies=dependencies,
                        payload=SyntheticDomainPayload(name=name),
                    )
                )
            return tuple(rows)

    settings = Settings(
        ai_provider="fake",
        ai_model="fake-model",
        context_domain_max_tokens=80,
    )
    result = ContextAssembler(
        settings,
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {"synthetic.context": StaticContextProviderFactory(MultiOperationProvider())}
        ),
    ).assemble(
        (),
        Message(
            id=uuid4(),
            conversation_id=uuid4(),
            owner_id=context.scope.owner_id,
            role=MessageRole.USER,
            content="Use the current value.",
            status=MessageStatus.COMPLETED,
            created_at=NOW,
            application_id="synthetic",
        ),
        refresh=False,
        application_context=context,
        context_selections=(
            ContextSelection(
                provider_id="synthetic.context",
                operation="current",
                fields=("name",),
                max_results=2,
                max_bytes=4_096,
                timeout_seconds=1,
                required=True,
            ),
            ContextSelection(
                provider_id="synthetic.context",
                operation="history",
                fields=("name",),
                max_results=1,
                max_bytes=4_096,
                timeout_seconds=1,
                required=False,
            ),
        ),
        clock=lambda: NOW,
    )

    reports = {item.item_id: item for item in result.manifest.items}
    assert reports["current-1"].injected
    assert reports["current-1"].selected_operation == "current"
    assert not reports["history-1"].injected
    assert reports["history-1"].selected_operation == "history"
    assert reports["history-1"].omission_reason == expected_reason


def test_multiple_items_from_a_required_provider_operation_remain_required():
    context = synthetic_context("synthetic.context")
    current_spec = SyntheticContextProvider.spec.operation("current")
    assert current_spec is not None
    spec = SyntheticContextProvider.spec.model_copy(
        update={"operations": (current_spec,), "maximum_items_per_call": 2}
    )

    class TwoCurrentItems:
        def __init__(self):
            self.spec = spec

        def validate_selection(self, request, inputs):
            del request, inputs

        def fetch(self, request, scope, *, deadline):
            del request, deadline
            return tuple(
                ContextItem(
                    source_class="domain_current",
                    provider_id=self.spec.provider_id,
                    source_id="current",
                    source_version="multi-operation-v1",
                    item_id=f"current-{index}",
                    owner_id=scope.owner_id,
                    application_id=scope.application_id,
                    workspace_id=scope.workspace_id,
                    authority="authoritative",
                    observed_at=NOW,
                    expires_at=NOW + timedelta(days=1),
                    sensitivity="personal",
                    source_refs=(ContextSourceReference(kind="record", reference_id=f"current-{index}"),),
                    payload=SyntheticDomainPayload(name=f"required current {index}"),
                )
                for index in (1, 2)
            )

    result = ContextAssembler(
        Settings(ai_provider="fake", ai_model="fake-model"),
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {"synthetic.context": StaticContextProviderFactory(TwoCurrentItems())}
        ),
    ).assemble(
        (),
        Message(
            id=uuid4(),
            conversation_id=uuid4(),
            owner_id=context.scope.owner_id,
            role=MessageRole.USER,
            content="Use the required values.",
            status=MessageStatus.COMPLETED,
            created_at=NOW,
            application_id="synthetic",
        ),
        refresh=False,
        application_context=context,
        context_selections=(
            ContextSelection(
                provider_id="synthetic.context",
                operation="current",
                fields=("name",),
                max_results=2,
                max_bytes=4_096,
                timeout_seconds=1,
                required=True,
            ),
        ),
        clock=lambda: NOW,
    )
    assert {item.item_id for item in result.manifest.items if item.injected} == {
        "current-1",
        "current-2",
    }


def test_optional_provider_failure_is_in_final_manifest_and_log(caplog):
    caplog.set_level("DEBUG", logger="personal_ai.context.assembler")
    context = synthetic_context("synthetic.context")
    provider = SyntheticContextProvider(fail="private provider text")
    result = ContextAssembler(
        Settings(ai_provider="fake", ai_model="fake-model"),
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {"synthetic.context": StaticContextProviderFactory(provider)}
        ),
    ).assemble(
        (),
        Message(
            id=uuid4(),
            conversation_id=uuid4(),
            owner_id=context.scope.owner_id,
            role=MessageRole.USER,
            content="Use available context.",
            status=MessageStatus.COMPLETED,
            created_at=NOW,
            application_id="synthetic",
        ),
        refresh=False,
        application_context=context,
        context_selections=(selection(required=False),),
    )

    assert result.manifest.source_failures[0].provider_id == "synthetic.context"
    assert result.manifest.source_failures[0].reason == "unavailable"
    assert "source_failures" in caplog.text
    assert "private provider text" not in caplog.text


def test_empty_required_source_stops_later_optional_sources():
    context = synthetic_context("synthetic.context", "synthetic.later")
    empty = SyntheticContextProvider()
    later_calls = []
    later = SyntheticContextProvider()
    later.spec = later.spec.model_copy(update={"provider_id": "synthetic.later"})
    empty.fetch = lambda request, scope, *, deadline: ()
    later.fetch = lambda request, scope, *, deadline: later_calls.append(True) or ()
    coordinator = ContextProviderCoordinator(
        {
            "synthetic.context": StaticContextProviderFactory(empty),
            "synthetic.later": StaticContextProviderFactory(later),
        }
    )
    with pytest.raises(ContextPreparationError, match="required_context_source_empty"):
        coordinator.prepare(
            context,
            (selection(required=True), selection(provider_id="synthetic.later")),
            ContextProviderInputs(scope=context.scope),
        )
    assert later_calls == []


def test_required_profile_with_no_shared_requested_fields_is_empty_failure():
    registry = default_application_registry()
    travel = registry.registration("travel")
    scope = RequestScope(owner_id="owner-empty-profile", request_id="request-1", application_id="travel")
    context = ApplicationContextRequest(
        definition=travel.definition,
        scope=scope,
        context_provider_capabilities=travel.context_providers,
        tool_capabilities=travel.tools,
    )
    repository = InMemoryGlobalProfileRepository(clock=lambda: NOW)
    repository.update(
        scope.owner_id,
        GlobalProfileUpdate(
            fields=(GlobalProfileFieldUpdate(field="locale", value="en-GB"),)
        ),
    )
    with pytest.raises(ContextPreparationError, match="required_context_source_empty"):
        ContextProviderCoordinator(
            {"global_profile": GlobalProfileContextProviderFactory(repository)}
        ).prepare(
            context,
            (
                ContextSelection(
                    provider_id="global_profile",
                    operation="profile",
                    fields=("locale", "preferred_units"),
                    max_results=1,
                    max_bytes=4_096,
                    timeout_seconds=1,
                    required=True,
                ),
            ),
            ContextProviderInputs(scope=scope, application_context=context),
        )


@pytest.mark.parametrize(
    "kind,exception,optional_reason,required_code",
    [
        ("factory", TimeoutError("private timeout"), "timeout", "required_context_source_timeout"),
        ("factory", ContextProviderError("context_provider_unavailable"), "unavailable", "required_context_source_unavailable"),
        ("factory", RuntimeError("private database message"), "source_failed", "required_context_source_failed"),
        ("validator", TimeoutError("private timeout"), "timeout", "required_context_source_timeout"),
        ("validator", ContextProviderError("context_provider_unavailable"), "unavailable", "required_context_source_unavailable"),
        ("validator", RuntimeError("private database message"), "source_failed", "required_context_source_failed"),
    ],
)
def test_optional_preflight_exceptions_are_mapped_to_safe_failures(
    kind, exception, optional_reason, required_code
):
    context = synthetic_context("synthetic.context")
    spec = SyntheticContextProvider.spec

    class RaisingFactory:
        def __init__(self):
            self.spec = spec

        def create(self, inputs):
            raise exception

    class RaisingValidator(SyntheticContextProvider):
        def validate_selection(self, request, inputs):
            raise exception

    provider = RaisingValidator()
    factory = (
        RaisingFactory()
        if kind == "factory"
        else StaticContextProviderFactory(provider)
    )
    coordinator = ContextProviderCoordinator({"synthetic.context": factory})
    optional = coordinator.prepare(
        context,
        (selection(required=False),),
        ContextProviderInputs(scope=context.scope),
    )
    assert optional.failures[0].reason == optional_reason
    assert "private" not in str(optional.failures[0])
    with pytest.raises(ContextPreparationError, match=required_code):
        coordinator.prepare(
            context,
            (selection(required=True),),
            ContextProviderInputs(scope=context.scope),
        )


def test_preflight_does_not_swallow_explicit_admission_denial():
    context = synthetic_context("synthetic.context")

    class DeniedProvider(SyntheticContextProvider):
        def validate_selection(self, request, inputs):
            raise ContextPreparationError("context_fields_not_allowed")

    provider = DeniedProvider()
    with pytest.raises(ContextPreparationError, match="context_fields_not_allowed"):
        ContextProviderCoordinator(
            {"synthetic.context": StaticContextProviderFactory(provider)}
        ).prepare(
            context,
            (selection(required=False),),
            ContextProviderInputs(scope=context.scope),
        )


def test_shared_deadline_is_checked_before_each_source(monkeypatch):
    import personal_ai.context.providers as providers_module

    context = synthetic_context("synthetic.context", "synthetic.later")
    first = SyntheticContextProvider()
    later_calls = []
    later = SyntheticContextProvider()
    later.spec = later.spec.model_copy(update={"provider_id": "synthetic.later"})
    first.fetch = lambda request, scope, *, deadline: ()
    later.fetch = lambda request, scope, *, deadline: later_calls.append(True) or ()
    readings = iter((0.0, 0.0, 0.3, 0.3, 0.4, 0.5))
    monkeypatch.setattr(providers_module, "monotonic", lambda: next(readings))
    coordinator = ContextProviderCoordinator(
        {
            "synthetic.context": StaticContextProviderFactory(first),
            "synthetic.later": StaticContextProviderFactory(later),
        }
    )
    with pytest.raises(ContextPreparationError, match="context_preparation_timeout"):
        coordinator.prepare(
            context,
            (selection(), selection(provider_id="synthetic.later")),
            ContextProviderInputs(scope=context.scope),
            deadline=0.5,
        )
    assert later_calls == []


def test_shared_deadline_exhausted_during_source_is_a_bounded_failure(monkeypatch):
    import personal_ai.context.providers as providers_module

    context = synthetic_context("synthetic.context", "synthetic.later")
    first = SyntheticContextProvider()
    later_calls = []
    later = SyntheticContextProvider()
    later.spec = later.spec.model_copy(update={"provider_id": "synthetic.later"})
    readings = iter((0.0, 0.0, 0.0, 0.0, 0.6))
    monkeypatch.setattr(providers_module, "monotonic", lambda: next(readings))

    def slow_fetch(request, scope, *, deadline):
        assert deadline == 0.5
        return ()

    first.fetch = slow_fetch
    later.fetch = lambda request, scope, *, deadline: later_calls.append(True) or ()
    coordinator = ContextProviderCoordinator(
        {
            "synthetic.context": StaticContextProviderFactory(first),
            "synthetic.later": StaticContextProviderFactory(later),
        }
    )
    with pytest.raises(ContextPreparationError, match="context_preparation_timeout"):
        coordinator.prepare(
            context,
            (selection(), selection(provider_id="synthetic.later")),
            ContextProviderInputs(scope=context.scope),
            deadline=0.5,
        )
    assert later_calls == []


def test_provider_timeout_is_cooperative_and_overrun_detection_happens_after_return(
    monkeypatch,
):
    import personal_ai.context.providers as providers_module

    context = synthetic_context("synthetic.context")
    cooperative = SyntheticContextProvider()
    propagated = []

    def dependency_call(*, deadline):
        propagated.append(deadline)
        raise TimeoutError("dependency deadline reached")

    cooperative.fetch = lambda request, scope, *, deadline: dependency_call(deadline=deadline)
    result = ContextProviderCoordinator(
        {"synthetic.context": StaticContextProviderFactory(cooperative)}
    ).prepare(
        context,
        (selection(timeout_seconds=0.1),),
        ContextProviderInputs(scope=context.scope),
    )
    assert len(propagated) == 1
    assert result.failures[0].reason == "timeout"

    non_cooperative = SyntheticContextProvider()
    # The provider ignores its deadline and returns only after the source limit.
    # The synchronous coordinator reports the overrun after return; it cannot
    # interrupt that provider while it is running.
    readings = iter((0.0, 0.2))
    monkeypatch.setattr(providers_module, "monotonic", lambda: next(readings))
    non_cooperative.fetch = lambda request, scope, *, deadline: ()
    overrun = ContextProviderCoordinator(
        {"synthetic.context": StaticContextProviderFactory(non_cooperative)}
    ).prepare(
        context,
        (selection(timeout_seconds=0.1),),
        ContextProviderInputs(scope=context.scope),
    )
    assert overrun.failures[0].reason == "timeout"


def test_assembler_passes_overall_deadline_to_source_and_profile_caps_sql_deadline():
    context = synthetic_context("synthetic.context")
    provider = SyntheticContextProvider()
    received = []
    provider.fetch = lambda request, scope, *, deadline: received.append(deadline) or ()
    overall_deadline = monotonic() + 1
    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id=context.scope.owner_id,
        role=MessageRole.USER,
        content="request",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
        application_id=context.scope.application_id,
    )
    ContextAssembler(
        Settings(ai_provider="fake", ai_model="fake"),
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {"synthetic.context": StaticContextProviderFactory(provider)}
        ),
    ).assemble(
        (),
        pending,
        refresh=False,
        deadline=overall_deadline,
        application_context=context,
        context_selections=(selection(timeout_seconds=2),),
    )
    assert len(received) == 1
    assert received[0] <= overall_deadline
    assert received[0] > overall_deadline - 0.1

    class RecordingProfileRepository:
        def __init__(self):
            self.deadline = None

        def shared_fields(self, owner_id, application_id, fields, *, deadline=None):
            self.deadline = deadline
            return ()

    registry = default_application_registry()
    travel = registry.registration("travel")
    profile_scope = RequestScope(
        owner_id="owner-profile-deadline",
        request_id="profile-deadline",
        application_id="travel",
    )
    profile_context = ApplicationContextRequest(
        definition=travel.definition,
        scope=profile_scope,
        context_provider_capabilities=travel.context_providers,
        tool_capabilities=travel.tools,
    )
    repository = RecordingProfileRepository()
    cap = monotonic() + 0.1
    # Use the request-bound provider through its registered factory protocol.
    from personal_ai.context.profile import GlobalProfileContextProviderFactory

    result = ContextProviderCoordinator(
        {"global_profile": GlobalProfileContextProviderFactory(repository)}
    ).prepare(
        profile_context,
        (
            ContextSelection(
                provider_id="global_profile",
                operation="profile",
                fields=("locale",),
                max_results=1,
                max_bytes=4_096,
                timeout_seconds=0.2,
            ),
        ),
        ContextProviderInputs(scope=profile_scope, application_context=profile_context),
        deadline=cap,
    )
    assert result.failures[0].reason == "empty"
    assert repository.deadline is not None
    assert repository.deadline <= cap
    assert repository.deadline > cap - 0.05


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


@pytest.mark.parametrize("max_results,expected", [(1, ("locale",)), (2, ("locale", "preferred_units")), (4, ("locale", "preferred_units"))])
def test_profile_projection_honors_result_limit_and_requested_order(max_results, expected):
    registry = default_application_registry()
    travel = registry.registration("travel")
    scope = RequestScope(owner_id="owner-profile", request_id="request-profile", application_id="travel")
    context = ApplicationContextRequest(
        definition=travel.definition,
        scope=scope,
        context_provider_capabilities=travel.context_providers,
        tool_capabilities=travel.tools,
    )
    repository = InMemoryGlobalProfileRepository(clock=lambda: NOW)
    repository.update(
        scope.owner_id,
        GlobalProfileUpdate(
            fields=(
                GlobalProfileFieldUpdate(
                    field="preferred_units", value="metric", shared_with_applications=("travel",)
                ),
                GlobalProfileFieldUpdate(
                    field="locale", value="en-GB", shared_with_applications=("travel",)
                ),
            )
        ),
    )
    coordinator = ContextProviderCoordinator(
        {"global_profile": GlobalProfileContextProviderFactory(repository)}
    )
    result = coordinator.prepare(
        context,
        (
            ContextSelection(
                provider_id="global_profile",
                operation="profile",
                fields=("locale", "preferred_units"),
                max_results=max_results,
                max_bytes=4_096,
                timeout_seconds=1,
            ),
        ),
        ContextProviderInputs(scope=scope, application_context=context),
    )
    assert tuple(item.item_id for item in result.items) == expected


def test_client_context_projection_honors_result_limit_in_requested_order():
    scope = RequestScope(
        owner_id="owner-1",
        request_id="request-1",
        application_id="synthetic",
        client_context={"display_mode": "compact", "layout": "wide"},
    )
    context = synthetic_context(scope=scope)
    registration = default_application_registry().registration("personal_ai")
    context = context.model_copy(
        update={"context_provider_capabilities": registration.context_providers}
    )
    result = ContextProviderCoordinator(
        {"client_context": ClientContextProviderFactory()}
    ).prepare(
        context,
        (
            ContextSelection(
                provider_id="client_context",
                operation="profile",
                fields=("layout", "display_mode"),
                max_results=1,
                max_bytes=4_096,
                timeout_seconds=0.1,
            ),
        ),
        ContextProviderInputs(scope=scope, application_context=context),
    )
    assert len(result.items) == 1
    assert result.items[0].payload.key == "layout"


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
    messages, _ = _conversation_history(2)
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
                max_results=2,
                max_bytes=4_096,
                timeout_seconds=1,
            ),
        ),
        ContextProviderInputs(scope=scope, application_context=context, active_messages=messages),
    )
    assert result.items[0].payload.role == "user"
    assert result.items[0].payload.id == str(messages[0].id)
    assert result.items[0].payload.content is None


def test_failed_assistant_content_cannot_be_reinjected_by_conversation_provider():
    registry = default_application_registry()
    application = registry.registration("personal_ai")
    scope = RequestScope(owner_id="local", request_id="request-failed-turn", application_id="personal_ai")
    context = ApplicationContextRequest(
        definition=application.definition,
        scope=scope,
        context_provider_capabilities=application.context_providers,
        tool_capabilities=application.tools,
    )
    conversation_id = uuid4()
    prior_user = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        owner_id="local",
        role=MessageRole.USER,
        content="Please keep this private.",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
        application_id="personal_ai",
    )
    failed_assistant = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        owner_id="local",
        role=MessageRole.ASSISTANT,
        content="failed partial secret must never reach the model",
        status=MessageStatus.FAILED,
        parent_message_id=prior_user.id,
        created_at=NOW + timedelta(seconds=1),
        application_id="personal_ai",
    )
    pending = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        owner_id="local",
        role=MessageRole.USER,
        content="Continue with a new request.",
        status=MessageStatus.COMPLETED,
        created_at=NOW + timedelta(seconds=2),
        application_id="personal_ai",
    )
    assembler = ContextAssembler(
        Settings(ai_provider="fake", ai_model="fake-model"),
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {"conversation_history": ConversationContextProviderFactory()}
        ),
    )
    assembled = assembler.assemble(
        (prior_user, failed_assistant),
        pending,
        refresh=False,
        application_context=context,
        context_selections=(
            ContextSelection(
                provider_id="conversation_history",
                operation="history",
                fields=("id", "role", "content"),
                max_results=3,
                max_bytes=16_384,
                timeout_seconds=1,
            ),
        ),
    )

    assert all(
        "failed partial secret" not in message.content for message in assembled.messages
    )
    assert not assembled.source_items
    assert (str(failed_assistant.id), "incomplete_turn") in assembled.manifest.excluded_messages


@pytest.mark.parametrize("history_count", [2, 3, 4])
def test_conversation_wrapper_bounds_history_without_summary(history_count):
    active, _ = _conversation_history(history_count)
    scope = RequestScope(owner_id="local", request_id="request-history", application_id="personal_ai")
    records = ConversationContextProvider(
        ContextProviderInputs(scope=scope, active_messages=active)
    ).fetch(
        ContextSelection(
            provider_id="conversation_history",
            operation="history",
            fields=("id", "content"),
            max_results=3,
            max_bytes=16_384,
            timeout_seconds=1,
        ),
        scope,
        deadline=monotonic() + 1,
    )
    assert len(records) == 2
    assert all(item.payload.kind == "message" for item in records)


@pytest.mark.parametrize("message_count", [32, 36, 200, 202])
def test_conversation_summary_keeps_exact_bounded_provenance_and_recent_history(message_count):
    active, summary = _conversation_history(message_count)
    scope = RequestScope(owner_id="local", request_id="request-summary", application_id="personal_ai")
    result = ConversationContextProvider(
        ContextProviderInputs(scope=scope, active_messages=active, summary=summary)
    ).fetch(
        ContextSelection(
            provider_id="conversation_history",
            operation="history",
            fields=("content", "source_message_ids"),
            max_results=50,
            max_bytes=65_536,
            timeout_seconds=1,
        ),
        scope,
        deadline=monotonic() + 1,
    )
    items = result.items if hasattr(result, "items") else result
    summaries = [item for item in items if item.payload.kind == "summary"]
    messages = [item for item in items if item.payload.kind == "message"]
    if message_count <= 200:
        assert len(summaries) == 1
        assert len(summaries[0].source_refs) == message_count
        assert tuple(ref.reference_id for ref in summaries[0].source_refs) == tuple(
            str(message.id) for message in active
        )
        assert 2 <= len(items) <= min(message_count + 1, 50)
        assert 1 <= len(messages) <= min(message_count, 49)
        assert sum(len(item.model_dump_json().encode("utf-8")) for item in items) <= 65_536
    else:
        assert summaries == []
        assert len(messages) == 50
        assert result.failures[0].reason == "summary_provenance_limit"
    if message_count == 36:
        assert summaries[0].payload.source_message_ids == tuple(
            str(message.id) for message in active
        )


def test_summary_projection_failure_preserves_messages_and_reports_bounded_reason():
    active, summary = _conversation_history(12, summary_content="x" * 12_000)
    scope = RequestScope(owner_id="local", request_id="request-summary", application_id="personal_ai")
    result = ConversationContextProvider(
        ContextProviderInputs(scope=scope, active_messages=active, summary=summary)
    ).fetch(
        ContextSelection(
            provider_id="conversation_history",
            operation="history",
            fields=("content", "source_message_ids"),
            max_results=10,
            max_bytes=4_096,
            timeout_seconds=1,
        ),
        scope,
        deadline=monotonic() + 1,
    )
    assert result.failures[0].reason == "summary_response_limit"
    assert len(result.items) <= 10
    assert len(result.items) % 2 == 0
    assert all(item.payload.kind == "message" for item in result.items)


def test_summary_projection_omission_and_incompatible_branch_keep_history():
    active, summary = _conversation_history(36)
    scope = RequestScope(owner_id="local", request_id="request-summary", application_id="personal_ai")
    omitted = ConversationContextProvider(
        ContextProviderInputs(scope=scope, active_messages=active, summary=summary)
    ).fetch(
        ContextSelection(
            provider_id="conversation_history",
            operation="history",
            fields=("content",),
            max_results=50,
            max_bytes=65_536,
            timeout_seconds=1,
        ),
        scope,
        deadline=monotonic() + 1,
    )
    summary_item = next(item for item in omitted if item.payload.kind == "summary")
    assert summary_item.payload.source_message_ids == ()
    assert len(summary_item.source_refs) == 36
    incompatible = summary.model_copy(update={"conversation_id": uuid4()})
    branch_result = ConversationContextProvider(
        ContextProviderInputs(scope=scope, active_messages=active, summary=incompatible)
    ).fetch(
        ContextSelection(
            provider_id="conversation_history",
            operation="history",
            fields=("content",),
            max_results=50,
            max_bytes=65_536,
            timeout_seconds=1,
        ),
        scope,
        deadline=monotonic() + 1,
    )
    assert len(branch_result) == 36
    assert all(item.payload.kind == "message" for item in branch_result)


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
        {"ai_memory": MemoryContextProviderFactory(Settings(ai_provider="fake", ai_model="fake"))},
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
    assert item.authority == "user_asserted"
    assert item.source_refs[0].reference_id == str(source_message_id)
    assert item.payload.content == "I prefer metric units."
    assert "embedding" not in item.payload.model_dump()


def test_planned_memory_preserves_authority_and_derived_suppression_with_fallback():
    registry = default_application_registry()
    application = registry.registration("personal_ai")
    scope = RequestScope(
        owner_id="local", request_id="request-planned-memory", application_id="personal_ai"
    )
    context = ApplicationContextRequest(
        definition=application.definition,
        scope=scope,
        context_provider_capabilities=application.context_providers,
        tool_capabilities=application.tools,
    )
    derived = _derived_memory_record(scope)
    backups = tuple(
        _memory_record(scope, content=source.excerpt).model_copy(
            update={
                "id": source.memory_id,
                "source_fingerprint": source.source_fingerprint,
                "source_conversation_id": source.source_conversation_id,
                "source_turn_id": source.source_turn_id,
                "source_message_ids": source.source_message_ids,
            }
        )
        for source in derived.sources
    )
    unrelated = _memory_record(scope, content="I like quiet hotels.")
    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id=scope.owner_id,
        role=MessageRole.USER,
        content="What do you remember about me?",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
        application_id=scope.application_id,
    )
    settings = Settings(
        ai_provider="fake", ai_model="fake-model", memory_enabled=True,
        memory_retrieval_limit=4,
    )
    coordinator = ContextProviderCoordinator(
        {"ai_memory": MemoryContextProviderFactory(settings)},
        feature_flags={"memory_enabled": True},
    )
    retrieval = RetrievalResult(
        selected=tuple(
            ScoredMemory(memory, 0.9 - index * 0.01)
            for index, memory in enumerate((*backups, derived, unrelated))
        )
    )

    def build(memory_budget):
        assembler = ContextAssembler(
        settings.model_copy(update={"memory_max_context_tokens": memory_budget}),
        FakeTokenCounter(),
        context_provider_coordinator=coordinator,
        permission_revalidator=BuiltInContextPermissionRevalidator(settings),
        context_planner=ContextPlanner(max_total_tokens=memory_budget),
        )
        plan = assembler.plan_context(pending.content, context, now=NOW)
        return assembler.assemble(
            (), pending, refresh=False, retrieval=retrieval,
            application_context=context, context_plan=plan,
        )

    fitting = build(512)
    derived_item = next(item for item in fitting.source_items if item.item_id == str(derived.id))
    original_items = {
        item.item_id: item for item in fitting.source_items if item.item_id != str(derived.id)
    }
    assert derived_item.authority == "derived"
    assert set(derived_item.represented_item_ids) == {str(item.id) for item in backups}
    assert all(item.authority == "user_asserted" for item in original_items.values())
    assert fitting.selected_memory_ids == (derived.id, unrelated.id)
    assert all(
        (item.id, "represented_by_derived_memory") in fitting.excluded_memories
        for item in backups
    )
    rendered = " ".join(message.content for message in fitting.messages)
    assert '"authority":"derived"' in rendered
    assert '"authority":"user_asserted"' in rendered
    reports = {item.item_id: item for item in fitting.manifest.items}
    assert reports[str(derived.id)].authority == "derived"
    assert reports[str(backups[0].id)].authority == "user_asserted"

    long_excerpt = "I like tea " + "quiet hotels are peaceful " * 17
    long_sources = tuple(
        source.model_copy(update={"excerpt": long_excerpt}) for source in derived.sources
    )
    oversized_content = (
        "Historical personal context from repeated user statements:\n"
        + "\n".join(source.excerpt for source in long_sources)
    )
    oversized_derived = derived.model_copy(
        update={
            "sources": long_sources,
            "content": oversized_content,
            "normalized_content": normalize(oversized_content),
        }
    )
    oversized_derived = DerivedMemory.model_validate(oversized_derived.model_dump())
    fallback_backups = tuple(
        Memory.model_validate(
            _memory_record(scope, content=long_excerpt)
            .model_copy(
                update={
                    "id": source.memory_id,
                    "source_fingerprint": source.source_fingerprint,
                    "source_conversation_id": source.source_conversation_id,
                    "source_turn_id": source.source_turn_id,
                    "source_message_ids": source.source_message_ids,
                }
            )
            .model_dump()
        )
        for source in long_sources
    )
    fallback_retrieval = RetrievalResult(
        selected=tuple(
            ScoredMemory(memory, 0.9 - index * 0.01)
            for index, memory in enumerate((*fallback_backups, oversized_derived, unrelated))
        )
    )
    fallback_assembler = ContextAssembler(
        settings.model_copy(update={"memory_max_context_tokens": 200}),
        FakeTokenCounter(),
        context_provider_coordinator=coordinator,
        permission_revalidator=BuiltInContextPermissionRevalidator(settings),
        context_planner=ContextPlanner(max_total_tokens=512),
    )
    fallback_plan = fallback_assembler.plan_context(pending.content, context, now=NOW)
    fallback = fallback_assembler.assemble(
        (), pending, refresh=False, retrieval=fallback_retrieval,
        application_context=context, context_plan=fallback_plan,
    )
    assert oversized_derived.id not in fallback.selected_memory_ids
    assert any(item.id in fallback.selected_memory_ids for item in fallback_backups)
    assert unrelated.id in fallback.selected_memory_ids
    assert any(
        memory_id == oversized_derived.id and reason == "budget"
        for memory_id, reason in fallback.excluded_memories
    )


def test_memory_limit_applies_after_derived_fit_and_backup_fallback():
    scope = RequestScope(owner_id="local", request_id="request-memory-fit", application_id="personal_ai")
    first_backup = _memory_record(scope, content="A small original memory backup.").model_copy(
        update={"id": UUID(int=21)}
    )
    second_backup = _memory_record(scope, content="Another small original backup.").model_copy(
        update={"id": UUID(int=22)}
    )
    derived = _derived_memory_record(scope)
    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id=scope.owner_id,
        role=MessageRole.USER,
        content="Use relevant history.",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
        application_id=scope.application_id,
    )
    scores = tuple(
        ScoredMemory(memory=memory, similarity=0.9 - index * 0.1)
        for index, memory in enumerate((derived, first_backup, second_backup))
    )

    fitting_settings = Settings(
        ai_provider="fake",
        ai_model="fake-model",
        memory_enabled=True,
        memory_retrieval_limit=1,
    )
    fitting = ContextAssembler(fitting_settings, FakeTokenCounter()).assemble(
        (), pending, refresh=False, retrieval=RetrievalResult(selected=scores)
    )
    assert fitting.selected_memory_ids == (derived.id,)
    assert (first_backup.id, "represented_by_derived_memory") in fitting.excluded_memories
    assert (second_backup.id, "represented_by_derived_memory") in fitting.excluded_memories

    oversized = derived.model_copy(
        update={"content": "oversized " * 80, "normalized_content": normalize("oversized " * 80)}
    )
    fallback_scores = tuple(
        ScoredMemory(memory=memory, similarity=0.9 - index * 0.1)
        for index, memory in enumerate((oversized, first_backup, second_backup))
    )
    fallback_settings = fitting_settings.model_copy(
        update={"memory_max_context_tokens": 80}
    )
    fallback = ContextAssembler(fallback_settings, FakeTokenCounter()).assemble(
        (), pending, refresh=False, retrieval=RetrievalResult(selected=fallback_scores)
    )
    assert fallback.selected_memory_ids == (first_backup.id,)
    assert (oversized.id, "budget") in fallback.excluded_memories
    assert (second_backup.id, "retrieval_limit") in fallback.excluded_memories


def test_optional_memory_count_forwards_its_short_deadline_through_assembler():
    class TimeoutSpy:
        def __init__(self):
            self.memory_timeouts = []

        def count_with_timeout(self, messages, timeout_seconds):
            if len(messages) == 1 and any(
                "Historical personal memory" in message.content
                and "MEMORY_MARKER" in message.content
                for message in messages
            ):
                self.memory_timeouts.append(timeout_seconds)
            return FakeTokenCounter().count(messages)

    scope = RequestScope(owner_id="local", request_id="request-memory-timeout", application_id="personal_ai")
    memory = _memory_record(scope, content="MEMORY_MARKER: optional user preference")
    settings = Settings(
        ai_provider="fake",
        ai_model="fake-model",
        memory_enabled=True,
        memory_timeout_seconds=0.2,
    )
    counter = TimeoutSpy()
    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id=scope.owner_id,
        role=MessageRole.USER,
        content="Use relevant history.",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
        application_id=scope.application_id,
    )
    ContextAssembler(settings, counter).assemble(
        (),
        pending,
        refresh=False,
        deadline=monotonic() + 60,
        retrieval=RetrievalResult(
            selected=(ScoredMemory(memory=memory, similarity=0.9),)
        ),
    )
    assert counter.memory_timeouts
    assert all(0 < timeout <= 0.2 for timeout in counter.memory_timeouts)


def test_inspector_logs_manifest_as_an_estimated_view(caplog):
    caplog.set_level("DEBUG", logger="personal_ai.context.assembler")
    active, _ = _conversation_history(2)
    report = ContextInspector(
        Settings(ai_provider="fake", ai_model="fake-model"),
        InMemorySummaryRepository(),
    ).inspect(active)

    assert report["manifest"]["actual_build"] is False
    assert report["manifest"]["view_kind"] == "estimated_current_view"
    assert "'view_kind': 'estimated_current_view'" in caplog.text
    assert "'actual_build': True" not in caplog.text


def test_summary_manifest_log_keeps_summary_identity_after_preparation(caplog):
    from personal_ai.context.contracts import fingerprint

    caplog.set_level("DEBUG", logger="personal_ai.context.assembler")
    active, summary = _conversation_history(4)
    active = tuple(
        message.model_copy(update={"content": f"historical detail {index} " * 80})
        for index, message in enumerate(active)
    )
    summary = summary.model_copy(
        update={
            "source_message_ids": tuple(message.id for message in active),
            "source_fingerprint": fingerprint(active),
            "coverage_message_ids": tuple(message.id for message in active),
            "coverage_fingerprint": fingerprint(active, include_state=True),
            "covers_through_message_id": active[-1].id,
        }
    )
    summaries = InMemorySummaryRepository()
    summaries.create(summary)
    pending = Message(
        id=uuid4(),
        conversation_id=active[0].conversation_id,
        owner_id="local",
        role=MessageRole.USER,
        content="Current task",
        status=MessageStatus.COMPLETED,
        created_at=NOW + timedelta(seconds=10),
        application_id="personal_ai",
    )
    settings = Settings(
        ai_provider="fake",
        ai_model="fake-model",
        max_context_tokens=400,
        max_response_tokens=64,
        context_safety_margin_tokens=32,
        max_summary_tokens=50,
        summary_trigger_tokens=1,
    )
    assembled = ContextAssembler(settings, FakeTokenCounter(), summaries).assemble(
        active, pending, refresh=False
    )

    assert assembled.summary is not None
    assert assembled.manifest.summary_id == str(summary.id)
    assert f"'summary_id': '{summary.id}'" in caplog.text


def test_memory_context_uses_assembler_eligibility_and_does_not_restore_excluded_records():
    registry = default_application_registry()
    application = registry.registration("personal_ai")
    scope = RequestScope(owner_id="local", request_id="request-memory", application_id="personal_ai")
    context = ApplicationContextRequest(
        definition=application.definition,
        scope=scope,
        context_provider_capabilities=application.context_providers,
        tool_capabilities=application.tools,
    )
    ordinary = _memory_record(scope)
    derived = _derived_memory_record(scope)
    rejected = _memory_record(scope, content="I prefer imperial units.", status="rejected")
    denied_builtin = _memory_record(scope, content="My password is hunter2.")
    denied_custom = _memory_record(scope, content="I prefer projectx for every task.")
    lifecycle_excluded = _memory_record(scope)
    retrieval = RetrievalResult(
        selected=tuple(
            ScoredMemory(memory, 0.9)
            for memory in (rejected, denied_builtin, denied_custom, ordinary, derived)
        ),
        excluded=((lifecycle_excluded.id, "superseded"),),
    )
    settings = Settings(
        ai_provider="fake",
        ai_model="fake",
        memory_enabled=True,
        memory_sensitive_terms=("projectx",),
    )
    coordinator = ContextProviderCoordinator(
        {"ai_memory": MemoryContextProviderFactory(settings)},
        feature_flags={"memory_enabled": True},
    )
    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id=scope.owner_id,
        role=MessageRole.USER,
        content="What preferences do I have?",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
        application_id=scope.application_id,
    )
    assembled = ContextAssembler(
        settings,
        FakeTokenCounter(),
        context_provider_coordinator=coordinator,
    ).assemble(
        (),
        pending,
        refresh=False,
        retrieval=retrieval,
        application_context=context,
        context_selections=(
            ContextSelection(
                provider_id="ai_memory",
                operation="search",
                fields=("content", "memory_type"),
                max_results=20,
                max_bytes=65_536,
                timeout_seconds=1,
            ),
        ),
    )
    projected_content = {item.payload.content for item in assembled.source_items}
    assert projected_content == {ordinary.content, derived.content}
    assert rejected.content not in projected_content
    assert denied_builtin.content not in projected_content
    assert denied_custom.content not in projected_content
    assert all(item.item_id != str(lifecycle_excluded.id) for item in assembled.source_items)


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


@pytest.mark.parametrize(
    "override",
    [
        {"owner_id": "foreign-owner", "canonical_url": "https://foreign.example/owner"},
        {"application_id": "travel", "canonical_url": "https://foreign.example/app"},
        {"workspace_id": "foreign-workspace", "canonical_url": "https://foreign.example/workspace"},
        {"session_id": uuid4(), "canonical_url": "https://foreign.example/session"},
        {"status": "stale", "canonical_url": "https://foreign.example/stale"},
    ],
)
def test_research_wrapper_rejects_foreign_or_unaccepted_observations(override):
    registry = default_application_registry()
    application = registry.registration("personal_ai")
    scope = RequestScope(owner_id="local", request_id="request-research", application_id="personal_ai")
    context = ApplicationContextRequest(
        definition=application.definition,
        scope=scope,
        context_provider_capabilities=application.context_providers,
        tool_capabilities=application.tools,
    )
    evidence, observations = _research_case(scope, observation_overrides=(override,))
    result = ContextProviderCoordinator(
        {"external_research": ResearchEvidenceContextProviderFactory()}
    ).prepare(
        context,
        (
            ContextSelection(
                provider_id="external_research",
                operation="search",
                fields=("passage",),
                max_results=1,
                max_bytes=8_192,
                timeout_seconds=1,
            ),
        ),
        ContextProviderInputs(
            scope=scope,
            application_context=context,
            evidence_records=((evidence, observations),),
        ),
    )
    assert result.items == ()
    assert "foreign.example" not in str(result)


@pytest.mark.parametrize("malformation", ["missing", "duplicate_observation", "duplicate_reference"])
def test_research_wrapper_rejects_incomplete_or_ambiguous_observation_ids(malformation):
    registry = default_application_registry()
    application = registry.registration("personal_ai")
    scope = RequestScope(owner_id="local", request_id="request-research", application_id="personal_ai")
    context = ApplicationContextRequest(
        definition=application.definition,
        scope=scope,
        context_provider_capabilities=application.context_providers,
        tool_capabilities=application.tools,
    )
    evidence, observations = _research_case(
        scope,
        observation_overrides=({}, {}) if malformation == "duplicate_reference" else ({},),
    )
    if malformation == "missing":
        evidence = evidence.model_copy(update={"source_observation_ids": (uuid4(),)})
    elif malformation == "duplicate_observation":
        observations = (observations[0], observations[0])
    else:
        evidence = evidence.model_copy(
            update={"source_observation_ids": (observations[0].id, observations[0].id)}
        )
        observations = (observations[0],)
    result = ContextProviderCoordinator(
        {"external_research": ResearchEvidenceContextProviderFactory()}
    ).prepare(
        context,
        (
            ContextSelection(
                provider_id="external_research",
                operation="search",
                fields=("passage",),
                max_results=1,
                max_bytes=8_192,
                timeout_seconds=1,
            ),
        ),
        ContextProviderInputs(
            scope=scope,
            application_context=context,
            evidence_records=((evidence, observations),),
        ),
    )
    assert result.items == ()


def test_research_wrapper_preserves_valid_multi_source_attribution_in_order():
    registry = default_application_registry()
    application = registry.registration("personal_ai")
    scope = RequestScope(owner_id="local", request_id="request-research", application_id="personal_ai")
    context = ApplicationContextRequest(
        definition=application.definition,
        scope=scope,
        context_provider_capabilities=application.context_providers,
        tool_capabilities=application.tools,
    )
    evidence, observations = _research_case(scope, observation_overrides=({}, {}))
    result = ContextProviderCoordinator(
        {"external_research": ResearchEvidenceContextProviderFactory()}
    ).prepare(
        context,
        (
            ContextSelection(
                provider_id="external_research",
                operation="search",
                fields=("passage", "expires_at"),
                max_results=1,
                max_bytes=8_192,
                timeout_seconds=1,
            ),
        ),
        ContextProviderInputs(
            scope=scope,
            application_context=context,
            evidence_records=((evidence, observations),),
        ),
    )
    item = result.items[0]
    assert tuple(ref.reference_id for ref in item.source_refs) == tuple(
        str(observation.id) for observation in observations
    )
    assert tuple(ref.uri for ref in item.source_refs) == tuple(
        observation.canonical_url for observation in observations
    )
    assert tuple(ref.fingerprint for ref in item.source_refs) == tuple(
        observation.content_fingerprint for observation in observations
    )
    assert item.expires_at == evidence.expires_at


def test_tool_results_require_registered_bounded_read_only_capability_and_typed_projection():
    tool = CapabilityRegistration(
        capability_id="synthetic.lookup",
        kind="tool",
        available=True,
        read_only_context=True,
        result_fields=("name", "availability"),
        max_result_bytes=4_096,
    )
    context = synthetic_context(tools=(tool,))
    provider = ToolResultProviderFactory(
        tool,
        lambda payload, fields: SyntheticDomainPayload(
            name=payload.name if "name" in fields else None,
            availability=payload.availability if "availability" in fields else None,
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
    assert result.items[0].payload.result.availability is None

    both = coordinator.prepare(
        context,
        (
            ContextSelection(
                provider_id="synthetic.lookup",
                operation="current",
                fields=("name", "availability"),
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
    assert both.items[0].payload.result.name == "Fixture stay"
    assert both.items[0].payload.result.availability == "available"

    overprojecting = ToolResultProviderFactory(
        tool,
        lambda payload, fields: SyntheticDomainPayload(
            name=payload.name if "name" in fields else None,
            availability=payload.availability,
        ),
    )
    rejected = ContextProviderCoordinator({"synthetic.lookup": overprojecting}).prepare(
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
    assert rejected.items == ()
    assert rejected.failures[0].reason == "unavailable"
    assert rejected.failures[0].operation == "current"

    class DirectToolPayload(BaseModel):
        result: SyntheticDomainPayload

    class ForgedToolProvider:
        spec = ContextProviderSpec(
            provider_id="synthetic.lookup",
            source_class="tool_result",
            source_version="test-v1",
            capability_kind="tool",
            operations=(
                ContextOperationSpec(
                    operation="current",
                    allowed_fields=("name", "availability"),
                    maximum_results=1,
                    maximum_bytes=4_096,
                    maximum_timeout_seconds=0.2,
                ),
            ),
            maximum_items_per_call=1,
        )

        def validate_selection(self, request, inputs):
            del request, inputs

        def fetch(self, request, scope, *, deadline):
            del request, deadline
            return (
                ContextItem(
                    source_class="tool_result",
                    provider_id=self.spec.provider_id,
                    source_id="call-2",
                    source_version="test-v1",
                    item_id="call-2",
                    owner_id=scope.owner_id,
                    application_id=scope.application_id,
                    workspace_id=scope.workspace_id,
                    authority="derived",
                    source_refs=(
                        ContextSourceReference(kind="tool_invocation", reference_id="call-2"),
                    ),
                    payload=DirectToolPayload(
                        result=SyntheticDomainPayload(
                            name="Selected stay", availability="unrequested secret"
                        )
                    ),
                ),
            )

    with pytest.raises(
        ContextPreparationError,
        match="context_provider_tool_projection_violation",
    ):
        ContextProviderCoordinator(
            {"synthetic.lookup": StaticContextProviderFactory(ForgedToolProvider())}
        ).prepare(
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
            ContextProviderInputs(scope=context.scope),
        )

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
