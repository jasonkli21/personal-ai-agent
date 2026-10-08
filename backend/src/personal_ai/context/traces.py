"""Compact, content-free manifests for inspecting actual context builds."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from personal_ai.auth.scope import ApplicationScope
from personal_ai.context.builder import ContextBuildManifest
from personal_ai.context.planner import ContextPlan

MAX_CONTEXT_TRACE_DECISIONS = 64
MAX_CONTEXT_TRACE_MESSAGES = 64
MAX_CONTEXT_TRACE_REQUESTS = 16
MAX_CONTEXT_TRACE_RETENTION = 32
MAX_CONTEXT_TRACE_BYTES = 48 * 1024
CONTEXT_BUILD_POLICY_VERSION = "context-build-policy-v1"


class UnsupportedContextTraceSchemaError(Exception):
    """A scoped retained trace uses a schema this runtime cannot inspect."""


class ContextTraceSourceRequest(BaseModel):
    """Safe admission bounds for one requested provider operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(min_length=1, max_length=81)
    operation: str = Field(min_length=1, max_length=64)
    fields: tuple[str, ...] = Field(default=(), max_length=8)
    field_count: int = Field(ge=0)
    fields_truncated: bool = False
    max_results: int = Field(ge=1, le=50)
    max_bytes: int = Field(ge=1, le=65_536)
    max_tokens: int | None = Field(default=None, ge=1, le=128_000)
    required: bool


class ContextTraceDecision(BaseModel):
    """A bounded planning or build decision without source payload text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: Literal["planning", "build"]
    source_id: str | None = Field(default=None, max_length=200)
    source_id_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    item_id_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provider_id: str | None = Field(default=None, max_length=81)
    source_version: str | None = Field(default=None, max_length=100)
    operation: str | None = Field(default=None, max_length=64)
    category: str = Field(min_length=1, max_length=64)
    disposition: Literal["selected", "omitted"]
    fields: tuple[str, ...] = Field(default=(), max_length=8)
    field_count: int = Field(default=0, ge=0)
    fields_truncated: bool = False
    authority: str | None = Field(default=None, max_length=32)
    sensitivity: str | None = Field(default=None, max_length=32)
    token_count: int | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=180)


class ContextTraceMessageExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=64)


class ContextTraceSourceBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str = Field(min_length=1, max_length=64)
    token_limit: int = Field(ge=1)
    token_count: int = Field(ge=0)
    counter_kind: str = Field(min_length=1, max_length=32)
    injected_item_count: int = Field(ge=0)
    omitted_item_count: int = Field(ge=0)


class ContextTraceProviderFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(min_length=1, max_length=81)
    operation: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=64)


class ContextTraceManifest(BaseModel):
    """Versioned metadata captured when a chat model input is prepared."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["context-trace-v1"] = "context-trace-v1"
    view_kind: Literal["actual_build"] = "actual_build"
    actual_build: Literal[True] = True
    request_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    application_id: str = Field(min_length=1, max_length=100)
    workspace_id: str | None = Field(default=None, max_length=100)
    recorded_at: datetime
    build_schema_version: str = Field(min_length=1, max_length=64)
    policy_version: str = Field(min_length=1, max_length=64)
    planner_version: str | None = Field(default=None, max_length=100)
    counter_kind: str = Field(min_length=1, max_length=32)
    counter_version: str = Field(min_length=1, max_length=200)
    global_input_tokens: int = Field(ge=1)
    actual_input_tokens: int = Field(ge=0)
    effective_sensitivity: str = Field(min_length=1, max_length=32)
    summary_id: str | None = Field(default=None, max_length=80)
    requested_sources: tuple[ContextTraceSourceRequest, ...] = Field(
        default=(), max_length=MAX_CONTEXT_TRACE_REQUESTS
    )
    requested_source_count: int = Field(ge=0)
    requested_sources_truncated: bool = False
    planning_decisions: tuple[ContextTraceDecision, ...] = Field(default=(), max_length=32)
    planning_decision_count: int = Field(ge=0)
    planning_decisions_truncated: bool = False
    source_decisions: tuple[ContextTraceDecision, ...] = Field(
        default=(), max_length=MAX_CONTEXT_TRACE_DECISIONS
    )
    source_decision_count: int = Field(ge=0)
    source_decisions_truncated: bool = False
    source_budgets: tuple[ContextTraceSourceBudget, ...] = Field(default=(), max_length=16)
    provider_failures: tuple[ContextTraceProviderFailure, ...] = Field(default=(), max_length=16)
    provider_failure_count: int = Field(ge=0)
    provider_failures_truncated: bool = False
    selected_message_ids: tuple[str, ...] = Field(default=(), max_length=MAX_CONTEXT_TRACE_MESSAGES)
    selected_message_count: int = Field(ge=0)
    selected_messages_truncated: bool = False
    excluded_messages: tuple[ContextTraceMessageExclusion, ...] = Field(
        default=(), max_length=MAX_CONTEXT_TRACE_MESSAGES
    )
    excluded_message_count: int = Field(ge=0)
    excluded_messages_truncated: bool = False

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("context_trace_timestamp_timezone_required")
        return value.astimezone(UTC)

    @classmethod
    def from_build(
        cls,
        manifest: ContextBuildManifest,
        *,
        request_id: str,
        conversation_id: UUID,
        user_message_id: UUID,
        assistant_message_id: UUID,
        scope: ApplicationScope,
        recorded_at: datetime | None = None,
        context_plan: ContextPlan | None = None,
    ) -> ContextTraceManifest:
        """Project the live build report into a bounded, content-free trace."""
        requests = tuple(
            ContextTraceSourceRequest(
                provider_id=selection.provider_id,
                operation=selection.operation,
                fields=selection.fields[:8],
                field_count=len(selection.fields),
                fields_truncated=len(selection.fields) > 8,
                max_results=selection.max_results,
                max_bytes=selection.max_bytes,
                max_tokens=selection.max_tokens,
                required=selection.required,
            )
            for selection in (context_plan.selections if context_plan else ())[:MAX_CONTEXT_TRACE_REQUESTS]
        )
        planning = tuple(
            ContextTraceDecision(
                stage="planning",
                source_id=decision.provider_id or decision.rule_id or decision.category,
                provider_id=decision.provider_id,
                operation=decision.operation,
                category=decision.category,
                disposition=decision.disposition,
                fields=decision.fields[:8],
                field_count=len(decision.fields),
                fields_truncated=len(decision.fields) > 8,
                reason=decision.reason,
            )
            for decision in (context_plan.decisions if context_plan else ())[:32]
        )
        source_decisions = tuple(
            ContextTraceDecision(
                stage="build",
                source_id_hash=_trace_identifier_hash("source", item.source_id),
                item_id_hash=_trace_identifier_hash("item", item.item_id),
                provider_id=item.provider_id,
                source_version=item.source_version,
                operation=item.selected_operation,
                category=item.source_class,
                disposition="selected" if item.injected else "omitted",
                authority=item.authority,
                sensitivity=item.sensitivity,
                token_count=item.token_count,
                reason=item.omission_reason,
            )
            for item in manifest.items[:MAX_CONTEXT_TRACE_DECISIONS]
        )
        excluded = tuple(
            ContextTraceMessageExclusion(message_id=message_id, reason=reason)
            for message_id, reason in manifest.excluded_messages[:MAX_CONTEXT_TRACE_MESSAGES]
        )
        trace = cls(
            request_id=request_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            application_id=scope.application_id,
            workspace_id=scope.workspace_id,
            recorded_at=recorded_at or datetime.now(UTC),
            build_schema_version=manifest.schema_version,
            policy_version=CONTEXT_BUILD_POLICY_VERSION,
            planner_version=manifest.planner_version,
            counter_kind=manifest.counter_kind,
            counter_version=manifest.counter_version,
            global_input_tokens=manifest.global_input_tokens,
            actual_input_tokens=manifest.actual_input_tokens,
            effective_sensitivity=manifest.effective_sensitivity,
            summary_id=manifest.summary_id,
            requested_sources=requests,
            requested_source_count=(len(context_plan.selections) if context_plan else 0),
            requested_sources_truncated=(
                len(context_plan.selections) > len(requests) if context_plan else False
            ),
            planning_decisions=planning,
            planning_decision_count=len(context_plan.decisions) if context_plan else 0,
            planning_decisions_truncated=(
                len(context_plan.decisions) > len(planning) if context_plan else False
            ),
            source_decisions=source_decisions,
            source_decision_count=len(manifest.items),
            source_decisions_truncated=len(manifest.items) > len(source_decisions),
            source_budgets=tuple(
                ContextTraceSourceBudget(
                    category=source.source_class,
                    token_limit=source.token_limit,
                    token_count=source.token_count,
                    counter_kind=source.counter_kind,
                    injected_item_count=source.injected_item_count,
                    omitted_item_count=source.omitted_item_count,
                )
                for source in manifest.sources
            ),
            provider_failures=tuple(
                ContextTraceProviderFailure(
                    provider_id=failure.provider_id,
                    operation=failure.operation,
                    reason=failure.reason,
                )
                for failure in manifest.source_failures[:16]
            ),
            provider_failure_count=len(manifest.source_failures),
            provider_failures_truncated=len(manifest.source_failures) > 16,
            selected_message_ids=manifest.selected_message_ids[:MAX_CONTEXT_TRACE_MESSAGES],
            selected_message_count=len(manifest.selected_message_ids),
            selected_messages_truncated=len(manifest.selected_message_ids) > MAX_CONTEXT_TRACE_MESSAGES,
            excluded_messages=excluded,
            excluded_message_count=len(manifest.excluded_messages),
            excluded_messages_truncated=len(manifest.excluded_messages) > len(excluded),
        )
        while len(trace.model_dump_json().encode()) > MAX_CONTEXT_TRACE_BYTES:
            if len(trace.source_decisions) > 16:
                trace = trace.model_copy(update={
                    "source_decisions": trace.source_decisions[:16],
                    "source_decisions_truncated": True,
                })
            elif len(trace.planning_decisions) > 8:
                trace = trace.model_copy(update={
                    "planning_decisions": trace.planning_decisions[:8],
                    "planning_decisions_truncated": True,
                })
            elif len(trace.selected_message_ids) > 16:
                trace = trace.model_copy(update={
                    "selected_message_ids": trace.selected_message_ids[:16],
                    "selected_messages_truncated": True,
                })
            elif len(trace.excluded_messages) > 16:
                trace = trace.model_copy(update={
                    "excluded_messages": trace.excluded_messages[:16],
                    "excluded_messages_truncated": True,
                })
            elif len(trace.requested_sources) > 8:
                trace = trace.model_copy(update={
                    "requested_sources": trace.requested_sources[:8],
                    "requested_sources_truncated": True,
                })
            elif any(len(source.fields) > 4 for source in trace.requested_sources):
                trace = trace.model_copy(update={
                    "requested_sources": tuple(
                        source.model_copy(update={
                            "fields": source.fields[:4],
                            "fields_truncated": True,
                        })
                        for source in trace.requested_sources
                    ),
                })
            elif any(len(decision.fields) > 4 for decision in (
                *trace.planning_decisions, *trace.source_decisions
            )):
                trace = trace.model_copy(update={
                    "planning_decisions": tuple(
                        decision.model_copy(update={
                            "fields": decision.fields[:4],
                            "fields_truncated": True,
                        })
                        for decision in trace.planning_decisions
                    ),
                    "source_decisions": tuple(
                        decision.model_copy(update={
                            "fields": decision.fields[:4],
                            "fields_truncated": True,
                        })
                        for decision in trace.source_decisions
                    ),
                })
            elif len(trace.source_decisions) > 8:
                trace = trace.model_copy(update={
                    "source_decisions": trace.source_decisions[:8],
                    "source_decisions_truncated": True,
                })
            elif len(trace.planning_decisions) > 4:
                trace = trace.model_copy(update={
                    "planning_decisions": trace.planning_decisions[:4],
                    "planning_decisions_truncated": True,
                })
            elif len(trace.selected_message_ids) > 8:
                trace = trace.model_copy(update={
                    "selected_message_ids": trace.selected_message_ids[:8],
                    "selected_messages_truncated": True,
                })
            elif len(trace.excluded_messages) > 8:
                trace = trace.model_copy(update={
                    "excluded_messages": trace.excluded_messages[:8],
                    "excluded_messages_truncated": True,
                })
            elif len(trace.requested_sources) > 4:
                trace = trace.model_copy(update={
                    "requested_sources": trace.requested_sources[:4],
                    "requested_sources_truncated": True,
                })
            elif any(len(source.fields) > 1 for source in trace.requested_sources):
                trace = trace.model_copy(update={
                    "requested_sources": tuple(
                        source.model_copy(update={
                            "fields": source.fields[:1],
                            "fields_truncated": True,
                        })
                        for source in trace.requested_sources
                    ),
                })
            elif any(len(decision.fields) > 1 for decision in (
                *trace.planning_decisions, *trace.source_decisions
            )):
                trace = trace.model_copy(update={
                    "planning_decisions": tuple(
                        decision.model_copy(update={
                            "fields": decision.fields[:1],
                            "fields_truncated": True,
                        })
                        for decision in trace.planning_decisions
                    ),
                    "source_decisions": tuple(
                        decision.model_copy(update={
                            "fields": decision.fields[:1],
                            "fields_truncated": True,
                        })
                        for decision in trace.source_decisions
                    ),
                })
            else:
                raise ValueError("context_trace_metadata_exceeds_size_limit")
        return trace


def _trace_identifier_hash(kind: str, value: str) -> str:
    """Keep arbitrary provider identifiers correlatable without persisting their values."""
    return sha256(f"context-trace-v1:{kind}:{value}".encode()).hexdigest()


class ContextTraceRepository(Protocol):
    """Owner- and application-scoped persistence for bounded actual build traces."""

    def put(
        self, *, owner_id: str, trace: ContextTraceManifest, deadline: float | None = None
    ) -> None: ...

    def latest_for_user_turn(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        conversation_id: UUID,
        user_message_id: UUID,
    ) -> ContextTraceManifest | None: ...


class InMemoryContextTraceRepository:
    """Deterministic fake with the same scoped lookup and retention contract."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str | None, UUID], list[ContextTraceManifest]] = {}

    def put(
        self, *, owner_id: str, trace: ContextTraceManifest, deadline: float | None = None
    ) -> None:
        del deadline
        key = (owner_id, trace.application_id, trace.workspace_id, trace.conversation_id)
        records = self.records.setdefault(key, [])
        if any(record.assistant_message_id == trace.assistant_message_id for record in records):
            raise ValueError("context_trace_duplicate")
        records.append(trace)
        records.sort(key=lambda record: (record.recorded_at, str(record.assistant_message_id)))
        del records[:-MAX_CONTEXT_TRACE_RETENTION]

    def latest_for_user_turn(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        conversation_id: UUID,
        user_message_id: UUID,
    ) -> ContextTraceManifest | None:
        key = (owner_id, scope.application_id, scope.workspace_id, conversation_id)
        return next(
            (
                record
                for record in reversed(self.records.get(key, ()))
                if record.user_message_id == user_message_id
            ),
            None,
        )
