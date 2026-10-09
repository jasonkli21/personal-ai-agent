"""Canonical owner-scoped Postgres routing decision observations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres import (
    PersistenceConflict,
    PostgresDatabase,
    PostgresPayloadRepository,
    _ensure_namespace,
)
from personal_ai.routing.phase21 import (
    RoutingDecisionEvent,
    RoutingDecisionObservation,
    RoutingDecisionRecord,
)


class RoutingDecisionUnavailable(LookupError):
    """The scoped observation is absent, expired, or no longer replayable."""


class PostgresRoutingDecisionRepository:
    """Immutable decision facts plus an append-only, bounded lifecycle trail."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def begin(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        observation: RoutingDecisionObservation,
        initial_event: RoutingDecisionEvent,
    ) -> None:
        _validate_scope(owner_id, scope, observation)
        if initial_event.event_type not in {"decision_preparing", "decision_no_route"}:
            raise ValueError("routing_decision_initial_event_invalid")
        facts_json = _canonical_json(observation.model_dump(mode="json"))
        events_json = _canonical_json([initial_event.model_dump(mode="json")])
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            from personal_ai.persistence.postgres_artifacts import assert_owner_unfenced

            assert_owner_unfenced(connection, owner_id)
            scope_id = _ensure_namespace(connection, owner_id, scope)
            cursor = connection.execute(
                "INSERT INTO routing_decisions(decision_id,scope_id,owner_id,application_id,"
                "workspace_id,request_id,run_id,parent_decision_id,root_decision_id,"
                "reselection_depth,lifecycle_status,"
                "decision_facts,outcome_events,created_at,updated_at,replay_until) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s) "
                "ON CONFLICT (scope_id,decision_id) DO NOTHING RETURNING decision_id",
                (
                    observation.routing_decision_id,
                    scope_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                    observation.request.request_id,
                    observation.request.run_id,
                    observation.parent_decision_id,
                    observation.root_decision_id,
                    observation.reselection_depth,
                    observation.lifecycle_status,
                    facts_json,
                    events_json,
                    observation.created_at,
                    now,
                    observation.replay_until,
                ),
            )
            if cursor.fetchone() is None:
                raise PersistenceConflict("routing decision already exists")

    def begin_reselection(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        observation: RoutingDecisionObservation,
        initial_event: RoutingDecisionEvent,
        parent_decision_id: UUID,
        max_reselections: int,
    ) -> None:
        _validate_scope(owner_id, scope, observation)
        if (
            observation.parent_decision_id != parent_decision_id
            or observation.reselection_depth < 1
            or not 1 <= max_reselections <= 4
            or observation.reselection_depth > max_reselections
            or initial_event.event_type not in {"decision_preparing", "decision_no_route"}
        ):
            raise ValueError("routing_reselection_lineage_invalid")
        facts_json = _canonical_json(observation.model_dump(mode="json"))
        events_json = _canonical_json([initial_event.model_dump(mode="json")])
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            from personal_ai.persistence.postgres_artifacts import assert_owner_unfenced

            assert_owner_unfenced(connection, owner_id)
            root = connection.execute(
                "SELECT root_decision_id,reselection_count,replay_until FROM routing_decisions "
                "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s FOR UPDATE",
                (
                    scope_id,
                    observation.root_decision_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                ),
            ).fetchone()
            if root is None or root[0] != observation.root_decision_id or root[2] <= now:
                raise RoutingDecisionUnavailable("routing reselection root unavailable")
            if int(root[1]) >= max_reselections:
                raise PersistenceConflict("routing_reselection_budget_exceeded")
            parent_row = connection.execute(
                "SELECT decision_facts,outcome_events,root_decision_id,reselection_depth,"
                "lifecycle_status,replay_until FROM routing_decisions WHERE scope_id=%s "
                "AND decision_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s FOR UPDATE",
                (
                    scope_id,
                    parent_decision_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                ),
            ).fetchone()
            if parent_row is None or parent_row[5] <= now:
                raise RoutingDecisionUnavailable("routing reselection parent unavailable")
            parent_record = _decode_record(parent_row[0], parent_row[1])
            parent = parent_record.observation
            if (
                parent_row[2] != observation.root_decision_id
                or int(parent_row[3]) + 1 != observation.reselection_depth
                or parent_row[4] != "preparing"
                or parent.routing_decision_id != parent_decision_id
                or parent_record.events[-1].event_type not in {
                    "preparation_failed", "reservation_failed", "dispatch_failed"
                }
                or parent.task != observation.task
                or parent.request.request_id != observation.request.request_id
                or parent.policy_version != observation.policy_version
                or parent.request.source_manifest_sha256
                != observation.request.source_manifest_sha256
            ):
                raise PersistenceConflict("routing_reselection_parent_not_retryable")
            parent_event = RoutingDecisionEvent(
                event_type="reselection_linked",
                occurred_at=observation.created_at,
                linked_decision_id=observation.routing_decision_id,
                outcome_code="reselection-created",
            )
            parent_events_json = _canonical_json([parent_event.model_dump(mode="json")])
            if len(parent_record.events) >= 32:
                raise PersistenceConflict("routing_reselection_parent_event_limit")
            updated_parent = connection.execute(
                "UPDATE routing_decisions SET outcome_events=outcome_events || %s::jsonb,"
                "updated_at=%s WHERE scope_id=%s AND decision_id=%s AND owner_id=%s "
                "AND replay_until>%s AND jsonb_array_length(outcome_events)<32 "
                "AND octet_length((outcome_events || %s::jsonb)::text)<=65536",
                (
                    parent_events_json,
                    now,
                    scope_id,
                    parent_decision_id,
                    owner_id,
                    now,
                    parent_events_json,
                ),
            )
            if updated_parent.rowcount != 1:
                raise PersistenceConflict("routing_reselection_parent_update_failed")
            updated_root = connection.execute(
                "UPDATE routing_decisions SET reselection_count=reselection_count+1 "
                "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s "
                "AND reselection_count<%s RETURNING reselection_count",
                (scope_id, observation.root_decision_id, owner_id, max_reselections),
            )
            if updated_root.fetchone() is None:
                raise PersistenceConflict("routing_reselection_budget_exceeded")
            child = connection.execute(
                "INSERT INTO routing_decisions(decision_id,scope_id,owner_id,application_id,"
                "workspace_id,request_id,run_id,parent_decision_id,root_decision_id,"
                "reselection_depth,lifecycle_status,decision_facts,outcome_events,created_at,"
                "updated_at,replay_until) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "%s::jsonb,%s::jsonb,%s,%s,%s) ON CONFLICT (scope_id,decision_id) "
                "DO NOTHING RETURNING decision_id",
                (
                    observation.routing_decision_id,
                    scope_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                    observation.request.request_id,
                    observation.request.run_id,
                    observation.parent_decision_id,
                    observation.root_decision_id,
                    observation.reselection_depth,
                    observation.lifecycle_status,
                    facts_json,
                    events_json,
                    observation.created_at,
                    now,
                    observation.replay_until,
                ),
            )
            if child.fetchone() is None:
                raise PersistenceConflict("routing decision already exists")

    def append_event(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        decision_id: UUID,
        event: RoutingDecisionEvent,
    ) -> RoutingDecisionRecord:
        event_json = _canonical_json(event.model_dump(mode="json"))
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        with self.database.transaction() as connection:
            from personal_ai.persistence.postgres_artifacts import assert_owner_unfenced

            assert_owner_unfenced(connection, owner_id)
            cursor = connection.execute(
                "UPDATE routing_decisions SET outcome_events=outcome_events || %s::jsonb,"
                "invocation_ids=CASE WHEN %s::uuid IS NULL THEN invocation_ids ELSE "
                "array_append(invocation_ids,%s::uuid) END,updated_at=%s,"
                "attempt_ids=CASE WHEN %s::uuid IS NULL THEN attempt_ids ELSE "
                "array_append(attempt_ids,%s::uuid) END,"
                "evaluation_run_ids=CASE WHEN %s::uuid IS NULL THEN evaluation_run_ids ELSE "
                "array_append(evaluation_run_ids,%s::uuid) END "
                "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND replay_until>%s "
                "AND NOT EXISTS (SELECT 1 FROM artifact_owner_fences f WHERE f.owner_id=%s) "
                "AND jsonb_array_length(outcome_events)<32 "
                "AND octet_length((outcome_events || %s::jsonb)::text)<=65536 "
                "RETURNING decision_facts,outcome_events",
                (
                    f"[{event_json}]",
                    event.invocation_id,
                    event.invocation_id,
                    datetime.now(UTC),
                    event.attempt_id,
                    event.attempt_id,
                    event.evaluation_run_id,
                    event.evaluation_run_id,
                    scope_id,
                    decision_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                    datetime.now(UTC),
                    owner_id,
                    f"[{event_json}]",
                ),
            )
            row = cursor.fetchone()
        if row is None:
            raise RoutingDecisionUnavailable("routing decision unavailable")
        return _decode_record(row[0], row[1])

    def get(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        decision_id: UUID,
    ) -> RoutingDecisionRecord:
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT decision_facts,outcome_events FROM routing_decisions "
                "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND replay_until>%s "
                "AND NOT EXISTS (SELECT 1 FROM artifact_owner_fences f WHERE f.owner_id=%s)",
                (
                    scope_id,
                    decision_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                    datetime.now(UTC),
                    owner_id,
                ),
            ).fetchone()
        if row is None:
            raise RoutingDecisionUnavailable("routing decision unavailable")
        return _decode_record(row[0], row[1])

    def list(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        request_id: str | None = None,
        run_id: str | None = None,
        invocation_id: UUID | None = None,
        attempt_id: UUID | None = None,
        evaluation_run_id: UUID | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 50,
    ) -> tuple[RoutingDecisionRecord, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("routing_decision_list_limit_invalid")
        if (
            request_id is None
            and run_id is None
            and invocation_id is None
            and attempt_id is None
            and evaluation_run_id is None
            and created_after is None
            and created_before is None
        ):
            raise ValueError("routing_decision_list_scope_required")
        if created_after is not None:
            created_after = _aware_utc(created_after)
        if created_before is not None:
            created_before = _aware_utc(created_before)
        if (
            created_after is not None
            and created_before is not None
            and created_after > created_before
        ):
            raise ValueError("routing_decision_time_range_invalid")
        clauses = [
            "scope_id=%s",
            "owner_id=%s",
            "application_id=%s",
            "workspace_id IS NOT DISTINCT FROM %s",
            "replay_until>%s",
            "NOT EXISTS (SELECT 1 FROM artifact_owner_fences f WHERE f.owner_id=%s)",
        ]
        parameters: list[Any] = [
            PostgresPayloadRepository.scope_id(owner_id, scope),
            owner_id,
            scope.application_id,
            scope.workspace_id,
            datetime.now(UTC),
            owner_id,
        ]
        if request_id is not None:
            clauses.append("request_id=%s")
            parameters.append(request_id)
        if run_id is not None:
            clauses.append("run_id=%s")
            parameters.append(run_id)
        if created_after is not None:
            clauses.append("created_at>=%s")
            parameters.append(created_after)
        if created_before is not None:
            clauses.append("created_at<=%s")
            parameters.append(created_before)
        if invocation_id is not None:
            clauses.append("invocation_ids @> ARRAY[%s::uuid]")
            parameters.append(invocation_id)
        if attempt_id is not None:
            clauses.append("attempt_ids @> ARRAY[%s::uuid]")
            parameters.append(attempt_id)
        if evaluation_run_id is not None:
            clauses.append("evaluation_run_ids @> ARRAY[%s::uuid]")
            parameters.append(evaluation_run_id)
        parameters.append(limit)
        query = (
            "SELECT decision_facts,outcome_events FROM routing_decisions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC,decision_id DESC LIMIT %s"
        )
        with self.database.connection() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(_decode_record(row[0], row[1]) for row in rows)

    def purge_expired(self, *, limit: int = 500) -> int:
        if not 1 <= limit <= 10_000:
            raise ValueError("routing_decision_purge_limit_invalid")
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "WITH expired AS (SELECT scope_id,decision_id FROM routing_decisions "
                "WHERE replay_until<=%s ORDER BY replay_until,decision_id LIMIT %s "
                "FOR UPDATE SKIP LOCKED) DELETE FROM routing_decisions d USING expired e "
                "WHERE d.scope_id=e.scope_id AND d.decision_id=e.decision_id",
                (datetime.now(UTC), limit),
            )
            return cursor.rowcount


def _validate_scope(
    owner_id: str,
    scope: ApplicationScope,
    observation: RoutingDecisionObservation,
) -> None:
    if (
        observation.owner_id != owner_id
        or observation.application_id != scope.application_id
        or observation.workspace_id != scope.workspace_id
    ):
        raise ValueError("routing_decision_scope_mismatch")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("routing_timestamp_must_be_aware")
    return value.astimezone(UTC)


def _decode_record(facts: Any, events: Any) -> RoutingDecisionRecord:
    if isinstance(facts, str):
        try:
            facts = json.loads(facts)
        except json.JSONDecodeError as error:
            raise RuntimeError("routing_decision_record_invalid") from error
    if isinstance(events, str):
        try:
            events = json.loads(events)
        except json.JSONDecodeError as error:
            raise RuntimeError("routing_decision_record_invalid") from error
    try:
        return RoutingDecisionRecord.model_validate({
            "observation": facts,
            "events": events,
        })
    except (TypeError, ValueError) as error:
        raise RuntimeError("routing_decision_record_invalid") from error
