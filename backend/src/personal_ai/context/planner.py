"""Versioned deterministic rules for selecting bounded context sources.

The planner describes a narrow retrieval plan. It does not authorize access;
the provider coordinator rechecks application scope, registered capabilities,
operation fields, deadlines, and result bounds before any provider runs.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_ai.applications.contracts import ApplicationContextRequest
from personal_ai.auth.scope import ApplicationScope, RequestScope
from personal_ai.context.providers import (
    ContextEntityReference,
    ContextOperation,
    ContextOperationSpec,
    ContextPreparationError,
    ContextProviderSpec,
    ContextSelection,
    ContextSourceClass,
)


class ContextPlanningCapability(BaseModel):
    """Provider implementation state visible to planning, never an authorization grant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["available", "not_registered", "unavailable", "disabled"]
    spec: ContextProviderSpec | None = None

    @model_validator(mode="after")
    def spec_matches_status(self) -> ContextPlanningCapability:
        if (self.status == "available") != (self.spec is not None):
            raise ValueError("context_planning_capability_spec_mismatch")
        return self


class ContextPlanningRule(BaseModel):
    """One explainable, bounded rule matching phrases in a user request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,96}:v[1-9][0-9]*$", max_length=120)
    category: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$", max_length=64)
    phrases: tuple[str, ...] = Field(min_length=1, max_length=24)
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,80}$", max_length=81)
    operation: ContextOperation
    fields: tuple[str, ...] = Field(default=(), max_length=32)
    max_results: int = Field(default=5, ge=1, le=50)
    max_bytes: int = Field(default=16_384, ge=1, le=65_536)
    max_tokens: int = Field(default=256, ge=1, le=16_384)
    timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    window_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    use_candidate_entities: bool = False
    require_candidate_entities: bool = False
    required: bool = False
    priority: int = Field(default=100, ge=0, le=10_000)
    exclusive_group: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    application_ids: tuple[str, ...] = Field(default=(), max_length=16)
    explanation: str = Field(min_length=1, max_length=180)

    @field_validator("phrases")
    @classmethod
    def normalize_phrases(cls, phrases: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(" ".join(item.casefold().split()) for item in phrases)
        if any(not item or len(item) > 100 for item in normalized):
            raise ValueError("context_planning_phrase_invalid")
        if len(normalized) != len(set(normalized)):
            raise ValueError("context_planning_phrases_must_be_unique")
        return normalized

    @field_validator("fields")
    @classmethod
    def validate_rule_fields(cls, fields: tuple[str, ...]) -> tuple[str, ...]:
        if len(fields) != len(set(fields)) or any(
            not re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", item) for item in fields
        ):
            raise ValueError("context_planning_fields_invalid")
        return fields

    @model_validator(mode="after")
    def entity_settings_are_consistent(self) -> ContextPlanningRule:
        if self.require_candidate_entities and not self.use_candidate_entities:
            raise ValueError("context_planning_entity_requirement_invalid")
        if len(self.application_ids) != len(set(self.application_ids)):
            raise ValueError("context_planning_application_ids_must_be_unique")
        return self


class ContextPlanDecision(BaseModel):
    """Safe, content-free reason explaining an included or omitted rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str | None = None
    category: str
    provider_id: str | None = None
    operation: ContextOperation | None = None
    source_class: ContextSourceClass | None = None
    fields: tuple[str, ...] = ()
    excluded_fields: tuple[str, ...] = ()
    disposition: Literal["selected", "omitted"]
    reason: str = Field(min_length=1, max_length=180)


class ContextPlan(BaseModel):
    """Deterministic retrieval choices for one request and application scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["context-plan-v1"] = "context-plan-v1"
    planner_version: str = Field(min_length=1, max_length=100)
    application_id: str
    workspace_id: str | None = None
    scope_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    intent_categories: tuple[str, ...] = ()
    selections: tuple[ContextSelection, ...] = Field(default=(), max_length=16)
    source_token_budgets: tuple[tuple[ContextSourceClass, int], ...] = ()
    decisions: tuple[ContextPlanDecision, ...] = Field(default=(), max_length=64)

    @classmethod
    def fingerprint_scope(cls, scope: RequestScope) -> str:
        identity = "\0".join(
            (
                scope.owner_id,
                scope.application_id,
                scope.workspace_id or "",
                scope.request_id,
            )
        )
        return sha256(identity.encode("utf-8")).hexdigest()

    @property
    def explanation_codes(self) -> tuple[str, ...]:
        return tuple(
            f"{item.rule_id or 'planner'}:{item.disposition}:{item.reason}"
            for item in self.decisions
        )


@dataclass(frozen=True, slots=True)
class _MatchedRule:
    rule: ContextPlanningRule
    spec: ContextProviderSpec
    operation_spec: ContextOperationSpec
    fields: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    entity_refs: tuple[ContextEntityReference, ...]
    window_start: datetime | None
    window_end: datetime | None


DEFAULT_CONTEXT_PLANNING_RULES = (
    ContextPlanningRule(
        rule_id="profile.preferred-units:v1",
        category="profile_units",
        phrases=("what units do i prefer", "which units do i prefer", "my preferred units"),
        provider_id="global_profile",
        operation="profile",
        fields=("preferred_units",),
        max_results=1,
        max_bytes=2_048,
        max_tokens=256,
        timeout_seconds=1,
        priority=5,
        explanation="The request asks for the explicitly shared preferred-units field.",
    ),
    ContextPlanningRule(
        rule_id="profile.locale:v1",
        category="profile_locale",
        phrases=("what language do i prefer", "my preferred language", "what locale did i choose"),
        provider_id="global_profile",
        operation="profile",
        fields=("locale",),
        max_results=1,
        max_bytes=2_048,
        max_tokens=256,
        timeout_seconds=1,
        priority=5,
        explanation="The request asks for the explicitly shared locale field.",
    ),
    ContextPlanningRule(
        rule_id="profile.response-style:v1",
        category="profile_response_style",
        phrases=(
            "what response style do i prefer",
            "my preferred response style",
            "how do i like you to respond",
        ),
        provider_id="global_profile",
        operation="profile",
        fields=("response_style",),
        max_results=1,
        max_bytes=2_048,
        max_tokens=256,
        timeout_seconds=1,
        priority=5,
        explanation="The request asks for the explicitly shared response-style field.",
    ),
    ContextPlanningRule(
        rule_id="profile.answer-length:v1",
        category="profile_answer_length",
        phrases=(
            "what answer length do i prefer",
            "my preferred answer length",
            "do i prefer short answers",
        ),
        provider_id="global_profile",
        operation="profile",
        fields=("answer_length",),
        max_results=1,
        max_bytes=2_048,
        max_tokens=256,
        timeout_seconds=1,
        priority=5,
        explanation="The request asks for the explicitly shared answer-length field.",
    ),
    ContextPlanningRule(
        rule_id="memory.personal-recall:v1",
        category="personal_recall",
        phrases=(
            "what did i tell you",
            "what have i told you",
            "what did i say",
            "what have i said",
            "what do you remember about me",
            "what do you know about me",
            "what preference did i mention",
        ),
        provider_id="ai_memory",
        operation="search",
        fields=("content", "memory_type", "effective_at"),
        max_results=5,
        max_bytes=16_384,
        max_tokens=512,
        timeout_seconds=2,
        priority=10,
        explanation="The request explicitly asks to recall previously saved personal context.",
    ),
)


class ContextPlanner:
    """Apply versioned rules to bounded intent and currently registered providers."""

    VERSION = "deterministic-context-planner-v1"
    MAX_INTENT_CHARS = 4_096
    MAX_CANDIDATE_ENTITIES = 16
    MAX_SELECTIONS = 16

    def __init__(
        self,
        rules: Sequence[ContextPlanningRule] | None = None,
        *,
        include_default_rules: bool = True,
        max_total_tokens: int = 1_200,
        clock=None,
    ) -> None:
        if max_total_tokens < 1:
            raise ValueError("context_planner_token_budget_invalid")
        configured = tuple(DEFAULT_CONTEXT_PLANNING_RULES if include_default_rules else ())
        configured += tuple(rules or ())
        if len({rule.rule_id for rule in configured}) != len(configured):
            raise ValueError("context_planning_rule_id_duplicate")
        self.rules = tuple(sorted(configured, key=lambda rule: (rule.priority, rule.rule_id)))
        self.max_total_tokens = max_total_tokens
        self.clock = clock or (lambda: datetime.now(UTC))

    def plan(
        self,
        intent: str,
        context: ApplicationContextRequest,
        capabilities: Mapping[str, ContextPlanningCapability],
        *,
        input_token_budget: int,
        candidate_entities: Sequence[ContextEntityReference] = (),
        now: datetime | None = None,
    ) -> ContextPlan:
        if input_token_budget < 1:
            raise ValueError("context_planner_input_budget_invalid")
        bounded_intent = " ".join(intent[: self.MAX_INTENT_CHARS].casefold().split())
        request_time = now or self.clock()
        if request_time.tzinfo is None or request_time.utcoffset() is None:
            raise ValueError("context_planner_clock_timezone_required")
        request_time = request_time.astimezone(UTC)
        scope = context.scope
        eligible_entities = tuple(
            reference
            for reference in candidate_entities[: self.MAX_CANDIDATE_ENTITIES]
            if reference.application_id == scope.application_id
            and reference.workspace_id == scope.workspace_id
        )

        matched: list[ContextPlanningRule] = []
        decisions: list[ContextPlanDecision] = []
        for rule in self.rules:
            if rule.application_ids and scope.application_id not in rule.application_ids:
                continue
            if not any(self._contains_phrase(bounded_intent, phrase) for phrase in rule.phrases):
                continue
            matched.append(rule)

        ambiguous_groups: set[str] = set()
        categories_by_group: dict[str, set[str]] = defaultdict(set)
        for rule in matched:
            if rule.exclusive_group:
                categories_by_group[rule.exclusive_group].add(rule.category)
        ambiguous_groups.update(
            group for group, categories in categories_by_group.items() if len(categories) > 1
        )

        candidates: dict[tuple[str, ContextOperation], list[_MatchedRule]] = defaultdict(list)
        for rule in matched:
            if rule.exclusive_group in ambiguous_groups:
                if rule.required:
                    raise ContextPreparationError("required_context_source_ambiguous")
                decisions.append(
                    ContextPlanDecision(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        provider_id=rule.provider_id,
                        operation=rule.operation,
                        fields=(),
                        disposition="omitted",
                        reason="ambiguous_intent",
                    )
                )
                continue

            capability = capabilities.get(rule.provider_id)
            if capability is None or capability.status == "not_registered":
                if rule.required:
                    raise ContextPreparationError("required_context_source_unavailable")
                decisions.append(self._omitted(rule, "provider_not_registered"))
                continue
            if capability.status != "available" or capability.spec is None:
                if rule.required:
                    raise ContextPreparationError("required_context_source_unavailable")
                reason = (
                    "provider_feature_disabled"
                    if capability.status == "disabled"
                    else "provider_unavailable"
                )
                decisions.append(self._omitted(rule, reason))
                continue
            spec = capability.spec
            operation_spec = spec.operation(rule.operation)
            if operation_spec is None:
                if rule.required:
                    raise ContextPreparationError("required_context_operation_unsupported")
                decisions.append(self._omitted(rule, "operation_unsupported", spec.source_class))
                continue
            allowed_fields = set(operation_spec.allowed_fields)
            if operation_spec.dynamic_fields:
                fields = rule.fields
                excluded_fields = ()
            else:
                fields = tuple(field for field in rule.fields if field in allowed_fields)
                excluded_fields = tuple(field for field in rule.fields if field not in allowed_fields)
            if operation_spec.fields_required and not fields:
                if rule.required:
                    raise ContextPreparationError("required_context_fields_unavailable")
                decisions.append(
                    ContextPlanDecision(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        provider_id=rule.provider_id,
                        operation=rule.operation,
                        source_class=spec.source_class,
                        excluded_fields=excluded_fields,
                        disposition="omitted",
                        reason="no_supported_fields",
                    )
                )
                continue
            if rule.required and excluded_fields:
                raise ContextPreparationError("required_context_fields_unavailable")
            if operation_spec.dynamic_fields and not fields:
                if rule.required:
                    raise ContextPreparationError("required_context_fields_unavailable")
                decisions.append(self._omitted(rule, "dynamic_fields_required", spec.source_class))
                continue
            if rule.window_seconds is not None and operation_spec.maximum_window_seconds < 1:
                if rule.required:
                    raise ContextPreparationError("required_context_window_unsupported")
                decisions.append(self._omitted(rule, "time_window_unsupported", spec.source_class))
                continue
            if operation_spec.requires_time_window and rule.window_seconds is None:
                if rule.required:
                    raise ContextPreparationError("required_context_window_unconfigured")
                decisions.append(self._omitted(rule, "time_window_unconfigured", spec.source_class))
                continue
            if rule.use_candidate_entities and operation_spec.accepts_entity_refs is False:
                if rule.required:
                    raise ContextPreparationError("required_context_entity_scope_unsupported")
                decisions.append(self._omitted(rule, "entity_scope_unsupported", spec.source_class))
                continue
            if rule.require_candidate_entities and not eligible_entities:
                if rule.required:
                    raise ContextPreparationError("required_context_entity_scope_unavailable")
                decisions.append(self._omitted(rule, "entity_reference_required", spec.source_class))
                continue
            if rule.required and operation_spec.maximum_results < 1:
                decisions.append(self._omitted(rule, "required_source_unbounded", spec.source_class))
                continue

            entity_refs = eligible_entities if rule.use_candidate_entities else ()
            start = end = None
            if rule.window_seconds is not None:
                duration = min(rule.window_seconds, operation_spec.maximum_window_seconds)
                start = request_time - timedelta(seconds=duration)
                end = request_time
            candidates[(rule.provider_id, rule.operation)].append(
                _MatchedRule(
                    rule,
                    spec,
                    operation_spec,
                    fields,
                    excluded_fields,
                    entity_refs,
                    start,
                    end,
                )
            )

        selections: list[ContextSelection] = []
        source_budgets: dict[ContextSourceClass, int] = defaultdict(int)
        total_budget = min(self.max_total_tokens, max(1, input_token_budget // 3))
        allocated = 0
        ordered_groups = sorted(
            candidates.items(),
            key=lambda row: (
                min(
                    (item.rule.priority for item in row[1] if item.rule.required),
                    default=10_001,
                ),
                row[0][0],
                row[0][1],
            ),
        )
        selected_by_operation: dict[tuple[str, ContextOperation], dict[str, object]] = {}

        def merged_fields(rows: Sequence[_MatchedRule]) -> tuple[str, ...]:
            return tuple(dict.fromkeys(field for row in rows for field in row.fields))

        def merged_result_limit(rows: Sequence[_MatchedRule]) -> int:
            operation_spec = rows[0].operation_spec
            if operation_spec.results_per_field:
                return len(merged_fields(rows))
            return min(
                max(row.rule.max_results for row in rows),
                operation_spec.maximum_results,
                rows[0].spec.maximum_items_per_call,
            )

        def bounds_reason(rows: Sequence[_MatchedRule]) -> str | None:
            operation_spec = rows[0].operation_spec
            result_limit = merged_result_limit(rows)
            if result_limit > min(
                operation_spec.maximum_results,
                rows[0].spec.maximum_items_per_call,
            ):
                return "selection_result_limit_exceeded"
            if len(merged_fields(rows)) > 32:
                return "selection_field_limit_exceeded"
            ends = [row.window_end for row in rows if row.window_end is not None]
            starts = [row.window_start for row in rows if row.window_start is not None]
            if ends and starts and max(starts) >= min(ends):
                return "incompatible_time_windows"
            return None

        # Required selections reserve their complete requested allocations
        # before any optional rule can spend from the request budget.
        for key, rows in ordered_groups:
            required_rows = sorted(
                (row for row in rows if row.rule.required),
                key=lambda item: (item.rule.priority, item.rule.rule_id),
            )
            if not required_rows:
                continue
            if len(selected_by_operation) >= self.MAX_SELECTIONS:
                raise ContextPreparationError("required_context_plan_budget_exceeded")
            if bounds_reason(required_rows):
                raise ContextPreparationError("required_context_source_bounds_exceeded")
            requested_tokens = sum(row.rule.max_tokens for row in required_rows)
            if requested_tokens > total_budget - allocated:
                raise ContextPreparationError("required_context_plan_budget_exceeded")
            selected_by_operation[key] = {
                "rows": required_rows,
                "tokens": requested_tokens,
            }
            allocated += requested_tokens

        optional_rows = sorted(
            (
                (key, row)
                for key, rows in candidates.items()
                for row in rows
                if not row.rule.required
            ),
            key=lambda item: (item[1].rule.priority, item[0][0], item[0][1], item[1].rule.rule_id),
        )
        for key, row in optional_rows:
            current = selected_by_operation.get(key)
            current_rows = list(current["rows"]) if current else []
            trial_rows = [*current_rows, row]
            source_class = row.spec.source_class
            reason = bounds_reason(trial_rows)
            if current is None and len(selected_by_operation) >= self.MAX_SELECTIONS:
                reason = "selection_limit_exceeded"
            if total_budget - allocated < row.rule.max_tokens:
                reason = reason or "plan_token_budget_exhausted"
            if reason:
                decisions.append(self._omitted(row.rule, reason, source_class))
                continue
            if current is None:
                current = {"rows": [], "tokens": 0}
                selected_by_operation[key] = current
            current["rows"] = trial_rows
            current["tokens"] = int(current["tokens"]) + row.rule.max_tokens
            allocated += row.rule.max_tokens

        for (provider_id, operation), state in sorted(
            selected_by_operation.items(),
            key=lambda item: (
                min(row.rule.priority for row in item[1]["rows"]),
                item[0][0],
                item[0][1],
            ),
        ):
            rows = sorted(state["rows"], key=lambda item: (item.rule.priority, item.rule.rule_id))
            source_class = rows[0].spec.source_class
            operation_spec = rows[0].operation_spec
            requested_fields = merged_fields(rows)
            excluded_fields = tuple(dict.fromkeys(
                field for row in rows for field in row.excluded_fields
            ))
            row_entities = tuple(dict.fromkeys(
                entity for row in rows for entity in row.entity_refs
            ))[: self.MAX_CANDIDATE_ENTITIES]
            ends = [row.window_end for row in rows if row.window_end is not None]
            starts = [row.window_start for row in rows if row.window_start is not None]
            window_end = min(ends) if ends else None
            window_start = max(starts) if starts else None
            if (
                window_start is not None
                and window_end is not None
                and window_start >= window_end
            ):
                raise ContextPreparationError("context_planner_window_merge_invalid")
            if (
                window_start is not None
                and window_end is not None
                and (window_end - window_start).total_seconds()
                > operation_spec.maximum_window_seconds
            ):
                window_start = window_end - timedelta(
                    seconds=operation_spec.maximum_window_seconds
                )
            selection = ContextSelection(
                provider_id=provider_id,
                operation=operation,
                fields=requested_fields,
                entity_refs=row_entities,
                window_start=window_start,
                window_end=window_end,
                max_results=merged_result_limit(rows),
                max_bytes=min(
                    sum(row.rule.max_bytes for row in rows),
                    operation_spec.maximum_bytes,
                ),
                max_tokens=int(state["tokens"]),
                timeout_seconds=min(
                    *(row.rule.timeout_seconds for row in rows),
                    *(row.operation_spec.maximum_timeout_seconds for row in rows),
                ),
                required=any(row.rule.required for row in rows),
                target_scope=ApplicationScope(
                    application_id=scope.application_id,
                    workspace_id=scope.workspace_id,
                ),
            )
            selections.append(selection)
            source_budgets[source_class] += selection.max_tokens or 0
            for row in rows:
                decisions.append(
                    ContextPlanDecision(
                        rule_id=row.rule.rule_id,
                        category=row.rule.category,
                        provider_id=provider_id,
                        operation=operation,
                        source_class=source_class,
                        fields=row.fields,
                        excluded_fields=row.excluded_fields,
                        disposition="selected",
                        reason=(
                            "selected_with_unsupported_fields_excluded"
                            if row.excluded_fields
                            else row.rule.explanation
                        ),
                    )
                )

        if not matched:
            decisions.append(
                ContextPlanDecision(
                    category="unmatched",
                    disposition="omitted",
                    reason="no_configured_rule_matched_bounded_intent",
                )
            )
        decisions.sort(
            key=lambda item: (
                item.rule_id or "~",
                item.provider_id or "~",
                item.operation or "~",
                item.disposition,
            )
        )
        return ContextPlan(
            planner_version=self.VERSION,
            application_id=scope.application_id,
            workspace_id=scope.workspace_id,
            scope_fingerprint=ContextPlan.fingerprint_scope(scope),
            intent_categories=tuple(sorted({item.category for item in matched})),
            selections=tuple(selections),
            source_token_budgets=tuple(sorted(source_budgets.items())),
            decisions=tuple(decisions),
        )

    @staticmethod
    def _contains_phrase(intent: str, phrase: str) -> bool:
        pattern = r"(?<!\w)" + r"\s+".join(re.escape(part) for part in phrase.split()) + r"(?!\w)"
        return re.search(pattern, intent) is not None

    @staticmethod
    def _omitted(
        rule: ContextPlanningRule,
        reason: str,
        source_class: ContextSourceClass | None = None,
    ) -> ContextPlanDecision:
        return ContextPlanDecision(
            rule_id=rule.rule_id,
            category=rule.category,
            provider_id=rule.provider_id,
            operation=rule.operation,
            source_class=source_class,
            fields=(),
            disposition="omitted",
            reason=reason,
        )
