"""Postgres adapters for the P-owned research aggregates.

Research sessions, request keys, iterative runs and their session lease changes
stay in P transactions. Payloads remain bounded aggregate snapshots validated by
the existing contracts; the typed columns provide scope, replay and revision
predicates without duplicating mutable child records.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from personal_ai.agents.research.contracts import ResearchError, ResearchSession, evolve
from personal_ai.agents.research.iterative_contracts import (
    ResearchRun,
    RunEvent,
    RunState,
    SafeEventPayload,
    validate_run_transition,
)
from personal_ai.agents.research.iterative_repositories import request_key
from personal_ai.agents.research.repositories import (
    claim_session,
    key_id,
    validate_save,
)
from personal_ai.auth.scope import (
    STANDALONE_APPLICATION_ID,
    ApplicationScope,
    current_application_scope,
    data_scope_matches,
    preserve_legacy_child_scope,
    scoped_record,
)
from personal_ai.persistence.postgres import (
    PostgresDatabase,
    PostgresPayloadRepository,
    _ensure_namespace,
)
from personal_ai.storage.errors import ResourceNotFoundError


def _scope(record) -> ApplicationScope:
    return ApplicationScope(
        application_id=record.application_id, workspace_id=record.workspace_id
    )


def _payload(record) -> dict:
    value = record.model_dump(mode="json")
    # run_token is excluded from normal API serialization but is a required
    # optimistic lease fence in durable research storage.
    if isinstance(record, ResearchSession):
        value["run_token"] = str(record.run_token) if record.run_token else None
    return value


def _insert(connection, family, *, owner_id, scope, record_id, payload,
            status=None, revision=1, created_at=None, idempotency_key=None):
    scope_id = _ensure_namespace(connection, owner_id, scope)
    connection.execute(
        f"INSERT INTO {family}(record_id,scope_id,owner_id,application_id,workspace_id,"
        "record_version,status,revision,created_at,expires_at,idempotency_key,payload) "
        "VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s::jsonb)",
        (
            record_id, scope_id, owner_id, scope.application_id, scope.workspace_id,
            status, revision, created_at or datetime.now(UTC), payload.get("expires_at"),
            idempotency_key,
            PostgresPayloadRepository._json(payload),
        ),
    )
    return scope_id


def _read(connection, family, *, owner_id, scope, record_id, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    row = connection.execute(
        f"SELECT payload,revision FROM {family} WHERE scope_id=%s AND record_id=%s "
        "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s" + suffix,
        (
            PostgresPayloadRepository.scope_id(owner_id, scope), record_id, owner_id,
            scope.application_id, scope.workspace_id,
        ),
    ).fetchone()
    if row is None:
        raise ResourceNotFoundError("research not found")
    return row[0], int(row[1])


class PostgresResearchRepository:
    """Research repository preserving request replay and revision fences."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database
        self.sessions = PostgresPayloadRepository(database, "research_sessions")
        self.request_keys = PostgresPayloadRepository(database, "research_request_keys")

    @staticmethod
    def _decode(payload, owner_id, scope):
        try:
            value = ResearchSession.model_validate(payload)
        except (ValueError, TypeError, KeyError) as error:
            raise RuntimeError("research_record_invalid") from error
        if value.owner_id != owner_id or not data_scope_matches(_payload(value), scope):
            raise ResourceNotFoundError("research not found")
        return value

    def get(self, owner_id, session_id, timeout_seconds=None, deadline=None):
        scope = current_application_scope()
        with self.database.connection(timeout_seconds=timeout_seconds, deadline=deadline) as connection:
            payload, _ = _read(
                connection, "research_sessions", owner_id=owner_id, scope=scope,
                record_id=str(session_id),
            )
        return self._decode(payload, owner_id, scope)

    def create(self, session: ResearchSession) -> ResearchSession:
        session = scoped_record(session)
        scope = _scope(session)
        request_key_id = key_id(session)
        mapping_payload = {
            "owner_id": session.owner_id,
            "session_id": str(session.id),
            "application_id": scope.application_id,
            "workspace_id": scope.workspace_id,
            "scope_version": 2,
        }
        try:
            with self.database.transaction() as connection:
                scope_id = _ensure_namespace(connection, session.owner_id, scope)
                existing = connection.execute(
                    "SELECT payload FROM research_request_keys WHERE scope_id=%s "
                    "AND record_id=%s AND owner_id=%s FOR UPDATE",
                    (scope_id, request_key_id, session.owner_id),
                ).fetchone()
                if existing is not None:
                    mapping = existing[0]
                    if mapping.get("owner_id") != session.owner_id or not data_scope_matches(mapping, scope):
                        raise ResourceNotFoundError("research not found")
                    old_payload, _ = _read(
                        connection, "research_sessions", owner_id=session.owner_id,
                        scope=scope, record_id=mapping["session_id"],
                    )
                    old = self._decode(old_payload, session.owner_id, scope)
                    if old.request_fingerprint != session.request_fingerprint:
                        raise ResearchError("idempotency_conflict", 409)
                    return old
                _insert(
                    connection, "research_sessions", owner_id=session.owner_id,
                    scope=scope, record_id=str(session.id), payload=_payload(session),
                    status=session.state, revision=session.revision, created_at=session.created_at,
                )
                _insert(
                    connection, "research_request_keys", owner_id=session.owner_id,
                    scope=scope, record_id=request_key_id, payload=mapping_payload,
                    created_at=session.created_at, idempotency_key=str(session.request.idempotency_key),
                )
        except Exception as error:
            if error.__class__.__name__ != "UniqueViolation":
                raise
            old = self.get_by_key(session.owner_id, session.request.idempotency_key)
            if old.request_fingerprint != session.request_fingerprint:
                raise ResearchError("idempotency_conflict", 409) from error
            return old
        return session

    def get_by_key(self, owner_id, key):
        scope = current_application_scope()
        namespace = (
            "" if scope.application_id == STANDALONE_APPLICATION_ID and scope.workspace_id is None
            else f":{scope.application_id}:{scope.workspace_id or ''}"
        )
        identifier = sha256(f"{owner_id}{namespace}:{key}".encode()).hexdigest()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM research_request_keys WHERE scope_id=%s AND record_id=%s "
                "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
                (
                    PostgresPayloadRepository.scope_id(owner_id, scope), identifier, owner_id,
                    scope.application_id, scope.workspace_id,
                ),
            ).fetchone()
            if row is None or not data_scope_matches(row[0], scope):
                raise ResourceNotFoundError("research not found")
            payload, _ = _read(
                connection, "research_sessions", owner_id=owner_id, scope=scope,
                record_id=row[0]["session_id"],
            )
        return self._decode(payload, owner_id, scope)

    def claim(self, owner_id, session_id, token, now, deadline):
        scope = current_application_scope()
        with self.database.transaction() as connection:
            payload, revision = _read(
                connection, "research_sessions", owner_id=owner_id, scope=scope,
                record_id=str(session_id), lock=True,
            )
            current = self._decode(payload, owner_id, scope)
            candidate = claim_session(current, token, now, deadline)
            cursor = connection.execute(
                "UPDATE research_sessions SET payload=%s::jsonb,status=%s,revision=%s "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                (
                    PostgresPayloadRepository._json(_payload(candidate)), candidate.state,
                    candidate.revision, PostgresPayloadRepository.scope_id(owner_id, scope),
                    str(session_id), revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ResearchError("research_conflict", 409)
        return candidate

    def save(self, session):
        session = scoped_record(session)
        scope = _scope(session)
        with self.database.transaction() as connection:
            payload, revision = _read(
                connection, "research_sessions", owner_id=session.owner_id, scope=scope,
                record_id=str(session.id), lock=True,
            )
            current = self._decode(payload, session.owner_id, scope)
            candidate = preserve_legacy_child_scope(current, session)
            validate_save(current, candidate)
            if candidate.revision != revision + 1:
                raise ResearchError("research_conflict", 409)
            cursor = connection.execute(
                "UPDATE research_sessions SET payload=%s::jsonb,status=%s,revision=%s,updated_at=%s "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                (
                    PostgresPayloadRepository._json(_payload(candidate)), candidate.state,
                    candidate.revision, candidate.updated_at,
                    PostgresPayloadRepository.scope_id(candidate.owner_id, scope),
                    str(candidate.id), revision,
                ),
            )
            if cursor.rowcount != 1:
                raise ResearchError("research_conflict", 409)
        return candidate

    def expire_due_for_owner(self, owner_id, *, now, correlation_id, limit=40):
        """Expire bounded due sessions and append matching audit rows atomically."""
        if not 1 <= limit <= 500:
            raise ValueError("research_expiry_limit_invalid")
        now = now.astimezone(UTC)
        from personal_ai.auth.scope import ApplicationScope
        from personal_ai.persistence.postgres_auth import _append_audit

        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT scope_id,record_id,payload,revision,expires_at FROM research_sessions "
                "WHERE owner_id=%s AND status=ANY(%s) AND expires_at<=%s "
                "ORDER BY expires_at,scope_id,record_id FOR UPDATE SKIP LOCKED LIMIT %s",
                (
                    owner_id, ["pending", "completed", "insufficient", "failed"], now, limit,
                ),
            ).fetchall()
            expired = 0
            for scope_id, record_id, payload, revision, expires_at in rows:
                scope = ApplicationScope(
                    application_id=payload.get("application_id", STANDALONE_APPLICATION_ID),
                    workspace_id=payload.get("workspace_id"),
                )
                session = self._decode(payload, owner_id, scope)
                if session.expires_at > now:
                    continue
                updated = evolve(
                    session,
                    state="expired",
                    answer=None,
                    citations=(),
                    updated_at=max(session.updated_at, now),
                    revision=session.revision + 1,
                )
                cursor = connection.execute(
                    "UPDATE research_sessions SET payload=%s::jsonb,status='expired',"
                    "revision=revision+1,updated_at=%s WHERE scope_id=%s AND record_id=%s "
                    "AND revision=%s AND status=ANY(%s)",
                    (
                        PostgresPayloadRepository._json(_payload(updated)), updated.updated_at,
                        scope_id, record_id, revision,
                        ["pending", "completed", "insufficient", "failed"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise ResearchError("research_conflict", 409)
                expires_value = payload.get("expires_at", expires_at.isoformat())
                audit_id = sha256((
                    f"research-expiry\0{record_id}\0{expires_value}"
                    f"\0{scope.application_id}\0{scope.workspace_id or ''}"
                ).encode()).hexdigest()
                _append_audit(
                    connection,
                    owner_id=owner_id,
                    audit_id=audit_id,
                    action="research.evidence.expire",
                    target_type="research_session",
                    target_id=record_id,
                    correlation_id=correlation_id,
                    result="expired",
                    scope=scope,
                    actor_subject="service:maintenance",
                )
                expired += 1
        return expired


class PostgresIterativeResearchRepository:
    """Run/session transactions with the existing lease and transition rules."""

    def __init__(self, database: PostgresDatabase, sessions: PostgresResearchRepository) -> None:
        self.database, self.session_repository = database, sessions

    @staticmethod
    def _decode_run(payload, owner_id, scope):
        try:
            run = ResearchRun.model_validate(payload)
        except (ValueError, TypeError, KeyError) as error:
            raise RuntimeError("research_run_invalid") from error
        if run.owner_id != owner_id or not data_scope_matches(_payload(run), scope):
            raise ResourceNotFoundError("research run not found")
        return run

    def get(self, owner_id, run_id):
        scope = current_application_scope()
        try:
            with self.database.connection() as connection:
                payload, _ = _read(
                    connection, "iterative_research_runs", owner_id=owner_id,
                    scope=scope, record_id=str(run_id),
                )
        except ResourceNotFoundError as error:
            raise ResourceNotFoundError("research run not found") from error
        return self._decode_run(payload, owner_id, scope)

    def get_by_key(self, owner_id, key):
        scope = current_application_scope()
        identifier = request_key(owner_id, key, scope.application_id, scope.workspace_id)
        with self.database.connection() as connection:
            mapping = connection.execute(
                "SELECT payload FROM iterative_research_request_keys WHERE scope_id=%s "
                "AND record_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s",
                (
                    PostgresPayloadRepository.scope_id(owner_id, scope), identifier, owner_id,
                    scope.application_id, scope.workspace_id,
                ),
            ).fetchone()
            if mapping is None or not data_scope_matches(mapping[0], scope):
                raise ResourceNotFoundError("research run not found")
            payload, _ = _read(
                connection, "iterative_research_runs", owner_id=owner_id,
                scope=scope, record_id=mapping[0]["run_id"],
            )
        return self._decode_run(payload, owner_id, scope)

    def create(self, run):
        run = scoped_record(run)
        scope = _scope(run)
        identifier = request_key(run.owner_id, run.idempotency_key, scope.application_id, scope.workspace_id)
        mapping = {
            "owner_id": run.owner_id, "run_id": str(run.id),
            "application_id": scope.application_id, "workspace_id": scope.workspace_id,
            "scope_version": 2,
        }
        try:
            with self.database.transaction() as connection:
                scope_id = _ensure_namespace(connection, run.owner_id, scope)
                old_key = connection.execute(
                    "SELECT payload FROM iterative_research_request_keys WHERE scope_id=%s "
                    "AND record_id=%s AND owner_id=%s FOR UPDATE",
                    (scope_id, identifier, run.owner_id),
                ).fetchone()
                if old_key is not None:
                    old_run, _ = _read(
                        connection, "iterative_research_runs", owner_id=run.owner_id,
                        scope=scope, record_id=old_key[0]["run_id"],
                    )
                    current = self._decode_run(old_run, run.owner_id, scope)
                    if current.request_fingerprint != run.request_fingerprint:
                        raise ResearchError("idempotency_conflict", 409)
                    return current
                session_payload, _ = _read(
                    connection, "research_sessions", owner_id=run.owner_id,
                    scope=scope, record_id=str(run.session_id), lock=True,
                )
                session = PostgresResearchRepository._decode(session_payload, run.owner_id, scope)
                if session.state != "pending" or session.iterative_run_id != run.id:
                    raise ResearchError("research_busy", 409)
                _insert(
                    connection, "iterative_research_runs", owner_id=run.owner_id,
                    scope=scope, record_id=str(run.id), payload=_payload(run),
                    status=run.state.value, revision=run.revision, created_at=run.created_at,
                )
                _insert(
                    connection, "iterative_research_request_keys", owner_id=run.owner_id,
                    scope=scope, record_id=identifier, payload=mapping,
                    created_at=run.created_at, idempotency_key=str(run.idempotency_key),
                )
        except Exception as error:
            if error.__class__.__name__ != "UniqueViolation":
                raise
            current = self.get_by_key(run.owner_id, run.idempotency_key)
            if current.request_fingerprint != run.request_fingerprint:
                raise ResearchError("idempotency_conflict", 409) from error
            return current
        return run

    def session(self, owner_id, session_id):
        return self.session_repository.get(owner_id, session_id)

    def claim(self, owner_id, run_id, token, now, lease_until, session_deadline):
        scope = current_application_scope()
        with self.database.transaction() as connection:
            run_payload, run_revision = _read(
                connection, "iterative_research_runs", owner_id=owner_id,
                scope=scope, record_id=str(run_id), lock=True,
            )
            run = self._decode_run(run_payload, owner_id, scope)
            session_payload, session_revision = _read(
                connection, "research_sessions", owner_id=owner_id, scope=scope,
                record_id=str(run.session_id), lock=True,
            )
            session = PostgresResearchRepository._decode(session_payload, owner_id, scope)
            if session.iterative_run_id != run.id:
                raise ResearchError("research_conflict", 409)
            if run.state in {RunState.COMPLETED, RunState.INSUFFICIENT, RunState.FAILED, RunState.CANCELLED}:
                return run, session
            if run.lease_expires_at is not None and run.lease_expires_at > now:
                raise ResearchError("research_run_busy", 409)
            unresolved = any(
                attempt.status == "started"
                and not any(child.parent_attempt_id == attempt.id for child in session.attempts)
                for attempt in session.attempts
            )
            if run.lease_owner is not None and (
                run.state in {RunState.EXTRACTING, RunState.SYNTHESIZING}
                or run.state == RunState.SEARCHING and unresolved
            ):
                raise ResearchError("research_recovery_required", 409)
            if session.state not in {"pending", "running"}:
                raise ResearchError("research_conflict", 409)
            if session.state == "running" and session.run_token != run.lease_owner:
                raise ResearchError("research_conflict", 409)
            updated_session = evolve(
                session, state="running", run_token=token,
                execution_deadline=session_deadline, updated_at=now,
                revision=session.revision + 1,
            )
            state = RunState.ASSESSING if run.state == RunState.PENDING else run.state
            event = RunEvent(
                id=uuid4(), run_id=run.id, sequence=len(run.events),
                event_type="assessing", idempotency_key=f"lease:{run.revision + 1}",
                safe_payload=SafeEventPayload(iteration=run.current_iteration, state=state),
                occurred_at=now,
            )
            candidate = ResearchRun.model_validate({
                **run.model_dump(), "state": state, "lease_owner": token,
                "lease_expires_at": lease_until, "updated_at": now,
                "revision": run.revision + 1, "events": (*run.events, event),
            })
            candidate = preserve_legacy_child_scope(run, scoped_record(candidate))
            validate_run_transition(run, candidate, lease_recovery=run.lease_owner is not None)
            connection.execute(
                "UPDATE iterative_research_runs SET payload=%s::jsonb,status=%s,revision=%s "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                (
                    PostgresPayloadRepository._json(_payload(candidate)), candidate.state.value,
                    candidate.revision, PostgresPayloadRepository.scope_id(owner_id, scope),
                    str(run.id), run_revision,
                ),
            )
            connection.execute(
                "UPDATE research_sessions SET payload=%s::jsonb,status=%s,revision=%s,updated_at=%s "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                (
                    PostgresPayloadRepository._json(_payload(updated_session)), updated_session.state,
                    updated_session.revision, updated_session.updated_at,
                    PostgresPayloadRepository.scope_id(owner_id, scope), str(session.id), session_revision,
                ),
            )
        return candidate, updated_session

    def commit(self, owner_id, run, session=None, *, now=None, allow_expired_lease=False):
        run = scoped_record(run)
        if session is not None:
            session = scoped_record(session)
        scope = _scope(run)
        with self.database.transaction() as connection:
            old_payload, run_revision = _read(
                connection, "iterative_research_runs", owner_id=owner_id,
                scope=scope, record_id=str(run.id), lock=True,
            )
            current = self._decode_run(old_payload, owner_id, scope)
            candidate_run = preserve_legacy_child_scope(current, run)
            checked_at = now or run.updated_at
            if (
                current.lease_owner is not None and current.lease_expires_at is not None
                and current.lease_expires_at <= checked_at and not allow_expired_lease
            ):
                raise ResearchError("research_conflict", 409)
            try:
                validate_run_transition(current, candidate_run)
            except ValueError as error:
                raise ResearchError("research_conflict", 409) from error
            if current.lease_owner != candidate_run.lease_owner and candidate_run.lease_owner is not None:
                raise ResearchError("research_conflict", 409)
            candidate_session = None
            session_revision = None
            if session is not None:
                old_session_payload, session_revision = _read(
                    connection, "research_sessions", owner_id=owner_id, scope=scope,
                    record_id=str(session.id), lock=True,
                )
                old_session = PostgresResearchRepository._decode(old_session_payload, owner_id, scope)
                candidate_session = preserve_legacy_child_scope(old_session, session)
                if (
                    old_session.iterative_run_id != current.id
                    or old_session.run_token != current.lease_owner
                    or old_session.state == "pending" and current.state != RunState.PENDING
                ):
                    raise ResearchError("research_conflict", 409)
                validate_save(old_session, candidate_session)
            connection.execute(
                "UPDATE iterative_research_runs SET payload=%s::jsonb,status=%s,revision=%s,updated_at=%s "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                (
                    PostgresPayloadRepository._json(_payload(candidate_run)), candidate_run.state.value,
                    candidate_run.revision, candidate_run.updated_at,
                    PostgresPayloadRepository.scope_id(owner_id, scope), str(run.id), run_revision,
                ),
            )
            if candidate_session is not None:
                connection.execute(
                    "UPDATE research_sessions SET payload=%s::jsonb,status=%s,revision=%s,updated_at=%s "
                    "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                    (
                        PostgresPayloadRepository._json(_payload(candidate_session)), candidate_session.state,
                        candidate_session.revision, candidate_session.updated_at,
                        PostgresPayloadRepository.scope_id(owner_id, scope), str(session.id), session_revision,
                    ),
                )
        return candidate_run
