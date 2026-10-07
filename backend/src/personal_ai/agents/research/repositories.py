"""Atomic bounded aggregates with owner-scoped creation and fenced execution."""

from datetime import datetime
from hashlib import sha256
from threading import RLock
from typing import Protocol
from uuid import UUID

from personal_ai.agents.research.contracts import ResearchError, ResearchSession, evolve
from personal_ai.auth.scope import (
    STANDALONE_APPLICATION_ID,
    preserve_legacy_child_scope,
    scope_matches,
    scoped_record,
)
from personal_ai.storage.errors import ResourceNotFoundError


def key_id(session):
    namespace = (
        "" if session.application_id == STANDALONE_APPLICATION_ID and session.workspace_id is None
        else f":{session.application_id}:{session.workspace_id or ''}"
    )
    return sha256(
        f"{session.owner_id}{namespace}:{session.request.idempotency_key}".encode()
    ).hexdigest()


def claim_session(session, token, now, deadline):
    if session.iterative_run_id is not None:
        raise ResearchError("research_session_owned_by_iterative_run", 409)
    if session.state != "pending":
        raise ResearchError("research_busy", 409)
    if session.expires_at <= now:
        raise ResearchError("research_expired", 409)
    return evolve(
        session,
        state="running",
        run_token=token,
        execution_deadline=deadline,
        updated_at=now,
        revision=session.revision + 1,
    )


def validate_save(current, candidate):
    pending_iterative_cancel = (
        current.state == "pending"
        and current.iterative_run_id is not None
        and candidate.state in {"insufficient", "failed"}
        and candidate.answer is None
        and not candidate.citations
    )
    if (
        (current.state != "running" and not pending_iterative_cancel)
        or current.run_token != candidate.run_token
        or current.revision + 1 != candidate.revision
    ):
        raise ResearchError("research_conflict", 409)
    if (
        current.request != candidate.request
        or current.created_at != candidate.created_at
        or current.policy_version != candidate.policy_version
        or current.iterative_run_id != candidate.iterative_run_id
        or current.execution_deadline != candidate.execution_deadline
        or candidate.state not in {"running", "completed", "insufficient", "failed"}
    ):
        raise ResearchError("research_conflict", 409)
    if current.queries:
        if len(current.queries) > len(candidate.queries):
            raise ResearchError("research_conflict", 409)
        for old, new in zip(current.queries, candidate.queries[: len(current.queries)], strict=True):
            if old.model_dump(exclude={"state", "executed_at"}) != new.model_dump(
                exclude={"state", "executed_at"}
            ) or (old.state != "planned" and old != new):
                raise ResearchError("research_conflict", 409)
        appended = candidate.queries[len(current.queries):]
        if any(query.sequence != len(current.queries) + index for index, query in enumerate(appended)):
            raise ResearchError("research_conflict", 409)
        old_ids = {query.id for query in current.queries}
        if any(query.parent_query_id not in old_ids for query in appended if query.parent_query_id):
            raise ResearchError("research_conflict", 409)
    # Provenance is append-only; extraction may merge links before its first persistence.
    for field in ("attempts", "observations", "evidence"):
        old, new = getattr(current, field), getattr(candidate, field)
        if new[: len(old)] != old:
            raise ResearchError("research_conflict", 409)
    if current.selection and current.selection != candidate.selection:
        raise ResearchError("research_conflict", 409)


class ResearchRepository(Protocol):
    def create(self, session: ResearchSession) -> ResearchSession: ...
    def get(
        self,
        owner_id: str,
        session_id: UUID,
        timeout_seconds: float | None = None,
        deadline: float | None = None,
    ) -> ResearchSession: ...
    def claim(
        self, owner_id: str, session_id: UUID, token: UUID, now: datetime, deadline: datetime
    ) -> ResearchSession: ...
    def save(self, session: ResearchSession) -> ResearchSession: ...
    def expire_due_for_owner(
        self, owner_id: str, *, now: datetime, correlation_id: str, limit: int = 40
    ) -> int: ...


class InMemoryResearchRepository:
    def __init__(self):
        self.sessions = {}
        self.keys = {}
        self.lock = RLock()

    def create(self, session):
        session = scoped_record(session)
        with self.lock:
            key = key_id(session)
            if key in self.keys:
                old = self.get(session.owner_id, self.keys[key])
                if old.request_fingerprint != session.request_fingerprint:
                    raise ResearchError("idempotency_conflict", 409)
                return old
            self.sessions[session.id] = session
            self.keys[key] = session.id
            return session

    def get(self, owner_id, session_id, timeout_seconds=None, deadline=None):
        del timeout_seconds, deadline
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None or session.owner_id != owner_id or not scope_matches(session):
                raise ResourceNotFoundError("research not found")
            return session

    def claim(self, owner_id, session_id, token, now, deadline):
        with self.lock:
            session = claim_session(self.get(owner_id, session_id), token, now, deadline)
            self.sessions[session_id] = session
            return session

    def save(self, session):
        session = scoped_record(session)
        with self.lock:
            current = self.get(session.owner_id, session.id)
            session = preserve_legacy_child_scope(current, session)
            validate_save(current, session)
            self.sessions[session.id] = session
            return session
