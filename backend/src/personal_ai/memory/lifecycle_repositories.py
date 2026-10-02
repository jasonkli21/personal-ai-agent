"""Lifecycle persistence adapters with owner isolation and lease fencing."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from threading import RLock
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

    def __init__(self, memories, messages):
        self.memories, self.messages = memories, messages
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
            return tuple(sorted(items, key=lambda e: (e.occurred_at, str(e.id)))[-limit:])

    def apply_event(self, event: MemoryLifecycleEvent) -> MemoryLifecycleOutcome:
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
            if not self._valid_target(
                event.owner_id, event.memory_id, require_active=event.event_type != "reactivated"
            ):
                return MemoryLifecycleOutcome(status="conflict", reason="source_inactive")
            for related_id in event.related_memory_ids:
                self._get_memory(event.owner_id, related_id)
            current = self.states.get(
                (event.owner_id, event.memory_id), _base_state(event.owner_id, event.memory_id)
            )
            updated = transition(current, event)
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
                if old.model_dump() != job.model_dump():
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
            or current.lease_expires_at <= _utc(now)
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
            if job.status not in ("pending", "retry"):
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
                    or source_messages(record, self.messages) is None
                ):
                    return "source_inactive"
                source_records.append(record)
            if tuple(source.id for source in source_records) != derived.source_memory_ids:
                raise ValueError("source_order_invalid")
            if derived.id in self.memories.derived_records:
                existing = self.memories.get_derived(owner_id=job.owner_id, memory_id=derived.id)
                if existing.model_dump() != derived.model_dump():
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
            return tuple(
                sorted(self.derived_sources.get((owner_id, memory_id), set()), key=str)[:limit]
            )


class FirestoreMemoryLifecycleRepository:
    """Firestore event/state/job adapter; lifecycle mutations are transactional."""

    def __init__(self, memories: FirestoreMemoryRepository, messages):
        self.memories, self.messages = memories, messages
        self.client = memories.client
        self.states = self.client.collection("memory_lifecycle_states")
        self.events = self.client.collection("memory_lifecycle_events")
        self.jobs = self.client.collection("memory_lifecycle_jobs")
        self.operations = self.client.collection("memory_lifecycle_operations")
        self.relations = self.client.collection("derived_memory_sources")

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
        snapshot = next(transaction.get(reference), None) if transaction else reference.get()
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
        query = query.order_by("occurred_at", direction=firestore.Query.ASCENDING).limit(limit)
        snapshots = self.memories._run(lambda: list(query.stream(retry=None, timeout=5)))
        try:
            return tuple(MemoryLifecycleEvent.model_validate(item.to_dict()) for item in snapshots)
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("memory lifecycle event invalid") from error

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
            for _ in range(64):
                if current is None or current in collected:
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
        return (
            assistant.owner_id == memory.owner_id
            and assistant.conversation_id == memory.source_conversation_id
            and assistant.role is MessageRole.ASSISTANT
            and assistant.status is MessageStatus.COMPLETED
            and assistant.parent_message_id in memory.source_message_ids
            and tuple(item.id for item in source_records) == memory.source_message_ids
            and fingerprint(source_records) == memory.source_fingerprint
        )

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

    def apply_event(self, event: MemoryLifecycleEvent) -> MemoryLifecycleOutcome:
        if event.id != event_idempotency_id(event.idempotency_key):
            raise ValueError("event_identity_invalid")
        event_ref = self.events.document(str(event.id))
        state_ref = self.states.document(self._state_ref_id(event.owner_id, event.memory_id))

        @firestore.transactional
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
            return self.memories._run(lambda: commit(self.client.transaction()))
        except (GoogleAPICallError, RetryError, OSError) as error:
            raise StorageUnavailableError("memory lifecycle unavailable") from error

    def create_job(self, job: MemoryJob) -> tuple[MemoryJob, bool]:
        if job.id != job_idempotency_id(job.idempotency_key):
            raise ValueError("job_identity_invalid")
        reference = self.jobs.document(str(job.id))

        @firestore.transactional
        def create(transaction):
            snapshot = next(transaction.get(reference), None)
            if snapshot is not None and snapshot.exists:
                try:
                    existing = MemoryJob.model_validate(snapshot.to_dict())
                except (ValueError, TypeError, KeyError) as error:
                    raise StorageUnavailableError("memory job invalid") from error
                if existing.model_dump() != job.model_dump():
                    raise ValueError("idempotency_key_reused")
                return existing, False
            transaction.create(reference, job.model_dump(mode="json"))
            return job, True

        return self.memories._run(lambda: create(self.client.transaction()))

    def get_job(self, *, owner_id: str, job_id: UUID) -> MemoryJob:
        snapshot = self.memories._run(
            lambda: self.jobs.document(str(job_id)).get(retry=None, timeout=5)
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

    def claim_job(self, *, owner_id: str, job_id: UUID, now: datetime, lease_seconds: int):
        now = _utc(now)
        reference = self.jobs.document(str(job_id))

        @firestore.transactional
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

        return self.memories._run(lambda: claim(self.client.transaction()))

    def _mutate_fenced_job(self, job: MemoryJob, token: UUID, now: datetime, changes):
        now = _utc(now)
        reference = self.jobs.document(str(job.id))

        @firestore.transactional
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
                or current.lease_expires_at <= now
            ):
                return False
            transaction.update(reference, {**changes, "updated_at": now.isoformat()})
            return True

        return self.memories._run(lambda: mutate(self.client.transaction()))

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
        query = self.jobs.where(filter=firestore.FieldFilter("publish_pending", "==", True))
        snapshots = self.memories._run(
            lambda: list(query.limit(limit).stream(retry=None, timeout=5))
        )
        records = [MemoryJob.model_validate(item.to_dict()) for item in snapshots]
        now = _utc(now)
        return tuple(
            job
            for job in records
            if job.status in ("pending", "retry")
            and (job.next_attempt_at is None or job.next_attempt_at <= now)
        )

    def mark_published(self, *, owner_id: str, job_id: UUID, updated_at: datetime):
        job = self.get_job(owner_id=owner_id, job_id=job_id)
        if job.status not in ("pending", "retry"):
            return job
        reference = self.jobs.document(str(job_id))
        self.memories._run(
            lambda: reference.update(
                {
                    "publish_pending": False,
                    "updated_at": _utc(updated_at).isoformat(),
                }
            )
        )
        return job.model_copy(update={"publish_pending": False, "updated_at": _utc(updated_at)})

    def discover_related(self, *, owner_id: str, memory_id: UUID, limit: int = 4):
        anchor = self.memories.get(owner_id=owner_id, memory_id=memory_id)
        result = self.memories.search(
            owner_id=owner_id,
            embedding=anchor.embedding,
            model=anchor.embedding_model,
            dimensions=anchor.embedding_dimensions,
            limit=limit,
            timeout=5,
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

    def dependencies(self, *, owner_id: str, memory_id: UUID, limit: int = 100):
        if not 1 <= limit <= 100:
            raise ValueError("dependency_limit_invalid")
        query = self.relations.where(filter=firestore.FieldFilter("owner_id", "==", owner_id))
        query = query.where(filter=firestore.FieldFilter("source_memory_id", "==", str(memory_id)))
        snapshots = self.memories._run(
            lambda: list(query.limit(limit).stream(retry=None, timeout=5))
        )
        return tuple(UUID(item.to_dict()["derived_memory_id"]) for item in snapshots)

    def commit_consolidation(
        self, *, job: MemoryJob, token: UUID, derived: DerivedMemory, now: datetime
    ):
        """Atomically revalidate lease and source provenance before derived writes."""
        now = _utc(now)
        operation_id = f"{job.id}:consolidate"
        operation_ref = self.operations.document(hashlib.sha256(operation_id.encode()).hexdigest())
        job_ref = self.jobs.document(str(job.id))
        derived_ref = self.client.collection("derived_memories").document(str(derived.id))

        @firestore.transactional
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
                or current_job.lease_expires_at <= now
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
                    or not self._read_original_tx(transaction, record)
                ):
                    return "source_inactive"
                sources.append((record, state))
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
                if event_records:
                    prior = next(transaction.get(event_ref), None)
                    if prior is not None and prior.exists:
                        old = MemoryLifecycleEvent.model_validate(prior.to_dict())
                        if old.model_dump() != event.model_dump():
                            raise ValueError("idempotency_key_reused")
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

        return self.memories._run(lambda: commit(self.client.transaction()))
