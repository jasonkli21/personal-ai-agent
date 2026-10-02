"""Lifecycle persistence adapters with owner isolation and lease fencing."""

from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from threading import RLock
from time import monotonic
from uuid import NAMESPACE_URL, UUID, uuid5

from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector

from personal_ai.context.contracts import fingerprint
from personal_ai.entities import Message, MessageRole, MessageStatus
from personal_ai.memory.contracts import DerivedMemory, Memory
from personal_ai.memory.lifecycle import (
    MemoryJob,
    MemoryLifecycleEvent,
    MemoryLifecycleOutcome,
    MemoryLifecycleState,
    transition,
)
from personal_ai.memory.repositories import FirestoreMemoryRepository
from personal_ai.memory.services import source_messages
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError

_OPERATION_DEADLINE = ContextVar("memory_lifecycle_deadline", default=None)


@contextmanager
def lifecycle_deadline(seconds):
    """Share one wall-clock RPC allowance across retrieval or a worker operation."""
    previous = _OPERATION_DEADLINE.get()
    deadline = monotonic() + seconds
    token = _OPERATION_DEADLINE.set(min(previous, deadline) if previous else deadline)
    try:
        yield
    finally:
        _OPERATION_DEADLINE.reset(token)


def rpc_timeout():
    deadline = _OPERATION_DEADLINE.get()
    left = 5 if deadline is None else min(5, deadline - monotonic())
    if left <= 0:
        raise TimeoutError("memory_lifecycle_timeout")
    return left


class _BoundedTransaction:
    def __init__(self, transaction):
        self.transaction = transaction

    def get(self, reference):
        if hasattr(reference, "path"):
            return iter(
                (reference.get(transaction=self.transaction, retry=None, timeout=rpc_timeout()),)
            )
        return reference.stream(transaction=self.transaction, retry=None, timeout=rpc_timeout())

    def __getattr__(self, name):
        return getattr(self.transaction, name)


def _same_job_intent(first, second):
    fields = {
        "status",
        "attempt_count",
        "lease_expires_at",
        "lease_token",
        "lease_generation",
        "publish_pending",
        "retry_reason",
        "next_attempt_at",
        "updated_at",
    }
    return first.model_dump(exclude=fields) == second.model_dump(exclude=fields)


def _compatible_derivation(derived, sources):
    from personal_ai.memory.lifecycle import IMPORTANCE_BY_TYPE

    records = [record for record, _ in sources]
    source_type = records[0].memory_type
    target_type = {"preference": "preference", "episodic_observation": "semantic_summary"}.get(
        source_type
    )
    importance = max(
        state.importance if state.importance is not None else IMPORTANCE_BY_TYPE[record.memory_type]
        for record, state in sources
    )
    return (
        all(record.memory_type == source_type for record in records)
        and len({record.normalized_content for record in records}) == 1
        and derived.memory_type == target_type
        and derived.importance <= importance
        and derived.confidence <= min(record.confidence for record in records)
        and derived.effective_at == max(record.effective_at for record in records)
    )


def event_idempotency_id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, "personal-ai-memory-event:" + key)


def job_idempotency_id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, "personal-ai-memory-job:" + key)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp_invalid")
    return value.astimezone(UTC)


def _base_state(owner_id: str, memory_id: UUID) -> MemoryLifecycleState:
    return MemoryLifecycleState(owner_id=owner_id, memory_id=memory_id)


class InMemoryMemoryLifecycleRepository:
    """Deterministic fake sharing the Phase 3 message mutation lock."""

    def __init__(self, memories, messages, *, clock=None):
        self.memories, self.messages = memories, messages
        self.clock = clock or (lambda: datetime.now(UTC))
        self.states: dict[tuple[str, UUID], MemoryLifecycleState] = {}
        self.events: dict[tuple[str, UUID], list[MemoryLifecycleEvent]] = {}
        self.events_by_key: dict[str, MemoryLifecycleEvent] = {}
        self.jobs: dict[UUID, MemoryJob] = {}
        self.jobs_by_key: dict[str, UUID] = {}
        self.derived_sources: dict[tuple[str, UUID], set[UUID]] = {}
        self.operations: dict[tuple[UUID, str], str] = {}
        self._lock = RLock()

    def _lock_sources(self):
        return getattr(self.messages, "_mutation_lock", self._lock)

    def _get_memory(self, owner_id: str, memory_id: UUID):
        try:
            return self.memories.get(owner_id=owner_id, memory_id=memory_id)
        except ResourceNotFoundError:
            return self.memories.get_derived(owner_id=owner_id, memory_id=memory_id)

    def _valid_source(self, memory: Memory, *, require_active: bool = True) -> bool:
        if memory.status != "active" or source_messages(memory, self.messages) is None:
            return False
        conversation = getattr(self.messages, "_conversations", None)
        # Match the transaction reservation check in the production adapter.
        if conversation is not None:
            record = conversation.get(
                owner_id=memory.owner_id, conversation_id=memory.source_conversation_id
            )
            if getattr(record, "context_preparation_id", None):
                return False
        state = self.states.get((memory.owner_id, memory.id))
        return not require_active or state is None or state.retrieval_status == "active"

    def _valid_target(self, owner_id: str, memory_id: UUID, *, require_active: bool = True) -> bool:
        memory = self._get_memory(owner_id, memory_id)
        if isinstance(memory, Memory):
            state = self.states.get((owner_id, memory_id))
            return self._valid_source(memory, require_active=require_active)
        state = self.states.get((owner_id, memory_id))
        if require_active and state and state.retrieval_status != "active":
            return False
        return all(
            self._valid_source(self.memories.get(owner_id=owner_id, memory_id=item.memory_id))
            and self.memories.get(owner_id=owner_id, memory_id=item.memory_id).source_fingerprint
            == item.source_fingerprint
            for item in memory.sources
        )

    def get_state(self, *, owner_id: str, memory_id: UUID) -> MemoryLifecycleState:
        with self._lock_sources(), self._lock:
            self._get_memory(owner_id, memory_id)
            return self.states.get((owner_id, memory_id), _base_state(owner_id, memory_id))

    def list_events(self, *, owner_id: str, memory_id: UUID, limit: int = 50):
        if limit < 1 or limit > 100:
            raise ValueError("event_limit_invalid")
        with self._lock:
            self._get_memory(owner_id, memory_id)
            items = self.events.get((owner_id, memory_id), [])
            return tuple(
                sorted(items, key=lambda e: (e.expected_state_version, str(e.id)))[-limit:]
            )

    def find_event(self, *, owner_id: str, memory_id: UUID, idempotency_key: str):
        with self._lock:
            event = self.events_by_key.get(idempotency_key)
            if event is None:
                return None
            if event.owner_id != owner_id or event.memory_id != memory_id:
                raise ResourceNotFoundError("memory event not found")
            return event

    def apply_event(
        self,
        event: MemoryLifecycleEvent,
        *,
        completed_assistant_id: UUID | None = None,
        job: MemoryJob | None = None,
        lease_token: UUID | None = None,
    ) -> MemoryLifecycleOutcome:
        with self._lock_sources(), self._lock:
            old = self.events_by_key.get(event.idempotency_key)
            if old:
                if old.model_dump() != event.model_dump():
                    raise ValueError("idempotency_key_reused")
                return MemoryLifecycleOutcome(
                    status="replayed",
                    state=self.get_state(owner_id=event.owner_id, memory_id=event.memory_id),
                    event_id=old.id,
                )
            if event.id != event_idempotency_id(event.idempotency_key):
                raise ValueError("event_identity_invalid")
            if event.job_id is not None:
                current_job = (
                    self._fenced_job(job, lease_token, event.occurred_at)
                    if job is not None and lease_token is not None and job.id == event.job_id
                    else None
                )
                if (
                    current_job is None
                    or current_job.owner_id != event.owner_id
                    or event.memory_id not in current_job.candidate_memory_ids
                    or not set(event.related_memory_ids) <= set(current_job.candidate_memory_ids)
                ):
                    return MemoryLifecycleOutcome(status="conflict", reason="stale_lease")
            elif job is not None or lease_token is not None:
                raise ValueError("job_fence_unexpected")
            if completed_assistant_id is not None:
                assistant = getattr(self.messages, "_messages", {}).get(completed_assistant_id)
                if (
                    assistant is None
                    or assistant.owner_id != event.owner_id
                    or assistant.role is not MessageRole.ASSISTANT
                    or assistant.status is not MessageStatus.COMPLETED
                ):
                    return MemoryLifecycleOutcome(status="conflict", reason="assistant_incomplete")
            if not self._valid_target(
                event.owner_id, event.memory_id, require_active=event.event_type != "reactivated"
            ):
                return MemoryLifecycleOutcome(status="conflict", reason="source_inactive")
            for related_id in event.related_memory_ids:
                self._get_memory(event.owner_id, related_id)
                if not self._valid_target(event.owner_id, related_id):
                    return MemoryLifecycleOutcome(
                        status="conflict", reason="related_source_inactive"
                    )
            current = self.states.get(
                (event.owner_id, event.memory_id), _base_state(event.owner_id, event.memory_id)
            )
            if event.event_type == "forgotten":
                from personal_ai.memory.lifecycle_policy import forgetting_decision

                record = self._get_memory(event.owner_id, event.memory_id)
                dependencies = self.dependencies(owner_id=event.owner_id, memory_id=event.memory_id)
                if not forgetting_decision(
                    record,
                    current,
                    now=event.occurred_at,
                    dependencies=dependencies,
                    dependency_lookup_complete=len(dependencies) < 100,
                ).eligible:
                    return MemoryLifecycleOutcome(status="conflict", reason="protected_memory")
            if event.event_type == "superseded":
                from personal_ai.memory.lifecycle_policy import contradiction_decision

                original = self._get_memory(event.owner_id, event.memory_id)
                newer = self._get_memory(event.owner_id, event.related_memory_ids[0])
                if (
                    not isinstance(original, Memory)
                    or not isinstance(newer, Memory)
                    or contradiction_decision(original, newer) != "supersede"
                ):
                    return MemoryLifecycleOutcome(
                        status="conflict", reason="ambiguous_contradiction"
                    )
            try:
                updated = transition(current, event)
            except ValueError as error:
                if str(error) == "state_version_conflict":
                    return MemoryLifecycleOutcome(
                        status="conflict", state=current, reason="state_version_conflict"
                    )
                raise
            self.events.setdefault((event.owner_id, event.memory_id), []).append(event)
            self.events_by_key[event.idempotency_key] = event
            self.states[(event.owner_id, event.memory_id)] = updated
            if event.event_type == "consolidated":
                for derived_id in event.related_memory_ids:
                    self.derived_sources.setdefault((event.owner_id, event.memory_id), set()).add(
                        derived_id
                    )
            return MemoryLifecycleOutcome(status="applied", state=updated, event_id=event.id)

    def create_job(self, job: MemoryJob) -> tuple[MemoryJob, bool]:
        with self._lock:
            old_id = self.jobs_by_key.get(job.idempotency_key)
            if old_id:
                old = self.jobs[old_id]
                if not _same_job_intent(old, job):
                    raise ValueError("idempotency_key_reused")
                return old, False
            if job.id != job_idempotency_id(job.idempotency_key):
                raise ValueError("job_identity_invalid")
            self.jobs[job.id] = job
            self.jobs_by_key[job.idempotency_key] = job.id
            return job, True

    def get_job(self, *, owner_id: str, job_id: UUID) -> MemoryJob:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or job.owner_id != owner_id:
                raise ResourceNotFoundError("memory job not found")
            return job

    def get_job_by_id(self, *, job_id: UUID) -> MemoryJob:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise ResourceNotFoundError("memory job not found")
            return job

    def claim_job(self, *, owner_id: str, job_id: UUID, now: datetime, lease_seconds: int):
        now = _utc(now)
        with self._lock:
            job = self.get_job(owner_id=owner_id, job_id=job_id)
            if job.status in ("completed", "terminal"):
                return None
            if job.status == "leased" and job.lease_expires_at and job.lease_expires_at > now:
                return None
            if job.next_attempt_at and job.next_attempt_at > now:
                return None
            if job.attempt_count >= job.max_attempts:
                self.jobs[job.id] = job.model_copy(
                    update={
                        "status": "terminal",
                        "retry_reason": "attempts_exhausted",
                        "updated_at": now,
                    }
                )
                return None
            from uuid import uuid4

            claimed = job.model_copy(
                update={
                    "status": "leased",
                    "attempt_count": job.attempt_count + 1,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "lease_token": uuid4(),
                    "lease_generation": job.lease_generation + 1,
                    "publish_pending": False,
                    "updated_at": now,
                }
            )
            self.jobs[job.id] = claimed
            return claimed

    def _fenced_job(self, job: MemoryJob, token: UUID, now: datetime):
        current = self.jobs.get(job.id)
        if (
            current is None
            or current.owner_id != job.owner_id
            or current.status != "leased"
            or current.lease_token != token
            or current.lease_expires_at is None
            or current.lease_expires_at <= max(_utc(now), self.clock())
        ):
            return None
        return current

    def complete_job(self, job: MemoryJob, *, token: UUID, now: datetime):
        with self._lock:
            current = self._fenced_job(job, token, now)
            if current is None:
                return False
            self.jobs[job.id] = current.model_copy(
                update={
                    "status": "completed",
                    "lease_expires_at": None,
                    "lease_token": None,
                    "retry_reason": None,
                    "updated_at": _utc(now),
                }
            )
            return True

    def fail_job(self, job: MemoryJob, *, token: UUID, now: datetime, reason: str, retryable: bool):
        now = _utc(now)
        with self._lock:
            current = self._fenced_job(job, token, now)
            if current is None:
                return False
            retry = retryable and current.attempt_count < current.max_attempts
            delay = min(300, 2 ** max(0, current.attempt_count - 1))
            self.jobs[job.id] = current.model_copy(
                update={
                    "status": "retry" if retry else "terminal",
                    "retry_reason": reason[:100],
                    "next_attempt_at": now + timedelta(seconds=delay) if retry else None,
                    "lease_expires_at": None,
                    "lease_token": None,
                    "publish_pending": retry,
                    "updated_at": now,
                }
            )
            return True

    def pending_for_publish(self, *, now: datetime, limit: int = 50):
        if not 1 <= limit <= 100:
            raise ValueError("job_limit_invalid")
        now = _utc(now)
        with self._lock:
            return tuple(
                job
                for job in sorted(
                    self.jobs.values(), key=lambda item: (item.created_at, str(item.id))
                )
                if job.status in ("pending", "retry")
                and job.publish_pending
                and (job.next_attempt_at is None or job.next_attempt_at <= now)
            )[:limit]

    def mark_published(self, *, owner_id: str, job_id: UUID, updated_at: datetime):
        with self._lock:
            job = self.get_job(owner_id=owner_id, job_id=job_id)
            if job.status not in ("pending", "retry") or job.updated_at != _utc(updated_at):
                return job
            updated = job.model_copy(
                update={"publish_pending": False, "updated_at": _utc(updated_at)}
            )
            self.jobs[job_id] = updated
            return updated

    def discover_related(self, *, owner_id: str, memory_id: UUID, limit: int = 4):
        if not 1 <= limit <= 4:
            raise ValueError("candidate_limit_invalid")
        with self._lock:
            anchor = self.memories.get(owner_id=owner_id, memory_id=memory_id)
            if anchor.status != "active":
                return ()
            candidates = [
                record
                for record in self.memories.records.values()
                if record.owner_id == owner_id
                and record.memory_type == anchor.memory_type
                and record.status == "active"
                and record.id != memory_id
                and record.embedding_model == anchor.embedding_model
                and record.embedding_dimensions == anchor.embedding_dimensions
                and self._valid_source(record)
            ]
            from personal_ai.memory.contracts import vector

            target = vector(anchor.embedding, anchor.embedding_dimensions)
            ranked = sorted(
                candidates,
                key=lambda item: (
                    -sum(
                        a * b
                        for a, b in zip(
                            target, vector(item.embedding, item.embedding_dimensions), strict=True
                        )
                    ),
                    str(item.id),
                ),
            )
            return (memory_id, *(item.id for item in ranked[: limit - 1]))

    def commit_consolidation(
        self, *, job: MemoryJob, token: UUID, derived: DerivedMemory, now: datetime
    ):
        """Commit a derived record, source events and reverse links under shared fake locks."""
        now = _utc(now)
        derived = DerivedMemory.model_validate(derived.model_dump())
        with self._lock_sources(), self._lock:
            key = (job.id, "consolidate")
            prior = self.operations.get(key)
            if prior:
                if prior != str(derived.id):
                    raise ValueError("operation_key_reused")
                return "replayed"
            current_job = self._fenced_job(job, token, now)
            if current_job is None:
                return "stale_lease"
            if (
                derived.owner_id != job.owner_id
                or derived.source_memory_ids != job.candidate_memory_ids
                or len(derived.sources) != len(job.candidate_memory_ids)
            ):
                raise ValueError("job_source_mismatch")
            source_records = []
            for source in derived.sources:
                record = self.memories.get(owner_id=job.owner_id, memory_id=source.memory_id)
                state = self.states.get((job.owner_id, record.id))
                if (
                    record.status != "active"
                    or record.source_fingerprint != source.source_fingerprint
                    or state
                    and state.retrieval_status != "active"
                    or not self._valid_source(record)
                ):
                    return "source_inactive"
                source_records.append(record)
            if any(
                source.content != provenance.excerpt
                or source.source_conversation_id != provenance.source_conversation_id
                or source.source_turn_id != provenance.source_turn_id
                or source.source_message_ids != provenance.source_message_ids
                or source.embedding_model != derived.embedding_model
                or source.embedding_dimensions != derived.embedding_dimensions
                for source, provenance in zip(source_records, derived.sources, strict=True)
            ):
                return "source_mismatch"
            if not _compatible_derivation(
                derived,
                [
                    (source, self.get_state(owner_id=job.owner_id, memory_id=source.id))
                    for source in source_records
                ],
            ):
                return "source_mismatch"
            if tuple(source.id for source in source_records) != derived.source_memory_ids:
                raise ValueError("source_order_invalid")
            if derived.id in self.memories.derived_records:
                existing = self.memories.get_derived(owner_id=job.owner_id, memory_id=derived.id)
                if existing.source_set_identity != derived.source_set_identity:
                    raise ValueError("derived_identity_conflict")
                return "replayed"
            events, states = [], []
            for source in source_records:
                state = self.states.get(
                    (job.owner_id, source.id), _base_state(job.owner_id, source.id)
                )
                key_value = f"{job.id}:consolidated:{source.id}"
                event = MemoryLifecycleEvent(
                    id=event_idempotency_id(key_value),
                    owner_id=job.owner_id,
                    memory_id=source.id,
                    event_type="consolidated",
                    reason_code="derived_memory_created",
                    policy_version=job.policy_version,
                    actor="system",
                    occurred_at=now,
                    idempotency_key=key_value,
                    related_memory_ids=(derived.id,),
                    job_id=job.id,
                    expected_state_version=state.state_version,
                )
                old = self.events_by_key.get(key_value)
                if old and old.model_dump() != event.model_dump():
                    raise ValueError("idempotency_key_reused")
                events.append(event)
                states.append(transition(state, event))
            self.memories.derived_records[derived.id] = derived
            for source, event, state in zip(source_records, events, states, strict=True):
                self.events.setdefault((job.owner_id, source.id), []).append(event)
                self.events_by_key[event.idempotency_key] = event
                self.states[(job.owner_id, source.id)] = state
                self.derived_sources.setdefault((job.owner_id, source.id), set()).add(derived.id)
            self.operations[key] = str(derived.id)
            return "applied"

    def dependencies(self, *, owner_id: str, memory_id: UUID, limit: int = 100):
        if not 1 <= limit <= 100:
            raise ValueError("dependency_limit_invalid")
        with self._lock:
            self._get_memory(owner_id, memory_id)
            return tuple(
                sorted(self.derived_sources.get((owner_id, memory_id), set()), key=str)[:limit]
            )

    def rebuild_state(self, *, owner_id: str, memory_id: UUID):
        with self._lock_sources(), self._lock:
            self._get_memory(owner_id, memory_id)
            current = _base_state(owner_id, memory_id)
            events = sorted(
                self.events.get((owner_id, memory_id), []),
                key=lambda event: (event.expected_state_version, str(event.id)),
            )
            for item in events:
                current = transition(current, item)
            self.states[(owner_id, memory_id)] = current
            return current

    def discover_forgetting_candidates(
        self, *, owner_id: str, older_than: datetime, limit: int = 4
    ):
        if not 1 <= limit <= 100:
            raise ValueError("candidate_limit_invalid")
        cutoff = _utc(older_than)
        with self._lock:
            eligible = [
                memory
                for memory in self.memories.records.values()
                if memory.owner_id == owner_id
                and memory.status == "active"
                and memory.memory_type in ("episodic_observation", "semantic_summary")
                and memory.effective_at <= cutoff
                and self.states.get(
                    (owner_id, memory.id), _base_state(owner_id, memory.id)
                ).retrieval_status
                == "active"
            ]
        eligible.sort(key=lambda item: (item.effective_at, str(item.id)))
        return tuple(item.id for item in eligible[:limit])

    def discover_maintenance_candidates(self, *, owner_id: str, limit: int = 4):
        if not 1 <= limit <= 4:
            raise ValueError("candidate_limit_invalid")
        with self._lock:
            eligible = [
                memory
                for memory in self.memories.records.values()
                if memory.owner_id == owner_id
                and memory.status == "active"
                and memory.memory_type in ("preference", "explicit_correction")
                and self._valid_source(memory)
                and self.states.get(
                    (owner_id, memory.id), _base_state(owner_id, memory.id)
                ).retrieval_status
                == "active"
            ]
        eligible.sort(key=lambda item: (-item.effective_at.timestamp(), str(item.id)))
        return tuple(item.id for item in eligible[:limit])


class FirestoreMemoryLifecycleRepository:
    """Firestore event/state/job adapter; lifecycle mutations are transactional."""

    def __init__(self, memories: FirestoreMemoryRepository, messages, *, clock=None):
        self.memories, self.messages = memories, messages
        self.clock = clock or (lambda: datetime.now(UTC))
        self.client = memories.client
        self.states = self.client.collection("memory_lifecycle_states")
        self.events = self.client.collection("memory_lifecycle_events")
        self.jobs = self.client.collection("memory_lifecycle_jobs")
        self.operations = self.client.collection("memory_lifecycle_operations")
        self.relations = self.client.collection("derived_memory_sources")

    def _transaction(self, function):
        """Use bounded begin/read/commit RPCs with no hidden SDK retries."""
        with lifecycle_deadline(5):
            transaction = self.client.transaction(max_attempts=1)
            api = self.client._firestore_api
            response = api.begin_transaction(
                request={"database": self.client._database_string},
                metadata=self.client._rpc_metadata,
                retry=None,
                timeout=rpc_timeout(),
            )
            transaction._id = response.transaction
            try:
                result = function(_BoundedTransaction(transaction))
                api.commit(
                    request={
                        "database": self.client._database_string,
                        "transaction": transaction.id,
                        "writes": transaction._write_pbs,
                    },
                    metadata=self.client._rpc_metadata,
                    retry=None,
                    timeout=rpc_timeout(),
                )
                return result
            except BaseException:
                try:
                    api.rollback(
                        request={
                            "database": self.client._database_string,
                            "transaction": transaction.id,
                        },
                        metadata=self.client._rpc_metadata,
                        retry=None,
                        timeout=1,
                    )
                except Exception:  # noqa: BLE001 - preserve the original error
                    logging.getLogger(__name__).info("Lifecycle rollback failed")
                raise
            finally:
                transaction._clean_up()

    @staticmethod
    def _state_ref_id(owner_id: str, memory_id: UUID) -> str:
        return str(memory_id)

    def _get_record(self, *, owner_id: str, memory_id: UUID, timeout: float = 5):
        try:
            return self.memories.get(owner_id=owner_id, memory_id=memory_id, timeout=timeout)
        except ResourceNotFoundError:
            return self.memories.get_derived(
                owner_id=owner_id, memory_id=memory_id, timeout=timeout
            )

    def _read_state(self, owner_id: str, memory_id: UUID, *, transaction=None):
        reference = self.states.document(self._state_ref_id(owner_id, memory_id))
        snapshot = (
            next(transaction.get(reference), None)
            if transaction
            else reference.get(retry=None, timeout=rpc_timeout())
        )
        if snapshot is None or not snapshot.exists:
            return _base_state(owner_id, memory_id)
        try:
            state = MemoryLifecycleState.model_validate(snapshot.to_dict())
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("memory lifecycle projection invalid") from error
        if state.owner_id != owner_id or state.memory_id != memory_id:
            raise ResourceNotFoundError("memory not found")
        return state

    def get_state(self, *, owner_id: str, memory_id: UUID) -> MemoryLifecycleState:
        self._get_record(owner_id=owner_id, memory_id=memory_id)
        try:
            return self.memories._run(lambda: self._read_state(owner_id, memory_id))
        except GoogleAPICallError as error:
            raise StorageUnavailableError("memory lifecycle unavailable") from error

    def list_events(self, *, owner_id: str, memory_id: UUID, limit: int = 50):
        if not 1 <= limit <= 100:
            raise ValueError("event_limit_invalid")
        self._get_record(owner_id=owner_id, memory_id=memory_id)
        query = self.events.where(filter=firestore.FieldFilter("owner_id", "==", owner_id))
        query = query.where(filter=firestore.FieldFilter("memory_id", "==", str(memory_id)))
        query = query.order_by(
            "expected_state_version", direction=firestore.Query.DESCENDING
        ).limit(limit)
        snapshots = self.memories._run(
            lambda: list(query.stream(retry=None, timeout=rpc_timeout()))
        )
        try:
            return tuple(
                reversed(
                    [MemoryLifecycleEvent.model_validate(item.to_dict()) for item in snapshots]
                )
            )
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("memory lifecycle event invalid") from error

    def find_event(self, *, owner_id: str, memory_id: UUID, idempotency_key: str):
        identifier = event_idempotency_id(idempotency_key)
        snapshot = self.memories._run(
            lambda: self.events.document(str(identifier)).get(retry=None, timeout=rpc_timeout())
        )
        if not snapshot.exists:
            return None
        try:
            event = MemoryLifecycleEvent.model_validate(snapshot.to_dict())
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("memory lifecycle event invalid") from error
        if event.owner_id != owner_id or event.memory_id != memory_id:
            raise ResourceNotFoundError("memory event not found")
        return event

    def _read_original_tx(self, transaction, memory: Memory):
        """Revalidate conversation reservation, source messages and ancestors in this transaction."""
        conversation_ref = self.client.collection("conversations").document(
            str(memory.source_conversation_id)
        )
        conversation = next(transaction.get(conversation_ref), None)
        if conversation is None or not conversation.exists:
            return False
        conversation_data = conversation.to_dict()
        if conversation_data.get("owner_id") != memory.owner_id or conversation_data.get(
            "context_preparation_id"
        ):
            return False
        message_collection = self.client.collection("messages")
        collected: dict[UUID, Message] = {}
        source_records = []
        for source_id in memory.source_message_ids:
            current, first = source_id, True
            path = set()
            for _ in range(64):
                if current in path:
                    return False
                path.add(current)
                if current is None:
                    break
                if current in collected:
                    if first:
                        cached = collected[current]
                        if (
                            cached.role is not MessageRole.USER
                            or cached.status is not MessageStatus.COMPLETED
                        ):
                            return False
                        source_records.append(cached)
                    break
                reference = message_collection.document(str(current))
                snapshot = next(transaction.get(reference), None)
                if snapshot is None or not snapshot.exists:
                    return False
                try:
                    message = Message.model_validate(snapshot.to_dict())
                except (ValueError, TypeError, KeyError):
                    return False
                if (
                    message.owner_id != memory.owner_id
                    or message.conversation_id != memory.source_conversation_id
                    or message.status is MessageStatus.SUPERSEDED
                ):
                    return False
                collected[message.id] = message
                if first:
                    if (
                        message.role is not MessageRole.USER
                        or message.status is not MessageStatus.COMPLETED
                    ):
                        return False
                    source_records.append(message)
                    first = False
                current = message.parent_message_id
            else:
                return False
        assistant_ref = message_collection.document(str(memory.source_turn_id))
        assistant_snapshot = next(transaction.get(assistant_ref), None)
        if assistant_snapshot is None or not assistant_snapshot.exists:
            return False
        try:
            assistant = Message.model_validate(assistant_snapshot.to_dict())
        except (ValueError, TypeError, KeyError):
            return False
        source_valid = (
            assistant.owner_id == memory.owner_id
            and assistant.conversation_id == memory.source_conversation_id
            and assistant.role is MessageRole.ASSISTANT
            and assistant.parent_message_id in memory.source_message_ids
            and tuple(item.id for item in source_records) == memory.source_message_ids
            and fingerprint(source_records) == memory.source_fingerprint
        )
        if not source_valid:
            return False
        if assistant.status is MessageStatus.COMPLETED:
            return True
        query = message_collection
        for field, value in (
            ("owner_id", memory.owner_id),
            ("conversation_id", str(memory.source_conversation_id)),
            ("parent_message_id", str(assistant.parent_message_id)),
            ("role", "assistant"),
            ("status", "completed"),
        ):
            query = query.where(filter=firestore.FieldFilter(field, "==", value))
        completions = list(transaction.get(query.limit(2)))
        return len(completions) == 1

    def _read_record_tx(self, transaction, owner_id: str, memory_id: UUID):
        original_ref = self.client.collection("memories").document(str(memory_id))
        snapshot = next(transaction.get(original_ref), None)
        if snapshot is not None and snapshot.exists:
            record = self.memories._record(snapshot)
            if record.owner_id != owner_id:
                raise ResourceNotFoundError("memory not found")
            return record
        derived_ref = self.client.collection("derived_memories").document(str(memory_id))
        snapshot = next(transaction.get(derived_ref), None)
        if snapshot is None or not snapshot.exists:
            raise ResourceNotFoundError("memory not found")
        data = snapshot.to_dict()
        data["embedding"] = tuple(data["embedding"])
        try:
            record = DerivedMemory.model_validate(data)
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("derived memory record invalid") from error
        if record.owner_id != owner_id:
            raise ResourceNotFoundError("memory not found")
        return record

    def _valid_record_tx(
        self, transaction, owner_id: str, memory_id: UUID, *, seen=None, require_active: bool = True
    ):
        seen = seen if seen is not None else set()
        if memory_id in seen or len(seen) >= 12:
            return False
        seen.add(memory_id)
        record = self._read_record_tx(transaction, owner_id, memory_id)
        state = self._read_state(owner_id, memory_id, transaction=transaction)
        if require_active and state.retrieval_status != "active":
            return False
        if isinstance(record, Memory):
            return record.status == "active" and self._read_original_tx(transaction, record)
        for source in record.sources:
            source_record = self._read_record_tx(transaction, owner_id, source.memory_id)
            if (
                not isinstance(source_record, Memory)
                or source_record.source_fingerprint != source.source_fingerprint
            ):
                return False
            if not self._valid_record_tx(transaction, owner_id, source.memory_id, seen=seen):
                return False
        return True

    def apply_event(
        self,
        event: MemoryLifecycleEvent,
        *,
        completed_assistant_id: UUID | None = None,
        job: MemoryJob | None = None,
        lease_token: UUID | None = None,
    ) -> MemoryLifecycleOutcome:
        if event.id != event_idempotency_id(event.idempotency_key):
            raise ValueError("event_identity_invalid")
        event_ref = self.events.document(str(event.id))
        state_ref = self.states.document(self._state_ref_id(event.owner_id, event.memory_id))

        def commit(transaction):
            existing_snapshot = next(transaction.get(event_ref), None)
            current_snapshot = next(transaction.get(state_ref), None)
            if existing_snapshot is not None and existing_snapshot.exists:
                try:
                    existing = MemoryLifecycleEvent.model_validate(existing_snapshot.to_dict())
                except (ValueError, TypeError, KeyError) as error:
                    raise StorageUnavailableError("memory lifecycle event invalid") from error
                if existing.model_dump() != event.model_dump():
                    raise ValueError("idempotency_key_reused")
                state = self._read_state(event.owner_id, event.memory_id, transaction=transaction)
                return MemoryLifecycleOutcome(status="replayed", state=state, event_id=event.id)
            if completed_assistant_id is not None:
                assistant_ref = self.client.collection("messages").document(
                    str(completed_assistant_id)
                )
                assistant_snapshot = next(transaction.get(assistant_ref), None)
                if assistant_snapshot is None or not assistant_snapshot.exists:
                    return MemoryLifecycleOutcome(status="conflict", reason="assistant_incomplete")
                try:
                    assistant = Message.model_validate(assistant_snapshot.to_dict())
                except (ValueError, TypeError, KeyError):
                    return MemoryLifecycleOutcome(status="conflict", reason="assistant_incomplete")
                if (
                    assistant.owner_id != event.owner_id
                    or assistant.role is not MessageRole.ASSISTANT
                    or assistant.status is not MessageStatus.COMPLETED
                ):
                    return MemoryLifecycleOutcome(status="conflict", reason="assistant_incomplete")
            if event.job_id is not None:
                if job is None or lease_token is None or job.id != event.job_id:
                    return MemoryLifecycleOutcome(status="conflict", reason="stale_lease")
                job_snapshot = next(transaction.get(self.jobs.document(str(event.job_id))), None)
                if job_snapshot is None or not job_snapshot.exists:
                    return MemoryLifecycleOutcome(status="conflict", reason="stale_lease")
                try:
                    current_job = MemoryJob.model_validate(job_snapshot.to_dict())
                except (ValueError, TypeError, KeyError) as error:
                    raise StorageUnavailableError("memory job invalid") from error
                if (
                    current_job.owner_id != event.owner_id
                    or event.memory_id not in current_job.candidate_memory_ids
                    or not set(event.related_memory_ids) <= set(current_job.candidate_memory_ids)
                    or current_job.status != "leased"
                    or current_job.lease_token != lease_token
                    or current_job.lease_expires_at is None
                    or current_job.lease_expires_at <= max(_utc(event.occurred_at), self.clock())
                ):
                    return MemoryLifecycleOutcome(status="conflict", reason="stale_lease")
            elif job is not None or lease_token is not None:
                raise ValueError("job_fence_unexpected")
            if current_snapshot is None or not current_snapshot.exists:
                state = _base_state(event.owner_id, event.memory_id)
            else:
                try:
                    state = MemoryLifecycleState.model_validate(current_snapshot.to_dict())
                except (ValueError, TypeError, KeyError) as error:
                    raise StorageUnavailableError("memory lifecycle projection invalid") from error
            if not self._valid_record_tx(
                transaction,
                event.owner_id,
                event.memory_id,
                require_active=event.event_type != "reactivated",
            ):
                return MemoryLifecycleOutcome(status="conflict", reason="source_inactive")
            for related_id in event.related_memory_ids:
                self._read_record_tx(transaction, event.owner_id, related_id)
                if not self._valid_record_tx(transaction, event.owner_id, related_id):
                    return MemoryLifecycleOutcome(
                        status="conflict", reason="related_source_inactive"
                    )
            record = self._read_record_tx(transaction, event.owner_id, event.memory_id)
            if event.event_type == "forgotten":
                from personal_ai.memory.lifecycle_policy import forgetting_decision

                query = self.relations.where(
                    filter=firestore.FieldFilter("owner_id", "==", event.owner_id)
                )
                query = query.where(
                    filter=firestore.FieldFilter("source_memory_id", "==", str(event.memory_id))
                ).limit(100)
                dependencies = tuple(
                    UUID(item.to_dict()["derived_memory_id"]) for item in transaction.get(query)
                )
                if not forgetting_decision(
                    record,
                    state,
                    now=event.occurred_at,
                    dependencies=dependencies,
                    dependency_lookup_complete=len(dependencies) < 100,
                ).eligible:
                    return MemoryLifecycleOutcome(status="conflict", reason="protected_memory")
            if event.event_type == "superseded":
                from personal_ai.memory.lifecycle_policy import contradiction_decision

                newer = self._read_record_tx(
                    transaction, event.owner_id, event.related_memory_ids[0]
                )
                if (
                    not isinstance(record, Memory)
                    or not isinstance(newer, Memory)
                    or contradiction_decision(record, newer) != "supersede"
                ):
                    return MemoryLifecycleOutcome(
                        status="conflict", reason="ambiguous_contradiction"
                    )
            try:
                updated = transition(state, event)
            except ValueError as error:
                if str(error) == "state_version_conflict":
                    return MemoryLifecycleOutcome(
                        status="conflict", state=state, reason="state_version_conflict"
                    )
                raise
            transaction.create(event_ref, event.model_dump(mode="json"))
            transaction.set(state_ref, updated.model_dump(mode="json"))
            return MemoryLifecycleOutcome(status="applied", state=updated, event_id=event.id)

        try:
            return self.memories._run(lambda: self._transaction(commit))
        except (GoogleAPICallError, RetryError, OSError) as error:
            raise StorageUnavailableError("memory lifecycle unavailable") from error

    def create_job(self, job: MemoryJob) -> tuple[MemoryJob, bool]:
        if job.id != job_idempotency_id(job.idempotency_key):
            raise ValueError("job_identity_invalid")
        reference = self.jobs.document(str(job.id))

        def create(transaction):
            snapshot = next(transaction.get(reference), None)
            if snapshot is not None and snapshot.exists:
                try:
                    existing = MemoryJob.model_validate(snapshot.to_dict())
                except (ValueError, TypeError, KeyError) as error:
                    raise StorageUnavailableError("memory job invalid") from error
                if not _same_job_intent(existing, job):
                    raise ValueError("idempotency_key_reused")
                return existing, False
            transaction.create(reference, job.model_dump(mode="json"))
            return job, True

        return self.memories._run(lambda: self._transaction(create))

    def get_job(self, *, owner_id: str, job_id: UUID) -> MemoryJob:
        snapshot = self.memories._run(
            lambda: self.jobs.document(str(job_id)).get(retry=None, timeout=rpc_timeout())
        )
        if not snapshot.exists:
            raise ResourceNotFoundError("memory job not found")
        try:
            job = MemoryJob.model_validate(snapshot.to_dict())
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("memory job invalid") from error
        if job.owner_id != owner_id:
            raise ResourceNotFoundError("memory job not found")
        return job

    def get_job_by_id(self, *, job_id: UUID) -> MemoryJob:
        snapshot = self.memories._run(
            lambda: self.jobs.document(str(job_id)).get(retry=None, timeout=rpc_timeout())
        )
        if not snapshot.exists:
            raise ResourceNotFoundError("memory job not found")
        try:
            return MemoryJob.model_validate(snapshot.to_dict())
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("memory job invalid") from error

    def claim_job(self, *, owner_id: str, job_id: UUID, now: datetime, lease_seconds: int):
        now = _utc(now)
        reference = self.jobs.document(str(job_id))

        def claim(transaction):
            snapshot = next(transaction.get(reference), None)
            if snapshot is None or not snapshot.exists:
                raise ResourceNotFoundError("memory job not found")
            job = MemoryJob.model_validate(snapshot.to_dict())
            if job.owner_id != owner_id:
                raise ResourceNotFoundError("memory job not found")
            if job.status in ("completed", "terminal"):
                return None
            if job.status == "leased" and job.lease_expires_at and job.lease_expires_at > now:
                return None
            if job.next_attempt_at and job.next_attempt_at > now:
                return None
            if job.attempt_count >= job.max_attempts:
                transaction.update(
                    reference,
                    {
                        "status": "terminal",
                        "retry_reason": "attempts_exhausted",
                        "updated_at": now.isoformat(),
                    },
                )
                return None
            from uuid import uuid4

            claimed = job.model_copy(
                update={
                    "status": "leased",
                    "attempt_count": job.attempt_count + 1,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                    "lease_token": uuid4(),
                    "lease_generation": job.lease_generation + 1,
                    "publish_pending": False,
                    "updated_at": now,
                }
            )
            transaction.update(reference, claimed.model_dump(mode="json"))
            return claimed

        return self.memories._run(lambda: self._transaction(claim))

    def _mutate_fenced_job(self, job: MemoryJob, token: UUID, now: datetime, changes):
        now = _utc(now)
        reference = self.jobs.document(str(job.id))

        def mutate(transaction):
            snapshot = next(transaction.get(reference), None)
            if snapshot is None or not snapshot.exists:
                return False
            current = MemoryJob.model_validate(snapshot.to_dict())
            if (
                current.owner_id != job.owner_id
                or current.status != "leased"
                or current.lease_token != token
                or current.lease_expires_at is None
                or current.lease_expires_at <= max(now, self.clock())
            ):
                return False
            transaction.update(reference, {**changes, "updated_at": now.isoformat()})
            return True

        return self.memories._run(lambda: self._transaction(mutate))

    def complete_job(self, job: MemoryJob, *, token: UUID, now: datetime):
        return self._mutate_fenced_job(
            job,
            token,
            now,
            {
                "status": "completed",
                "lease_expires_at": None,
                "lease_token": None,
                "retry_reason": None,
            },
        )

    def fail_job(self, job: MemoryJob, *, token: UUID, now: datetime, reason: str, retryable: bool):
        now = _utc(now)
        retry = retryable and job.attempt_count < job.max_attempts
        delay = min(300, 2 ** max(0, job.attempt_count - 1))
        return self._mutate_fenced_job(
            job,
            token,
            now,
            {
                "status": "retry" if retry else "terminal",
                "retry_reason": reason[:100],
                "next_attempt_at": (now + timedelta(seconds=delay)).isoformat() if retry else None,
                "lease_expires_at": None,
                "lease_token": None,
                "publish_pending": retry,
            },
        )

    def pending_for_publish(self, *, now: datetime, limit: int = 50):
        if not 1 <= limit <= 100:
            raise ValueError("job_limit_invalid")
        now = _utc(now)
        records = {}
        for status in ("pending", "retry"):
            query = self.jobs.where(filter=firestore.FieldFilter("status", "==", status))
            query = query.where(filter=firestore.FieldFilter("publish_pending", "==", True))
            if status == "retry":
                query = query.where(
                    filter=firestore.FieldFilter("next_attempt_at", "<=", now.isoformat())
                )
            if status == "retry":
                query = query.order_by("next_attempt_at", direction=firestore.Query.ASCENDING)
            query = query.order_by("created_at", direction=firestore.Query.ASCENDING)
            query = query.limit(limit)
            snapshots = self.memories._run(
                lambda query=query: list(query.stream(retry=None, timeout=rpc_timeout()))
            )
            for snapshot in snapshots:
                job = MemoryJob.model_validate(snapshot.to_dict())
                if job.status == status and (
                    job.next_attempt_at is None or job.next_attempt_at <= now
                ):
                    records[job.id] = job
        return tuple(
            sorted(records.values(), key=lambda item: (item.created_at, str(item.id)))[:limit]
        )

    def mark_published(self, *, owner_id: str, job_id: UUID, updated_at: datetime):
        reference = self.jobs.document(str(job_id))

        def mutate(transaction):
            snapshot = next(transaction.get(reference), None)
            if snapshot is None or not snapshot.exists:
                raise ResourceNotFoundError("memory job not found")
            job = MemoryJob.model_validate(snapshot.to_dict())
            if job.owner_id != owner_id:
                raise ResourceNotFoundError("memory job not found")
            if job.status not in ("pending", "retry") or job.updated_at != _utc(updated_at):
                return job
            updated = job.model_copy(
                update={"publish_pending": False, "updated_at": _utc(updated_at)}
            )
            transaction.update(reference, updated.model_dump(mode="json"))
            return updated

        return self.memories._run(lambda: self._transaction(mutate))

    def discover_related(self, *, owner_id: str, memory_id: UUID, limit: int = 4):
        anchor = self.memories.get(owner_id=owner_id, memory_id=memory_id)
        result = self.memories.search(
            owner_id=owner_id,
            embedding=anchor.embedding,
            model=anchor.embedding_model,
            dimensions=anchor.embedding_dimensions,
            limit=limit,
            timeout=5,
            memory_type=anchor.memory_type,
        )
        selected = []
        for candidate in result:
            if candidate.memory.memory_type == anchor.memory_type:
                selected.append(candidate.memory.id)
            if len(selected) >= limit:
                break
        if memory_id not in selected:
            selected.insert(0, memory_id)
        return tuple(selected[:limit])

    def discover_maintenance_candidates(self, *, owner_id: str, limit: int = 4):
        if not 1 <= limit <= 4:
            raise ValueError("candidate_limit_invalid")
        found = {}
        for memory_type in ("preference", "explicit_correction"):
            query = self.client.collection("memories")
            for field, value in (
                ("owner_id", owner_id),
                ("status", "active"),
                ("memory_type", memory_type),
            ):
                query = query.where(filter=firestore.FieldFilter(field, "==", value))
            query = query.order_by("effective_at", direction=firestore.Query.DESCENDING)
            query = query.limit(min(100, limit * 4))
            snapshots = self.memories._run(
                lambda query=query: list(query.stream(retry=None, timeout=rpc_timeout()))
            )
            for snapshot in snapshots:
                memory = self.memories._record(snapshot)
                state = self.get_state(owner_id=owner_id, memory_id=memory.id)
                if state.retrieval_status == "active" and source_messages(memory, self.messages):
                    found[memory.id] = memory
        ordered = sorted(
            found.values(), key=lambda item: (-item.effective_at.timestamp(), str(item.id))
        )
        return tuple(item.id for item in ordered[:limit])

    def dependencies(self, *, owner_id: str, memory_id: UUID, limit: int = 100):
        if not 1 <= limit <= 100:
            raise ValueError("dependency_limit_invalid")
        query = self.relations.where(filter=firestore.FieldFilter("owner_id", "==", owner_id))
        query = query.where(filter=firestore.FieldFilter("source_memory_id", "==", str(memory_id)))
        snapshots = self.memories._run(
            lambda: list(query.limit(limit).stream(retry=None, timeout=rpc_timeout()))
        )
        return tuple(UUID(item.to_dict()["derived_memory_id"]) for item in snapshots)

    def rebuild_state(self, *, owner_id: str, memory_id: UUID):
        self._get_record(owner_id=owner_id, memory_id=memory_id)
        query = self.events.where(filter=firestore.FieldFilter("owner_id", "==", owner_id))
        query = query.where(filter=firestore.FieldFilter("memory_id", "==", str(memory_id)))
        query = query.order_by("expected_state_version", direction=firestore.Query.ASCENDING)
        records = []
        cursor = None
        while len(records) < 10_000:
            page = query.limit(100)
            if cursor is not None:
                page = page.start_after(cursor)
            snapshots = self.memories._run(
                lambda page=page: list(page.stream(retry=None, timeout=rpc_timeout()))
            )
            if not snapshots:
                break
            records.extend(
                MemoryLifecycleEvent.model_validate(item.to_dict()) for item in snapshots
            )
            cursor = snapshots[-1]
        if len(records) >= 10_000:
            raise StorageUnavailableError("memory lifecycle history exceeds rebuild bound")
        rebuilt = _base_state(owner_id, memory_id)
        for event in sorted(records, key=lambda item: (item.expected_state_version, str(item.id))):
            rebuilt = transition(rebuilt, event)
        reference = self.states.document(self._state_ref_id(owner_id, memory_id))

        def write(transaction):
            current_snapshot = next(transaction.get(reference), None)
            current = (
                _base_state(owner_id, memory_id)
                if current_snapshot is None or not current_snapshot.exists
                else MemoryLifecycleState.model_validate(current_snapshot.to_dict())
            )
            if current.state_version > rebuilt.state_version:
                return False
            transaction.set(reference, rebuilt.model_dump(mode="json"))
            return True

        changed = self.memories._run(lambda: self._transaction(write))
        return rebuilt if changed else self.get_state(owner_id=owner_id, memory_id=memory_id)

    def discover_forgetting_candidates(
        self, *, owner_id: str, older_than: datetime, limit: int = 4
    ):
        if not 1 <= limit <= 100:
            raise ValueError("candidate_limit_invalid")
        cutoff = _utc(older_than)
        found = {}
        for memory_type in ("episodic_observation", "semantic_summary"):
            query = self.client.collection("memories")
            for field, value in (
                ("owner_id", owner_id),
                ("status", "active"),
                ("memory_type", memory_type),
            ):
                query = query.where(filter=firestore.FieldFilter(field, "==", value))
            query = query.where(filter=firestore.FieldFilter("effective_at", "<=", cutoff))
            query = query.order_by("effective_at", direction=firestore.Query.ASCENDING).limit(limit)
            snapshots = self.memories._run(
                lambda query=query: list(query.stream(retry=None, timeout=rpc_timeout()))
            )
            for snapshot in snapshots:
                record = self.memories._record(snapshot)
                if (
                    self.get_state(owner_id=owner_id, memory_id=record.id).retrieval_status
                    == "active"
                ):
                    found[record.id] = record
        ordered = sorted(found.values(), key=lambda item: (item.effective_at, str(item.id)))
        return tuple(item.id for item in ordered[:limit])

    def commit_consolidation(
        self, *, job: MemoryJob, token: UUID, derived: DerivedMemory, now: datetime
    ):
        """Atomically revalidate lease and source provenance before derived writes."""
        now = _utc(now)
        derived = DerivedMemory.model_validate(derived.model_dump())
        operation_id = f"{job.id}:consolidate"
        operation_ref = self.operations.document(hashlib.sha256(operation_id.encode()).hexdigest())
        job_ref = self.jobs.document(str(job.id))
        derived_ref = self.client.collection("derived_memories").document(str(derived.id))

        def commit(transaction):
            operation_snapshot = next(transaction.get(operation_ref), None)
            if operation_snapshot is not None and operation_snapshot.exists:
                result = operation_snapshot.to_dict()
                if result.get("derived_memory_id") != str(derived.id):
                    raise ValueError("operation_key_reused")
                return "replayed"
            job_snapshot = next(transaction.get(job_ref), None)
            if job_snapshot is None or not job_snapshot.exists:
                return "stale_lease"
            current_job = MemoryJob.model_validate(job_snapshot.to_dict())
            if (
                current_job.owner_id != job.owner_id
                or current_job.status != "leased"
                or current_job.lease_token != token
                or current_job.lease_expires_at is None
                or current_job.lease_expires_at <= max(now, self.clock())
            ):
                return "stale_lease"
            if (
                derived.owner_id != job.owner_id
                or derived.source_memory_ids != job.candidate_memory_ids
                or len(derived.sources) != len(job.candidate_memory_ids)
            ):
                raise ValueError("job_source_mismatch")
            sources = []
            for source_id, provenance in zip(
                job.candidate_memory_ids, derived.sources, strict=True
            ):
                record = self._read_record_tx(transaction, job.owner_id, source_id)
                state = self._read_state(job.owner_id, source_id, transaction=transaction)
                if (
                    not isinstance(record, Memory)
                    or record.status != "active"
                    or state.retrieval_status != "active"
                    or record.source_fingerprint != provenance.source_fingerprint
                    or record.content != provenance.excerpt
                    or record.source_conversation_id != provenance.source_conversation_id
                    or record.source_turn_id != provenance.source_turn_id
                    or record.source_message_ids != provenance.source_message_ids
                    or record.embedding_model != derived.embedding_model
                    or record.embedding_dimensions != derived.embedding_dimensions
                    or not self._read_original_tx(transaction, record)
                ):
                    return "source_inactive"
                sources.append((record, state))
            if not _compatible_derivation(derived, sources):
                return "source_mismatch"
            existing = next(transaction.get(derived_ref), None)
            if existing is not None and existing.exists:
                return "derived_conflict"
            event_records, updated_states, relation_refs = [], [], []
            for source, state in sources:
                key = f"{job.id}:consolidated:{source.id}"
                event = MemoryLifecycleEvent(
                    id=event_idempotency_id(key),
                    owner_id=job.owner_id,
                    memory_id=source.id,
                    event_type="consolidated",
                    reason_code="derived_memory_created",
                    policy_version=job.policy_version,
                    actor="system",
                    occurred_at=now,
                    idempotency_key=key,
                    related_memory_ids=(derived.id,),
                    job_id=job.id,
                    expected_state_version=state.state_version,
                )
                event_ref = self.events.document(str(event.id))
                prior = next(transaction.get(event_ref), None)
                if prior is not None and prior.exists:
                    return "operation_incomplete"
                updated_states.append(transition(state, event))
                event_records.append((event_ref, event))
                relation_id = hashlib.sha256(
                    f"{job.owner_id}:{source.id}:{derived.id}".encode()
                ).hexdigest()
                relation_refs.append((self.relations.document(relation_id), source.id))
            transaction.create(
                derived_ref,
                {
                    **derived.model_dump(mode="json"),
                    "embedding": Vector(derived.embedding),
                },
            )
            for (event_ref, event), updated, (relation_ref, source_id) in zip(
                event_records, updated_states, relation_refs, strict=True
            ):
                state_ref = self.states.document(self._state_ref_id(job.owner_id, event.memory_id))
                transaction.create(event_ref, event.model_dump(mode="json"))
                transaction.set(state_ref, updated.model_dump(mode="json"))
                transaction.create(
                    relation_ref,
                    {
                        "owner_id": job.owner_id,
                        "source_memory_id": str(source_id),
                        "derived_memory_id": str(derived.id),
                        "created_at": now.isoformat(),
                    },
                )
            transaction.create(
                operation_ref,
                {
                    "owner_id": job.owner_id,
                    "job_id": str(job.id),
                    "operation": "consolidate",
                    "derived_memory_id": str(derived.id),
                    "created_at": now.isoformat(),
                },
            )
            return "applied"

        return self.memories._run(lambda: self._transaction(commit))
