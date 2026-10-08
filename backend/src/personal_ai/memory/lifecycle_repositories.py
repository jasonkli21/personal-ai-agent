"""Lifecycle persistence adapters with owner isolation and lease fencing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.auth.scope import (
    STANDALONE_APPLICATION_ID,
    current_application_scope,
    scope_matches,
    scope_normalized_dump,
    scoped_record,
)
from personal_ai.entities import MessageRole, MessageStatus
from personal_ai.memory.contracts import DerivedMemory, Memory, embedding_space_for
from personal_ai.memory.lifecycle import (
    MemoryJob,
    MemoryLifecycleEvent,
    MemoryLifecycleOutcome,
    MemoryLifecycleState,
    transition,
)
from personal_ai.memory.services import source_messages
from personal_ai.storage.errors import ResourceNotFoundError

_SCOPE_UNSET = object()


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
        "application_id",
        "workspace_id",
        "scope_version",
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
        and len({embedding_space_for(record) for record in records}) == 1
        and embedding_space_for(derived) == embedding_space_for(records[0])
        and len({record.normalized_content for record in records}) == 1
        and derived.memory_type == target_type
        and derived.importance <= importance
        and derived.confidence <= min(record.confidence for record in records)
        and derived.effective_at == max(record.effective_at for record in records)
    )


def event_idempotency_id(
    key: str,
    application_id: str | None = None,
    workspace_id: str | None | object = _SCOPE_UNSET,
) -> UUID:
    scope = current_application_scope()
    application_id = application_id or scope.application_id
    if workspace_id is _SCOPE_UNSET:
        workspace_id = scope.workspace_id if application_id == scope.application_id else None
    namespace = (
        "" if application_id == STANDALONE_APPLICATION_ID and workspace_id is None
        else f"{application_id}:{workspace_id or ''}:"
    )
    return uuid5(NAMESPACE_URL, "personal-ai-memory-event:" + namespace + key)


def job_idempotency_id(
    key: str,
    application_id: str | None = None,
    workspace_id: str | None | object = _SCOPE_UNSET,
) -> UUID:
    scope = current_application_scope()
    application_id = application_id or scope.application_id
    if workspace_id is _SCOPE_UNSET:
        workspace_id = scope.workspace_id if application_id == scope.application_id else None
    namespace = (
        "" if application_id == STANDALONE_APPLICATION_ID and workspace_id is None
        else f"{application_id}:{workspace_id or ''}:"
    )
    return uuid5(NAMESPACE_URL, "personal-ai-memory-job:" + namespace + key)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp_invalid")
    return value.astimezone(UTC)


def _base_state(owner_id: str, memory_id: UUID) -> MemoryLifecycleState:
    return scoped_record(MemoryLifecycleState(owner_id=owner_id, memory_id=memory_id))


class InMemoryMemoryLifecycleRepository:
    """Deterministic fake sharing the Phase 3 message mutation lock."""

    def __init__(self, memories, messages, *, clock=None):
        self.memories, self.messages = memories, messages
        self.clock = clock or (lambda: datetime.now(UTC))
        self.states: dict[tuple[str, UUID], MemoryLifecycleState] = {}
        self.events: dict[tuple[str, UUID], list[MemoryLifecycleEvent]] = {}
        self.events_by_key: dict[tuple[str, str | None, str], MemoryLifecycleEvent] = {}
        self.jobs: dict[UUID, MemoryJob] = {}
        self.jobs_by_key: dict[tuple[str, str | None, str], UUID] = {}
        self.derived_sources: dict[tuple[str, UUID, str, str | None], set[UUID]] = {}
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
        if (
            not scope_matches(memory)
            or memory.status != "active"
            or source_messages(memory, self.messages) is None
        ):
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
        if state is not None and not scope_matches(state):
            return False
        return not require_active or state is None or state.retrieval_status == "active"

    def _valid_target(self, owner_id: str, memory_id: UUID, *, require_active: bool = True) -> bool:
        memory = self._get_memory(owner_id, memory_id)
        if isinstance(memory, Memory):
            state = self.states.get((owner_id, memory_id))
            return self._valid_source(memory, require_active=require_active)
        state = self.states.get((owner_id, memory_id))
        if require_active and state and scope_matches(state) and state.retrieval_status != "active":
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
            state = self.states.get((owner_id, memory_id))
            return state if state is not None and scope_matches(state) else _base_state(owner_id, memory_id)

    def list_events(self, *, owner_id: str, memory_id: UUID, limit: int = 50):
        if limit < 1 or limit > 100:
            raise ValueError("event_limit_invalid")
        with self._lock:
            self._get_memory(owner_id, memory_id)
            items = [
                event for event in self.events.get((owner_id, memory_id), [])
                if scope_matches(event)
            ]
            return tuple(
                sorted(items, key=lambda e: (e.expected_state_version, str(e.id)))[-limit:]
            )

    def find_event(self, *, owner_id: str, memory_id: UUID, idempotency_key: str):
        with self._lock:
            current = current_application_scope()
            event = self.events_by_key.get((current.application_id, current.workspace_id, idempotency_key))
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
        completed_assistant_conversation_id: UUID | None = None,
        job: MemoryJob | None = None,
        lease_token: UUID | None = None,
    ) -> MemoryLifecycleOutcome:
        with self._lock_sources(), self._lock:
            event = scoped_record(event)
            event_key = (event.application_id, event.workspace_id, event.idempotency_key)
            old = self.events_by_key.get(event_key)
            if old:
                if scope_normalized_dump(old) != scope_normalized_dump(event):
                    raise ValueError("idempotency_key_reused")
                return MemoryLifecycleOutcome(
                    status="replayed",
                    state=self.get_state(owner_id=event.owner_id, memory_id=event.memory_id),
                    event_id=old.id,
                )
            if event.id != event_idempotency_id(
                event.idempotency_key, event.application_id, event.workspace_id
            ):
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
                    or not scope_matches(current_job)
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
                    or (completed_assistant_conversation_id is not None and assistant.conversation_id != completed_assistant_conversation_id)
                    or not scope_matches(assistant)
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
            current = self.states.get((event.owner_id, event.memory_id))
            if current is None or not scope_matches(current):
                current = _base_state(event.owner_id, event.memory_id)
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
            self.events_by_key[event_key] = event
            self.states[(event.owner_id, event.memory_id)] = updated
            if event.event_type == "consolidated":
                for derived_id in event.related_memory_ids:
                    self.derived_sources.setdefault(
                        (
                            event.owner_id,
                            event.memory_id,
                            event.application_id,
                            event.workspace_id,
                        ),
                        set(),
                    ).add(derived_id)
            return MemoryLifecycleOutcome(status="applied", state=updated, event_id=event.id)

    def create_job(self, job: MemoryJob) -> tuple[MemoryJob, bool]:
        with self._lock:
            job = scoped_record(job)
            job_key = (job.application_id, job.workspace_id, job.idempotency_key)
            old_id = self.jobs_by_key.get(job_key)
            if old_id:
                old = self.jobs[old_id]
                if not _same_job_intent(old, job):
                    raise ValueError("idempotency_key_reused")
                return old, False
            if job.id != job_idempotency_id(job.idempotency_key, job.application_id, job.workspace_id):
                raise ValueError("job_identity_invalid")
            self.jobs[job.id] = job
            self.jobs_by_key[job_key] = job.id
            return job, True

    def get_job(self, *, owner_id: str, job_id: UUID) -> MemoryJob:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or job.owner_id != owner_id or not scope_matches(job):
                raise ResourceNotFoundError("memory job not found")
            return job

    def get_job_by_id(self, *, job_id: UUID) -> MemoryJob:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or not scope_matches(job):
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
            or not scope_matches(current)
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
                and scope_matches(record)
                and record.memory_type == anchor.memory_type
                and record.status == "active"
                and record.id != memory_id
                and record.embedding_model == anchor.embedding_model
                and record.embedding_dimensions == anchor.embedding_dimensions
                and embedding_space_for(record) == embedding_space_for(anchor)
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
            if current_job is None or not scope_matches(job) or not scope_matches(derived):
                return "stale_lease"
            if (derived.application_id, derived.workspace_id) != (
                job.application_id, job.workspace_id
            ):
                return "source_mismatch"
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
                    and not scope_matches(state)
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
                or embedding_space_for(source) != embedding_space_for(derived)
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
                state = self.states.get((job.owner_id, source.id))
                if state is None or not scope_matches(state):
                    state = _base_state(job.owner_id, source.id)
                key_value = f"{job.id}:consolidated:{source.id}"
                event = MemoryLifecycleEvent(
                    id=event_idempotency_id(
                        key_value, job.application_id, job.workspace_id
                    ),
                    owner_id=job.owner_id,
                    application_id=job.application_id,
                    workspace_id=job.workspace_id,
                    scope_version=2,
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
                event_key = (event.application_id, event.workspace_id, event.idempotency_key)
                old = self.events_by_key.get(event_key)
                if old and scope_normalized_dump(old) != scope_normalized_dump(event):
                    raise ValueError("idempotency_key_reused")
                events.append(event)
                states.append(transition(state, event))
            self.memories.derived_records[derived.id] = derived
            for source, event, state in zip(source_records, events, states, strict=True):
                self.events.setdefault((job.owner_id, source.id), []).append(event)
                self.events_by_key[(event.application_id, event.workspace_id, event.idempotency_key)] = event
                self.states[(job.owner_id, source.id)] = state
                self.derived_sources.setdefault(
                    (job.owner_id, source.id, job.application_id, job.workspace_id), set()
                ).add(derived.id)
            self.operations[key] = str(derived.id)
            return "applied"

    def dependencies(self, *, owner_id: str, memory_id: UUID, limit: int = 100):
        if not 1 <= limit <= 100:
            raise ValueError("dependency_limit_invalid")
        with self._lock:
            self._get_memory(owner_id, memory_id)
            found = []
            scope = current_application_scope()
            key = (owner_id, memory_id, scope.application_id, scope.workspace_id)
            for derived_id in sorted(self.derived_sources.get(key, set()), key=str):
                try:
                    self.memories.get_derived(owner_id=owner_id, memory_id=derived_id)
                except ResourceNotFoundError:
                    continue
                found.append(derived_id)
                if len(found) == limit:
                    break
            return tuple(found)

    def rebuild_state(self, *, owner_id: str, memory_id: UUID):
        with self._lock_sources(), self._lock:
            self._get_memory(owner_id, memory_id)
            current = _base_state(owner_id, memory_id)
            events = sorted(
                (item for item in self.events.get((owner_id, memory_id), []) if scope_matches(item)),
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
                and scope_matches(memory)
                and memory.status == "active"
                and memory.memory_type in ("episodic_observation", "semantic_summary")
                and memory.effective_at <= cutoff
                and self.get_state(owner_id=owner_id, memory_id=memory.id).retrieval_status == "active"
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
                and scope_matches(memory)
                and memory.status == "active"
                and memory.memory_type in ("preference", "explicit_correction")
                and self._valid_source(memory)
                and self.get_state(owner_id=owner_id, memory_id=memory.id).retrieval_status == "active"
            ]
        eligible.sort(key=lambda item: (-item.effective_at.timestamp(), str(item.id)))
        return tuple(item.id for item in eligible[:limit])
