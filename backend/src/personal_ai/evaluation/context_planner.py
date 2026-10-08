"""Synthetic Phase 13 planner baseline; no domain or model provider is contacted."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from hashlib import sha256
from math import ceil
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import ConfigDict, create_model

from personal_ai.applications.contracts import (
    ApplicationContextRequest,
    ApplicationDefinition,
    CapabilityRegistration,
)
from personal_ai.applications.registry import default_application_registry
from personal_ai.auth.scope import RequestScope, bind_request_scope, reset_request_scope
from personal_ai.context.adapters import (
    BuiltInContextPermissionRevalidator,
    MemoryContextProviderFactory,
)
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.contracts import TokenCount
from personal_ai.context.planner import ContextPlanner, ContextPlanningRule
from personal_ai.context.profile import (
    GlobalProfileContextProviderFactory,
    GlobalProfileFieldUpdate,
    GlobalProfileUpdate,
    InMemoryGlobalProfileRepository,
)
from personal_ai.context.providers import (
    ContextItem,
    ContextOperationSpec,
    ContextProviderCoordinator,
    ContextProviderSpec,
    ContextSourceReference,
    StaticContextProviderFactory,
)
from personal_ai.entities import Message, MessageRole, MessageStatus
from personal_ai.memory.contracts import Memory, RetrievalResult, ScoredMemory, normalize
from personal_ai.settings import Settings

FIXTURE_PATH = Path(__file__).with_name("context-plan-fixtures.json")
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


class _EnvelopeTokenCounter:
    """Conservative offline estimate that counts serialized source envelopes."""

    counter_version = "phase13-envelope-byte-estimate-v1"

    def count(self, messages):
        tokens = 10 + sum(ceil(len(message.content.encode("utf-8")) / 4) + 2 for message in messages)
        return TokenCount(tokens, "estimated")


class _FixtureProvider:
    def __init__(self, provider_id: str, source_class: str, operation: ContextOperationSpec):
        self.spec = ContextProviderSpec(
            provider_id=provider_id,
            source_class=source_class,
            source_version="phase13-synthetic-v1",
            operations=(operation,),
            maximum_items_per_call=operation.maximum_results,
        )
        self.payload_type = create_model(
            f"{provider_id.replace('.', '_').title()}Payload",
            __config__=ConfigDict(extra="forbid", frozen=True),
            **{field: (str | None, None) for field in operation.allowed_fields},
        )
        self.calls: list[dict] = []

    def validate_selection(self, selection, inputs):
        del inputs
        if selection.provider_id != self.spec.provider_id:
            raise ValueError("fixture_provider_identity_mismatch")

    def fetch(self, selection, scope, *, deadline):
        del deadline
        self.calls.append(selection.model_dump(mode="json", exclude_none=True))
        payload = self.payload_type(
            **{field: f"synthetic {field}" for field in selection.fields}
        )
        return (
            ContextItem(
                source_class=self.spec.source_class,
                provider_id=self.spec.provider_id,
                source_id="synthetic-record-set",
                source_version="fixture-record-v1",
                item_id="fixture-item-1",
                owner_id=scope.owner_id,
                application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                authority="authoritative",
                observed_at=NOW,
                sensitivity="sensitive",
                source_refs=(ContextSourceReference(kind="record", reference_id="fixture-item-1"),),
                payload=payload,
            ),
        )


class _RecordingProvider:
    def __init__(self, provider, calls):
        self.provider = provider
        self.spec = provider.spec
        self.calls = calls

    def validate_selection(self, selection, inputs):
        return self.provider.validate_selection(selection, inputs)

    def fetch(self, selection, scope, *, deadline):
        self.calls.append(_selection_summary(selection))
        return self.provider.fetch(selection, scope, deadline=deadline)


class _RecordingFactory:
    def __init__(self, factory):
        self.factory = factory
        self.spec = factory.spec
        self.calls = []

    def create(self, inputs):
        return _RecordingProvider(self.factory.create(inputs), self.calls)


def _builtin_memory(scope) -> Memory:
    source_message_id = uuid5(NAMESPACE_URL, "phase13-eval-memory-source-message")
    content = "I prefer an aisle seat when I travel."
    return Memory(
        id=uuid5(NAMESPACE_URL, "phase13-eval-memory"),
        owner_id=scope.owner_id,
        memory_type="preference",
        content=content,
        confidence=0.9,
        source_message_ids=(source_message_id,),
        rationale_code="user_preference",
        normalized_content=normalize(content),
        source_conversation_id=uuid5(NAMESPACE_URL, "phase13-eval-memory-conversation"),
        source_turn_id=uuid5(NAMESPACE_URL, "phase13-eval-memory-turn"),
        source_fingerprint=sha256(str(source_message_id).encode()).hexdigest(),
        observed_at=NOW,
        effective_at=NOW,
        created_at=NOW,
        embedding=(1.0, 0.0),
        embedding_model="phase13-offline-fixture",
        embedding_dimensions=2,
        application_id=scope.application_id,
        workspace_id=scope.workspace_id,
        scope_version=2,
    )


def _builtin_profile_repository(scope, shared_fields) -> InMemoryGlobalProfileRepository:
    values = {
        "preferred_units": "metric",
        "locale": "en-US",
        "response_style": "concise",
        "answer_length": "short",
    }
    repository = InMemoryGlobalProfileRepository(clock=lambda: NOW)
    repository.update(
        scope.owner_id,
        GlobalProfileUpdate(
            fields=tuple(
                GlobalProfileFieldUpdate(
                    field=field,
                    value=values[field],
                    shared_with_applications=("personal_ai",) if field in shared_fields else (),
                )
                for field in values
            )
        ),
    )
    return repository


def _rule(fixture: dict, provider_id: str, category: str | None = None):
    return ContextPlanningRule(
        rule_id=f"fixture.{fixture['name']}.{provider_id.replace('.', '-')}:v1",
        category=category or fixture["category"],
        phrases=(fixture["phrase"],),
        provider_id=provider_id,
        operation=fixture.get("operation", "current"),
        fields=tuple(fixture.get("rule_fields", ())),
        max_results=3,
        max_bytes=4_096,
        max_tokens=fixture.get("max_tokens", 96),
        timeout_seconds=1,
        window_seconds=fixture.get("window_seconds"),
        exclusive_group="domain" if fixture.get("ambiguous") else None,
        application_ids=(fixture["application_id"],),
        explanation=f"Synthetic baseline for {fixture['name']}.",
    )


def _selection_summary(selection) -> dict:
    window_seconds = None
    if selection.window_start is not None:
        window_seconds = int((selection.window_end - selection.window_start).total_seconds())
    return {
        "provider_id": selection.provider_id,
        "operation": selection.operation,
        "fields": sorted(selection.fields),
        "max_results": selection.max_results,
        "max_bytes": selection.max_bytes,
        "max_tokens": selection.max_tokens,
        "timeout_seconds": selection.timeout_seconds,
        "window_seconds": window_seconds,
    }


def _call_summary(call: dict) -> dict:
    window_seconds = None
    if call.get("window_start") is not None:
        start = datetime.fromisoformat(call["window_start"])
        end = datetime.fromisoformat(call["window_end"])
        window_seconds = int((end - start).total_seconds())
    return {
        "provider_id": call["provider_id"],
        "operation": call["operation"],
        "fields": sorted(call.get("fields", ())),
        "max_results": call["max_results"],
        "max_bytes": call["max_bytes"],
        "max_tokens": call["max_tokens"],
        "timeout_seconds": call["timeout_seconds"],
        "window_seconds": window_seconds,
    }


def _item_fields(item) -> set[str]:
    payload = item.payload.model_dump(mode="json", exclude_none=True)
    if item.provider_id == "global_profile":
        return {payload["field"]} if payload.get("value") else set()
    if item.provider_id == "ai_memory":
        return {field for field in ("content", "memory_type", "effective_at") if payload.get(field)}
    return set(payload) - {"record_kind"}


def _run_fixture(fixture: dict, *, counter=None) -> dict:
    provider_ids = fixture.get("provider_ids", [fixture.get("provider_id")])
    scope = RequestScope(
        owner_id="synthetic-owner",
        request_id=f"evaluation-{fixture['name']}",
        application_id=fixture["application_id"],
        workspace_id="synthetic-workspace",
    )
    providers = []
    factories = {}
    capabilities = []
    rules = []
    retrieval = None
    profile_repository = None
    settings = Settings(
        ai_provider="gemini",
        ai_model="synthetic-eval",
        max_context_tokens=2_048,
        max_response_tokens=100,
        context_safety_margin_tokens=20,
        summary_trigger_tokens=1_000,
        max_summary_tokens=512,
        memory_enabled=True,
        memory_embedding_model="phase13-offline-fixture",
        memory_embedding_dimensions=2,
        memory_max_context_tokens=512,
        context_profile_max_tokens=512,
    )

    for provider_id in provider_ids:
        if fixture.get("use_default_rules"):
            if provider_id == "ai_memory":
                recording_factory = _RecordingFactory(MemoryContextProviderFactory(settings))
                factories[provider_id] = recording_factory
                providers.append(recording_factory)
                retrieval = RetrievalResult(
                    selected=(ScoredMemory(_builtin_memory(scope), 0.95),)
                )
                capabilities.append(
                    CapabilityRegistration(
                        capability_id=provider_id,
                        kind="context_provider",
                        available=True,
                        feature_gate="memory_enabled",
                    )
                )
            elif provider_id == "global_profile":
                shared = fixture.get("shared_profile_fields", fixture["expected_fields"])
                profile_repository = _builtin_profile_repository(scope, set(shared))
                recording_factory = _RecordingFactory(
                    GlobalProfileContextProviderFactory(profile_repository)
                )
                factories[provider_id] = recording_factory
                providers.append(recording_factory)
                capabilities.append(
                    CapabilityRegistration(
                        capability_id=provider_id,
                        kind="context_provider",
                        available=True,
                    )
                )
            else:
                raise ValueError("phase13_builtin_fixture_provider_unsupported")
            continue

        if fixture.get("ambiguous"):
            source_class = "domain_history" if "health" in provider_id else "domain_current"
            fields = ("medication_name",) if "health" in provider_id else ("city",)
            operation = "history" if "health" in provider_id else "current"
            category = "health" if "health" in provider_id else "travel"
            fixture_rule = {
                **fixture,
                "category": category,
                "operation": operation,
                "phrase": "travel health records",
                "rule_fields": fields,
            }
        else:
            source_class = fixture["source_class"]
            fields = tuple(fixture["allowed_fields"])
            operation = fixture["operation"]
            category = fixture.get("category")
            fixture_rule = fixture
        operation_spec = ContextOperationSpec(
            operation=operation,
            allowed_fields=fields,
            requires_time_window=(operation == "history"),
            maximum_window_seconds=fixture.get("max_window_seconds", 365 * 86_400),
            maximum_results=8,
            maximum_bytes=8_192,
            maximum_timeout_seconds=2,
        )
        if not fixture.get("provider_unavailable"):
            provider = _FixtureProvider(provider_id, source_class, operation_spec)
            providers.append(provider)
            factories[provider_id] = StaticContextProviderFactory(provider)
        capabilities.append(
            CapabilityRegistration(
                capability_id=provider_id,
                kind="context_provider",
                available=True,
            )
        )
        if fixture.get("ambiguous"):
            rules.append(_rule(fixture_rule, provider_id, category))
        else:
            rules.append(_rule(fixture_rule, provider_id))

    definition = ApplicationDefinition(
        application_id=fixture["application_id"],
        display_name=fixture["application_id"].title(),
        memory_namespace=fixture["application_id"],
        context_provider_ids=tuple(provider_ids),
        context_policy=default_application_registry().get(
            fixture["application_id"]
        ).context_policy,
    )
    context = ApplicationContextRequest(
        definition=definition,
        scope=scope,
        context_provider_capabilities=tuple(capabilities),
    )
    planner = ContextPlanner(
        rules or None, include_default_rules=fixture.get("use_default_rules", False)
    )
    coordinator = ContextProviderCoordinator(factories, feature_flags={"memory_enabled": True})
    assembler = ContextAssembler(
        settings,
        counter or _EnvelopeTokenCounter(),
        context_provider_coordinator=coordinator,
        context_planner=planner,
        permission_revalidator=BuiltInContextPermissionRevalidator(settings, profile_repository),
    )
    user = Message(
        id=uuid5(NAMESPACE_URL, f"{fixture['name']}:pending"),
        conversation_id=uuid5(NAMESPACE_URL, f"{fixture['name']}:conversation"),
        owner_id=scope.owner_id,
        application_id=scope.application_id,
        workspace_id=scope.workspace_id,
        scope_version=2,
        role=MessageRole.USER,
        content=fixture["intent"],
        status=MessageStatus.COMPLETED,
        created_at=NOW,
    )

    started = time.perf_counter()
    plan = assembler.plan_context(fixture["intent"], context, now=NOW)
    scope_token = bind_request_scope(scope)
    try:
        assembled = assembler.assemble(
            (), user, retrieval=retrieval, application_context=context,
            context_plan=plan, refresh=False,
        )
    finally:
        reset_request_scope(scope_token)
    latency_ms = (time.perf_counter() - started) * 1000

    selected_fields = sorted({field for selection in plan.selections for field in selection.fields})
    expected_fields = set(fixture["expected_fields"])
    excluded_fields = set(fixture["excluded_fields"])
    returned = list(assembled.source_items)
    response_bytes = sum(len(item.model_dump_json().encode("utf-8")) for item in returned)
    reasons = [decision.reason for decision in plan.decisions if decision.disposition == "omitted"]
    expected_reason = fixture.get("expected_omission_reason")
    planned_support = set().union(*(set(item.fields) for item in plan.selections)) if plan.selections else set()
    retrieved_support = set().union(*(_item_fields(item) for item in returned)) if returned else set()
    injected_keys = {
        (report.provider_id, report.item_id)
        for report in assembled.manifest.items
        if report.injected
    }
    injected_items = [
        item for item in returned if (item.provider_id, item.item_id) in injected_keys
    ]
    injected_support = set().union(*(_item_fields(item) for item in injected_items)) if injected_items else set()
    answer_needs = set(fixture["answer_support_needs"])
    expected_retrieved = set(fixture.get("expected_retrieved_fields", expected_fields))
    expected_injected = set(fixture.get("expected_injected_fields", expected_fields))
    actual_selections = sorted(
        (_selection_summary(item) for item in plan.selections),
        key=lambda item: (item["provider_id"], item["operation"]),
    )
    expected_selections = sorted(
        fixture.get("expected_selections", []),
        key=lambda item: (item["provider_id"], item["operation"]),
    )
    provider_calls = [call for provider in providers for call in provider.calls]
    normalized_calls = sorted(
        (_call_summary(item) for item in provider_calls),
        key=lambda item: (item["provider_id"], item["operation"]),
    )
    calls_match_plan = (
        len(normalized_calls) == len(actual_selections)
        and normalized_calls == actual_selections
    )
    metadata_valid = all(item.source_refs for item in returned) and all(
        item.permission_dependencies
        for item in returned
        if item.provider_id in {"ai_memory", "global_profile"}
    )
    expected_authority = fixture.get("expected_authority")
    authority_valid = expected_authority is None or all(
        item.authority == expected_authority for item in returned
    )
    source_report = assembled.manifest
    passed = (
        set(selected_fields) == expected_fields
        and not (set(selected_fields) & excluded_fields)
        and (expected_reason is None or expected_reason in reasons)
        and actual_selections == expected_selections
        and calls_match_plan
        and retrieved_support == expected_retrieved
        and injected_support == expected_injected
        and answer_needs.issubset(injected_support)
        and metadata_valid
        and authority_valid
        and source_report is not None
        and assembled.budget.selected_total <= assembled.budget.input_budget
    )
    return {
        "fixture": fixture["name"],
        "fixture_version": 2,
        "result": "passed" if passed else "failed",
        "planner_version": plan.planner_version,
        "intent_categories": list(plan.intent_categories),
        "selected_provider_operations": [
            {"provider_id": item.provider_id, "operation": item.operation}
            for item in plan.selections
        ],
        "planned_selections": actual_selections,
        "expected_selections": expected_selections,
        "selected_fields": selected_fields,
        "retrieved_support_fields": sorted(retrieved_support),
        "expected_retrieved_fields": sorted(expected_retrieved),
        "injected_support_fields": sorted(injected_support),
        "expected_injected_fields": sorted(expected_injected),
        "expected_fields": sorted(expected_fields),
        "excluded_fields": sorted(excluded_fields),
        "unrelated_fields_requested": sorted(set(selected_fields) & excluded_fields),
        "overfetch_fields": sorted(set(selected_fields) - expected_fields),
        "omitted_expected_fields": sorted(expected_fields - set(selected_fields)),
        "answer_support_needs": sorted(answer_needs),
        "answer_support_needs_planned": answer_needs.issubset(planned_support),
        "answer_support_needs_injected": answer_needs.issubset(injected_support),
        "omission_reasons": reasons,
        "provider_calls": provider_calls,
        "provider_response_bytes": response_bytes,
        "source_item_authorities": sorted({item.authority for item in returned}),
        "source_reference_counts": [len(item.source_refs) for item in returned],
        "permission_dependency_counts": [len(item.permission_dependencies) for item in returned],
        "estimated_input_tokens": assembled.budget.selected_total,
        "planned_source_token_budgets": [
            {"source_class": source, "tokens": tokens}
            for source, tokens in plan.source_token_budgets
        ],
        "latency_ms": round(latency_ms, 3),
        "input_budget_tokens": assembled.budget.input_budget,
    }


def evaluate() -> list[dict]:
    fixtures = json.loads(FIXTURE_PATH.read_text())["fixtures"]
    return [_run_fixture(fixture) for fixture in fixtures]


def main() -> int:
    rows = evaluate()
    print(json.dumps(rows, indent=2))
    return 1 if any(row["result"] != "passed" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
