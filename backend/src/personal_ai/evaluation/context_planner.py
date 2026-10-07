"""Synthetic Phase 13 planner baseline; no domain or model provider is contacted."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import ConfigDict, create_model

from personal_ai.applications.contracts import (
    ApplicationContextRequest,
    ApplicationDefinition,
    CapabilityRegistration,
)
from personal_ai.auth.scope import RequestScope
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.planner import ContextPlanner, ContextPlanningRule
from personal_ai.context.providers import (
    ContextItem,
    ContextOperationSpec,
    ContextProviderCoordinator,
    ContextProviderSpec,
    ContextSourceReference,
    StaticContextProviderFactory,
)
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import Message, MessageRole, MessageStatus
from personal_ai.settings import Settings

FIXTURE_PATH = Path(__file__).with_name("context-plan-fixtures.json")
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


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


def _run_fixture(fixture: dict) -> dict:
    provider_ids = fixture.get("provider_ids", [fixture.get("provider_id")])
    providers = []
    factories = {}
    capabilities = []
    rules = []
    for index, provider_id in enumerate(provider_ids):
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
        elif not fixture.get("use_default_rules"):
            rules.append(_rule(fixture_rule, provider_id))

    definition = ApplicationDefinition(
        application_id=fixture["application_id"],
        display_name=fixture["application_id"].title(),
        memory_namespace=fixture["application_id"],
        context_provider_ids=tuple(provider_ids),
    )
    scope = RequestScope(
        owner_id="synthetic-owner",
        request_id=f"evaluation-{fixture['name']}",
        application_id=fixture["application_id"],
        workspace_id="synthetic-workspace",
    )
    context = ApplicationContextRequest(
        definition=definition,
        scope=scope,
        context_provider_capabilities=tuple(capabilities),
    )
    planner = ContextPlanner(rules or None, include_default_rules=fixture.get("use_default_rules", False))
    coordinator = ContextProviderCoordinator(factories)
    settings = Settings(
        ai_provider="gemini",
        ai_model="synthetic-eval",
        max_context_tokens=2_048,
        max_response_tokens=100,
        context_safety_margin_tokens=20,
        summary_trigger_tokens=1_000,
        max_summary_tokens=512,
        memory_enabled=True,
    )
    assembler = ContextAssembler(
        settings,
        FakeTokenCounter(),
        context_provider_coordinator=coordinator,
        context_planner=planner,
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
    assembled = assembler.assemble(
        (), user, application_context=context, context_plan=plan, refresh=False
    )
    latency_ms = (time.perf_counter() - started) * 1000

    selected_fields = sorted({field for selection in plan.selections for field in selection.fields})
    expected_fields = set(fixture["expected_fields"])
    excluded_fields = set(fixture["excluded_fields"])
    returned = [item for item in assembled.source_items]
    response_bytes = sum(len(item.model_dump_json().encode("utf-8")) for item in returned)
    reasons = [decision.reason for decision in plan.decisions if decision.disposition == "omitted"]
    expected_reason = fixture.get("expected_omission_reason")
    overfetch_fields = sorted(set(selected_fields) - expected_fields)
    omission_fields = sorted(expected_fields - set(selected_fields))
    answer_needs = set(fixture["answer_support_needs"])
    source_report = assembled.manifest
    provider_calls = [call for provider in providers for call in provider.calls]
    calls_match_plan = (
        all(set(call["fields"]) == expected_fields for call in provider_calls)
        if expected_fields
        else not provider_calls
    )
    passed = (
        set(selected_fields) == expected_fields
        and not (set(selected_fields) & excluded_fields)
        and (expected_reason is None or expected_reason in reasons)
        and calls_match_plan
        and len(assembled.source_items) == len(plan.selections)
        and answer_needs.issubset(set(selected_fields))
        and source_report is not None
        and assembled.budget.selected_total <= assembled.budget.input_budget
    )
    return {
        "fixture": fixture["name"],
        "fixture_version": 1,
        "result": "passed" if passed else "failed",
        "planner_version": plan.planner_version,
        "intent_categories": list(plan.intent_categories),
        "selected_provider_operations": [
            {"provider_id": item.provider_id, "operation": item.operation}
            for item in plan.selections
        ],
        "selected_fields": selected_fields,
        "expected_fields": sorted(expected_fields),
        "excluded_fields": sorted(excluded_fields),
        "unrelated_fields_requested": sorted(set(selected_fields) & excluded_fields),
        "overfetch_fields": overfetch_fields,
        "omitted_expected_fields": omission_fields,
        "answer_support_needs": sorted(answer_needs),
        "answer_support_needs_selected": answer_needs.issubset(set(selected_fields)),
        "omission_reasons": reasons,
        "provider_calls": [call for provider in providers for call in provider.calls],
        "provider_response_bytes": response_bytes,
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


if __name__ == "__main__":
    rows = evaluate()
    print(json.dumps(rows, indent=2))
