"""Typed, bounded observation payloads for retained artifact kinds."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from personal_ai.context.traces import ContextTraceManifest

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][-A-Za-z0-9._:+/]{0,199}$")
_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,99}$")
_NUMERIC_SERIES_FIELDS = frozenset({"source_reference_counts", "permission_dependency_counts"})


class _ObservationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RoutingCandidate(_ObservationModel):
    candidate_id: str | None = Field(default=None, max_length=200)
    endpoint_id: str | None = Field(default=None, max_length=200)
    provider_id: str | None = Field(default=None, max_length=100)
    model_id: str | None = Field(default=None, max_length=200)
    profile_version: int | None = Field(default=None, ge=1)
    eligible: bool | None = None
    selected: bool | None = None
    score: float | None = None
    reason_code: str | None = Field(default=None, max_length=100)
    rejection_codes: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator(
        "candidate_id", "endpoint_id", "provider_id", "model_id", "reason_code",
    )
    @classmethod
    def token_fields_only(cls, value):
        if value is not None and not _SAFE_TOKEN.fullmatch(value):
            raise ValueError("artifact_observation_token_invalid")
        return value

    @field_validator("rejection_codes")
    @classmethod
    def token_codes_only(cls, values):
        if any(not _SAFE_TOKEN.fullmatch(value) for value in values):
            raise ValueError("artifact_observation_token_invalid")
        return values


class RoutingObservation(_ObservationModel):
    schema_version: Literal["routing-observation-v1"] = "routing-observation-v1"
    strategy_id: str | None = Field(default=None, max_length=100)
    strategy_version: str | None = Field(default=None, max_length=100)
    policy_version: str | None = Field(default=None, max_length=100)
    result_code: str | None = Field(default=None, max_length=100)
    candidates: tuple[RoutingCandidate, ...] = Field(default=(), max_length=32)

    @field_validator("strategy_id", "strategy_version", "policy_version", "result_code")
    @classmethod
    def token_fields_only(cls, value):
        if value is not None and not _SAFE_TOKEN.fullmatch(value):
            raise ValueError("artifact_observation_token_invalid")
        return value


class EvaluationMetric(_ObservationModel):
    name: str = Field(min_length=1, max_length=100, pattern=_SAFE_NAME.pattern)
    value: int | float | bool

    @field_validator("value")
    @classmethod
    def finite_number(cls, value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("artifact_observation_number_invalid")
        return value


class EvaluationLabel(_ObservationModel):
    field: Literal[
        "schema_version", "fixture", "name", "result", "state", "status",
        "failure_reason", "failure_code", "variant", "policy_version",
        "provider_id", "model_id", "endpoint_profile_id", "task_id", "operation",
        "classification", "reason_code", "configuration_class", "expected_state",
    ]
    value: str = Field(min_length=1, max_length=200, pattern=_SAFE_TOKEN.pattern)


class EvaluationCase(_ObservationModel):
    case_id: str = Field(min_length=1, max_length=200, pattern=_SAFE_TOKEN.pattern)
    passed: bool | None = None
    metrics: tuple[EvaluationMetric, ...] = Field(default=(), max_length=256)
    labels: tuple[EvaluationLabel, ...] = Field(default=(), max_length=32)


class EvaluationObservationBatch(_ObservationModel):
    schema_version: Literal["evaluation-observations-v1"] = "evaluation-observations-v1"
    passed: bool | None = None
    cases: tuple[EvaluationCase, ...] = Field(min_length=1, max_length=10000)


class RawEvaluationOutput(_ObservationModel):
    """Provider output only. Prompt text, fixture inputs and credentials are forbidden."""

    case_id: str = Field(min_length=1, max_length=200, pattern=_SAFE_TOKEN.pattern)
    task_profile_id: str = Field(min_length=1, max_length=200, pattern=_SAFE_TOKEN.pattern)
    endpoint_profile_id: str = Field(min_length=1, max_length=200, pattern=_SAFE_TOKEN.pattern)
    endpoint_profile_version: int = Field(ge=1)
    provider_id: str = Field(min_length=1, max_length=100, pattern=_SAFE_TOKEN.pattern)
    model_id: str = Field(min_length=1, max_length=200, pattern=_SAFE_TOKEN.pattern)
    serializer_id: str = Field(min_length=1, max_length=200, pattern=_SAFE_TOKEN.pattern)
    runtime_id: str = Field(min_length=1, max_length=200, pattern=_SAFE_TOKEN.pattern)
    invocation_id: UUID
    attempt_id: UUID
    status: Literal["success", "incomplete", "failure", "rejected"]
    output_text: str = Field(max_length=65_536)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    usage_confidence: Literal["exact", "derived", "configured", "unknown"] = "unknown"
    latency_ms: int = Field(ge=0, le=600_000)


class RawEvaluationOutputBatch(_ObservationModel):
    schema_version: Literal["evaluation-raw-outputs-v1"] = "evaluation-raw-outputs-v1"
    evaluation_run_id: UUID
    retention_policy_reference: str = Field(min_length=1, max_length=200, pattern=_SAFE_TOKEN.pattern)
    retention_expires_at: datetime
    outputs: tuple[RawEvaluationOutput, ...] = Field(min_length=1, max_length=16)

    @field_validator("retention_expires_at")
    @classmethod
    def retention_timestamp_is_aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("artifact_retention_timestamp_invalid")
        return value


class DebugReplayObservationBatch(_ObservationModel):
    schema_version: Literal["debug-replay-observations-v1"] = "debug-replay-observations-v1"
    cases: tuple[EvaluationCase, ...] = Field(min_length=1, max_length=10000)


class MinimalEvaluationObservation(_ObservationModel):
    """Small compatibility shape for direct, scalar-only evaluation observations."""

    case_id: str | None = Field(default=None, max_length=200, pattern=_SAFE_TOKEN.pattern)
    fixture: str | None = Field(default=None, max_length=200, pattern=_SAFE_TOKEN.pattern)
    result: Literal["passed", "failed", "skipped"] | None = None
    passed: bool | None = None
    score: int | float | None = None
    count: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    @field_validator("score")
    @classmethod
    def finite_score(cls, value):
        if value is not None and isinstance(value, float) and not math.isfinite(value):
            raise ValueError("artifact_observation_number_invalid")
        return value


def _assert_context_trace_tokens(value):
    if isinstance(value, str):
        if not _SAFE_TOKEN.fullmatch(value):
            raise ValueError("artifact_raw_observation_denied")
    elif isinstance(value, dict):
        for key, item in value.items():
            if not _SAFE_NAME.fullmatch(str(key)):
                raise ValueError("artifact_observation_field_invalid")
            _assert_context_trace_tokens(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_context_trace_tokens(item)


def validate_context_trace(value):
    trace = ContextTraceManifest.model_validate(value)
    dumped = trace.model_dump(mode="json")
    _assert_context_trace_tokens(dumped)
    return dumped


def validate_observation(kind: str, value, *, jsonl: bool):
    """Require a versioned contract before an observation body is retained."""
    if kind == "context_trace":
        if jsonl:
            raise ValueError("artifact_context_trace_format_invalid")
        return validate_context_trace(value)
    if kind == "routing_trace":
        if jsonl:
            raise ValueError("artifact_routing_trace_format_invalid")
        return RoutingObservation.model_validate(value).model_dump(mode="json")
    if kind == "evaluation":
        if not jsonl and isinstance(value, dict) and value.get("schema_version") == "evaluation-raw-outputs-v1":
            return RawEvaluationOutputBatch.model_validate(value).model_dump(mode="json")
        items = value if jsonl else [value]
        if not isinstance(items, (list, tuple)):
            raise ValueError("artifact_evaluation_format_invalid")
        for item in items:
            if isinstance(item, dict) and item.get("schema_version") == "evaluation-observations-v1":
                EvaluationObservationBatch.model_validate(item)
            else:
                MinimalEvaluationObservation.model_validate(item)
        return value
    if kind == "debug_replay":
        if not jsonl or not isinstance(value, (list, tuple)):
            raise ValueError("artifact_debug_replay_format_invalid")
        for item in value:
            if isinstance(item, dict) and item.get("schema_version") == "debug-replay-observations-v1":
                DebugReplayObservationBatch.model_validate(item)
            else:
                MinimalEvaluationObservation.model_validate(item)
        return value
    return value


def _safe_string_field(key: str, value: str):
    if key not in {
        "schema_version", "fixture", "name", "result", "state", "status",
        "failure_reason", "failure_code", "variant", "policy_version", "provider_id",
        "model_id", "endpoint_profile_id", "task_id", "operation", "classification",
        "reason_code", "configuration_class", "expected_state",
    }:
        return None
    if not _SAFE_TOKEN.fullmatch(value):
        return None
    return EvaluationLabel(field=key, value=value)


def _metric_name(key: str) -> bool:
    return bool(
        _SAFE_NAME.fullmatch(key)
        and (
            key in {
                "passed", "score", "similarity", "confidence", "latency", "count",
                "attempts", "queries", "sources", "events", "evidence", "citations",
            }
            or key.endswith((
                "_count", "_tokens", "_bytes", "_ms", "_seconds", "_version",
                "_total", "_budget", "_delta", "_score", "_attempts", "_queries",
                "_sources", "_events", "_citations", "_evidence", "_calls", "_cost",
            ))
        )
    )


def _project_case(value, index: int) -> EvaluationCase:
    if not isinstance(value, dict):
        raise TypeError("artifact_evaluation_case_invalid")
    case_id = next(
        (
            value[key]
            for key in ("fixture", "name", "case_id")
            if isinstance(value.get(key), str) and _SAFE_TOKEN.fullmatch(value[key])
        ),
        f"case-{index}",
    )
    metrics: list[EvaluationMetric] = []
    labels: list[EvaluationLabel] = []

    def visit(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if not _SAFE_NAME.fullmatch(str(key)):
                    continue
                if isinstance(child, (int, float, bool)) and not isinstance(child, complex):
                    if _metric_name(key) and len(metrics) < 256:
                        metrics.append(EvaluationMetric(name=key, value=child))
                elif isinstance(child, str):
                    label = _safe_string_field(key, child)
                    if label is not None and len(labels) < 32:
                        labels.append(label)
                elif isinstance(child, (list, tuple)):
                    if child and all(isinstance(entry, (int, float)) and not isinstance(entry, bool) for entry in child):
                        if key not in _NUMERIC_SERIES_FIELDS:
                            raise ValueError("artifact_vector_observation_denied")
                        metrics.extend(
                            EvaluationMetric(name=key, value=entry)
                            for entry in child[: max(0, 256 - len(metrics))]
                        )
                    for entry in child:
                        if isinstance(entry, dict):
                            visit(entry)
                elif isinstance(child, dict):
                    visit(child)

    visit(value)
    passed = value.get("passed") if isinstance(value.get("passed"), bool) else None
    return EvaluationCase(case_id=case_id, passed=passed, metrics=tuple(metrics), labels=tuple(labels))


def evaluation_batch(rows):
    """Project a full CLI report to bounded IDs, outcome labels and numeric facts."""
    if not isinstance(rows, (list, tuple)) or not rows:
        rows = [rows]
    if len(rows) == 1 and isinstance(rows[0], dict) and isinstance(rows[0].get("results"), list):
        report = rows[0]
        cases_source = [report, *report["results"]]
    else:
        cases_source = list(rows)
    if len(cases_source) > 10000:
        raise ValueError("artifact_evaluation_batch_limit")
    cases = tuple(_project_case(item, index + 1) for index, item in enumerate(cases_source))
    report_passed = rows[0].get("passed") if len(rows) == 1 and isinstance(rows[0], dict) else None
    return EvaluationObservationBatch(passed=report_passed, cases=cases)


def debug_replay_batch(observations):
    if not isinstance(observations, (list, tuple)) or not 1 <= len(observations) <= 10000:
        raise ValueError("artifact_debug_replay_format_invalid")
    cases = tuple(_project_case(item, index + 1) for index, item in enumerate(observations))
    return DebugReplayObservationBatch(cases=cases)
