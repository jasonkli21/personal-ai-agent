"""Deterministic Phase 13 planning and narrow provider execution contracts."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ConfigDict, create_model

from personal_ai.applications.contracts import (
    ApplicationContextRequest,
    ApplicationDefinition,
    CapabilityRegistration,
)
from personal_ai.auth.scope import RequestScope, bind_request_scope, reset_request_scope
from personal_ai.context.adapters import (
    BuiltInContextPermissionRevalidator,
    MemoryContextProviderFactory,
)
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.planner import (
    ContextPlanner,
    ContextPlanningCapability,
    ContextPlanningRule,
)
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
    ContextPreparationError,
    ContextProviderCoordinator,
    ContextProviderSpec,
    ContextSourceReference,
    StaticContextProviderFactory,
)
from personal_ai.context.repositories import InMemorySummaryRepository
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import Conversation, Message, MessageRole, MessageStatus
from personal_ai.llm.fake import FakeLLMClient
from personal_ai.services.chat_turns import ChatTurnService
from personal_ai.settings import Settings
from personal_ai.storage.fake import InMemoryConversationRepository, InMemoryMessageRepository

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


class FixtureProvider:
    def __init__(
        self,
        provider_id: str,
        source_class: str,
        operation: ContextOperationSpec,
        *,
        values: dict[str, str] | None = None,
    ) -> None:
        self.spec = ContextProviderSpec(
            provider_id=provider_id,
            source_class=source_class,
            source_version="fixture-provider-v1",
            operations=(operation,),
            maximum_items_per_call=operation.maximum_results,
        )
        self.payload_type = create_model(
            f"{provider_id.replace('.', '_').title()}Payload",
            __config__=ConfigDict(extra="forbid", frozen=True),
            **{field: (str | None, None) for field in operation.allowed_fields},
        )
        self.values = values or {field: f"fixture {field}" for field in operation.allowed_fields}
        self.calls: list[dict[str, Any]] = []

    def validate_selection(self, selection, inputs):
        assert selection.provider_id == self.spec.provider_id
        assert inputs.scope.application_id

    def fetch(self, selection, scope, *, deadline):
        del deadline
        self.calls.append(selection.model_dump(mode="json", exclude_none=True))
        payload = self.payload_type(
            **{field: self.values.get(field) for field in selection.fields}
        )
        entity_refs = selection.entity_refs
        return (
            ContextItem(
                source_class=self.spec.source_class,
                provider_id=self.spec.provider_id,
                source_id="fixture-records-v1",
                source_version="fixture-record-v1",
                item_id="fixture-item-1",
                owner_id=scope.owner_id,
                application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                entity_refs=entity_refs,
                authority="authoritative",
                observed_at=NOW,
                sensitivity="sensitive",
                source_refs=(ContextSourceReference(kind="record", reference_id="fixture-item-1"),),
                payload=payload,
            ),
        )


def _context(provider: FixtureProvider, application_id: str) -> ApplicationContextRequest:
    definition = ApplicationDefinition(
        application_id=application_id,
        display_name=application_id.title(),
        memory_namespace=application_id,
        context_provider_ids=(provider.spec.provider_id,),
    )
    capability = CapabilityRegistration(
        capability_id=provider.spec.provider_id,
        kind="context_provider",
        available=True,
    )
    scope = RequestScope(
        owner_id="owner-1",
        request_id="request-1",
        application_id=application_id,
        workspace_id="workspace-1",
    )
    return ApplicationContextRequest(
        definition=definition,
        scope=scope,
        context_provider_capabilities=(capability,),
    )


def _rule(
    *,
    application_id: str,
    category: str,
    provider_id: str,
    operation: str,
    fields: tuple[str, ...],
    phrase: str,
    window_seconds: int | None = None,
    use_candidate_entities: bool = False,
    require_candidate_entities: bool = False,
    exclusive_group: str | None = None,
    required: bool = False,
    max_tokens: int = 80,
) -> ContextPlanningRule:
    return ContextPlanningRule(
        rule_id=f"{category}.{provider_id.replace('.', '-')}:v1",
        category=category,
        phrases=(phrase,),
        provider_id=provider_id,
        operation=operation,
        fields=fields,
        max_results=3,
        max_bytes=4_096,
        max_tokens=max_tokens,
        timeout_seconds=1,
        window_seconds=window_seconds,
        use_candidate_entities=use_candidate_entities,
        require_candidate_entities=require_candidate_entities,
        required=required,
        exclusive_group=exclusive_group,
        application_ids=(application_id,),
        explanation=f"Select the bounded {category} fields needed for this request.",
    )


def _assembler(provider: FixtureProvider, context: ApplicationContextRequest, planner: ContextPlanner):
    coordinator = ContextProviderCoordinator(
        {provider.spec.provider_id: StaticContextProviderFactory(provider)}
    )
    settings = Settings(
        ai_provider="gemini",
        ai_model="fixture-model",
        max_context_tokens=4_096,
        max_response_tokens=100,
        context_safety_margin_tokens=20,
        summary_trigger_tokens=1_000,
        max_summary_tokens=512,
    )
    return ContextAssembler(
        settings,
        FakeTokenCounter(),
        context_provider_coordinator=coordinator,
        context_planner=planner,
    )


def _pending(context: ApplicationContextRequest, content: str) -> Message:
    return Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id=context.scope.owner_id,
        application_id=context.scope.application_id,
        workspace_id=context.scope.workspace_id,
        scope_version=2,
        role=MessageRole.USER,
        content=content,
        status=MessageStatus.COMPLETED,
        created_at=NOW,
    )


def test_default_standalone_recall_rule_is_deterministic_and_narrow():
    provider = FixtureProvider(
        "ai_memory",
        "ai_memory",
        ContextOperationSpec(
            operation="search",
            allowed_fields=("content", "memory_type", "effective_at", "source_message_ids"),
            maximum_results=8,
            maximum_bytes=8_192,
            maximum_timeout_seconds=2,
        ),
    )
    context = _context(provider, "personal_ai")
    assembler = _assembler(provider, context, ContextPlanner())

    first = assembler.plan_context("What did I tell you to remember about my travel?", context, now=NOW)
    second = assembler.plan_context("What did I tell you to remember about my travel?", context, now=NOW)

    assert first == second
    assert len(first.selections) == 1
    assert first.selections[0].provider_id == "ai_memory"
    assert first.selections[0].fields == ("content", "memory_type", "effective_at")
    assert first.selections[0].max_results == 5
    assert first.selections[0].max_bytes == 8_192
    assert first.selections[0].max_tokens == 256
    assert "source_message_ids" not in first.selections[0].fields


def test_default_profile_rule_selects_one_shared_field():
    provider = FixtureProvider(
        "global_profile",
        "global_profile",
        ContextOperationSpec(
            operation="profile",
            allowed_fields=("preferred_units", "locale", "response_style", "answer_length"),
            maximum_results=4,
            maximum_bytes=8_192,
            maximum_timeout_seconds=2,
        ),
    )
    context = _context(provider, "personal_ai")
    assembler = _assembler(provider, context, ContextPlanner())

    plan = assembler.plan_context("What units do I prefer?", context, now=NOW)

    assert len(plan.selections) == 1
    assert plan.selections[0].provider_id == "global_profile"
    assert plan.selections[0].fields == ("preferred_units",)
    assert plan.selections[0].max_results == 1


@pytest.mark.parametrize(
    ("application_id", "category", "provider_id", "source_class", "operation", "fields", "phrase", "allowed", "window_seconds"),
    [
        (
            "travel", "travel", "travel.trip_context", "domain_current", "current",
            ("city", "start_date", "end_date", "payment_details"), "hotel dates in oslo",
            ("city", "start_date", "end_date"), None,
        ),
        (
            "shopping", "shopping", "shopping.product_context", "domain_current", "current",
            ("product_name", "price", "tax_id"), "compare saved chair prices",
            ("product_name", "price"), None,
        ),
        (
            "finance", "finance", "finance.account_context", "domain_current", "current",
            ("balance", "currency", "tax_id"), "account cash balance",
            ("balance", "currency"), None,
        ),
        (
            "health", "health", "health.history_context", "domain_history", "history",
            ("medication_name", "dose", "diagnosis", "observed_at"), "medication dose history",
            ("medication_name", "dose", "observed_at"), 30 * 86_400,
        ),
    ],
)
def test_domain_rules_fetch_only_selected_fields_and_execute_through_builder(
    application_id, category, provider_id, source_class, operation, fields, phrase, allowed, window_seconds
):
    operation_spec = ContextOperationSpec(
        operation=operation,
        allowed_fields=fields,
        accepts_entity_refs=application_id == "health",
        requires_time_window=application_id == "health",
        maximum_window_seconds=30 * 86_400 if application_id == "health" else 365 * 86_400,
        maximum_results=6,
        maximum_bytes=6_000,
        maximum_timeout_seconds=2,
    )
    provider = FixtureProvider(provider_id, source_class, operation_spec)
    context = _context(provider, application_id)
    rule = _rule(
        application_id=application_id,
        category=category,
        provider_id=provider_id,
        operation=operation,
        fields=allowed,
        phrase=phrase,
        window_seconds=90 * 86_400 if application_id == "health" else window_seconds,
        use_candidate_entities=application_id == "health",
        require_candidate_entities=application_id == "health",
    )
    planner = ContextPlanner((rule,), include_default_rules=False)
    assembler = _assembler(provider, context, planner)
    entity = ContextEntityReference(
        entity_type="health_record",
        entity_id="medication-list-1",
        application_id=application_id,
        workspace_id=context.scope.workspace_id,
    )
    plan = assembler.plan_context(
        f"Please review my {phrase}.",
        context,
        candidate_entities=(entity,) if application_id == "health" else (),
        now=NOW,
    )
    pending = _pending(context, f"Please review my {phrase}.")

    assembled = assembler.assemble(
        (), pending, application_context=context, context_plan=plan, refresh=False
    )

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["fields"] == list(allowed)
    assert set(call["fields"]).isdisjoint(
        {"payment_details", "tax_id", "diagnosis"} - set(allowed)
    )
    assert plan.selections[0].max_results == 3
    assert plan.selections[0].max_bytes == 4_096
    assert plan.selections[0].max_tokens == 80
    assert assembled.context_plan == plan
    assert assembled.manifest is not None
    assert assembled.manifest.planner_version == ContextPlanner.VERSION
    assert assembled.manifest.planning_decisions
    assert assembled.manifest.actual_input_tokens <= assembled.manifest.global_input_tokens
    if application_id == "health":
        assert call["entity_refs"][0]["entity_id"] == "medication-list-1"
        assert datetime.fromisoformat(call["window_end"]) == NOW
        assert datetime.fromisoformat(call["window_start"]) == NOW - timedelta(
            seconds=30 * 86_400
        )


def test_ambiguous_domain_intent_selects_no_provider():
    rules = (
        _rule(
            application_id="travel",
            category="travel",
            provider_id="travel.trip_context",
            operation="current",
            fields=("city",),
            phrase="travel health records",
            exclusive_group="domain",
        ),
        _rule(
            application_id="travel",
            category="health",
            provider_id="travel.trip_context",
            operation="current",
            fields=("city",),
            phrase="travel health records",
            exclusive_group="domain",
        ),
    )
    provider = FixtureProvider(
        "travel.trip_context",
        "domain_current",
        ContextOperationSpec(operation="current", allowed_fields=("city",)),
    )
    context = _context(provider, "travel")
    assembler = _assembler(provider, context, ContextPlanner(rules, include_default_rules=False))

    plan = assembler.plan_context("Review my travel health records", context, now=NOW)
    assembled = assembler.assemble(
        (), _pending(context, "Review my travel health records"),
        application_context=context, context_plan=plan, refresh=False,
    )

    assert plan.selections == ()
    assert [item.reason for item in plan.decisions] == ["ambiguous_intent", "ambiguous_intent"]
    assert provider.calls == []
    assert assembled.manifest is not None
    assert assembled.manifest.planner_version == ContextPlanner.VERSION


def test_unavailable_optional_provider_does_not_widen_to_another_registered_provider():
    unavailable_provider_id = "travel.trip_context"
    rule = _rule(
        application_id="travel",
        category="travel",
        provider_id=unavailable_provider_id,
        operation="current",
        fields=("city",),
        phrase="hotel in oslo",
    )
    unrelated = FixtureProvider(
        "travel.research_context",
        "external_research",
        ContextOperationSpec(operation="search", allowed_fields=("passage",)),
    )
    context = _context(unrelated, "travel")
    planner = ContextPlanner((rule,), include_default_rules=False)
    assembler = _assembler(unrelated, context, planner)

    plan = assembler.plan_context("Find my hotel in Oslo", context, now=NOW)
    assembled = assembler.assemble(
        (), _pending(context, "Find my hotel in Oslo"),
        application_context=context, context_plan=plan, refresh=False,
    )

    assert plan.selections == ()
    assert plan.decisions[0].reason == "provider_not_registered"
    assert unrelated.calls == []
    assert assembled.source_items == ()


def test_unavailable_required_provider_stops_planning_before_retrieval():
    rule = _rule(
        application_id="travel",
        category="travel",
        provider_id="travel.trip_context",
        operation="current",
        fields=("city",),
        phrase="hotel in oslo",
        required=True,
    )
    unrelated = FixtureProvider(
        "travel.research_context",
        "external_research",
        ContextOperationSpec(operation="search", allowed_fields=("passage",)),
    )
    context = _context(unrelated, "travel")
    assembler = _assembler(
        unrelated, context, ContextPlanner((rule,), include_default_rules=False)
    )

    with pytest.raises(ContextPreparationError, match="required_context_source_unavailable"):
        assembler.plan_context("Find my hotel in Oslo", context, now=NOW)
    assert unrelated.calls == []


def test_global_planner_token_budget_omits_lower_priority_sources():
    first = FixtureProvider(
        "travel.trip_context",
        "domain_current",
        ContextOperationSpec(operation="current", allowed_fields=("city",)),
    )
    second = FixtureProvider(
        "travel.research_context",
        "external_research",
        ContextOperationSpec(operation="search", allowed_fields=("passage",)),
    )
    first_rule = _rule(
        application_id="travel",
        category="travel_trip",
        provider_id=first.spec.provider_id,
        operation="current",
        fields=("city",),
        phrase="trip city",
        max_tokens=20,
    ).model_copy(update={"priority": 10})
    second_rule = _rule(
        application_id="travel",
        category="travel_research",
        provider_id=second.spec.provider_id,
        operation="search",
        fields=("passage",),
        phrase="trip city",
        max_tokens=20,
    ).model_copy(update={"priority": 20})
    context = ApplicationContextRequest(
        definition=ApplicationDefinition(
            application_id="travel",
            display_name="Travel",
            memory_namespace="travel",
            context_provider_ids=(first.spec.provider_id, second.spec.provider_id),
        ),
        scope=RequestScope(
            owner_id="owner-1",
            request_id="request-1",
            application_id="travel",
            workspace_id="workspace-1",
        ),
        context_provider_capabilities=(
            CapabilityRegistration(
                capability_id=first.spec.provider_id,
                kind="context_provider",
                available=True,
            ),
            CapabilityRegistration(
                capability_id=second.spec.provider_id,
                kind="context_provider",
                available=True,
            ),
        ),
    )
    plan = ContextPlanner(
        (first_rule, second_rule), include_default_rules=False, max_total_tokens=20
    ).plan(
        "trip city",
        context,
        {
            first.spec.provider_id: ContextPlanningCapability(
                status="available", spec=first.spec
            ),
            second.spec.provider_id: ContextPlanningCapability(
                status="available", spec=second.spec
            ),
        },
        input_token_budget=100,
        now=NOW,
    )

    assert len(plan.selections) == 1
    assert plan.selections[0].provider_id == first.spec.provider_id
    assert plan.selections[0].max_tokens == 20
    assert any(
        decision.reason == "plan_token_budget_exhausted" and decision.disposition == "omitted"
        for decision in plan.decisions
    )


def test_scope_fingerprint_prevents_plan_reuse_across_requests():
    provider = FixtureProvider(
        "travel.trip_context",
        "domain_current",
        ContextOperationSpec(operation="current", allowed_fields=("city",)),
    )
    context = _context(provider, "travel")
    planner = ContextPlanner(
        (_rule(
            application_id="travel",
            category="travel",
            provider_id="travel.trip_context",
            operation="current",
            fields=("city",),
            phrase="trip city",
        ),),
        include_default_rules=False,
    )
    assembler = _assembler(provider, context, planner)
    plan = assembler.plan_context("trip city", context, now=NOW)
    other_context = context.model_copy(
        update={"scope": context.scope.model_copy(update={"request_id": "request-2"})}
    )

    with pytest.raises(Exception, match="context_plan_scope_mismatch"):
        assembler.assemble(
            (), _pending(other_context, "trip city"),
            application_context=other_context, context_plan=plan, refresh=False,
        )


def test_profile_share_is_rechecked_after_selected_provider_fetch():
    class RevokingProfileRepository(InMemoryGlobalProfileRepository):
        shared_read_count = 0

        def shared_fields(self, owner_id, application_id, fields, *, deadline=None):
            result = super().shared_fields(
                owner_id, application_id, fields, deadline=deadline
            )
            self.shared_read_count += 1
            if self.shared_read_count == 1:
                super().update(
                    owner_id,
                    GlobalProfileUpdate(remove_fields=("preferred_units",)),
                )
            return result

    settings = Settings(
        ai_provider="gemini",
        ai_model="fixture-model",
        max_context_tokens=4_096,
        max_response_tokens=100,
        context_safety_margin_tokens=20,
        summary_trigger_tokens=1_000,
        max_summary_tokens=512,
    )
    repository = RevokingProfileRepository(clock=lambda: NOW)
    repository.update(
        "owner-1",
        GlobalProfileUpdate(
            fields=(
                GlobalProfileFieldUpdate(
                    field="preferred_units",
                    value="metric",
                    shared_with_applications=("personal_ai",),
                ),
            )
        ),
    )
    factory = GlobalProfileContextProviderFactory(repository)
    context = _context(factory, "personal_ai")
    assembler = ContextAssembler(
        settings,
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {"global_profile": factory}
        ),
        permission_revalidator=BuiltInContextPermissionRevalidator(settings, repository),
    )
    plan = assembler.plan_context("What units do I prefer?", context, now=NOW)
    scope_token = bind_request_scope(context.scope)
    try:
        assembled = assembler.assemble(
            (), _pending(context, "What units do I prefer?"),
            application_context=context, context_plan=plan, refresh=False,
        )
    finally:
        reset_request_scope(scope_token)

    assert repository.shared_read_count == 2
    assert "metric" not in " ".join(message.content for message in assembled.messages)
    assert assembled.manifest is not None
    assert any(
        item.item_id == "preferred_units"
        and item.omission_reason == "permission_revoked"
        for item in assembled.manifest.items
    )


def test_planned_source_budget_limits_builder_source_ceiling():
    provider = FixtureProvider(
        "shopping.product_context",
        "domain_current",
        ContextOperationSpec(
            operation="current",
            allowed_fields=("product_name", "price"),
            maximum_bytes=4_096,
            maximum_results=3,
            maximum_timeout_seconds=1,
        ),
    )
    context = _context(provider, "shopping")
    rule = _rule(
        application_id="shopping",
        category="shopping",
        provider_id="shopping.product_context",
        operation="current",
        fields=("product_name", "price"),
        phrase="compare chair prices",
        max_tokens=12,
    )
    assembler = _assembler(
        provider, context, ContextPlanner((rule,), include_default_rules=False)
    )
    plan = assembler.plan_context("compare chair prices", context, now=NOW)
    result = assembler.assemble(
        (), _pending(context, "compare chair prices"),
        application_context=context, context_plan=plan, refresh=False,
    )

    source_report = next(
        report for report in result.manifest.sources if report.source_class == "domain_current"
    )
    assert plan.selections[0].max_tokens == 12
    assert source_report.token_limit == 12
    assert result.budget.selected_total <= result.budget.input_budget


def test_chat_plans_before_running_memory_retrieval():
    settings = Settings(ai_provider="gemini", ai_model="fixture-model", memory_enabled=True)
    factory = MemoryContextProviderFactory(settings)
    capability = CapabilityRegistration(
        capability_id="ai_memory",
        kind="context_provider",
        available=True,
    )
    definition = ApplicationDefinition(
        application_id="personal_ai",
        display_name="Personal AI",
        memory_namespace="personal_ai",
        context_provider_ids=("ai_memory",),
    )
    application_context = ApplicationContextRequest(
        definition=definition,
        scope=RequestScope(owner_id="local", request_id="request-chat", application_id="personal_ai"),
        context_provider_capabilities=(capability,),
    )
    assembler = ContextAssembler(
        settings,
        FakeTokenCounter(),
        InMemorySummaryRepository(),
        context_provider_coordinator=ContextProviderCoordinator(
            {"ai_memory": factory}, feature_flags={"memory_enabled": True}
        ),
    )
    planned_intents = []
    original_plan = assembler.plan_context

    def record_plan(intent, context, **kwargs):
        planned_intents.append(intent)
        return original_plan(intent, context, **kwargs)

    assembler.plan_context = record_plan

    class Retriever:
        def __init__(self):
            self.queries = []

        def retrieve(self, owner_id, query, active, *, timeout):
            del owner_id, active, timeout
            assert planned_intents[-1] == query
            self.queries.append(query)

    retriever = Retriever()
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    conversation_ids = []
    for index in range(2):
        conversation = Conversation(
            id=uuid4(),
            owner_id="local",
            title=f"planner-{index}",
            created_at=NOW,
            updated_at=NOW,
        )
        conversations.create(conversation)
        conversation_ids.append(conversation.id)
    service = ChatTurnService(
        conversations,
        messages,
        FakeLLMClient(),
        owner_id="local",
        application_context=application_context,
        model="fixture-model",
        context_assembler=assembler,
        memory_retriever=retriever,
    )

    service.send(conversation_ids[0], "What is the capital of Norway?", request_id="ordinary")
    service.send(
        conversation_ids[1],
        "What did I tell you to remember about travel?",
        request_id="recall",
    )

    assert planned_intents == [
        "What is the capital of Norway?",
        "What did I tell you to remember about travel?",
    ]
    assert retriever.queries == ["What did I tell you to remember about travel?"]
