"""Phase 15 server-owned policy preflight and sensitivity contract fixtures."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import BaseModel

from personal_ai.applications.contracts import (
    ApplicationContextPolicy,
    ApplicationContextRequest,
    ApplicationDefinition,
    CapabilityRegistration,
    ContextFieldPolicy,
    ContextOperationPolicy,
    ContextProviderPolicy,
)
from personal_ai.applications.registry import default_application_registry
from personal_ai.auth.scope import ApplicationScope, RequestScope
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.authorization import authorize_context_selections
from personal_ai.context.providers import (
    ContextItem,
    ContextOperationSpec,
    ContextPermissionDependency,
    ContextPreparationError,
    ContextProviderCoordinator,
    ContextProviderInputs,
    ContextProviderSpec,
    ContextSelection,
    ContextSourceReference,
    StaticContextProviderFactory,
)
from personal_ai.context.repositories import InMemorySummaryRepository
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import Conversation, Message, MessageRole, MessageStatus
from personal_ai.llm import GeminiLLMClient
from personal_ai.llm.fake import FakeLLMClient
from personal_ai.services.chat_turns import ChatTurnService
from personal_ai.settings import Settings
from personal_ai.storage.fake import InMemoryConversationRepository, InMemoryMessageRepository


class Payload(BaseModel):
    value: str


class OverbroadPayload(BaseModel):
    value: str
    diagnosis: str


class Source:
    spec = ContextProviderSpec(
        provider_id="synthetic.health",
        source_class="domain_current",
        source_version="synthetic-health-v1",
        operations=(ContextOperationSpec(operation="current", allowed_fields=("value",)),),
    )

    def __init__(self, sensitivity="personal"):
        self.sensitivity = sensitivity
        self.calls = 0

    def validate_selection(self, selection, inputs):
        return None

    def fetch(self, selection, scope, *, deadline):
        del selection, deadline
        self.calls += 1
        return (
            ContextItem(
                source_class="domain_current",
                provider_id=self.spec.provider_id,
                source_id="fixture-record",
                source_version="fixture-v1",
                item_id="item-1",
                owner_id=scope.owner_id,
                application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                authority="authoritative",
                observed_at=datetime(2026, 10, 7, tzinfo=UTC),
                sensitivity=self.sensitivity,
                source_refs=(ContextSourceReference(kind="record", reference_id="item-1"),),
                payload=Payload(value="synthetic"),
            ),
        )


class OverbroadSource(Source):
    def fetch(self, selection, scope, *, deadline):
        del selection, deadline
        self.calls += 1
        return (
            ContextItem(
                source_class="domain_current",
                provider_id=self.spec.provider_id,
                source_id="fixture-record",
                source_version="fixture-v1",
                item_id="item-1",
                owner_id=scope.owner_id,
                application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                authority="authoritative",
                observed_at=datetime(2026, 10, 7, tzinfo=UTC),
                sensitivity="personal",
                source_refs=(ContextSourceReference(kind="record", reference_id="item-1"),),
                payload=OverbroadPayload(value="allowed", diagnosis="private diagnosis"),
            ),
        )


def _context(policy, application_id="health"):
    provider_id = "synthetic.health"
    definition = ApplicationDefinition(
        application_id=application_id,
        display_name=application_id,
        memory_namespace=application_id,
        context_provider_ids=(provider_id,),
        context_policy=policy,
    )
    return ApplicationContextRequest(
        definition=definition,
        scope=RequestScope(
            owner_id="owner-1", request_id="request-1", application_id=application_id,
            workspace_id="workspace-1",
        ),
        context_provider_capabilities=(CapabilityRegistration(
            capability_id=provider_id, kind="context_provider", available=True
        ),),
    )


def _policy(*, sensitivity="personal", model_disclosure=True):
    base = ApplicationContextPolicy()
    return ApplicationContextPolicy(
        version="synthetic-health-policy-v1",
        provider_policies=(
            *base.provider_policies,
            ContextProviderPolicy(
                provider_id="synthetic.health",
                operations=(ContextOperationPolicy(
                    operation="current",
                    fields=(ContextFieldPolicy(
                        field="value",
                        sensitivity=sensitivity,
                        model_disclosure=model_disclosure,
                    ),),
                    sensitivity=sensitivity,
                ),),
            ),
        ),
        maximum_model_sensitivity="sensitive",
    )


def _selection():
    return ContextSelection(
        provider_id="synthetic.health",
        operation="current",
        fields=("value",),
        target_scope=ApplicationScope(application_id="health", workspace_id="workspace-1"),
    )


def test_restricted_field_is_denied_before_factory_or_source_call():
    source = Source()
    context = _context(_policy(sensitivity="restricted"))
    factory = StaticContextProviderFactory(source)
    coordinator = ContextProviderCoordinator({"synthetic.health": factory})

    with pytest.raises(ContextPreparationError, match="context_model_disclosure_denied"):
        coordinator.prepare(
            context,
            (_selection(),),
            ContextProviderInputs(scope=context.scope, application_context=context),
        )

    assert source.calls == 0


def test_unknown_field_sensitivity_is_denied_before_source_call():
    source = Source()
    context = _context(_policy(sensitivity="unknown"))
    coordinator = ContextProviderCoordinator({"synthetic.health": source})

    with pytest.raises(ContextPreparationError, match="context_unknown_sensitivity_denied"):
        coordinator.prepare(
            context,
            (_selection(),),
            ContextProviderInputs(scope=context.scope, application_context=context),
        )

    assert source.calls == 0


def test_health_source_without_application_policy_is_denied_before_fetch():
    source = Source()
    personal_context = _context(ApplicationContextPolicy(), application_id="personal_ai")
    selection = ContextSelection(
        provider_id="synthetic.health",
        operation="current",
        fields=("value",),
        target_scope=ApplicationScope(application_id="personal_ai", workspace_id="workspace-1"),
    )
    coordinator = ContextProviderCoordinator({"synthetic.health": source})

    with pytest.raises(ContextPreparationError, match="context_policy_denied"):
        coordinator.prepare(
            personal_context,
            (selection,),
            ContextProviderInputs(scope=personal_context.scope, application_context=personal_context),
        )

    assert source.calls == 0


def test_server_policy_sensitivity_is_joined_with_provider_label():
    source = Source(sensitivity="personal")
    context = _context(_policy(sensitivity="sensitive"))
    coordinator = ContextProviderCoordinator({"synthetic.health": source})

    result = coordinator.prepare(
        context,
        (_selection(),),
        ContextProviderInputs(scope=context.scope, application_context=context),
    )

    assert result.items[0].sensitivity == "sensitive"
    assert {item.sensitivity for item in result.items[0].field_sensitivity} == {"sensitive"}
    assert source.calls == 1


def test_unselected_payload_field_is_denied_from_model_input():
    source = OverbroadSource()
    context = _context(_policy())

    class Counter(FakeTokenCounter):
        def __init__(self):
            self.calls = 0
            self.seen_messages = []

        def count(self, messages):
            self.calls += 1
            self.seen_messages.extend(messages)
            return super().count(messages)

    counter = Counter()
    assembler = ContextAssembler(
        Settings(
            ai_provider="fake", ai_model="fake-model", max_context_tokens=4_096,
            max_response_tokens=128, context_safety_margin_tokens=32,
            summary_trigger_tokens=512, max_summary_tokens=256,
        ),
        counter,
        context_provider_coordinator=ContextProviderCoordinator({
            "synthetic.health": source,
        }),
    )
    pending = Message(
        id=uuid4(), conversation_id=uuid4(), owner_id=context.scope.owner_id,
        role=MessageRole.USER, content="Use only the allowed field.",
        status=MessageStatus.COMPLETED, created_at=datetime(2026, 10, 7, tzinfo=UTC),
        application_id="health", workspace_id="workspace-1",
    )

    with pytest.raises(
        ContextPreparationError, match="context_provider_projection_violation"
    ):
        assembler.assemble(
            (), pending, application_context=context, context_selections=(_selection(),)
        )

    assert source.calls == 1
    assert counter.calls > 0
    assert "private diagnosis" not in "\n".join(
        message.content for message in counter.seen_messages
    )


def test_denied_conversation_policy_fails_before_history_summary_and_counting():
    context = _context(ApplicationContextPolicy(provider_policies=()))

    class Counter(FakeTokenCounter):
        calls = 0

        def count(self, messages):
            self.calls += 1
            return super().count(messages)

    class SummaryRepository(InMemorySummaryRepository):
        calls = 0

        def compatible(self, **kwargs):
            self.calls += 1
            return super().compatible(**kwargs)

    counter = Counter()
    summaries = SummaryRepository()
    assembler = ContextAssembler(
        Settings(ai_provider="fake", ai_model="fake-model"), counter, summaries
    )
    now = datetime(2026, 10, 7, tzinfo=UTC)
    pending = Message(
        id=uuid4(), conversation_id=uuid4(), owner_id=context.scope.owner_id,
        role=MessageRole.USER, content="Private new message",
        status=MessageStatus.COMPLETED, created_at=now,
        application_id="health", workspace_id="workspace-1",
    )
    history = (
        Message(
            id=uuid4(), conversation_id=pending.conversation_id,
            owner_id=context.scope.owner_id, role=MessageRole.USER,
            content="Private history", status=MessageStatus.COMPLETED,
            created_at=now, application_id="health", workspace_id="workspace-1",
        ),
        Message(
            id=uuid4(), conversation_id=pending.conversation_id,
            owner_id=context.scope.owner_id, role=MessageRole.ASSISTANT,
            content="Private response", status=MessageStatus.COMPLETED,
            created_at=now, application_id="health", workspace_id="workspace-1",
        ),
    )

    with pytest.raises(ContextPreparationError, match="context_policy_denied"):
        assembler.assemble(history, pending, application_context=context, refresh=True)

    assert counter.calls == 0
    assert summaries.calls == 0


def test_default_health_policy_is_application_scoped_and_field_specific():
    registry = default_application_registry()
    health = registry.get("health")
    health_scope = RequestScope(
        owner_id="owner-1", request_id="health-policy", application_id="health",
        workspace_id="workspace-1",
    )
    health_context = ApplicationContextRequest(
        definition=health,
        scope=health_scope,
        context_provider_capabilities=registry.registration("health").context_providers,
    )
    allowed_health_fields = ContextSelection(
        provider_id="health.history_context",
        operation="history",
        fields=("medication_name", "dose", "observed_at"),
        target_scope=ApplicationScope(application_id="health", workspace_id="workspace-1"),
    )
    authorize_context_selections(health_context, (allowed_health_fields,))

    with pytest.raises(ContextPreparationError, match="context_field_policy_denied"):
        authorize_context_selections(
            health_context,
            (allowed_health_fields.model_copy(update={"fields": ("diagnosis",)}),),
        )

    personal = registry.get("personal_ai")
    personal_context = ApplicationContextRequest(
        definition=personal,
        scope=RequestScope(
            owner_id="owner-1", request_id="outside-health", application_id="personal_ai",
        ),
        # A forged capability entry cannot create a policy rule.
        context_provider_capabilities=(CapabilityRegistration(
            capability_id="health.history_context", kind="context_provider", available=True
        ),),
    )
    with pytest.raises(ContextPreparationError, match="context_policy_denied"):
        authorize_context_selections(
            personal_context,
            (ContextSelection(
                provider_id="health.history_context", operation="history",
                fields=("medication_name",),
            ),),
        )


def test_permission_dependency_can_name_a_versioned_future_grant_scope():
    dependency = ContextPermissionDependency(
        permission_id="grant-17",
        version="grant-v3",
        purpose="future explicit context share",
        source_application_id="health",
        destination_application_id="personal_ai",
    )
    assert dependency.version == "grant-v3"
    assert dependency.source_application_id == "health"
    assert dependency.destination_application_id == "personal_ai"


def test_explicit_source_access_without_model_disclosure_fails_before_fetch():
    source = Source()
    context = _context(_policy(sensitivity="sensitive", model_disclosure=False))
    coordinator = ContextProviderCoordinator({"synthetic.health": source})

    with pytest.raises(ContextPreparationError, match="context_field_policy_denied"):
        coordinator.prepare(
            context,
            (_selection(),),
            ContextProviderInputs(scope=context.scope, application_context=context),
        )

    assert source.calls == 0


def test_context_assembler_denies_before_summary_or_counter_calls():
    source = Source()
    context = _context(_policy(sensitivity="restricted"))

    class Counter(FakeTokenCounter):
        calls = 0

        def count(self, messages):
            self.calls += 1
            return super().count(messages)

    class SummaryRepository(InMemorySummaryRepository):
        calls = 0

        def compatible(self, **kwargs):
            self.calls += 1
            return super().compatible(**kwargs)

    counter = Counter()
    summaries = SummaryRepository()
    assembler = ContextAssembler(
        Settings(
            ai_provider="fake", ai_model="fake-model", max_context_tokens=4_096,
            max_response_tokens=128, context_safety_margin_tokens=32,
            summary_trigger_tokens=1_000, max_summary_tokens=512,
        ),
        counter,
        summaries,
        context_provider_coordinator=ContextProviderCoordinator({
            "synthetic.health": source,
        }),
    )
    pending = Message(
        id=uuid4(), conversation_id=uuid4(), owner_id=context.scope.owner_id,
        role=MessageRole.USER, content="Read a restricted health field.",
        status=MessageStatus.COMPLETED, created_at=datetime(2026, 10, 7, tzinfo=UTC),
        application_id="health", workspace_id="workspace-1",
    )

    with pytest.raises(ContextPreparationError, match="context_model_disclosure_denied"):
        assembler.assemble(
            (), pending, refresh=True, application_context=context,
            context_selections=(_selection(),),
        )

    assert counter.calls == 0
    assert summaries.calls == 0
    assert source.calls == 0


def test_chat_passes_effective_sensitivity_and_policy_version_to_inference():
    context = _context(ApplicationContextPolicy(), application_id="personal_ai").model_copy(
        update={"scope": RequestScope(
            owner_id="owner-1", request_id="request-1", application_id="personal_ai"
        )}
    )
    settings = Settings(ai_provider="fake", ai_model="fake-model")
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    conversation = Conversation(
        id=uuid4(), owner_id=context.scope.owner_id, title="policy-context",
        created_at=datetime(2026, 10, 7, tzinfo=UTC), updated_at=datetime(2026, 10, 7, tzinfo=UTC),
        application_id="personal_ai", workspace_id="workspace-1",
    )
    conversations.create(conversation)
    llm = FakeLLMClient(("safe answer",))
    service = ChatTurnService(
        conversations,
        messages,
        llm,
        owner_id=context.scope.owner_id,
        application_context=context,
        model="fake-model",
        context_assembler=ContextAssembler(settings, FakeTokenCounter()),
    )

    async def consume(stream):
        async for _event in stream:
            pass

    asyncio.run(consume(service.send(conversation.id, "Hello.", request_id="inference-policy")))

    inference_context = llm.inference_contexts[0]
    assert inference_context is not None
    assert inference_context.effective_sensitivity == "sensitive"
    assert inference_context.maximum_sensitivity == "sensitive"
    assert inference_context.policy_version == "application-context-policy-v1"


def test_real_provider_chat_requires_application_context_before_reserving_turn():
    settings = Settings(ai_provider="gemini", ai_model="gemini-test", ai_api_key="test-key")
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    now = datetime(2026, 10, 7, tzinfo=UTC)
    conversation = Conversation(
        id=uuid4(), owner_id="local", title="unscoped", created_at=now, updated_at=now
    )
    conversations.create(conversation)
    llm = GeminiLLMClient(settings)
    service = ChatTurnService(
        conversations,
        messages,
        llm,
        owner_id="local",
        model="gemini-test",
        context_assembler=ContextAssembler(settings, FakeTokenCounter()),
    )

    with pytest.raises(ContextPreparationError, match="application_context_required"):
        service.send(conversation.id, "Hello", request_id="unscoped-real-provider")

    assert messages.list_active(owner_id="local", conversation_id=conversation.id) == []
