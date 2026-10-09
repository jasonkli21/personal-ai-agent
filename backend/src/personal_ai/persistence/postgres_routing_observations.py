"""Canonical owner-scoped Postgres routing decision observations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

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
    reselection_requirements_preserved,
    source_references_are_subset,
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
        initial_record = RoutingDecisionRecord(observation=observation, events=(initial_event,))
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
                existing = connection.execute(
                    "SELECT decision_facts,outcome_events FROM routing_decisions "
                    "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s FOR UPDATE",
                    (scope_id, observation.routing_decision_id, owner_id),
                ).fetchone()
                if existing is None:
                    raise PersistenceConflict("routing decision already exists")
                existing_record = _decode_record(existing[0], existing[1])
                if existing_record != initial_record:
                    raise PersistenceConflict("routing decision idempotency conflict")

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
        ):
            raise ValueError("routing_reselection_lineage_invalid")
        RoutingDecisionRecord(observation=observation, events=(initial_event,))
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
                or parent.request.run_id != observation.request.run_id
                or parent.policy_version != observation.policy_version
                or observation.root_deadline_at != parent.root_deadline_at
                or not reselection_requirements_preserved(
                    parent.request.requirements, observation.request.requirements
                )
                or not _source_narrowing_is_allowed(parent, observation)
                or not set(parent.request.excluded_endpoint_profile_ids).issubset(
                    observation.request.excluded_endpoint_profile_ids
                )
                or parent.provisional_plan.selected_endpoint_profile_id
                not in observation.request.excluded_endpoint_profile_ids
            ):
                raise PersistenceConflict("routing_reselection_parent_not_retryable")
            parent_event = RoutingDecisionEvent(
                event_type="reselection_linked",
                event_id=uuid5(observation.routing_decision_id, "phase21-parent-link-v1"),
                occurred_at=observation.created_at,
                linked_decision_id=observation.routing_decision_id,
                outcome_code="reselection-created",
            )
            RoutingDecisionRecord(
                observation=parent,
                events=(*parent_record.events, parent_event),
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
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        with self.database.transaction() as connection:
            from personal_ai.persistence.postgres_artifacts import assert_owner_unfenced

            assert_owner_unfenced(connection, owner_id)
            row = connection.execute(
                "SELECT decision_facts,outcome_events FROM routing_decisions "
                "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND replay_until>%s "
                "AND NOT EXISTS (SELECT 1 FROM artifact_owner_fences f WHERE f.owner_id=%s) "
                "FOR UPDATE",
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
            record = _decode_record(row[0], row[1])
            duplicate = next(
                (prior for prior in record.events if prior.event_id == event.event_id), None
            )
            if duplicate is not None:
                if duplicate != event:
                    raise PersistenceConflict("routing event idempotency conflict")
                return record
            updated = RoutingDecisionRecord(
                observation=record.observation,
                events=(*record.events, event),
            )
            if len(updated.events) > 32:
                raise PersistenceConflict("routing decision event limit exceeded")
            events_json = _canonical_json(
                [item.model_dump(mode="json") for item in updated.events]
            )
            cursor = connection.execute(
                "UPDATE routing_decisions SET outcome_events=%s::jsonb,"
                "invocation_ids=CASE WHEN %s::uuid IS NULL THEN invocation_ids ELSE "
                "array_append(invocation_ids,%s::uuid) END,updated_at=%s,"
                "attempt_ids=CASE WHEN %s::uuid IS NULL THEN attempt_ids ELSE "
                "array_append(attempt_ids,%s::uuid) END,"
                "evaluation_run_ids=CASE WHEN %s::uuid IS NULL THEN evaluation_run_ids ELSE "
                "array_append(evaluation_run_ids,%s::uuid) END "
                "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND replay_until>%s "
                "AND jsonb_array_length(outcome_events)<32 "
                "AND octet_length(%s::jsonb::text)<=65536 RETURNING decision_id",
                (
                    events_json,
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
                    events_json,
                ),
            )
            if cursor.fetchone() is None:
                raise PersistenceConflict("routing decision event publication failed")
        if row is None:
            raise RoutingDecisionUnavailable("routing decision unavailable")
        return updated

    def consume_auxiliary_call(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        decision_id: UUID,
        max_auxiliary_calls: int,
        event: RoutingDecisionEvent,
    ) -> int:
        """Atomically consume one root budget slot and persist its idempotency event."""
        if (
            event.event_type != "auxiliary_call_reserved"
            or not 0 <= max_auxiliary_calls <= 16
        ):
            raise ValueError("routing_auxiliary_call_reservation_invalid")
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        with self.database.transaction() as connection:
            from personal_ai.persistence.postgres_artifacts import assert_owner_unfenced

            assert_owner_unfenced(connection, owner_id)
            hint = connection.execute(
                "SELECT decision_facts FROM routing_decisions WHERE scope_id=%s "
                "AND decision_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND replay_until>%s",
                (
                    scope_id, decision_id, owner_id, scope.application_id,
                    scope.workspace_id, event.occurred_at,
                ),
            ).fetchone()
            if hint is None:
                raise RoutingDecisionUnavailable("routing decision unavailable")
            hinted_facts = hint[0]
            if isinstance(hinted_facts, str):
                hinted_facts = json.loads(hinted_facts)
            root_id = UUID(str(hinted_facts["root_decision_id"]))
            root_row = connection.execute(
                "SELECT auxiliary_calls_used,decision_facts,replay_until "
                "FROM routing_decisions WHERE scope_id=%s AND decision_id=%s "
                "AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s FOR UPDATE",
                (scope_id, root_id, owner_id, scope.application_id, scope.workspace_id),
            ).fetchone()
            if root_row is None or root_row[2] <= event.occurred_at:
                raise RoutingDecisionUnavailable("routing decision root unavailable")
            root_facts = root_row[1]
            if isinstance(root_facts, str):
                root_facts = json.loads(root_facts)
            root_observation = RoutingDecisionObservation.model_validate(root_facts)
            if root_observation.root_deadline_at <= event.occurred_at:
                raise PersistenceConflict("routing_root_deadline_expired")
            child_row = connection.execute(
                "SELECT decision_facts,outcome_events FROM routing_decisions "
                "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND replay_until>%s FOR UPDATE",
                (
                    scope_id, decision_id, owner_id, scope.application_id,
                    scope.workspace_id, event.occurred_at,
                ),
            ).fetchone()
            if child_row is None:
                raise RoutingDecisionUnavailable("routing decision unavailable")
            child = _decode_record(child_row[0], child_row[1])
            if child.observation.root_decision_id != root_id:
                raise PersistenceConflict("routing_decision_root_changed")
            duplicate = next(
                (prior for prior in child.events if prior.event_id == event.event_id), None
            )
            if duplicate is not None:
                if duplicate != event:
                    raise PersistenceConflict("routing event idempotency conflict")
                return int(root_row[0])
            if (
                child.observation.lifecycle_status != "preparing"
                or max_auxiliary_calls > child.observation.task.max_auxiliary_calls
            ):
                raise PersistenceConflict("routing_auxiliary_call_not_permitted")
            updated_child = RoutingDecisionRecord(
                observation=child.observation,
                events=(*child.events, event),
            )
            used = int(root_row[0])
            if used >= max_auxiliary_calls:
                raise PersistenceConflict("routing_auxiliary_call_budget_exceeded")
            root_update = connection.execute(
                "UPDATE routing_decisions SET auxiliary_calls_used=auxiliary_calls_used+1 "
                "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s "
                "AND auxiliary_calls_used<%s AND replay_until>%s "
                "RETURNING auxiliary_calls_used",
                (scope_id, root_id, owner_id, max_auxiliary_calls, event.occurred_at),
            ).fetchone()
            if root_update is None:
                raise PersistenceConflict("routing_auxiliary_call_budget_exceeded")
            events_json = _canonical_json(
                [item.model_dump(mode="json") for item in updated_child.events]
            )
            child_update = connection.execute(
                "UPDATE routing_decisions SET outcome_events=%s::jsonb,updated_at=%s "
                "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s "
                "AND replay_until>%s AND jsonb_array_length(outcome_events)<32 "
                "AND octet_length(%s::jsonb::text)<=65536 RETURNING decision_id",
                (
                    events_json, event.occurred_at, scope_id, decision_id,
                    owner_id, event.occurred_at, events_json,
                ),
            )
            if child_update.fetchone() is None:
                raise PersistenceConflict("routing_auxiliary_call_publication_failed")
            return int(root_update[0])

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


def _source_narrowing_is_allowed(parent, child) -> bool:
    parent_refs = set(parent.request.source_reference_sha256s)
    child_refs = set(child.request.source_reference_sha256s)
    return child_refs == parent_refs or (
        parent.task.allow_source_narrowing
        and source_references_are_subset(
            child.request.source_reference_sha256s,
            parent.request.source_reference_sha256s,
        )
    )


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
