"""Request and worker correlation for provider accounting."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace

from personal_ai.auth.scope import current_application_scope, current_request_scope


@dataclass(frozen=True, slots=True)
class UsageExecutionContext:
    owner_id: str
    application_id: str
    workspace_id: str | None
    request_id: str
    task_id: str
    run_id: str | None = None


_usage_context: ContextVar[UsageExecutionContext | None] = ContextVar(
    "personal_ai_usage_execution_context", default=None
)


@contextmanager
def bind_usage_context(context: UsageExecutionContext) -> Iterator[None]:
    token = _usage_context.set(context)
    try:
        yield
    finally:
        _usage_context.reset(token)


def current_usage_context() -> UsageExecutionContext | None:
    return _usage_context.get()


@contextmanager
def bind_usage_task(task_id: str, *, run_id: str | None = None) -> Iterator[None]:
    """Add semantic task/run attribution while retaining the validated request scope."""
    current = resolve_execution_context(task_id)
    with bind_usage_context(replace(
        current,
        task_id=task_id,
        run_id=run_id if run_id is not None else current.run_id,
    )):
        yield


def resolve_execution_context(operation: str) -> UsageExecutionContext:
    explicit = current_usage_context()
    request_scope = current_request_scope()
    application_scope = current_application_scope()
    return UsageExecutionContext(
        owner_id=(explicit.owner_id if explicit else request_scope.owner_id if request_scope else "local"),
        application_id=(explicit.application_id if explicit else application_scope.application_id),
        workspace_id=(explicit.workspace_id if explicit else application_scope.workspace_id),
        request_id=(
            explicit.request_id
            if explicit
            else request_scope.request_id
            if request_scope
            else "unscoped"
        ),
        task_id=explicit.task_id if explicit else operation,
        run_id=explicit.run_id if explicit else None,
    )
