"""Postgres lifecycle projection/events composed with DynamoDB lease authority."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from personal_ai.auth.scope import (
    ApplicationScope,
    current_application_scope,
    scope_matches,
    scope_normalized_dump,
    scoped_record,
)
from personal_ai.entities import MessageRole, MessageStatus
from personal_ai.memory.contracts import DerivedMemory, Memory
from personal_ai.memory.lifecycle import (
    MemoryJob,
    MemoryLifecycleEvent,
    MemoryLifecycleOutcome,
    MemoryLifecycleState,
    transition,
)
from personal_ai.memory.lifecycle_policy import contradiction_decision, forgetting_decision
from personal_ai.memory.lifecycle_repositories import (
    _base_state,
    _compatible_derivation,
    event_idempotency_id,
)
from personal_ai.persistence.postgres import (
    PersistenceConflict,
    PostgresPayloadRepository,
    _ensure_namespace,
)
from personal_ai.persistence.postgres_memory import PostgresMemoryRepository
from personal_ai.storage.errors import (
    ConversationConflictError,
    ResourceNotFoundError,
)


class PostgresMemoryLifecycleRepository:
    """P owns lifecycle state/events; DDB remains canonical for jobs and leases."""

    def __init__(self, memories: PostgresMemoryRepository, messages, jobs, *, clock=None):
        self.memories, self.messages, self.jobs = memories, messages, jobs
        self.database = memories.database
        self.clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _scope(record):
        return ApplicationScope(
            application_id=record.application_id, workspace_id=record.workspace_id
        )

    def _get_record(self, *, owner_id, memory_id):
        try:
            return self.memories.get(owner_id=owner_id, memory_id=memory_id)
        except ResourceNotFoundError:
            return self.memories.get_derived(owner_id=owner_id, memory_id=memory_id)

    def _read_record_tx(self, connection, owner_id, memory_id, scope):
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        row = connection.execute(
            "SELECT payload,embedding FROM memories WHERE scope_id=%s AND record_id=%s "
            "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
            (scope_id, str(memory_id), owner_id, scope.application_id, scope.workspace_id),
        ).fetchone()
        if row is not None:
            record = Memory.model_validate({**row[0], "embedding": tuple(row[1])})
            if record.owner_id != owner_id or not scope_matches(record, scope):
                raise ResourceNotFoundError("memory not found")
            return record
        row = connection.execute(
            "SELECT payload,embedding FROM derived_memories WHERE scope_id=%s AND record_id=%s "
            "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
            (scope_id, str(memory_id), owner_id, scope.application_id, scope.workspace_id),
        ).fetchone()
        if row is None:
            raise ResourceNotFoundError("memory not found")
        record = DerivedMemory.model_validate({**row[0], "embedding": tuple(row[1])})
        if record.owner_id != owner_id or not scope_matches(record, scope):
            raise ResourceNotFoundError("memory not found")
        return record

    def _read_state(self, connection, owner_id, memory_id, scope, *, lock=False):
        suffix = " FOR UPDATE" if lock else ""
        row = connection.execute(
            "SELECT payload,revision FROM memory_lifecycle_states WHERE scope_id=%s "
            "AND record_id=%s AND owner_id=%s AND application_id=%s "
            "AND workspace_id IS NOT DISTINCT FROM %s" + suffix,
            (
                PostgresPayloadRepository.scope_id(owner_id, scope), str(memory_id), owner_id,
                scope.application_id, scope.workspace_id,
            ),
        ).fetchone()
        if row is None:
            return _base_state(owner_id, memory_id), None
        state = MemoryLifecycleState.model_validate(row[0])
        if state.owner_id != owner_id or state.memory_id != memory_id or not scope_matches(state, scope):
            raise ResourceNotFoundError("memory not found")
        return state, int(row[1])

    def get_state(self, *, owner_id: str, memory_id: UUID):
        self._get_record(owner_id=owner_id, memory_id=memory_id)
        scope = current_application_scope()
        with self.database.connection() as connection:
            state, _ = self._read_state(connection, owner_id, memory_id, scope)
        return state

    def list_events(self, *, owner_id: str, memory_id: UUID, limit: int = 50):
        if not 1 <= limit <= 100:
            raise ValueError("event_limit_invalid")
        self._get_record(owner_id=owner_id, memory_id=memory_id)
        scope = current_application_scope()
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM memory_lifecycle_events WHERE scope_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND aggregate_id=%s ORDER BY event_sequence DESC LIMIT %s",
                (
                    PostgresPayloadRepository.scope_id(owner_id, scope), owner_id,
                    scope.application_id, scope.workspace_id, str(memory_id), limit,
                ),
            ).fetchall()
        return tuple(
            reversed(tuple(MemoryLifecycleEvent.model_validate(row[0]) for row in rows))
        )

    def find_event(self, *, owner_id: str, memory_id: UUID, idempotency_key: str):
        scope = current_application_scope()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM memory_lifecycle_events WHERE scope_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND idempotency_key=%s",
                (
                    PostgresPayloadRepository.scope_id(owner_id, scope), owner_id,
                    scope.application_id, scope.workspace_id, idempotency_key,
                ),
            ).fetchone()
        if row is None:
            return None
        event = MemoryLifecycleEvent.model_validate(row[0])
        if event.memory_id != memory_id or not scope_matches(event, scope):
            raise ResourceNotFoundError("memory event not found")
        return event

    def _source_is_valid(self, owner_id, record):
        if isinstance(record, Memory):
            from personal_ai.memory.services import source_messages

            return record.status == "active" and source_messages(record, self.messages, timeout=5)
        try:
            sources = [
                self.memories.get(owner_id=owner_id, memory_id=source.memory_id)
                for source in record.sources
            ]
        except ResourceNotFoundError:
            return False
        return all(
            isinstance(source, Memory) and source.source_fingerprint == provenance.source_fingerprint
            and self._source_is_valid(owner_id, source)
            for source, provenance in zip(sources, record.sources, strict=True)
        )

    def _apply_event_tx(
        self, connection, event: MemoryLifecycleEvent, *, completed_assistant_id=None,
        job: MemoryJob | None = None,
    ):
        scope = ApplicationScope(
            application_id=event.application_id, workspace_id=event.workspace_id
        )
        owner_id = event.owner_id
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        event_payload = event.model_dump(mode="json")
        existing = connection.execute(
            "SELECT payload FROM memory_lifecycle_events WHERE scope_id=%s AND record_id=%s FOR UPDATE",
            (scope_id, str(event.id)),
        ).fetchone()
        if existing is not None:
            old = MemoryLifecycleEvent.model_validate(existing[0])
            if scope_normalized_dump(old) != scope_normalized_dump(event):
                raise ValueError("idempotency_key_reused")
            state, _ = self._read_state(connection, owner_id, event.memory_id, scope)
            return {"status": "replayed", "reason": None, "event_id": str(event.id),
                    "state_version": state.state_version}

        current, revision = self._read_state(
            connection, owner_id, event.memory_id, scope, lock=True
        )
        record = self._read_record_tx(connection, owner_id, event.memory_id, scope)
        if not isinstance(record, DerivedMemory):
            if record.status != "active":
                return {"status": "conflict", "reason": "source_inactive"}
        elif record.status != "active":
            return {"status": "conflict", "reason": "source_inactive"}
        if completed_assistant_id is not None:
            if not isinstance(record, Memory):
                return {"status": "conflict", "reason": "assistant_incomplete"}
            try:
                assistant = self.messages.get(
                    owner_id=owner_id, conversation_id=record.source_conversation_id,
                    message_id=completed_assistant_id,
                )
            except ResourceNotFoundError:
                return {"status": "conflict", "reason": "assistant_incomplete"}
            if assistant.role is not MessageRole.ASSISTANT or assistant.status is not MessageStatus.COMPLETED:
                return {"status": "conflict", "reason": "assistant_incomplete"}
        if event.job_id is not None and (job is None or job.id != event.job_id):
            return {"status": "conflict", "reason": "stale_lease"}
        if not self._source_is_valid(owner_id, record):
            return {"status": "conflict", "reason": "source_inactive"}
        if event.event_type == "forgotten":
            rows = connection.execute(
                "SELECT derived_memory_id FROM derived_memory_sources WHERE scope_id=%s "
                "AND source_memory_id=%s ORDER BY derived_memory_id LIMIT 101",
                (scope_id, str(event.memory_id)),
            ).fetchall()
            dependencies = tuple(UUID(row[0]) for row in rows)
            if not forgetting_decision(
                record, current, now=event.occurred_at, dependencies=dependencies,
                dependency_lookup_complete=len(dependencies) < 101,
            ).eligible:
                return {"status": "conflict", "reason": "protected_memory"}
        if event.event_type == "superseded":
            if len(event.related_memory_ids) != 1:
                return {"status": "conflict", "reason": "ambiguous_contradiction"}
            related = self._read_record_tx(connection, owner_id, event.related_memory_ids[0], scope)
            if not isinstance(record, Memory) or not isinstance(related, Memory) or contradiction_decision(record, related) != "supersede":
                return {"status": "conflict", "reason": "ambiguous_contradiction"}
        for related_id in event.related_memory_ids:
            if related_id == event.memory_id and event.event_type == "consolidated":
                continue
            try:
                self._read_record_tx(connection, owner_id, related_id, scope)
            except ResourceNotFoundError:
                return {"status": "conflict", "reason": "related_source_inactive"}
        try:
            updated = transition(current, event)
        except ValueError as error:
            if str(error) == "state_version_conflict":
                return {"status": "conflict", "reason": "state_version_conflict"}
            raise
        connection.execute(
            "INSERT INTO memory_lifecycle_events(record_id,scope_id,owner_id,application_id,workspace_id,"
            "record_version,status,revision,event_sequence,aggregate_id,created_at,fingerprint,"
            "idempotency_key,payload) VALUES (%s,%s,%s,%s,%s,1,'active',1,%s,%s,%s,%s,%s,%s::jsonb)",
            (
                str(event.id), scope_id, owner_id, scope.application_id, scope.workspace_id,
                updated.state_version, str(event.memory_id), event.occurred_at,
                hashlib.sha256(event.model_dump_json().encode()).hexdigest(),
                event.idempotency_key, PostgresPayloadRepository._json(event_payload),
            ),
        )
        if revision is None:
            _ensure_namespace(connection, owner_id, scope)
            connection.execute(
                "INSERT INTO memory_lifecycle_states(record_id,scope_id,owner_id,application_id,"
                "workspace_id,record_version,status,revision,created_at,payload) "
                "VALUES (%s,%s,%s,%s,%s,1,'active',1,%s,%s::jsonb)",
                (
                    str(event.memory_id), scope_id, owner_id, scope.application_id,
                    scope.workspace_id, event.occurred_at,
                    PostgresPayloadRepository._json(updated.model_dump(mode="json")),
                ),
            )
        else:
            connection.execute(
                "UPDATE memory_lifecycle_states SET payload=%s::jsonb,revision=revision+1,updated_at=%s "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                (
                    PostgresPayloadRepository._json(updated.model_dump(mode="json")),
                    event.occurred_at, scope_id, str(event.memory_id), revision,
                ),
            )
        return {"status": "applied", "reason": None, "event_id": str(event.id),
                "state_version": updated.state_version}

    def apply_event(
        self, event: MemoryLifecycleEvent, *, completed_assistant_id=None,
        job: MemoryJob | None = None, lease_token: UUID | None = None,
    ):
        event = scoped_record(event)
        if event.id != event_idempotency_id(event.idempotency_key, event.application_id, event.workspace_id):
            raise ValueError("event_identity_invalid")
        if event.job_id is None and (job is not None or lease_token is not None):
            raise ValueError("job_fence_unexpected")
        if event.job_id is not None:
            if job is None or lease_token is None or job.id != event.job_id:
                return scoped_record(MemoryLifecycleOutcome(status="conflict", reason="stale_lease"))
            try:
                record = self._get_record(owner_id=event.owner_id, memory_id=event.memory_id)
                receipt, _ = self.memories.apply_job_effect(
                    job=job, lease_token=lease_token, record=record,
                    operation_id=str(event.id),
                    effect=lambda connection: self._apply_event_tx(connection, event, job=job),
                )
            except ConversationConflictError:
                return scoped_record(MemoryLifecycleOutcome(status="conflict", reason="stale_lease"))
            status = receipt.result_refs.get("status", "applied")
            reason = receipt.result_refs.get("reason")
            state = self.get_state(owner_id=event.owner_id, memory_id=event.memory_id)
            return scoped_record(MemoryLifecycleOutcome(
                status=status, state=state, event_id=event.id if status != "conflict" else None,
                reason=reason,
            ))
        with self.database.transaction() as connection:
            result = self._apply_event_tx(
                connection, event, completed_assistant_id=completed_assistant_id
            )
        state = self.get_state(owner_id=event.owner_id, memory_id=event.memory_id)
        return scoped_record(MemoryLifecycleOutcome(
            status=result["status"], state=state,
            event_id=event.id if result["status"] != "conflict" else None,
            reason=result["reason"],
        ))

    def create_job(self, job): return self.jobs.create_job(job)
    def get_job(self, *, owner_id, job_id): return self.jobs.get_job(owner_id=owner_id, job_id=job_id)
    def get_job_by_id(self, *, job_id, scope=None): return self.jobs.get_job_by_id(job_id=job_id, scope=scope)
    def claim_job(self, *, owner_id, job_id, now, lease_seconds):
        return self.jobs.claim_job(owner_id=owner_id, job_id=job_id, now=now, lease_seconds=lease_seconds)
    def complete_job(self, job, *, token, now): return self.jobs.complete_job(job, token=token, now=now)
    def fail_job(self, job, *, token, now, reason, retryable):
        return self.jobs.fail_job(job, token=token, now=now, reason=reason, retryable=retryable)
    def pending_for_publish(self, *, now, limit=50):
        return self.jobs.pending_for_publish(now=now, limit=limit)
    def mark_published(self, *, owner_id, job_id, updated_at):
        return self.jobs.mark_published(owner_id=owner_id, job_id=job_id, updated_at=updated_at)

    def dependencies(self, *, owner_id, memory_id, limit=100):
        if not 1 <= limit <= 100:
            raise ValueError("dependency_limit_invalid")
        scope = current_application_scope()
        self._get_record(owner_id=owner_id, memory_id=memory_id)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT derived_memory_id FROM derived_memory_sources WHERE scope_id=%s "
                "AND source_memory_id=%s ORDER BY derived_memory_id LIMIT %s",
                (PostgresPayloadRepository.scope_id(owner_id, scope), str(memory_id), limit + 1),
            ).fetchall()
        return tuple(UUID(row[0]) for row in rows)

    def discover_related(self, *, owner_id, memory_id, limit=4):
        if not 1 <= limit <= 4:
            raise ValueError("candidate_limit_invalid")
        anchor = self._get_record(owner_id=owner_id, memory_id=memory_id)
        matches = self.memories.search(
            owner_id=owner_id, embedding=anchor.embedding, model=anchor.embedding_model,
            dimensions=anchor.embedding_dimensions, limit=limit + 1,
            memory_type=anchor.memory_type,
        )
        found = []
        for item in matches:
            if item.memory.id == memory_id or item.memory.memory_type != anchor.memory_type:
                continue
            if self._source_is_valid(owner_id, item.memory):
                found.append(item.memory.id)
            if len(found) >= limit - 1:
                break
        return tuple(([memory_id] + found)[:limit])

    def discover_forgetting_candidates(self, *, owner_id, older_than, limit=4):
        if not 1 <= limit <= 100:
            raise ValueError("candidate_limit_invalid")
        scope = current_application_scope()
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT record_id FROM memories WHERE scope_id=%s AND owner_id=%s AND status='active' "
                "AND memory_type=ANY(%s) AND effective_at<=%s ORDER BY effective_at,record_id LIMIT %s",
                (
                    PostgresPayloadRepository.scope_id(owner_id, scope), owner_id,
                    ["episodic_observation", "semantic_summary"], older_than, limit * 4,
                ),
            ).fetchall()
        candidates = []
        for (record_id,) in rows:
            memory = self.memories.get(owner_id=owner_id, memory_id=UUID(record_id))
            state = self.get_state(owner_id=owner_id, memory_id=memory.id)
            if state.retrieval_status == "active" and self._source_is_valid(owner_id, memory):
                candidates.append(memory.id)
            if len(candidates) >= limit:
                break
        return tuple(candidates)

    def discover_maintenance_candidates(self, *, owner_id, limit=4):
        if not 1 <= limit <= 4:
            raise ValueError("candidate_limit_invalid")
        scope = current_application_scope()
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT record_id FROM memories WHERE scope_id=%s AND owner_id=%s AND status='active' "
                "AND memory_type=ANY(%s) ORDER BY effective_at DESC,record_id LIMIT %s",
                (
                    PostgresPayloadRepository.scope_id(owner_id, scope), owner_id,
                    ["preference", "explicit_correction"], min(100, limit * 4),
                ),
            ).fetchall()
        candidates = []
        for (record_id,) in rows:
            memory = self.memories.get(owner_id=owner_id, memory_id=UUID(record_id))
            if (
                self.get_state(owner_id=owner_id, memory_id=memory.id).retrieval_status == "active"
                and self._source_is_valid(owner_id, memory)
            ):
                candidates.append(memory.id)
            if len(candidates) >= limit:
                break
        return tuple(candidates)

    def rebuild_state(self, *, owner_id, memory_id):
        self._get_record(owner_id=owner_id, memory_id=memory_id)
        scope = current_application_scope()
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM memory_lifecycle_events WHERE scope_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND aggregate_id=%s ORDER BY event_sequence LIMIT 10001",
                (
                    PostgresPayloadRepository.scope_id(owner_id, scope), owner_id,
                    scope.application_id, scope.workspace_id, str(memory_id),
                ),
            ).fetchall()
        if len(rows) > 10_000:
            from personal_ai.storage.errors import StorageUnavailableError

            raise StorageUnavailableError("memory lifecycle history exceeds rebuild bound")
        events = tuple(MemoryLifecycleEvent.model_validate(row[0]) for row in rows)
        rebuilt = _base_state(owner_id, memory_id)
        for event in events:
            rebuilt = transition(rebuilt, event)
        scope = current_application_scope()
        with self.database.transaction() as connection:
            current, revision = self._read_state(connection, owner_id, memory_id, scope, lock=True)
            if current.state_version > rebuilt.state_version:
                return current
            if revision is None:
                _ensure_namespace(connection, owner_id, scope)
                connection.execute(
                    "INSERT INTO memory_lifecycle_states(record_id,scope_id,owner_id,application_id,"
                    "workspace_id,record_version,status,revision,created_at,payload) "
                    "VALUES (%s,%s,%s,%s,%s,1,'active',1,now(),%s::jsonb)",
                    (
                        str(memory_id), PostgresPayloadRepository.scope_id(owner_id, scope), owner_id,
                        scope.application_id, scope.workspace_id,
                        PostgresPayloadRepository._json(rebuilt.model_dump(mode="json")),
                    ),
                )
            else:
                connection.execute(
                    "UPDATE memory_lifecycle_states SET payload=%s::jsonb,revision=revision+1 "
                    "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                    (
                        PostgresPayloadRepository._json(rebuilt.model_dump(mode="json")),
                        PostgresPayloadRepository.scope_id(owner_id, scope), str(memory_id), revision,
                    ),
                )
        return rebuilt

    def commit_consolidation(self, *, job: MemoryJob, token: UUID, derived: DerivedMemory, now: datetime):
        derived = scoped_record(derived)
        if (
            derived.owner_id != job.owner_id
            or (derived.application_id, derived.workspace_id) != (job.application_id, job.workspace_id)
            or derived.source_memory_ids != job.candidate_memory_ids
        ):
            return "source_mismatch"
        operation_id = f"{job.id}:consolidate"

        def effect(connection):
            scope = ApplicationScope(application_id=job.application_id, workspace_id=job.workspace_id)
            scope_id = PostgresPayloadRepository.scope_id(job.owner_id, scope)
            sources = []
            for source in derived.sources:
                row = connection.execute(
                    "SELECT payload,embedding FROM memories WHERE scope_id=%s AND record_id=%s "
                    "AND owner_id=%s AND status='active' FOR UPDATE",
                    (scope_id, str(source.memory_id), job.owner_id),
                ).fetchone()
                if row is None:
                    return {"status": "source_inactive"}
                memory = Memory.model_validate({**row[0], "embedding": tuple(row[1])})
                state, _ = self._read_state(connection, job.owner_id, memory.id, scope)
                if (
                    state.retrieval_status != "active"
                    or memory.source_fingerprint != source.source_fingerprint
                    or memory.content != source.excerpt
                    or memory.source_conversation_id != source.source_conversation_id
                    or memory.source_turn_id != source.source_turn_id
                    or memory.source_message_ids != source.source_message_ids
                ):
                    return {"status": "source_mismatch"}
                sources.append((memory, state))
            if not _compatible_derivation(derived, sources):
                return {"status": "source_mismatch"}
            existing = connection.execute(
                "SELECT payload,embedding FROM derived_memories WHERE scope_id=%s AND record_id=%s FOR UPDATE",
                (scope_id, str(derived.id)),
            ).fetchone()
            if existing is not None:
                old = DerivedMemory.model_validate({**existing[0], "embedding": tuple(existing[1])})
                if old.source_set_identity != derived.source_set_identity:
                    return {"status": "derived_conflict"}
                return {"status": "replayed", "derived_id": str(old.id)}
            self.memories._insert_derived(connection, scope_id, derived)
            for ordinal, source in enumerate(derived.sources, 1):
                connection.execute(
                    "INSERT INTO derived_memory_sources(scope_id,derived_memory_id,source_memory_id,"
                    "source_ordinal,source_fingerprint,source_conversation_id,source_turn_id,source_message_ids,excerpt) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        scope_id, str(derived.id), str(source.memory_id), ordinal,
                        source.source_fingerprint, str(source.source_conversation_id),
                        str(source.source_turn_id), [str(value) for value in source.source_message_ids],
                        source.excerpt,
                    ),
                )
            for source, state in sources:
                key = f"{job.id}:consolidated:{source.id}"
                event = MemoryLifecycleEvent(
                    id=event_idempotency_id(key, job.application_id, job.workspace_id),
                    owner_id=job.owner_id, application_id=job.application_id,
                    workspace_id=job.workspace_id, scope_version=2, memory_id=source.id,
                    event_type="consolidated", reason_code="derived_memory_created",
                    policy_version=job.policy_version, actor="system", occurred_at=now,
                    idempotency_key=key, related_memory_ids=(derived.id,), job_id=job.id,
                    expected_state_version=state.state_version,
                )
                result = self._apply_event_tx(connection, event, job=job)
                if result["status"] not in {"applied", "replayed"}:
                    raise PersistenceConflict("consolidation lifecycle event rejected")
            return {"status": "applied", "derived_id": str(derived.id)}

        try:
            receipt, _ = self.memories.apply_job_effect(
                job=job, lease_token=token, record=derived,
                operation_id=operation_id, effect=effect,
            )
        except ConversationConflictError:
            return "stale_lease"
        return receipt.result_refs.get("status", "applied")
