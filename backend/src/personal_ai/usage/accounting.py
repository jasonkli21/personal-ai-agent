"""Construction helpers for a safe logical invocation descriptor."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from personal_ai.usage.context import resolve_execution_context
from personal_ai.usage.contracts import InvocationMetadata, ProviderEndpoint


def new_invocation(
    endpoint: ProviderEndpoint,
    *,
    operation: str,
    quota_operation: str,
    input_tokens_estimate: int | None = None,
    output_tokens_bound: int | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
) -> InvocationMetadata:
    scope = resolve_execution_context(quota_operation)
    if task_id is not None or run_id is not None:
        scope = replace(
            scope,
            task_id=task_id if task_id is not None else scope.task_id,
            run_id=run_id if run_id is not None else scope.run_id,
        )
    return InvocationMetadata(
        invocation_id=uuid4(),
        owner_id=scope.owner_id,
        application_id=scope.application_id,
        workspace_id=scope.workspace_id,
        task_id=scope.task_id,
        operation=operation,
        request_id=(scope.request_id if scope.request_id != "unscoped" else str(uuid4())),
        run_id=scope.run_id,
        endpoint=endpoint,
        input_tokens_estimate=input_tokens_estimate,
        output_tokens_bound=output_tokens_bound,
    )


def estimated_tokens(text: str) -> int:
    """Return a bounded conservative planning estimate; never persist source text."""
    return min(2_000_000, max(1, (len(text) + 2) // 3)) if text else 0


def unit_reservations(
    *, input_tokens: int | None = None, output_tokens: int | None = None, requests: int = 1,
    additional_units: dict[str, int] | None = None,
) -> tuple[tuple[str, int], ...]:
    values: dict[str, int] = {"requests": requests}
    if input_tokens is not None:
        values["input_tokens"] = input_tokens
    if output_tokens is not None:
        values["output_tokens"] = output_tokens
    if input_tokens is not None and output_tokens is not None:
        values["tokens"] = input_tokens + output_tokens
    elif input_tokens is not None:
        values["tokens"] = input_tokens
    if additional_units:
        for unit, amount in additional_units.items():
            if not unit or isinstance(amount, bool) or amount < 0:
                raise ValueError("usage_reservation_units_invalid")
            values[unit] = amount
    return tuple(sorted(values.items()))
