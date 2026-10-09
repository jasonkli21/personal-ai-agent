"""Versioned validator registry and bounded exact-source validation contracts."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_ai.validation.checks import constraint_passes, json_object, type_matches


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always", allow_inf_nan=False)


class ValidationResult(FrozenContract):
    accepted: bool
    reasons: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def coherent(self):
        if len(self.model_dump_json().encode()) > 512:
            raise ValueError("validation_result_too_large")
        if self.accepted == bool(self.reasons) or any(
            not reason or len(reason) > 100
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in reason)
            for reason in self.reasons
        ):
            raise ValueError("validation_result_invalid")
        return self


class Constraint(FrozenContract):
    path: str = Field(min_length=1, max_length=200)
    operator: Literal["lte", "gte", "equals", "not_equals", "not_contains"]
    value: str | int | float | bool


class PreparedSource(FrozenContract):
    """Exact authorized source contents; transient and never written to observations."""

    source_id: str = Field(min_length=1, max_length=200)
    reference_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(max_length=262144)


class ValidationInput(FrozenContract):
    input_contract_id: str = Field(min_length=1, max_length=200)
    output_contract_id: str = Field(min_length=1, max_length=200)
    required_fields: tuple[str, ...] = Field(default=(), max_length=64)
    field_types: dict[str, Literal[
        "string", "number", "integer", "array", "object", "boolean"
    ]] = Field(default_factory=dict, max_length=64)
    sources: tuple[PreparedSource, ...] = Field(default=(), max_length=64)
    required_citations: tuple[str, ...] = Field(default=(), max_length=64)
    require_source_spans: bool = False
    hard_constraints: tuple[Constraint, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def meaningful(self):
        ids = [source.source_id for source in self.sources]
        if len(set(ids)) != len(ids) or not set(self.required_citations).issubset(ids):
            raise ValueError("validation_source_contract_invalid")
        if not (self.required_fields or self.field_types or self.required_citations
                or self.require_source_spans or self.hard_constraints):
            raise ValueError("validation_contract_empty")
        return self


class TaskValidator(Protocol):
    validator_id: str
    validator_version: str
    input_contract_id: str
    output_contract_id: str

    def validate(self, inputs: ValidationInput, output: str) -> ValidationResult: ...


class TaskValidatorRegistry:
    def __init__(self):
        self._validators = {}

    def register(self, validator: TaskValidator):
        key = (validator.validator_id, validator.validator_version)
        if key in self._validators:
            raise ValueError("task_validator_duplicate")
        self._validators[key] = validator

    def resolve(self, validator_id, validator_version):
        try:
            return self._validators[validator_id, validator_version]
        except KeyError:
            raise ValueError("task_validator_unavailable") from None


class StructuredTaskValidator:
    """Schema, citation membership/coverage, exact spans, and supplied hard rules.

    Domain validators may compose this check and impose their own authoritative
    rules. Model-generated source IDs and quotes never authorize a disclosure.
    """

    validator_id = "structured-sources"
    validator_version = "1"
    input_contract_id = "prepared-sources-v1"
    output_contract_id = "structured-sources-v1"

    def validate(self, inputs, output):
        data = json_object(output)
        if data is None:
            return ValidationResult(accepted=False, reasons=("schema_invalid",))
        reasons = []
        if not set(inputs.required_fields).issubset(data) or any(
            not type_matches(data.get(key), kind)
            for key, kind in inputs.field_types.items() if key in data
        ):
            reasons.append("schema_invalid")
        sources = {source.source_id: source.text for source in inputs.sources}
        citations = data.get("citations", [])
        if (not isinstance(citations, list)
            or any(not isinstance(c, str) or c not in sources for c in citations)
            or len(citations) != len(set(citations))
            or not set(inputs.required_citations).issubset(citations)):
            reasons.append("citations_invalid")
        spans = data.get("source_spans", [])
        if inputs.require_source_spans and (not isinstance(spans, list) or not spans) or not isinstance(spans, list) or any(
            not self._span_valid(span, sources) for span in spans
        ):
            reasons.append("source_spans_invalid")
        if any(not constraint_passes(data, rule) for rule in inputs.hard_constraints):
            reasons.append("hard_constraint_failed")
        return ValidationResult(accepted=not reasons, reasons=tuple(reasons))

    @staticmethod
    def _span_valid(span, sources):
        if not isinstance(span, dict):
            return False
        source = sources.get(span.get("source_id")) if isinstance(span.get("source_id"), str) else None
        start, end, quote = span.get("start"), span.get("end"), span.get("quote")
        return (source is not None and type(start) is int and type(end) is int
                and 0 <= start < end <= len(source) and isinstance(quote, str)
                and source[start:end] == quote)
