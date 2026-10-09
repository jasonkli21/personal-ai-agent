"""Compact canonical routing facts, normalized events and transactional root controls."""

import json
from contextlib import contextmanager
from uuid import uuid5

from personal_ai.persistence.postgres import (
    PersistenceConflict,
    PostgresPayloadRepository,
    _ensure_namespace,
)
from personal_ai.persistence.postgres_owner_lifecycle import assert_owner_unfenced
from personal_ai.routing.phase21 import (
    RoutingDecision,
    RoutingEvent,
    RoutingRecord,
    reselection_requirements_preserved,
    sources_allowed,
    transition,
)


class RoutingDecisionUnavailable(LookupError):
    pass


def database_time(connection):
    return connection.execute("SELECT clock_timestamp()").fetchone()[0]


class PostgresRoutingDecisionRepository:
    def __init__(self, database):
        self.database = database

    @contextmanager
    def transaction(self, *, owner_id):
        with self.database.transaction() as connection:
            assert_owner_unfenced(connection, owner_id)
            yield connection

    def get_in_transaction(self, connection, *, owner_id, scope, decision_id, lock=False):
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        row = connection.execute(
            "SELECT decision_facts,status,root_decision_id,parent_decision_id,created_at,replay_until,"
            "request_id,run_id FROM routing_decisions "
            "WHERE scope_id=%s AND decision_id=%s AND owner_id=%s AND application_id=%s "
            "AND workspace_id IS NOT DISTINCT FROM %s AND replay_until>clock_timestamp() "
            "AND NOT EXISTS(SELECT 1 FROM owner_lifecycle_fences WHERE owner_id=%s)"
            + (" FOR UPDATE" if lock else ""),
            (scope_id, decision_id, owner_id, scope.application_id, scope.workspace_id, owner_id),
        ).fetchone()
        if row is None:
            raise RoutingDecisionUnavailable("routing_decision_unavailable")
        try:
            decision = RoutingDecision.model_validate(row[0])
            if (
                decision.routing_decision_id != decision_id
                or decision.owner_id != owner_id
                or decision.application_id != scope.application_id
                or decision.workspace_id != scope.workspace_id
                or row[2:]
                != (
                    decision.root_decision_id,
                    decision.parent_decision_id,
                    decision.created_at,
                    decision.replay_until,
                    decision.request.request_id,
                    decision.request.run_id,
                )
            ):
                raise ValueError("routing_projection_corrupt")
            events = connection.execute(
                "SELECT payload,kind,event_id,attempt_id,sequence,owner_id,application_id,workspace_id FROM routing_decision_events "
                "WHERE scope_id=%s AND decision_id=%s ORDER BY sequence",
                (scope_id, decision_id),
            ).fetchall()
            decoded = tuple(RoutingEvent.model_validate(e[0]) for e in events)
            if any(
                (e.kind, e.event_id, e.attempt_id) != raw[1:4]
                or raw[4:] != (i, owner_id, scope.application_id, scope.workspace_id)
                for i, (e, raw) in enumerate(zip(decoded, events), start=1)
            ):
                raise ValueError("routing_event_projection_corrupt")
            return RoutingRecord(decision=decision, status=row[1], events=decoded)
        except (ValueError, TypeError) as error:
            raise RuntimeError("routing_decision_record_invalid") from error

    def get(self, *, owner_id, scope, decision_id):
        # Single snapshot prevents mixed state/events during a concurrent transition.
        with self.transaction(owner_id=owner_id) as c:
            return self.get_in_transaction(
                c, owner_id=owner_id, scope=scope, decision_id=decision_id, lock=True
            )

    def lock_root(self, c, *, owner_id, scope, decision_id):
        hint = self.get_in_transaction(c, owner_id=owner_id, scope=scope, decision_id=decision_id)
        root = self.get_in_transaction(
            c, owner_id=owner_id, scope=scope, decision_id=hint.decision.root_decision_id, lock=True
        )
        if root.decision.routing_decision_id != root.decision.root_decision_id:
            raise PersistenceConflict("routing_root_corrupt")
        return self.get_in_transaction(
            c, owner_id=owner_id, scope=scope, decision_id=decision_id, lock=True
        )

    def begin(self, *, owner_id, scope, decision):
        decision = RoutingDecision.model_validate(decision.model_dump())
        if (decision.owner_id, decision.application_id, decision.workspace_id) != (
            owner_id,
            scope.application_id,
            scope.workspace_id,
        ):
            raise ValueError("routing_scope_mismatch")
        with self.transaction(owner_id=owner_id) as c:
            return self.begin_in_transaction(c, owner_id=owner_id, scope=scope, decision=decision)

    def begin_in_transaction(self, c, *, owner_id, scope, decision):
        decision = RoutingDecision.model_validate(decision.model_dump())
        if (decision.owner_id, decision.application_id, decision.workspace_id) != (
            owner_id,
            scope.application_id,
            scope.workspace_id,
        ):
            raise ValueError("routing_scope_mismatch")
        scope_id = _ensure_namespace(c, owner_id, scope)
        now = database_time(c)
        if decision.created_at > now:
            raise PersistenceConflict("routing_creation_in_future")
        # Lost-ack retry must win before consuming another root budget.
        try:
            existing = self.get_in_transaction(
                c,
                owner_id=owner_id,
                scope=scope,
                decision_id=decision.routing_decision_id,
                lock=True,
            )
        except RoutingDecisionUnavailable:
            existing = None
        if existing:
            if not same_request(existing.decision, decision):
                raise PersistenceConflict("routing_decision_idempotency_conflict")
            return existing
        if decision.parent_decision_id:
            parent = self.lock_root(
                c, owner_id=owner_id, scope=scope, decision_id=decision.parent_decision_id
            )
            p = parent.decision
            if (
                parent.status != "failed"
                or p.selected is None
                or p.task != decision.task
                or p.root_decision_id != decision.root_decision_id
                or p.reselection_depth + 1 != decision.reselection_depth
                or p.root_deadline_at != decision.root_deadline_at
                or p.request.request_id != decision.request.request_id
                or p.request.run_id != decision.request.run_id
                or p.request.policy_version != decision.request.policy_version
                or not reselection_requirements_preserved(
                    p.request.requirements, decision.request.requirements
                )
                or not sources_allowed(p, decision.request.source_reference_sha256s)
                or not set(p.request.excluded_endpoint_profile_ids).issubset(
                    decision.request.excluded_endpoint_profile_ids
                )
                or p.selected.endpoint_profile_id
                not in decision.request.excluded_endpoint_profile_ids
                or decision.replay_until > p.replay_until
                or now >= p.root_deadline_at
            ):
                raise PersistenceConflict("routing_reselection_parent_not_retryable")
            # An unresolved physical send can never authorize another selection.
            unresolved = c.execute(
                "SELECT 1 FROM provider_invocations i JOIN provider_attempts a USING(invocation_id) "
                "WHERE i.owner_id=%s AND i.application_id=%s "
                "AND i.workspace_id IS NOT DISTINCT FROM %s AND i.request_id=%s "
                "AND a.status IN ('pending','unknown','timeout') LIMIT 1",
                (
                    owner_id,
                    decision.application_id,
                    decision.workspace_id,
                    decision.request.request_id,
                ),
            ).fetchone()
            if unresolved:
                raise PersistenceConflict("provider_outcome_unresolved")
            # Reselection is a single-child chain, not a branching policy. Its
            # validated depth is the consumed root budget; no duplicate counter.
            self.append_in_transaction(
                c,
                scope=scope,
                record=parent,
                event=RoutingEvent(
                    kind="reselected",
                    event_id=uuid5(decision.routing_decision_id, "parent-link"),
                    occurred_at=decision.created_at,
                    linked_decision_id=decision.routing_decision_id,
                ),
            )
        status = "selected" if decision.selected else "no_route"
        inserted = c.execute(
            "INSERT INTO routing_decisions(scope_id,decision_id,owner_id,application_id,workspace_id,"
            "request_id,run_id,root_decision_id,parent_decision_id,status,decision_facts,created_at,replay_until) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s) "
            "ON CONFLICT DO NOTHING RETURNING decision_id",
            (
                scope_id,
                decision.routing_decision_id,
                owner_id,
                scope.application_id,
                scope.workspace_id,
                decision.request.request_id,
                decision.request.run_id,
                decision.root_decision_id,
                decision.parent_decision_id,
                status,
                decision.model_dump_json(),
                decision.created_at,
                decision.replay_until,
            ),
        ).fetchone()
        if inserted is None:
            raise PersistenceConflict("routing_decision_idempotency_conflict")
        event = RoutingEvent(
            kind=status,
            event_id=uuid5(decision.routing_decision_id, "initial"),
            occurred_at=decision.created_at,
            reason=decision.no_route_reason,
        )
        self._insert_event(c, scope, decision, event, 1)
        return RoutingRecord(decision=decision, status=status, events=(event,))

    def _insert_event(self, c, scope, decision, event, sequence):
        c.execute(
            "INSERT INTO routing_decision_events(scope_id,decision_id,event_id,sequence,owner_id,"
            "application_id,workspace_id,kind,attempt_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            (
                PostgresPayloadRepository.scope_id(decision.owner_id, scope),
                decision.routing_decision_id,
                event.event_id,
                sequence,
                decision.owner_id,
                scope.application_id,
                scope.workspace_id,
                event.kind,
                event.attempt_id,
                event.model_dump_json(),
            ),
        )

    def append_in_transaction(self, c, *, scope, record, event):
        event = RoutingEvent.model_validate(event.model_dump())
        duplicate = next((e for e in record.events if e.event_id == event.event_id), None)
        if duplicate:
            if duplicate != event:
                raise PersistenceConflict("routing_event_idempotency_conflict")
            return record
        if event.occurred_at > database_time(c):
            raise PersistenceConflict("routing_event_in_future")
        updated = RoutingRecord(
            decision=record.decision,
            status=transition(record.status, event.kind),
            events=(*record.events, event),
        )
        self._insert_event(c, scope, record.decision, event, len(updated.events))
        c.execute(
            "UPDATE routing_decisions SET status=%s WHERE scope_id=%s AND decision_id=%s",
            (
                updated.status,
                PostgresPayloadRepository.scope_id(record.decision.owner_id, scope),
                record.decision.routing_decision_id,
            ),
        )
        return updated

    def consume_auxiliary_call(self, *, owner_id, scope, decision_id, event_id):
        with self.transaction(owner_id=owner_id) as c:
            record = self.lock_root(c, owner_id=owner_id, scope=scope, decision_id=decision_id)
            scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
            row = c.execute(
                "SELECT auxiliary_calls_used FROM routing_decisions WHERE scope_id=%s AND decision_id=%s",
                (scope_id, record.decision.root_decision_id),
            ).fetchone()
            duplicate = next((e for e in record.events if e.event_id == event_id), None)
            if duplicate:
                if duplicate.kind != "auxiliary":
                    raise PersistenceConflict("routing_event_idempotency_conflict")
                return row[0]
            now = database_time(c)
            if record.status != "selected" or now >= record.decision.root_deadline_at:
                raise PersistenceConflict("routing_auxiliary_not_permitted")
            maximum = record.decision.task.max_auxiliary_calls
            if row[0] >= maximum:
                raise PersistenceConflict("routing_auxiliary_call_budget_exceeded")
            c.execute(
                "UPDATE routing_decisions SET auxiliary_calls_used=auxiliary_calls_used+1 "
                "WHERE scope_id=%s AND decision_id=%s",
                (scope_id, record.decision.root_decision_id),
            )
            self.append_in_transaction(
                c,
                scope=scope,
                record=record,
                event=RoutingEvent(kind="auxiliary", event_id=event_id, occurred_at=now),
            )
            return row[0] + 1

    def list(self, *, owner_id, scope, request_id=None, limit=50):
        if request_id is None or not 1 <= limit <= 100:
            raise ValueError("routing_list_scope_required")
        with self.transaction(owner_id=owner_id) as c:
            rows = c.execute(
                "SELECT decision_id FROM routing_decisions WHERE owner_id=%s "
                "AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND request_id=%s AND replay_until>clock_timestamp() ORDER BY created_at LIMIT %s",
                (owner_id, scope.application_id, scope.workspace_id, request_id, limit),
            ).fetchall()
            return tuple(
                self.get_in_transaction(
                    c, owner_id=owner_id, scope=scope, decision_id=r[0], lock=True
                )
                for r in rows
            )

    def legacy_audit(self, *, owner_id, scope, decision_id):
        """Read-only retained V1 data. Historical strategy code is unavailable.

        No V1 object constructor, validator, writer or executor remains active.
        """
        with self.transaction(owner_id=owner_id) as c:
            row = c.execute(
                "SELECT decision_facts,outcome_events FROM routing_decisions_legacy "
                "WHERE owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND decision_id=%s AND replay_until>clock_timestamp()",
                (owner_id, scope.application_id, scope.workspace_id, decision_id),
            ).fetchone()
        if row is None:
            raise RoutingDecisionUnavailable("legacy_routing_audit_unavailable")
        facts, events = row
        if (
            not isinstance(facts, dict)
            or not isinstance(events, list)
            or facts.get("schema_version") != "routing-decision-v1"
            or facts.get("routing_decision_id") != str(decision_id)
            or (facts.get("owner_id"), facts.get("application_id"), facts.get("workspace_id"))
            != (owner_id, scope.application_id, scope.workspace_id)
            or len(json.dumps(facts).encode()) > 98304
            or len(json.dumps(events).encode()) > 98304
        ):
            raise RuntimeError("legacy_routing_audit_invalid")
        return {
            "decision_facts": row[0],
            "events": row[1],
            "replay_status": "historical_strategy_unavailable",
        }

    def purge_expired(self, *, limit=500):
        if not 1 <= limit <= 10000:
            raise ValueError("routing_purge_limit_invalid")
        with self.database.transaction() as c:
            total = 0
            for table in ("routing_decisions", "routing_decisions_legacy"):
                total += c.execute(
                    f"WITH expired AS (SELECT scope_id,decision_id FROM {table} WHERE replay_until<=clock_timestamp() "
                    f"ORDER BY replay_until LIMIT %s FOR UPDATE SKIP LOCKED) DELETE FROM {table} d USING expired e "
                    "WHERE d.scope_id=e.scope_id AND d.decision_id=e.decision_id",
                    (limit,),
                ).rowcount
            return total


def same_request(a, b):
    return (
        a.routing_decision_id,
        a.root_decision_id,
        a.parent_decision_id,
        a.reselection_depth,
        a.owner_id,
        a.application_id,
        a.workspace_id,
        a.request,
        a.task,
    ) == (
        b.routing_decision_id,
        b.root_decision_id,
        b.parent_decision_id,
        b.reselection_depth,
        b.owner_id,
        b.application_id,
        b.workspace_id,
        b.request,
        b.task,
    )
