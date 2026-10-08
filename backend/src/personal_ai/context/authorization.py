"""Fail-closed context authorization and sensitivity joining.

Application policy is server-owned. These checks are deliberately performed
before provider factories and again before model-input construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

from personal_ai.applications.contracts import (
    SENSITIVITY_RANK,
    ApplicationContextRequest,
    ContextOperationPolicy,
    ContextSensitivity,
)
from personal_ai.auth.scope import ApplicationScope
from personal_ai.context.providers import (
    ContextFieldSensitivity,
    ContextItem,
    ContextPreparationError,
    ContextSelection,
)
from personal_ai.llm.client import InferenceContext


def _at_most(value: ContextSensitivity, ceiling: ContextSensitivity) -> bool:
    return value != "unknown" and ceiling != "unknown" and SENSITIVITY_RANK[value] <= SENSITIVITY_RANK[ceiling]


def authorize_base_disclosure(context: ApplicationContextRequest) -> ContextSensitivity:
    """Authorize mandatory user/history content before summaries or counts."""
    baseline = ContextSelection(
        provider_id="conversation_history",
        operation="history",
        fields=("content", "role"),
    )
    _operation, history_sensitivity = _selection_policy(context, baseline)
    sensitivity = context.definition.sensitivity_defaults.conversation
    if not _at_most(sensitivity, context.definition.context_policy.maximum_model_sensitivity):
        raise ContextPreparationError("context_model_disclosure_denied")
    return max(
        (sensitivity, history_sensitivity),
        key=lambda value: SENSITIVITY_RANK[value],
    )


def _selection_policy(
    context: ApplicationContextRequest, selection: ContextSelection
) -> tuple[ContextOperationPolicy, ContextSensitivity]:
    scope = context.scope
    expected_scope = ApplicationScope(
        application_id=scope.application_id, workspace_id=scope.workspace_id
    )
    if policy_cross_application_denied(context) and (
        (selection.target_scope or expected_scope) != expected_scope
        or any(
            reference.application_id != scope.application_id
            or reference.workspace_id != scope.workspace_id
            for reference in selection.entity_refs
        )
    ):
        raise ContextPreparationError("context_cross_application_denied")

    policy = context.definition.context_policy
    operation = policy.operation(selection.provider_id, selection.operation)
    if operation is None or not operation.source_access or not operation.model_disclosure:
        raise ContextPreparationError("context_policy_denied")

    declared: list[ContextSensitivity] = [operation.sensitivity]
    fields_by_name = {item.field: item for item in operation.fields}
    if selection.fields:
        for field in selection.fields:
            rule = fields_by_name.get(field)
            if rule is None and operation.allow_dynamic_fields:
                assert operation.dynamic_sensitivity is not None
                sensitivity = operation.dynamic_sensitivity
            elif rule is None:
                raise ContextPreparationError("context_field_policy_denied")
            else:
                if not rule.source_access or not rule.model_disclosure:
                    raise ContextPreparationError("context_field_policy_denied")
                sensitivity = rule.sensitivity
            if sensitivity == "unknown":
                raise ContextPreparationError("context_unknown_sensitivity_denied")
            if not _at_most(sensitivity, policy.maximum_model_sensitivity):
                raise ContextPreparationError("context_model_disclosure_denied")
            declared.append(sensitivity)
    elif not operation.allow_empty_fields:
        raise ContextPreparationError("context_fields_required")

    if any(value == "unknown" for value in declared):
        raise ContextPreparationError("context_unknown_sensitivity_denied")
    effective = max(declared, key=lambda value: SENSITIVITY_RANK[value])
    if not _at_most(effective, policy.maximum_model_sensitivity):
        raise ContextPreparationError("context_model_disclosure_denied")
    return operation, effective


def policy_cross_application_denied(context: ApplicationContextRequest) -> bool:
    """This phase registers only the hard deny default; grants remain future work."""
    return context.definition.context_policy.cross_application == "deny"


def authorize_context_selections(
    context: ApplicationContextRequest, selections: Sequence[ContextSelection]
) -> None:
    """Authorize every requested operation before any source or auxiliary call."""
    for selection in selections:
        _selection_policy(context, selection)


def authorize_context_selection(
    context: ApplicationContextRequest, selection: ContextSelection
) -> ContextSensitivity:
    """Return the joined server classification for one authorized operation."""
    _operation, sensitivity = _selection_policy(context, selection)
    return sensitivity


def apply_item_policy(
    context: ApplicationContextRequest,
    selection: ContextSelection,
    item: ContextItem,
) -> ContextItem:
    """Join server policy with adapter labels before model-input counting."""
    _operation, declared_sensitivity = _selection_policy(context, selection)
    if item.sensitivity == "unknown":
        raise ContextPreparationError("context_unknown_sensitivity_denied")
    # An adapter cannot relabel a field as less sensitive than the server policy.
    # A higher adapter label signals a provider contract mismatch and fails closed.
    if SENSITIVITY_RANK[item.sensitivity] > SENSITIVITY_RANK[declared_sensitivity]:
        raise ContextPreparationError("context_policy_sensitivity_mismatch")

    effective = max(
        (item.sensitivity, declared_sensitivity),
        key=lambda value: SENSITIVITY_RANK[value],
    )
    if not _at_most(effective, context.definition.context_policy.maximum_model_sensitivity):
        raise ContextPreparationError("context_model_disclosure_denied")
    projected_payload, projected_fields = _project_payload(item, selection)
    if item.provider_id in {"client_context", "global_profile"}:
        payload_fields = ("value",)
    elif item.source_class == "tool_result":
        payload_fields = ("result",)
    else:
        payload_fields = projected_fields
    prior_labels = {label.field: label.sensitivity for label in item.field_sensitivity}
    field_labels_by_name = dict(prior_labels)
    for name in payload_fields:
        if name in type(item.payload).model_fields:
            previous = field_labels_by_name.get(name, item.sensitivity)
            field_labels_by_name[name] = max(
                (previous, declared_sensitivity), key=lambda value: SENSITIVITY_RANK[value]
            )
    field_labels = tuple(
        ContextFieldSensitivity(field=name, sensitivity=sensitivity)
        for name, sensitivity in sorted(field_labels_by_name.items())
    )
    projection_type = create_model(
        f"Authorized{type(item.payload).__name__}Projection",
        __config__=ConfigDict(extra="forbid", frozen=True),
        **{name: (Any, ...) for name in projected_payload},
    )
    safe_payload = projection_type(**projected_payload)
    return item.model_copy(update={
        "disclosed_payload": safe_payload,
        "sensitivity": effective,
        "field_sensitivity": field_labels,
    })


def _project_payload(
    item: ContextItem, selection: ContextSelection
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Render only selected policy fields; adapter metadata stays server-side."""
    payload = item.payload
    payload_data = payload.model_dump(
        mode="json", exclude_none=True, exclude_defaults=True
    )
    selected = set(selection.fields)

    if item.provider_id == "client_context":
        field = getattr(payload, "key", None)
        if not isinstance(field, str) or field not in selected:
            raise ContextPreparationError("context_provider_projection_violation")
        return {field: payload_data.get("value")}, (field,)

    if item.provider_id == "global_profile":
        field = getattr(payload, "field", None)
        if not isinstance(field, str) or field not in selected:
            raise ContextPreparationError("context_provider_projection_violation")
        return {field: payload_data.get("value")}, (field,)

    if item.source_class == "tool_result":
        result = getattr(payload, "result", None)
        if not isinstance(result, BaseModel):
            raise ContextPreparationError("context_provider_projection_violation")
        values = result.model_dump(mode="json", exclude_none=True)
        if set(values) - selected:
            raise ContextPreparationError("context_provider_projection_violation")
        return values, tuple(sorted(values))

    # The built-in wrappers carry small discriminator/reference fields used by
    # source validation. They are not model input fields. Every other populated
    # payload field must correspond to the exact authorized projection.
    internal_fields = {
        "conversation_history": {"kind"},
        "ai_memory": {"record_kind"},
        "external_research": {"evidence_id", "source_observation_ids"},
    }.get(item.provider_id, set())
    populated = set(payload_data)
    if populated - internal_fields - selected:
        raise ContextPreparationError("context_provider_projection_violation")
    projected = {name: payload_data[name] for name in sorted(populated & selected)}
    return projected, tuple(projected)


def authorize_effective_sensitivity(
    context: ApplicationContextRequest, sensitivity: ContextSensitivity
) -> None:
    """Check the final sensitivity join immediately before inference dispatch."""
    if not _at_most(
        sensitivity, context.definition.context_policy.maximum_model_sensitivity
    ):
        raise ContextPreparationError("context_model_disclosure_denied")


def make_inference_context(
    context: ApplicationContextRequest, sensitivity: ContextSensitivity
) -> InferenceContext:
    """Create the inference envelope only after the server policy check."""
    authorize_effective_sensitivity(context, sensitivity)
    policy = context.definition.context_policy
    try:
        return InferenceContext(
            effective_sensitivity=sensitivity,
            maximum_sensitivity=policy.maximum_model_sensitivity,
            policy_version=policy.version,
        )
    except ValueError as error:
        raise ContextPreparationError("context_model_disclosure_denied") from error
