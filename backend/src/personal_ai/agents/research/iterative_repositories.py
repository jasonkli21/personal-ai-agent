"""Owner-scoped, revision-fenced storage for Phase 8 runs and events."""

from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid4

from google.api_core.exceptions import GoogleAPICallError, RetryError

from personal_ai.agents.research.contracts import ResearchError, ResearchSession, evolve
from personal_ai.agents.research.iterative_contracts import (
    ResearchRun,
    validate_run_transition,
)
from personal_ai.agents.research.repositories import validate_save
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError
from personal_ai.storage.firestore import _firestore_client
from personal_ai.storage.transactions import bounded_transaction


def request_key(run: ResearchRun) -> str:
    return sha256(f"{run.owner_id}:{run.idempotency_key}".encode()).hexdigest()


class IterativeResearchRepository(Protocol):
    def create(self, run: ResearchRun) -> ResearchRun: ...
    def get(self, owner_id: str, run_id: UUID) -> ResearchRun: ...
    def get_by_key(self, owner_id: str, key: UUID) -> ResearchRun: ...
    def claim(self, owner_id: str, run_id: UUID, token: UUID, now, lease_until, session_deadline): ...
    def commit(
        self,
        owner_id: str,
        run: ResearchRun,
        session: ResearchSession | None = None,
    ) -> ResearchRun: ...
    def session(self, owner_id: str, session_id: UUID) -> ResearchSession: ...


class InMemoryIterativeResearchRepository:
    """Test fake sharing one lock with the Phase 5 session fake."""

    def __init__(self, sessions):
        self.session_repository = sessions
        self.runs: dict[UUID, ResearchRun] = {}
        self.keys: dict[str, UUID] = {}
        self.lock = sessions.lock

    def create(self, run):
        with self.lock:
            key = request_key(run)
            if key in self.keys:
                old = self.runs[self.keys[key]]
                if old.request_fingerprint != run.request_fingerprint:
                    raise ResearchError("idempotency_conflict", 409)
                return old
            session = self.session_repository.get(run.owner_id, run.session_id)
            if session.state != "pending":
                raise ResearchError("research_busy", 409)
            self.runs[run.id] = run
            self.keys[key] = run.id
            return run

    def get(self, owner_id, run_id):
        with self.lock:
            run = self.runs.get(run_id)
            if run is None or run.owner_id != owner_id:
                raise ResourceNotFoundError("research run not found")
            return run

    def get_by_key(self, owner_id, key):
        with self.lock:
            run_id = self.keys.get(sha256(f"{owner_id}:{key}".encode()).hexdigest())
            if run_id is None:
                raise ResourceNotFoundError("research run not found")
            return self.get(owner_id, run_id)

    def session(self, owner_id, session_id):
        return self.session_repository.get(owner_id, session_id)

    def claim(self, owner_id, run_id, token, now, lease_until, session_deadline):
        from personal_ai.agents.research.iterative_contracts import (
            RunEvent,
            RunState,
            SafeEventPayload,
        )

        with self.lock:
            run = self.get(owner_id, run_id)
            session = self.session_repository.get(owner_id, run.session_id)
            if run.state.value in {"completed", "insufficient", "failed", "cancelled"}:
                return run, session
            if run.lease_expires_at is not None and run.lease_expires_at > now:
                raise ResearchError("research_run_busy", 409)
            unresolved = any(
                attempt.status == "started"
                and not any(child.parent_attempt_id == attempt.id for child in session.attempts)
                for attempt in session.attempts
            )
            if run.lease_owner is not None and (
                run.state.value in {"extracting", "synthesizing"}
                or run.state.value == "searching" and unresolved
            ):
                raise ResearchError("research_recovery_required", 409)
            if session.state not in {"pending", "running"}:
                raise ResearchError("research_conflict", 409)
            if session.state == "running" and session.run_token != run.lease_owner:
                raise ResearchError("research_conflict", 409)
            updated_session = evolve(
                session,
                state="running",
                run_token=token,
                execution_deadline=session_deadline,
                updated_at=now,
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
            from personal_ai.agents.research.iterative_contracts import validate_run_transition
            validate_run_transition(run, candidate, lease_recovery=run.lease_owner is not None)
            self.runs[run.id] = candidate
            self.session_repository.sessions[session.id] = updated_session
            return candidate, updated_session

    def commit(self, owner_id, run, session=None):
        with self.lock:
            current = self.get(owner_id, run.id)
            try:
                validate_run_transition(current, run)
            except ValueError as error:
                raise ResearchError("research_conflict", 409) from error
            if current.lease_owner != run.lease_owner and run.lease_owner is not None:
                raise ResearchError("research_conflict", 409)
            if session is not None:
                old_session = self.session_repository.get(owner_id, session.id)
                if old_session.run_token != current.lease_owner:
                    raise ResearchError("research_conflict", 409)
                validate_save(old_session, session)
                self.session_repository.sessions[session.id] = session
            self.runs[run.id] = run
            return run


class FirestoreIterativeResearchRepository:
    """Run/event writes and fenced session changes share a Firestore transaction."""

    def __init__(self, client=None, *, project_id=None, emulator_host=None):
        self.client = client if client is not None else _firestore_client(project_id, emulator_host)
        self.runs = self.client.collection("iterative_research_runs")
        self.keys = self.client.collection("iterative_research_request_keys")
        self.sessions = self.client.collection("research_sessions")

    @staticmethod
    def _data(record):
        data = record.model_dump(mode="json")
        if isinstance(record, ResearchSession):
            data["run_token"] = str(record.run_token) if record.run_token else None
        return data

    @staticmethod
    def _decode(snapshot, owner_id):
        if not snapshot.exists:
            raise ResourceNotFoundError("research run not found")
        run = ResearchRun.model_validate(snapshot.to_dict())
        if run.owner_id != owner_id:
            raise ResourceNotFoundError("research run not found")
        return run

    @staticmethod
    def _decode_session(snapshot, owner_id):
        if not snapshot.exists:
            raise ResourceNotFoundError("research not found")
        session = ResearchSession.model_validate(snapshot.to_dict())
        if session.owner_id != owner_id:
            raise ResourceNotFoundError("research not found")
        return session

    @staticmethod
    def _run(operation):
        try:
            return operation()
        except (GoogleAPICallError, RetryError, OSError, ValueError) as error:
            raise StorageUnavailableError("iterative research storage unavailable") from error

    def create(self, run):
        def operation(transaction, timeout):
            key_ref = self.keys.document(request_key(run))
            key_snapshot = key_ref.get(transaction=transaction, retry=None, timeout=timeout())
            if key_snapshot.exists:
                data = key_snapshot.to_dict()
                if data.get("owner_id") != run.owner_id:
                    raise ResourceNotFoundError("research run not found")
                old = self._decode(
                    self.runs.document(data["run_id"]).get(
                        transaction=transaction, retry=None, timeout=timeout()
                    ),
                    run.owner_id,
                )
                if old.request_fingerprint != run.request_fingerprint:
                    raise ResearchError("idempotency_conflict", 409)
                return old
            session = self._decode_session(
                self.sessions.document(str(run.session_id)).get(
                    transaction=transaction, retry=None, timeout=timeout()
                ),
                run.owner_id,
            )
            if session.state != "pending":
                raise ResearchError("research_busy", 409)
            transaction.create(self.runs.document(str(run.id)), self._data(run))
            transaction.create(key_ref, {"owner_id": run.owner_id, "run_id": str(run.id)})
            return run

        return self._run(lambda: bounded_transaction(self.client, operation))

    def get(self, owner_id, run_id):
        return self._run(
            lambda: self._decode(
                self.runs.document(str(run_id)).get(retry=None, timeout=5), owner_id
            )
        )

    def get_by_key(self, owner_id, key):
        mapping = self._run(
            lambda: self.keys.document(
                sha256(f"{owner_id}:{key}".encode()).hexdigest()
            ).get(retry=None, timeout=5)
        )
        if not mapping.exists or mapping.to_dict().get("owner_id") != owner_id:
            raise ResourceNotFoundError("research run not found")
        return self.get(owner_id, UUID(mapping.to_dict()["run_id"]))

    def claim(self, owner_id, run_id, token, now, lease_until, session_deadline):
        from personal_ai.agents.research.iterative_contracts import (
            RunEvent,
            RunState,
            SafeEventPayload,
            validate_run_transition,
        )

        def operation(transaction, timeout):
            run_ref = self.runs.document(str(run_id))
            run = self._decode(
                run_ref.get(transaction=transaction, retry=None, timeout=timeout()), owner_id
            )
            session_ref = self.sessions.document(str(run.session_id))
            session = self._decode_session(
                session_ref.get(transaction=transaction, retry=None, timeout=timeout()), owner_id
            )
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
                id=uuid4(), run_id=run.id,
                sequence=len(run.events), event_type="assessing",
                idempotency_key=f"lease:{run.revision + 1}",
                safe_payload=SafeEventPayload(iteration=run.current_iteration, state=state),
                occurred_at=now,
            )
            candidate = ResearchRun.model_validate({
                **run.model_dump(), "state": state, "lease_owner": token,
                "lease_expires_at": lease_until, "updated_at": now,
                "revision": run.revision + 1, "events": (*run.events, event),
            })
            validate_run_transition(run, candidate, lease_recovery=run.lease_owner is not None)
            transaction.set(run_ref, self._data(candidate))
            transaction.set(session_ref, self._data(updated_session))
            return candidate, updated_session

        return self._run(lambda: bounded_transaction(self.client, operation))

    def session(self, owner_id, session_id):
        return self._run(
            lambda: self._decode_session(
                self.sessions.document(str(session_id)).get(retry=None, timeout=5), owner_id
            )
        )

    def commit(self, owner_id, run, session=None):
        def operation(transaction, timeout):
            run_ref = self.runs.document(str(run.id))
            current = self._decode(
                run_ref.get(transaction=transaction, retry=None, timeout=timeout()), owner_id
            )
            try:
                validate_run_transition(current, run)
            except ValueError as error:
                raise ResearchError("research_conflict", 409) from error
            if current.lease_owner != run.lease_owner and run.lease_owner is not None:
                raise ResearchError("research_conflict", 409)
            session_ref, old_session = None, None
            if session is not None:
                session_ref = self.sessions.document(str(session.id))
                old_session = self._decode_session(
                    session_ref.get(transaction=transaction, retry=None, timeout=timeout()),
                    owner_id,
                )
                if old_session.run_token != current.lease_owner:
                    raise ResearchError("research_conflict", 409)
                validate_save(old_session, session)
            transaction.set(run_ref, self._data(run))
            if session_ref is not None:
                transaction.set(session_ref, self._data(session))
            return run

        return self._run(lambda: bounded_transaction(self.client, operation))
