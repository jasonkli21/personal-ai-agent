"""Atomic bounded aggregates with owner-scoped creation and fenced execution."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import RLock
from time import monotonic
from typing import Protocol
from uuid import UUID

from google.api_core.exceptions import GoogleAPICallError, RetryError

from personal_ai.agents.research.contracts import ResearchError, ResearchSession, evolve
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError
from personal_ai.storage.firestore import _firestore_client
from personal_ai.storage.transactions import bounded_transaction


def key_id(session):
    return sha256(f"{session.owner_id}:{session.request.idempotency_key}".encode()).hexdigest()


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


class InMemoryResearchRepository:
    def __init__(self):
        self.sessions = {}
        self.keys = {}
        self.lock = RLock()

    def create(self, session):
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
            if session is None or session.owner_id != owner_id:
                raise ResourceNotFoundError("research not found")
            return session

    def claim(self, owner_id, session_id, token, now, deadline):
        with self.lock:
            session = claim_session(self.get(owner_id, session_id), token, now, deadline)
            self.sessions[session_id] = session
            return session

    def save(self, session):
        with self.lock:
            validate_save(self.get(session.owner_id, session.id), session)
            self.sessions[session.id] = session
            return session


class FirestoreResearchRepository:
    def __init__(self, client=None, *, project_id=None, emulator_host=None):
        self.client = client if client is not None else _firestore_client(project_id, emulator_host)
        self.sessions = self.client.collection("research_sessions")
        self.keys = self.client.collection("research_request_keys")

    def _run(self, operation):
        try:
            return operation()
        except (GoogleAPICallError, RetryError, OSError, ValueError) as error:
            raise StorageUnavailableError("research storage unavailable") from error

    @staticmethod
    def _decode(snapshot, owner_id):
        if not snapshot.exists:
            raise ResourceNotFoundError("research not found")
        session = ResearchSession.model_validate(snapshot.to_dict())
        if session.owner_id != owner_id:
            raise ResourceNotFoundError("research not found")
        return session

    @staticmethod
    def _data(session):
        data = session.model_dump(mode="json")
        data["run_token"] = str(session.run_token) if session.run_token else None
        return data

    def get(self, owner_id, session_id, timeout_seconds=None, deadline=None):
        def rpc_timeout():
            if deadline is None:
                return timeout_seconds or 5
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("research read deadline")
            return min(remaining, timeout_seconds) if timeout_seconds else remaining

        return self._run(
            lambda: self._decode(
                self.sessions.document(str(session_id)).get(
                    retry=None, timeout=rpc_timeout()
                ),
                owner_id,
            )
        )

    def create(self, session):
        def operation(tx, timeout):
            ref = self.keys.document(key_id(session))
            snapshot = ref.get(transaction=tx, retry=None, timeout=timeout())
            if snapshot.exists:
                mapping = snapshot.to_dict()
                if mapping["owner_id"] != session.owner_id:
                    raise ResourceNotFoundError("research not found")
                old = self._decode(
                    self.sessions.document(mapping["session_id"]).get(
                        transaction=tx, retry=None, timeout=timeout()
                    ),
                    session.owner_id,
                )
                if old.request_fingerprint != session.request_fingerprint:
                    raise ResearchError("idempotency_conflict", 409)
                return old
            tx.create(self.sessions.document(str(session.id)), self._data(session))
            tx.create(ref, {"owner_id": session.owner_id, "session_id": str(session.id)})
            return session

        return self._run(lambda: bounded_transaction(self.client, operation))

    def claim(self, owner_id, session_id, token, now, deadline):
        def operation(tx, timeout):
            ref = self.sessions.document(str(session_id))
            old = self._decode(ref.get(transaction=tx, retry=None, timeout=timeout()), owner_id)
            session = claim_session(old, token, now, deadline)
            tx.set(ref, self._data(session))
            return session

        return self._run(lambda: bounded_transaction(self.client, operation))

    def save(self, session):
        def operation(tx, timeout):
            ref = self.sessions.document(str(session.id))
            old = self._decode(
                ref.get(transaction=tx, retry=None, timeout=timeout()), session.owner_id
            )
            validate_save(old, session)
            tx.set(ref, self._data(session))
            return session

        return self._run(lambda: bounded_transaction(self.client, operation))

    def expire_due_for_owner(self, owner_id, *, now, correlation_id, limit=40):
        """Mark expired sessions ineligible while retaining evidence for export/audit."""
        from google.cloud import firestore

        # Aggregate timestamps are UTC ISO strings. A native Firestore timestamp
        # cannot match them. Query through the next whole second, then compare
        # decoded instants: ISO strings with optional fractions do not sort
        # chronologically within the same second ("...00Z" > "...00.1Z").
        now = now.astimezone(UTC)
        bound = (now + timedelta(seconds=1)).replace(microsecond=0)
        query_bound = bound.isoformat().replace("+00:00", "Z")
        serialized_now = now.isoformat().replace("+00:00", "Z")

        query = (
            self.sessions.where(filter=firestore.FieldFilter("owner_id", "==", owner_id))
            .where(
                filter=firestore.FieldFilter(
                    "state", "in", ["pending", "completed", "insufficient", "failed"]
                )
            )
            .where(filter=firestore.FieldFilter("expires_at", "<", query_bound))
            .order_by("expires_at")
            .limit(limit)
        )

        def operation():
            snapshots = tuple(query.stream(retry=None, timeout=5))
            if not snapshots:
                return 0
            batch = self.client.batch()
            expired = 0
            for snapshot in snapshots:
                values = snapshot.to_dict() or {}
                if values.get("owner_id") != owner_id or values.get("state") not in {
                    "pending", "completed", "insufficient", "failed"
                }:
                    continue
                session = self._decode(snapshot, owner_id)
                if session.expires_at > now:
                    continue
                batch.update(
                    snapshot.reference,
                    {
                        "state": "expired",
                        "answer": None,
                        "citations": [],
                        "revision": int(values.get("revision", 0)) + 1,
                        "updated_at": serialized_now,
                    },
                    option=firestore.LastUpdateOption(snapshot.update_time),
                )
                audit_id = sha256(
                    f"research-expiry\0{snapshot.id}\0{values.get('expires_at')}".encode()
                ).hexdigest()
                audit_ref = self.client.collection("audit_events").document(audit_id)
                batch.create(audit_ref, {
                    "id": audit_id,
                    "actor_subject": "service:maintenance",
                    "owner_id": owner_id,
                    "action": "research.evidence.expire",
                    "target_type": "research_session",
                    "target_id": snapshot.id,
                    "result": "expired",
                    "correlation_id": correlation_id,
                    "occurred_at": now,
                })
                expired += 1
            if expired:
                batch.commit(retry=None, timeout=5)
            return expired

        return self._run(operation)
