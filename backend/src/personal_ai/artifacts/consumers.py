"""Shared, privacy-safe retention entry points; consumers never hold object clients."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from time import monotonic
from uuid import uuid4

from personal_ai.auth.scope import ApplicationScope

logger = logging.getLogger(__name__)

_TRACE_WRITER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="artifact-trace")
_TRACE_SLOTS = BoundedSemaphore(4)


class ArtifactContextTraceRepository:
    """Keep the existing bounded inspector manifest; artifact failure is advisory."""

    def __init__(self, repository, service):
        self.repository, self.service = repository, service

    def put(self, *, owner_id, trace, deadline=None):
        self.repository.put(owner_id=owner_id, trace=trace, deadline=deadline)
        if not _TRACE_SLOTS.acquire(blocking=False):
            return

        def retain():
            try:
                if deadline is not None and monotonic() >= deadline:
                    return
                self._retain(owner_id, trace)
            finally:
                _TRACE_SLOTS.release()

        try:
            _TRACE_WRITER.submit(retain)
        except Exception:  # noqa: BLE001 - optional queue admission is advisory
            _TRACE_SLOTS.release()

    def _retain(self, owner_id, trace):
        try:
            if trace.source_decisions:
                # Phase 14/15 immutable source/grant propagation is still incomplete.
                # Retain only actual builds whose dependencies are owner history today.
                return
            # This is the retained actual build, never a reconstruction from current data.
            self.service().write(
                trace.model_dump(mode="json"),
                owner_id=owner_id,
                scope=ApplicationScope(
                    application_id=trace.application_id, workspace_id=trace.workspace_id
                ),
                kind="context_trace",
                identity=trace.request_id,
                schema_version=trace.schema_version,
                sensitivity=trace.effective_sensitivity,
                summary={"input_tokens": trace.actual_input_tokens},
            )
        except Exception as error:  # noqa: BLE001 - optional retention must remain advisory
            logger.info("Optional context artifact failed error_class=%s", type(error).__name__)

    def latest_for_user_turn(self, **kwargs):
        return self.repository.latest_for_user_turn(**kwargs)


def retain_evaluation(service, rows, *, owner_id, scope, evaluation_run_id=None):
    run_id = evaluation_run_id or uuid4()
    return service.write(
        rows,
        owner_id=owner_id,
        scope=scope,
        kind="evaluation",
        identity=str(run_id),
        evaluation_run_id=run_id,
        schema_version="evaluation-observations-v1",
        jsonl=True,
        summary={"row_count": len(rows)},
        retention_days=30,
    )


def retain_routing_trace(
    service, observation, *, owner_id, scope, routing_decision_id, invocation_id=None
):
    return service.write(
        observation,
        owner_id=owner_id,
        scope=scope,
        kind="routing_trace",
        identity=str(routing_decision_id),
        routing_decision_id=routing_decision_id,
        invocation_id=invocation_id,
        schema_version="routing-artifact-v1",
        retention_days=90,
    )


def retain_debug_replay(
    service,
    observations,
    *,
    owner_id,
    scope,
    run_id,
    source_rights_until=None,
    source_rights_verified=False,
):
    return service.write(
        observations,
        owner_id=owner_id,
        scope=scope,
        kind="debug_replay",
        identity=str(run_id),
        cascade_run_id=run_id,
        schema_version="debug-replay-v1",
        jsonl=True,
        source_rights_until=source_rights_until,
        source_rights_verified=source_rights_verified,
    )
