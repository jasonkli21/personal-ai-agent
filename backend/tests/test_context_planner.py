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
from personal_ai.context.contracts import ContextError
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


class MultiOperationFixtureProvider:
    def __init__(self):
        self.spec = ContextProviderSpec(
            provider_id="travel.shared_context",
            source_class="domain_current",
            source_version="fixture-provider-v1",
            operations=(
                ContextOperationSpec(operation="current", allowed_fields=("current_fact",)),
                ContextOperationSpec(operation="history", allowed_fields=("history_fact",)),
            ),
        )
        self.payload_type = create_model(
            "MultiOperationPayload",
            __config__=ConfigDict(extra="forbid", frozen=True),
            current_fact=(str | None, None),
            history_fact=(str | None, None),
        )
        self.calls = []

    def validate_selection(self, selection, inputs):
        del inputs
        assert self.spec.operation(selection.operation) is not None

    def fetch(self, selection, scope, *, deadline):
        del deadline
        self.calls.append((selection.operation, selection.max_tokens))
        payload = self.payload_type(
            **{
                field: (
                    "oversized " * 80
                    if field == "current_fact"
                    else "bounded history"
                )
                for field in selection.fields
            }
        )
        return (
            ContextItem(
                source_class="domain_current",
                provider_id=self.spec.provider_id,
                source_id="fixture-records-v1",
                source_version="fixture-record-v1",
                item_id=selection.operation,
                owner_id=scope.owner_id,
                application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                authority="authoritative",
                observed_at=NOW,
                sensitivity="sensitive",
                source_refs=(
                    ContextSourceReference(kind="record", reference_id=selection.operation),
                ),
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


def _context_for_providers(providers, application_id: str) -> ApplicationContextRequest:
    provider_ids = tuple(provider.spec.provider_id for provider in providers)
    return ApplicationContextRequest(
        definition=ApplicationDefinition(
            application_id=application_id,
            display_name=application_id.title(),
            memory_namespace=application_id,
            context_provider_ids=provider_ids,
        ),
        scope=RequestScope(
            owner_id="owner-1",
            request_id="request-many",
            application_id=application_id,
            workspace_id="workspace-1",
        ),
        context_provider_capabilities=tuple(
            CapabilityRegistration(
                capability_id=provider.spec.provider_id,
                kind="context_provider",
                available=True,
            )
            for provider in providers
        ),
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
    assert first.selections[0].max_tokens == 512
    assert "source_message_ids" not in first.selections[0].fields


@pytest.mark.parametrize(
    "intent",
    [
        "Remember to explain recursion step by step.",
        "What do you remember about recursion?",
        "I cannot remember how to reset my router.",
        "Do not recall my saved personal information.",
        "Remember that I prefer metric units.",
        "What do you not remember about me?",
        "I don't recall what I told you.",
    ],
)
def test_non_recall_or_negated_memory_language_does_not_select_memory(intent):
    provider = FixtureProvider(
        "ai_memory",
        "ai_memory",
        ContextOperationSpec(
            operation="search",
            allowed_fields=("content", "memory_type", "effective_at"),
            maximum_results=8,
            maximum_bytes=8_192,
            maximum_timeout_seconds=2,
        ),
    )
    context = _context(provider, "personal_ai")
    assembler = _assembler(provider, context, ContextPlanner())

    plan = assembler.plan_context(intent, context, now=NOW)
    assembled = assembler.assemble(
        (), _pending(context, intent), application_context=context,
        context_plan=plan, refresh=False,
    )

    assert not any(item.provider_id == "ai_memory" for item in plan.selections)
    assert provider.calls == []
    assert not any(item.source_class == "ai_memory" for item in assembled.source_items)


@pytest.mark.parametrize(
    "intent",
    ["What did I tell you?", "What do you remember about me?"],
)
def test_explicit_personal_recall_phrases_still_select_memory(intent):
    provider = FixtureProvider(
        "ai_memory",
        "ai_memory",
        ContextOperationSpec(
            operation="search",
            allowed_fields=("content", "memory_type", "effective_at"),
        ),
    )
    context = _context(provider, "personal_ai")
    plan = _assembler(provider, context, ContextPlanner()).plan_context(
        intent, context, now=NOW
    )

    assert [(item.provider_id, item.operation) for item in plan.selections] == [
        ("ai_memory", "search")
    ]


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
    ("fields", "intent"),
    [
        (("preferred_units", "locale"), "My preferred units and my preferred language"),
        (
            ("preferred_units", "locale", "response_style", "answer_length"),
            (
                "What are my preferred units, my preferred language, my preferred response style, "
                "and my preferred answer length?"
            ),
        ),
    ],
)
def test_merged_profile_rules_fetch_every_shared_field(fields, intent):
    values = {
        "preferred_units": "metric",
        "locale": "en-US",
        "response_style": "concise",
        "answer_length": "short",
    }
    repository = InMemoryGlobalProfileRepository(clock=lambda: NOW)
    repository.update(
        "owner-1",
        GlobalProfileUpdate(
            fields=tuple(
                GlobalProfileFieldUpdate(
                    field=field,
                    value=values[field],
                    shared_with_applications=("personal_ai",),
                )
                for field in fields
            )
        ),
    )
    factory = GlobalProfileContextProviderFactory(repository)
    context = _context(factory, "personal_ai")
    settings = Settings(
        ai_provider="gemini",
        ai_model="fixture-model",
        max_context_tokens=4_096,
        max_response_tokens=100,
        context_safety_margin_tokens=20,
        summary_trigger_tokens=1_000,
        max_summary_tokens=512,
    )
    assembler = ContextAssembler(
        settings,
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {"global_profile": factory}
        ),
        permission_revalidator=BuiltInContextPermissionRevalidator(settings, repository),
    )
    plan = assembler.plan_context(intent, context, now=NOW)
    scope_token = bind_request_scope(context.scope)
    try:
        assembled = assembler.assemble(
            (), _pending(context, intent), application_context=context,
            context_plan=plan, refresh=False,
        )
    finally:
        reset_request_scope(scope_token)

    assert set(plan.selections[0].fields) == set(fields)
    assert plan.selections[0].max_results == len(fields)
    admitted = {
        item.payload.field: item.payload.value
        for item in assembled.source_items
        if item.payload.field in fields
    }
    assert admitted == {field: values[field] for field in fields}
    assert set(assembled.manifest.injected_item_ids) == set(fields)
    rendered = " ".join(message.content for message in assembled.messages)
    assert all(values[field] in rendered for field in fields)


def test_required_profile_field_survives_optional_field_budget_pressure():
    values = {"preferred_units": "metric", "locale": "en-US"}
    repository = InMemoryGlobalProfileRepository(clock=lambda: NOW)
    repository.update(
        "owner-1",
        GlobalProfileUpdate(
            fields=tuple(
                GlobalProfileFieldUpdate(
                    field=field,
                    value=value,
                    shared_with_applications=("personal_ai",),
                )
                for field, value in values.items()
            )
        ),
    )
    factory = GlobalProfileContextProviderFactory(repository)
    context = _context(factory, "personal_ai")
    required_rule = _rule(
        application_id="personal_ai", category="required_units",
        provider_id="global_profile", operation="profile", fields=("preferred_units",),
        phrase="profile request", required=True, max_tokens=80,
    )
    optional_rule = _rule(
        application_id="personal_ai", category="optional_locale",
        provider_id="global_profile", operation="profile", fields=("locale",),
        phrase="profile request", max_tokens=80,
    )
    planner = ContextPlanner(
        (required_rule, optional_rule), include_default_rules=False, max_total_tokens=80
    )
    settings = Settings(
        ai_provider="gemini", ai_model="fixture-model", max_context_tokens=4_096,
        max_response_tokens=100, context_safety_margin_tokens=20,
        summary_trigger_tokens=1_000, max_summary_tokens=512,
    )
    assembler = ContextAssembler(
        settings,
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {"global_profile": factory}
        ),
        permission_revalidator=BuiltInContextPermissionRevalidator(settings, repository),
        context_planner=planner,
    )
    plan = assembler.plan_context("profile request", context, now=NOW)
    scope_token = bind_request_scope(context.scope)
    try:
        assembled = assembler.assemble(
            (), _pending(context, "profile request"), application_context=context,
            context_plan=plan, refresh=False,
        )
    finally:
        reset_request_scope(scope_token)

    assert len(plan.selections) == 1
    assert plan.selections[0].fields == ("preferred_units",)
    assert plan.selections[0].required
    assert plan.selections[0].max_results == 1
    assert any(
        item.rule_id == optional_rule.rule_id
        and item.disposition == "omitted"
        and item.reason == "plan_token_budget_exhausted"
        for item in plan.decisions
    )
    assert [item.payload.field for item in assembled.source_items] == ["preferred_units"]
    assert "metric" in " ".join(message.content for message in assembled.messages)


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


def test_required_sources_reserve_plan_tokens_before_higher_priority_optional_sources():
    optional = FixtureProvider(
        "travel.optional_context",
        "domain_current",
        ContextOperationSpec(operation="current", allowed_fields=("city",)),
    )
    required = FixtureProvider(
        "travel.required_context",
        "domain_current",
        ContextOperationSpec(operation="current", allowed_fields=("dates",)),
    )
    context = _context_for_providers((optional, required), "travel")
    optional_rule = _rule(
        application_id="travel", category="optional", provider_id=optional.spec.provider_id,
        operation="current", fields=("city",), phrase="trip planning", max_tokens=20,
    ).model_copy(update={"priority": 1})
    required_rule = _rule(
        application_id="travel", category="required", provider_id=required.spec.provider_id,
        operation="current", fields=("dates",), phrase="trip planning", max_tokens=20,
        required=True,
    ).model_copy(update={"priority": 50})
    plan = ContextPlanner(
        (optional_rule, required_rule), include_default_rules=False, max_total_tokens=20
    ).plan(
        "trip planning",
        context,
        {
            provider.spec.provider_id: ContextPlanningCapability(
                status="available", spec=provider.spec
            )
            for provider in (optional, required)
        },
        input_token_budget=100,
        now=NOW,
    )

    assert [(item.provider_id, item.fields, item.required) for item in plan.selections] == [
        (required.spec.provider_id, ("dates",), True)
    ]
    assert any(
        item.rule_id == optional_rule.rule_id
        and item.disposition == "omitted"
        and item.reason == "plan_token_budget_exhausted"
        for item in plan.decisions
    )


def test_required_sources_fail_when_their_combined_budget_does_not_fit():
    providers = tuple(
        FixtureProvider(
            provider_id,
            "domain_current",
            ContextOperationSpec(operation="current", allowed_fields=("city",)),
        )
        for provider_id in ("travel.first_context", "travel.second_context")
    )
    context = _context_for_providers(providers, "travel")
    rules = tuple(
        _rule(
            application_id="travel", category=f"required_{index}",
            provider_id=provider.spec.provider_id, operation="current", fields=("city",),
            phrase="required trip data", required=True, max_tokens=10,
        )
        for index, provider in enumerate(providers)
    )
    with pytest.raises(ContextPreparationError, match="required_context_plan_budget_exceeded"):
        ContextPlanner(rules, include_default_rules=False, max_total_tokens=19).plan(
            "required trip data",
            context,
            {
                provider.spec.provider_id: ContextPlanningCapability(
                    status="available", spec=provider.spec
                )
                for provider in providers
            },
            input_token_budget=100,
            now=NOW,
        )


def test_selection_count_exhaustion_omits_optional_and_fails_required_rules():
    providers = tuple(
        FixtureProvider(
            f"travel.source_{index:02d}",
            "domain_current",
            ContextOperationSpec(operation="current", allowed_fields=("city",)),
        )
        for index in range(17)
    )
    context = ApplicationContextRequest(
        definition=ApplicationDefinition(
            application_id="travel",
            display_name="Travel",
            memory_namespace="travel",
            context_provider_ids=tuple(item.spec.provider_id for item in providers[:16]),
        ),
        scope=RequestScope(
            owner_id="owner-1", request_id="request-limit", application_id="travel",
            workspace_id="workspace-1",
        ),
        context_provider_capabilities=tuple(
            CapabilityRegistration(
                capability_id=item.spec.provider_id, kind="context_provider", available=True
            )
            for item in providers
        ),
    )
    optional_rules = tuple(
        _rule(
            application_id="travel", category=f"source_{index}",
            provider_id=provider.spec.provider_id, operation="current", fields=("city",),
            phrase="all travel sources", max_tokens=1,
        )
        for index, provider in enumerate(providers)
    )
    capabilities = {
        item.spec.provider_id: ContextPlanningCapability(status="available", spec=item.spec)
        for item in providers
    }
    optional_plan = ContextPlanner(
        optional_rules, include_default_rules=False, max_total_tokens=100
    ).plan("all travel sources", context, capabilities, input_token_budget=1_000, now=NOW)
    assert len(optional_plan.selections) == ContextPlanner.MAX_SELECTIONS
    assert any(item.reason == "selection_limit_exceeded" for item in optional_plan.decisions)

    required_rules = tuple(rule.model_copy(update={"required": True}) for rule in optional_rules)
    with pytest.raises(ContextPreparationError, match="required_context_plan_budget_exceeded"):
        ContextPlanner(
            required_rules, include_default_rules=False, max_total_tokens=100
        ).plan("all travel sources", context, capabilities, input_token_budget=1_000, now=NOW)


def test_each_provider_operation_obeys_its_own_token_allocation():
    large = FixtureProvider(
        "travel.large_context", "domain_current",
        ContextOperationSpec(operation="current", allowed_fields=("city",)),
        values={"city": "oversized " * 80},
    )
    small = FixtureProvider(
        "travel.small_context", "domain_current",
        ContextOperationSpec(operation="current", allowed_fields=("price",)),
        values={"price": "bounded value"},
    )
    providers = (large, small)
    context = _context_for_providers(providers, "travel")
    rules = (
        _rule(
            application_id="travel", category="large", provider_id=large.spec.provider_id,
            operation="current", fields=("city",), phrase="trip details", max_tokens=12,
        ),
        _rule(
            application_id="travel", category="small", provider_id=small.spec.provider_id,
            operation="current", fields=("price",), phrase="trip details", max_tokens=200,
        ),
    )
    settings = Settings(
        ai_provider="gemini", ai_model="fixture-model", max_context_tokens=4_096,
        max_response_tokens=100, context_safety_margin_tokens=20, summary_trigger_tokens=1_000,
        max_summary_tokens=512,
    )
    assembler = ContextAssembler(
        settings,
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {item.spec.provider_id: StaticContextProviderFactory(item) for item in providers}
        ),
        context_planner=ContextPlanner(rules, include_default_rules=False, max_total_tokens=212),
    )
    plan = assembler.plan_context("trip details", context, now=NOW)
    assembled = assembler.assemble(
        (), _pending(context, "trip details"), application_context=context,
        context_plan=plan, refresh=False,
    )
    reports = {item.provider_id: item for item in assembled.manifest.items}

    assert {item.provider_id: item.max_tokens for item in plan.selections} == {
        large.spec.provider_id: 12,
        small.spec.provider_id: 200,
    }
    assert reports[large.spec.provider_id].omission_reason == "selection_budget"
    assert reports[small.spec.provider_id].injected
    assert assembled.budget.selected_total <= assembled.budget.input_budget
    source_budget = next(
        item for item in assembled.manifest.sources if item.source_class == "domain_current"
    )
    assert source_budget.token_count <= source_budget.token_limit

    required_rules = (rules[0].model_copy(update={"required": True}),)
    required_assembler = ContextAssembler(
        settings,
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {large.spec.provider_id: StaticContextProviderFactory(large)}
        ),
        context_planner=ContextPlanner(
            required_rules, include_default_rules=False, max_total_tokens=20
        ),
    )
    required_plan = required_assembler.plan_context("trip details", context, now=NOW)
    with pytest.raises(ContextError, match="context_source_unavailable"):
        required_assembler.assemble(
            (), _pending(context, "trip details"), application_context=context,
            context_plan=required_plan, refresh=False,
        )


def test_each_operation_of_one_provider_obeys_its_own_token_allocation():
    provider = MultiOperationFixtureProvider()
    context = _context_for_providers((provider,), "travel")
    rules = (
        _rule(
            application_id="travel", category="current", provider_id=provider.spec.provider_id,
            operation="current", fields=("current_fact",), phrase="trip details",
            max_tokens=12,
        ),
        _rule(
            application_id="travel", category="history", provider_id=provider.spec.provider_id,
            operation="history", fields=("history_fact",), phrase="trip details",
            max_tokens=200,
        ),
    )
    settings = Settings(
        ai_provider="gemini", ai_model="fixture-model", max_context_tokens=4_096,
        max_response_tokens=100, context_safety_margin_tokens=20, summary_trigger_tokens=1_000,
        max_summary_tokens=512,
    )
    assembler = ContextAssembler(
        settings,
        FakeTokenCounter(),
        context_provider_coordinator=ContextProviderCoordinator(
            {provider.spec.provider_id: StaticContextProviderFactory(provider)}
        ),
        context_planner=ContextPlanner(rules, include_default_rules=False, max_total_tokens=212),
    )
    plan = assembler.plan_context("trip details", context, now=NOW)
    assembled = assembler.assemble(
        (), _pending(context, "trip details"), application_context=context,
        context_plan=plan, refresh=False,
    )
    reports = {
        (item.provider_id, item.selected_operation): item for item in assembled.manifest.items
    }

    assert provider.calls == [("current", 12), ("history", 200)]
    assert reports[(provider.spec.provider_id, "current")].omission_reason == "selection_budget"
    assert reports[(provider.spec.provider_id, "history")].injected
    assert assembled.budget.selected_total <= assembled.budget.input_budget


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


@pytest.mark.parametrize(
    ("memory_timeout", "request_timeout", "expected_timeout"),
    [(5, 30, 2), (0.5, 30, 0.5), (5, 0.5, 0.5)],
)
def test_chat_plans_before_memory_retrieval_and_caps_its_timeout(
    memory_timeout, request_timeout, expected_timeout
):
    settings = Settings(
        ai_provider="gemini", ai_model="fixture-model", memory_enabled=True,
        memory_timeout_seconds=memory_timeout, request_timeout_seconds=request_timeout,
    )
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
            self.timeouts = []

        def retrieve(self, owner_id, query, active, *, timeout):
            del owner_id, active
            assert planned_intents[-1] == query
            self.queries.append(query)
            self.timeouts.append(timeout)

    retriever = Retriever()
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    conversation_ids = []
    intents = [
        "What is the capital of Norway?",
        "What did I tell you to remember about travel?",
        "Remember to explain recursion step by step.",
        "I cannot remember how to reset my router.",
        "Do not recall my saved personal information.",
        "Remember that I prefer metric units.",
        "What do you not remember about me?",
        "I don't recall what I told you.",
    ]
    for index in range(len(intents)):
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

    for index, intent in enumerate(intents):
        service.send(conversation_ids[index], intent, request_id=f"intent-{index}")

    assert planned_intents == intents
    assert retriever.queries == ["What did I tell you to remember about travel?"]
    assert len(retriever.timeouts) == 1
    assert 0 < retriever.timeouts[0] <= expected_timeout

    service._application_context = None
    unplanned_conversation = Conversation(
        id=uuid4(), owner_id="local", title="unplanned", created_at=NOW, updated_at=NOW
    )
    conversations.create(unplanned_conversation)
    service.send(
        unplanned_conversation.id,
        "Remember this general instruction for the current answer.",
        request_id="unplanned-memory",
    )
    assert retriever.queries == ["What did I tell you to remember about travel?"]
