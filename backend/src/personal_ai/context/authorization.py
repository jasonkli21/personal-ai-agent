"""Fail-closed context authorization and sensitivity joining.

Application policy is server-owned. These checks are deliberately performed
before provider factories and again before model-input construction.
"""

from __future__ import annotations

from collections.abc import Sequence

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


def _at_most(value: ContextSensitivity, ceiling: ContextSensitivity) -> bool:
    return value != "unknown" and ceiling != "unknown" and SENSITIVITY_RANK[value] <= SENSITIVITY_RANK[ceiling]


def authorize_base_disclosure(context: ApplicationContextRequest) -> None:
    """Reject an unsafe baseline before summaries, counts, or provider calls."""
    sensitivity = context.definition.sensitivity_defaults.conversation
    policy = context.definition.context_policy
    if not _at_most(sensitivity, policy.maximum_model_sensitivity):
        raise ContextPreparationError("context_model_disclosure_denied")


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
    field_labels = tuple(
        ContextFieldSensitivity(field=label.field, sensitivity=max(
            (label.sensitivity, declared_sensitivity),
            key=lambda value: SENSITIVITY_RANK[value],
        ))
        for label in item.field_sensitivity
    )
    return item.model_copy(update={"sensitivity": effective, "field_sensitivity": field_labels})


def authorize_effective_sensitivity(
    context: ApplicationContextRequest, sensitivity: ContextSensitivity
) -> None:
    """Check the final sensitivity join immediately before inference dispatch."""
    if not _at_most(
        sensitivity, context.definition.context_policy.maximum_model_sensitivity
    ):
        raise ContextPreparationError("context_model_disclosure_denied")
