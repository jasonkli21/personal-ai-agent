"""Postgres knowledge/vector repository for the current memory contracts."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Any, Protocol
from uuid import UUID

from personal_ai.auth.scope import (
    ApplicationScope,
    current_application_scope,
    scope_matches,
    scoped_record,
)
from personal_ai.memory.contracts import DerivedMemory, Memory, ScoredMemory, vector
from personal_ai.persistence.effect_receipts import PostgresEffectReceiptRepository
from personal_ai.persistence.postgres import (
    PersistenceConflict,
    PostgresDatabase,
    PostgresPayloadRepository,
    _ensure_namespace,
)
from personal_ai.storage.errors import (
    ConversationConflictError,
    ResourceNotFoundError,
    StorageUnavailableError,
)

PGVECTOR_COSINE_ERROR_BOUND = 0.0002
MEMORY_SEARCH_SCAN_LIMIT = 5_000


@dataclass(frozen=True)
class EffectGuardToken:
    owner_id: str
    operation_id: str
    attempt_id: str
    fingerprint: str
    execution_deadline: datetime
    scope: ApplicationScope
    coordination_conversation_id: UUID | None = None
    coordination_job_id: UUID | None = None
    lease_generation: int | None = None


class MemorySourceGuard(Protocol):
    """DynamoDB source/job guards used only for durable knowledge writes."""

    def acquire(
        self, record: Memory | DerivedMemory, *, timeout: float
    ) -> EffectGuardToken: ...

    def acquire_lifecycle_event(
        self, record: Memory | DerivedMemory, *, operation_id: str, fingerprint: str,
        completed_assistant_id: UUID | None, completed_assistant_conversation_id: UUID | None,
        timeout: float,
    ) -> EffectGuardToken: ...

    def acknowledge(
        self,
        token: EffectGuardToken,
        *,
        outcome: str,
        result_refs: dict[str, Any],
    ) -> None: ...

    def acquire_job(
        self, job: Any, lease_token: UUID, record: Memory | DerivedMemory, *,
        operation_id: str, timeout: float,
    ) -> EffectGuardToken: ...

    def recover_pending_job(self, *, owner_id: str, job_id: UUID, scope: ApplicationScope,
                            receipts) -> int: ...


class PostgresMemoryRepository:
    """Lossless embeddings and provenance with source-guarded P transactions."""

    def __init__(
        self,
        database: PostgresDatabase,
        source_guard: MemorySourceGuard,
        *,
        receipt_repository: PostgresEffectReceiptRepository | None = None,
        search_scan_limit: int = MEMORY_SEARCH_SCAN_LIMIT,
    ) -> None:
        if source_guard is None:
            raise ValueError("memory_source_guard_required")
        self.database = database
        self.source_guard = source_guard
        self.receipts = receipt_repository or PostgresEffectReceiptRepository(database)
        self.search_scan_limit = search_scan_limit

    def recover_pending_operations(
        self, *, owner_id: str, conversation_id: UUID, scope: ApplicationScope, limit: int = 50
    ) -> int:
        """Arbitrate pending direct-extraction effects before releasing D guards."""
        recover = getattr(self.source_guard, "recover_pending", None)
        if recover is None:
            raise RuntimeError("memory_source_guard_recovery_unavailable")
        return recover(
            owner_id=owner_id,
            conversation_id=conversation_id,
            scope=scope,
            receipts=self.receipts,
            limit=limit,
        )

    def recover_pending_job_operation(
        self, *, owner_id: str, job_id: UUID, scope: ApplicationScope
    ) -> int:
        """Resolve the P receipt before D may replace a job's lease generation."""
        recover = getattr(self.source_guard, "recover_pending_job", None)
        if recover is None:
            raise RuntimeError("memory_job_guard_recovery_unavailable")
        return recover(
            owner_id=owner_id, job_id=job_id, scope=scope, receipts=self.receipts
        )

    def recover_pending_effects(self, *, owner_id: str, limit: int = 50) -> int:
        """Resolve bounded in-doubt direct and job effects before worker progress."""
        recover = getattr(self.source_guard, "recover_pending_effects", None)
        if recover is None:
            raise RuntimeError("memory_effect_recovery_unavailable")
        return recover(owner_id=owner_id, limit=limit, receipts=self.receipts)

    def apply_lifecycle_effect(
        self, *, event, record: Memory | DerivedMemory, operation_id: str,
        fingerprint: str, completed_assistant_id: UUID | None,
        completed_assistant_conversation_id: UUID | None, effect, timeout: float = 5,
    ):
        """Guard D source/consumer chats around one atomic P event and receipt."""
        token = self.source_guard.acquire_lifecycle_event(
            record, operation_id=operation_id, fingerprint=fingerprint,
            completed_assistant_id=completed_assistant_id,
            completed_assistant_conversation_id=completed_assistant_conversation_id,
            timeout=timeout,
        )
        receipt, applied = self.receipts.apply(
            owner_id=event.owner_id, scope=token.scope,
            operation_id=token.operation_id, attempt_id=token.attempt_id,
            fingerprint=token.fingerprint, execution_deadline=token.execution_deadline,
            effect=effect,
        )
        self.source_guard.acknowledge(
            token, outcome=receipt.outcome, result_refs=receipt.result_refs
        )
        return receipt, applied

    def apply_job_effect(
        self,
        *,
        job: Any,
        lease_token: UUID,
        record: Memory | DerivedMemory,
        operation_id: str,
        effect: Callable[[Any], dict[str, Any]],
        timeout: float = 5,
    ):
        """Apply one P transaction under the narrow D job/source guard protocol."""
        token = self.source_guard.acquire_job(
            job, lease_token, record, operation_id=operation_id, timeout=timeout
        )
        receipt, applied = self.receipts.apply(
            owner_id=record.owner_id,
            scope=token.scope,
            operation_id=token.operation_id,
            attempt_id=token.attempt_id,
            fingerprint=token.fingerprint,
            execution_deadline=token.execution_deadline,
            effect=effect,
        )
        self.source_guard.acknowledge(
            token, outcome=receipt.outcome, result_refs=receipt.result_refs
        )
        return receipt, applied

    def create(self, memory: Memory, *, timeout: float = 5) -> tuple[Memory, bool]:
        from personal_ai.memory.repositories import validate

        memory = validate(scoped_record(memory))
        guard = self.source_guard.acquire(memory, timeout=timeout)
        if guard.scope != _scope_of(memory):
            raise ConversationConflictError("memory source scope changed")

        def apply(connection):
            existing = self._read_memory_row(
                connection, guard.scope, memory.owner_id, str(memory.id), lock=True
            )
            if existing is not None:
                current = _memory_from_row(existing)
                if current != memory:
                    raise PersistenceConflict("memory identity payload changed")
                return {"memory_id": str(memory.id), "record_hash": _model_hash(current), "created": False}
            self._insert_memory(connection, guard.scope, memory)
            return {"memory_id": str(memory.id), "record_hash": _model_hash(memory), "created": True}

        # Unknown SQL outcomes intentionally leave the D guard in place.
        # Recovery must arbitrate an abort receipt before releasing it.
        receipt, applied = self.receipts.apply(
            owner_id=memory.owner_id,
            scope=guard.scope,
            operation_id=guard.operation_id,
            attempt_id=guard.attempt_id,
            fingerprint=guard.fingerprint,
            execution_deadline=guard.execution_deadline,
            effect=apply,
        )
        self.source_guard.acknowledge(
            guard, outcome=receipt.outcome, result_refs=receipt.result_refs
        )
        try:
            saved = self.get(owner_id=memory.owner_id, memory_id=memory.id, timeout=timeout)
        except ResourceNotFoundError as error:
            raise StorageUnavailableError("memory effect receipt missing record") from error
        return saved, bool(applied and receipt.result_refs.get("created", True))

    def get(self, *, owner_id: str, memory_id: UUID, timeout: float = 5) -> Memory:
        scope = current_application_scope()
        with self.database.connection() as connection:
            row = self._read_memory_row(connection, scope, owner_id, str(memory_id))
        if row is None:
            raise ResourceNotFoundError("memory not found")
        try:
            return _memory_from_row(row)
        except (TypeError, ValueError, KeyError) as error:
            raise StorageUnavailableError("memory record invalid") from error

    def get_derived(self, *, owner_id: str, memory_id: UUID, timeout: float = 5) -> DerivedMemory:
        scope = current_application_scope()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload,embedding FROM derived_memories WHERE scope_id=%s AND record_id=%s "
                "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND status='active' "
                "AND (SELECT count(*) FROM derived_memory_sources ds "
                "WHERE ds.scope_id=derived_memories.scope_id "
                "AND ds.derived_memory_id=derived_memories.record_id) BETWEEN 2 AND 4 "
                "AND NOT EXISTS (SELECT 1 FROM derived_memory_sources ds "
                "LEFT JOIN memories source ON source.scope_id=ds.scope_id "
                "AND source.record_id=ds.source_memory_id "
                "LEFT JOIN memory_lifecycle_states state ON state.scope_id=ds.scope_id "
                "AND state.record_id=ds.source_memory_id "
                "WHERE ds.scope_id=derived_memories.scope_id "
                "AND ds.derived_memory_id=derived_memories.record_id "
                "AND (source.record_id IS NULL OR source.status<>'active' "
                "OR source.source_fingerprint<>ds.source_fingerprint "
                "OR COALESCE(state.payload->>'retrieval_status','active')<>'active'))",
                (
                    PostgresPayloadRepository.scope_id(owner_id, scope),
                    str(memory_id),
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                ),
            ).fetchone()
        if row is None:
            raise ResourceNotFoundError("memory not found")
        try:
            return DerivedMemory.model_validate({**row[0], "embedding": tuple(row[1])})
        except (TypeError, ValueError, KeyError) as error:
            raise StorageUnavailableError("memory record invalid") from error

    def create_derived(
        self, memory: DerivedMemory, *, timeout: float = 5
    ) -> tuple[DerivedMemory, bool]:
        guard = self.source_guard.acquire(memory, timeout=timeout)
        if guard.scope != _scope_of(memory):
            raise ConversationConflictError("memory source scope changed")

        def apply(connection):
            scope_id = _ensure_namespace(connection, memory.owner_id, guard.scope)
            existing = connection.execute(
                "SELECT payload,embedding FROM derived_memories WHERE scope_id=%s AND record_id=%s FOR UPDATE",
                (scope_id, str(memory.id)),
            ).fetchone()
            if existing is not None:
                saved = DerivedMemory.model_validate({**existing[0], "embedding": tuple(existing[1])})
                if saved != memory:
                    raise PersistenceConflict("derived memory identity payload changed")
                return {"memory_id": str(memory.id), "record_hash": _model_hash(saved), "created": False}
            source_ids = [str(identifier) for identifier in memory.source_memory_ids]
            source_rows = connection.execute(
                "SELECT m.record_id,m.status,m.source_fingerprint,m.source_conversation_id,"
                "m.source_turn_id,m.source_message_ids,m.memory_type,m.embedding_model,"
                "m.embedding_dimensions,m.embedding,m.payload,"
                "COALESCE(state.payload->>'retrieval_status','active') "
                "FROM memories m LEFT JOIN memory_lifecycle_states state "
                "ON state.scope_id=m.scope_id AND state.record_id=m.record_id "
                "WHERE m.scope_id=%s AND m.owner_id=%s AND m.record_id=ANY(%s) "
                "FOR UPDATE OF m",
                (scope_id, memory.owner_id, source_ids),
            ).fetchall()
            by_id = {row[0]: row for row in source_rows}
            if set(by_id) != set(source_ids):
                raise ConversationConflictError("memory source inactive")
            ordered_sources = [by_id[identifier] for identifier in source_ids]
            if any(row[1] != "active" or row[11] != "active" for row in ordered_sources):
                raise ConversationConflictError("memory source inactive")
            source_records = []
            source_states = []
            from personal_ai.memory.lifecycle import MemoryLifecycleState
            from personal_ai.memory.lifecycle_repositories import (
                _base_state,
                _compatible_derivation,
            )

            for row, provenance in zip(ordered_sources, memory.sources, strict=True):
                source = _memory_from_row((row[10], row[9]))
                if (
                    row[2].strip() != provenance.source_fingerprint
                    or row[3] != str(provenance.source_conversation_id)
                    or row[4] != str(provenance.source_turn_id)
                    or tuple(row[5]) != tuple(str(item) for item in provenance.source_message_ids)
                    or source.content != provenance.excerpt
                    or row[7] != memory.embedding_model
                    or row[8] != memory.embedding_dimensions
                ):
                    raise ConversationConflictError("memory source provenance changed")
                state_row = connection.execute(
                    "SELECT payload FROM memory_lifecycle_states WHERE scope_id=%s AND record_id=%s",
                    (scope_id, row[0]),
                ).fetchone()
                state = (
                    _base_state(memory.owner_id, source.id)
                    if state_row is None else MemoryLifecycleState.model_validate(state_row[0])
                )
                source_records.append(source)
                source_states.append(state)
            if not _compatible_derivation(
                memory, list(zip(source_records, source_states, strict=True))
            ):
                raise ConversationConflictError("memory source derivation incompatible")
            self._insert_derived(connection, scope_id, memory)
            for ordinal, source in enumerate(memory.sources, 1):
                connection.execute(
                    "INSERT INTO derived_memory_sources(scope_id,derived_memory_id,source_memory_id,"
                    "source_ordinal,source_fingerprint,source_conversation_id,source_turn_id,"
                    "source_message_ids,excerpt) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        scope_id,
                        str(memory.id),
                        str(source.memory_id),
                        ordinal,
                        source.source_fingerprint,
                        str(source.source_conversation_id),
                        str(source.source_turn_id),
                        [str(item) for item in source.source_message_ids],
                        source.excerpt,
                    ),
                )
            return {"memory_id": str(memory.id), "record_hash": _model_hash(memory), "created": True}

        receipt, applied = self.receipts.apply(
            owner_id=memory.owner_id,
            scope=guard.scope,
            operation_id=guard.operation_id,
            attempt_id=guard.attempt_id,
            fingerprint=guard.fingerprint,
            execution_deadline=guard.execution_deadline,
            effect=apply,
        )
        self.source_guard.acknowledge(
            guard, outcome=receipt.outcome, result_refs=receipt.result_refs
        )
        return self.get_derived(owner_id=memory.owner_id, memory_id=memory.id, timeout=timeout), bool(
            applied and receipt.result_refs.get("created", True)
        )

    def search(
        self,
        *,
        owner_id: str,
        embedding,
        model: str,
        dimensions: int,
        provider: str = "google_genai",
        normalization: str = "l2",
        document_task: str = "RETRIEVAL_DOCUMENT",
        query_task: str = "RETRIEVAL_QUERY",
        embedding_space_version: str = "v1",
        limit: int,
        timeout: float = 5,
        memory_type: str | None = None,
    ) -> list[ScoredMemory]:
        return self._search(
            table="memories",
            owner_id=owner_id,
            embedding=embedding,
            model=model,
            dimensions=dimensions,
            provider=provider,
            normalization=normalization,
            document_task=document_task,
            query_task=query_task,
            embedding_space_version=embedding_space_version,
            limit=limit,
            timeout=timeout,
            memory_type=memory_type,
            derived=False,
        )

    def search_derived(
        self,
        *,
        owner_id: str,
        embedding,
        model: str,
        dimensions: int,
        provider: str = "google_genai",
        normalization: str = "l2",
        document_task: str = "RETRIEVAL_DOCUMENT",
        query_task: str = "RETRIEVAL_QUERY",
        embedding_space_version: str = "v1",
        limit: int,
        timeout: float = 5,
    ) -> list[ScoredMemory]:
        return self._search(
            table="derived_memories",
            owner_id=owner_id,
            embedding=embedding,
            model=model,
            dimensions=dimensions,
            provider=provider,
            normalization=normalization,
            document_task=document_task,
            query_task=query_task,
            embedding_space_version=embedding_space_version,
            limit=limit,
            timeout=timeout,
            memory_type=None,
            derived=True,
        )

    def _search(
        self,
        *,
        table: str,
        owner_id: str,
        embedding,
        model: str,
        dimensions: int,
        provider: str,
        normalization: str,
        document_task: str,
        query_task: str,
        embedding_space_version: str,
        limit: int,
        timeout: float,
        memory_type: str | None,
        derived: bool,
    ) -> list[ScoredMemory]:
        if limit < 1:
            return []
        if table not in {"memories", "derived_memories"}:
            raise ValueError("memory_table_invalid")
        query_vector = vector(embedding, dimensions)
        query_text = "[" + ",".join(format(value, ".17g") for value in query_vector) + "]"
        scope = current_application_scope()
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        deadline = monotonic() + timeout
        extra_filter = "" if memory_type is None or derived else " AND memory_type=%s"
        params: list[Any] = [
            scope_id,
            owner_id,
            scope.application_id,
            scope.workspace_id,
            provider,
            model,
            dimensions,
            normalization,
            document_task,
            query_task,
            embedding_space_version,
        ]
        if memory_type is not None and not derived:
            params.append(memory_type)
        derived_filter = (
            " AND (SELECT count(*) FROM derived_memory_sources ds WHERE ds.scope_id="
            "derived_memories.scope_id AND ds.derived_memory_id=derived_memories.record_id) BETWEEN 2 AND 4 "
            "AND NOT EXISTS (SELECT 1 FROM derived_memory_sources ds LEFT JOIN memories source "
            "ON source.scope_id=ds.scope_id AND source.record_id=ds.source_memory_id "
            "LEFT JOIN memory_lifecycle_states state ON state.scope_id=ds.scope_id "
            "AND state.record_id=ds.source_memory_id WHERE ds.scope_id=derived_memories.scope_id "
            "AND ds.derived_memory_id=derived_memories.record_id AND (source.record_id IS NULL "
            "OR source.status<>'active' OR source.source_fingerprint<>ds.source_fingerprint "
            "OR COALESCE(state.payload->>'retrieval_status','active')<>'active'))"
            if derived else ""
        )
        lifecycle_filter = (
            " AND COALESCE((SELECT lifecycle.payload->>'retrieval_status' "
            f"FROM memory_lifecycle_states lifecycle WHERE lifecycle.scope_id={table}.scope_id "
            f"AND lifecycle.record_id={table}.record_id),'active')='active'"
        )
        with self.database.connection() as connection:
            count = connection.execute(
                f"SELECT count(*) FROM {table} WHERE scope_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s "
                "AND status='active' AND embedding_provider=%s AND embedding_model=%s "
                "AND embedding_dimensions=%s AND embedding_normalization=%s "
                "AND document_task=%s AND query_task=%s "
                "AND COALESCE(payload->>'embedding_space_version','v1')=%s"
                + extra_filter + lifecycle_filter + derived_filter,
                params,
            ).fetchone()[0]
            if count > self.search_scan_limit:
                raise StorageUnavailableError("memory search parity bound exceeded")
            rows = connection.execute(
                f"SELECT payload,embedding,(embedding::vector <=> %s::vector) AS distance "
                f"FROM {table} WHERE scope_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND status='active' "
                "AND embedding_provider=%s AND embedding_model=%s AND embedding_dimensions=%s "
                "AND embedding_normalization=%s AND document_task=%s AND query_task=%s "
                "AND COALESCE(payload->>'embedding_space_version','v1')=%s"
                + extra_filter
                + lifecycle_filter
                + derived_filter
                + " ORDER BY distance, record_id LIMIT %s",
                [query_text, *params, self.search_scan_limit + 1],
            ).fetchall()
        if monotonic() > deadline:
            raise StorageUnavailableError("memory search timeout")
        if len(rows) > self.search_scan_limit:
            raise StorageUnavailableError("memory search parity bound exceeded")
        scores = []
        model_type = DerivedMemory if derived else Memory
        for payload, values, distance in rows:
            values = tuple(float(value) for value in values)
            cast_similarity = 1.0 - float(distance)
            exact_similarity = sum(
                a * b
                for a, b in zip(query_vector, vector(values, dimensions), strict=True)
            )
            if abs(exact_similarity - cast_similarity) > PGVECTOR_COSINE_ERROR_BOUND:
                raise StorageUnavailableError("memory vector parity bound exceeded")
            record = model_type.model_validate({**payload, "embedding": values})
            if record.owner_id != owner_id or not scope_matches(record, scope):
                raise StorageUnavailableError("memory scope mismatch")
            scores.append(ScoredMemory(record, exact_similarity))
        return sorted(scores, key=lambda score: (-score.similarity, str(score.memory.id)))[:limit]

    def _read_memory_row(self, connection, scope, owner_id, record_id, *, lock=False):
        suffix = " FOR UPDATE" if lock else ""
        return connection.execute(
            "SELECT payload,embedding FROM memories WHERE scope_id=%s AND record_id=%s "
            "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s" + suffix,
            (
                PostgresPayloadRepository.scope_id(owner_id, scope),
                record_id,
                owner_id,
                scope.application_id,
                scope.workspace_id,
            ),
        ).fetchone()

    def _insert_memory(self, connection, scope, memory: Memory) -> None:
        scope_id = _ensure_namespace(connection, memory.owner_id, scope)
        payload = memory.model_dump(mode="json")
        payload.pop("embedding")
        connection.execute(
            "INSERT INTO memories(scope_id,record_id,owner_id,application_id,workspace_id,"
            "memory_type,status,source_conversation_id,source_turn_id,source_message_ids,"
            "source_fingerprint,embedding_provider,embedding_model,embedding_dimensions,"
            "embedding_normalization,document_task,query_task,embedding,created_at,effective_at,payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            (
                scope_id,
                str(memory.id),
                memory.owner_id,
                memory.application_id,
                memory.workspace_id,
                memory.memory_type,
                memory.status,
                str(memory.source_conversation_id),
                str(memory.source_turn_id),
                [str(item) for item in memory.source_message_ids],
                memory.source_fingerprint,
                memory.embedding_provider,
                memory.embedding_model,
                memory.embedding_dimensions,
                memory.embedding_normalization,
                memory.embedding_document_task,
                memory.embedding_query_task,
                list(memory.embedding),
                memory.created_at,
                memory.effective_at,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )

    def _insert_derived(self, connection, scope_id, memory: DerivedMemory) -> None:
        payload = memory.model_dump(mode="json")
        payload.pop("embedding")
        connection.execute(
            "INSERT INTO derived_memories(scope_id,record_id,owner_id,application_id,workspace_id,"
            "memory_type,status,source_set_identity,embedding_provider,embedding_model,"
            "embedding_dimensions,embedding_normalization,document_task,query_task,embedding,"
            "created_at,effective_at,payload) VALUES (%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            (
                scope_id,
                str(memory.id),
                memory.owner_id,
                memory.application_id,
                memory.workspace_id,
                memory.memory_type,
                memory.source_set_identity,
                memory.embedding_provider,
                memory.embedding_model,
                memory.embedding_dimensions,
                memory.embedding_normalization,
                memory.embedding_document_task,
                memory.embedding_query_task,
                list(memory.embedding),
                memory.created_at,
                memory.effective_at,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )


def _scope_of(record: Memory | DerivedMemory) -> ApplicationScope:
    return ApplicationScope(
        application_id=record.application_id, workspace_id=record.workspace_id
    )


def _memory_from_row(row) -> Memory:
    payload, embedding = row
    return Memory.model_validate({**payload, "embedding": tuple(embedding)})


def _model_hash(record: Memory | DerivedMemory) -> str:
    import hashlib

    encoded = record.model_dump_json(exclude_none=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
