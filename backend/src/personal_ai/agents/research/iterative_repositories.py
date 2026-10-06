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
from personal_ai.auth.scope import (
    STANDALONE_APPLICATION_ID,
    current_application_scope,
    data_scope_matches,
    scope_matches,
    scoped_record,
)
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError
from personal_ai.storage.firestore import _firestore_client
from personal_ai.storage.transactions import bounded_transaction


def request_key(
    owner_id: str,
    idempotency_key: UUID,
    application_id: str | None = None,
    workspace_id: str | None = None,
) -> str:
    scope = current_application_scope()
    application_id = application_id or scope.application_id
    if application_id == scope.application_id and workspace_id is None:
        workspace_id = scope.workspace_id
    namespace = (
        "" if application_id == STANDALONE_APPLICATION_ID and workspace_id is None
        else f":{application_id}:{workspace_id or ''}"
    )
    return sha256(f"{owner_id}{namespace}:{idempotency_key}".encode()).hexdigest()


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
        *,
        now=None,
        allow_expired_lease: bool = False,
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
        run = scoped_record(run)
        with self.lock:
            key = request_key(run.owner_id, run.idempotency_key, run.application_id, run.workspace_id)
            if key in self.keys:
                old = self.runs[self.keys[key]]
                if old.request_fingerprint != run.request_fingerprint:
                    raise ResearchError("idempotency_conflict", 409)
                return old
            session = self.session_repository.get(run.owner_id, run.session_id)
            if session.state != "pending" or session.iterative_run_id != run.id:
                raise ResearchError("research_busy", 409)
            self.runs[run.id] = run
            self.keys[key] = run.id
            return run

    def get(self, owner_id, run_id):
        with self.lock:
            run = self.runs.get(run_id)
            if run is None or run.owner_id != owner_id or not scope_matches(run):
                raise ResourceNotFoundError("research run not found")
            return run

    def get_by_key(self, owner_id, key):
        with self.lock:
            run_id = self.keys.get(request_key(owner_id, key))
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
            if session.iterative_run_id != run.id:
                raise ResearchError("research_conflict", 409)
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
            candidate = scoped_record(candidate)
            from personal_ai.agents.research.iterative_contracts import validate_run_transition
            validate_run_transition(run, candidate, lease_recovery=run.lease_owner is not None)
            self.runs[run.id] = candidate
            self.session_repository.sessions[session.id] = updated_session
            return candidate, updated_session

    def commit(self, owner_id, run, session=None, *, now=None, allow_expired_lease=False):
        run = scoped_record(run)
        if session is not None:
            session = scoped_record(session)
        with self.lock:
            current = self.get(owner_id, run.id)
            now = now or run.updated_at
            if (
                current.lease_owner is not None
                and current.lease_expires_at is not None
                and current.lease_expires_at <= now
                and not allow_expired_lease
            ):
                raise ResearchError("research_conflict", 409)
            try:
                validate_run_transition(current, run)
            except ValueError as error:
                raise ResearchError("research_conflict", 409) from error
            if current.lease_owner != run.lease_owner and run.lease_owner is not None:
                raise ResearchError("research_conflict", 409)
            if session is not None:
                old_session = self.session_repository.get(owner_id, session.id)
                if (
                    old_session.iterative_run_id != current.id
                    or old_session.run_token != current.lease_owner
                    or old_session.state == "pending" and current.state.value != "pending"
                ):
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
        if run.owner_id != owner_id or not scope_matches(run):
            raise ResourceNotFoundError("research run not found")
        return run

    @staticmethod
    def _decode_session(snapshot, owner_id):
        if not snapshot.exists:
            raise ResourceNotFoundError("research not found")
        session = ResearchSession.model_validate(snapshot.to_dict())
        if session.owner_id != owner_id or not scope_matches(session):
            raise ResourceNotFoundError("research not found")
        return session

    @staticmethod
    def _run(operation):
        try:
            return operation()
        except (GoogleAPICallError, RetryError, OSError, ValueError) as error:
            raise StorageUnavailableError("iterative research storage unavailable") from error

    def create(self, run):
        run = scoped_record(run)
        def operation(transaction, timeout):
            key_ref = self.keys.document(
                request_key(run.owner_id, run.idempotency_key, run.application_id, run.workspace_id)
            )
            key_snapshot = key_ref.get(transaction=transaction, retry=None, timeout=timeout())
            if key_snapshot.exists:
                data = key_snapshot.to_dict()
                if data.get("owner_id") != run.owner_id or not data_scope_matches(data):
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
            if session.state != "pending" or session.iterative_run_id != run.id:
                raise ResearchError("research_busy", 409)
            transaction.create(self.runs.document(str(run.id)), self._data(run))
            transaction.create(key_ref, {
                "owner_id": run.owner_id,
                "run_id": str(run.id),
                "application_id": run.application_id,
                "workspace_id": run.workspace_id,
                "scope_version": 2,
            })
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
                request_key(owner_id, key)
            ).get(retry=None, timeout=5)
        )
        if (not mapping.exists or mapping.to_dict().get("owner_id") != owner_id
                or not data_scope_matches(mapping.to_dict())):
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
            candidate = scoped_record(candidate)
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

    def commit(self, owner_id, run, session=None, *, now=None, allow_expired_lease=False):
        run = scoped_record(run)
        if session is not None:
            session = scoped_record(session)
        if not scope_matches(run) or session is not None and not scope_matches(session):
            raise ResourceNotFoundError("research run not found")
        def operation(transaction, timeout):
            run_ref = self.runs.document(str(run.id))
            current = self._decode(
                run_ref.get(transaction=transaction, retry=None, timeout=timeout()), owner_id
            )
            checked_at = now or run.updated_at
            if (
                current.lease_owner is not None
                and current.lease_expires_at is not None
                and current.lease_expires_at <= checked_at
                and not allow_expired_lease
            ):
                raise ResearchError("research_conflict", 409)
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
                if (
                    old_session.iterative_run_id != current.id
                    or old_session.run_token != current.lease_owner
                    or old_session.state == "pending" and current.state.value != "pending"
                ):
                    raise ResearchError("research_conflict", 409)
                validate_save(old_session, session)
            transaction.set(run_ref, self._data(run))
            if session_ref is not None:
                transaction.set(session_ref, self._data(session))
            return run

        return self._run(lambda: bounded_transaction(self.client, operation))
