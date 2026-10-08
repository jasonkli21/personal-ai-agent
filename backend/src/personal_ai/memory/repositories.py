"""Owner-scoped memory stores with bounded, scope-correct retrieval."""

from threading import RLock
from uuid import UUID

from personal_ai.auth.scope import (
    scope_matches,
    scoped_record,
)
from personal_ai.context.contracts import fingerprint
from personal_ai.memory.contracts import DerivedMemory, Memory, ScoredMemory, identity, vector
from personal_ai.storage.errors import (
    ConversationConflictError,
    ResourceNotFoundError,
)


def validate(memory):
    record = Memory.model_validate(memory.model_dump())
    if record.id != identity(
        record.owner_id,
        record.source_fingerprint,
        record,
        application_id=record.application_id,
        workspace_id=record.workspace_id,
    ):
        raise ValueError("identity_invalid")
    return record.model_copy(
        update={"embedding": vector(record.embedding, record.embedding_dimensions)}
    )


class InMemoryMemoryRepository:
    def __init__(self, messages):
        self.messages = messages
        self.records: dict[UUID, Memory] = {}
        self.derived_records: dict[UUID, DerivedMemory] = {}
        self._lock = RLock()

    def create(self, memory, *, timeout=5):
        memory = validate(scoped_record(memory))
        with self.messages._mutation_lock:
            return self._create(memory)

    def _create(self, memory):
        with self._lock:
            if memory.id in self.records:
                return self.get(owner_id=memory.owner_id, memory_id=memory.id), False
            if self.messages is not None:
                active = self.messages.list_active(
                    owner_id=memory.owner_id,
                    conversation_id=memory.source_conversation_id,
                )
                sources = [m for m in active if m.id in memory.source_message_ids]
                assistant = next((m for m in active if m.id == memory.source_turn_id), None)
                if (
                    assistant is None
                    or assistant.status.value != "completed"
                    or assistant.role.value != "assistant"
                    or assistant.parent_message_id not in memory.source_message_ids
                    or tuple(m.id for m in sources) != memory.source_message_ids
                    or fingerprint(sources) != memory.source_fingerprint
                ):
                    raise ConversationConflictError("memory source inactive")
            self.records[memory.id] = memory
            return memory, True

    def get(self, *, owner_id, memory_id, timeout=5):
        record = self.records.get(memory_id)
        if record is None or record.owner_id != owner_id or not scope_matches(record):
            raise ResourceNotFoundError("memory not found")
        return record

    def search(
        self,
        *,
        owner_id,
        embedding,
        model,
        dimensions,
        provider="google_genai",
        normalization="l2",
        document_task="RETRIEVAL_DOCUMENT",
        query_task="RETRIEVAL_QUERY",
        embedding_space_version="v1",
        limit,
        timeout=5,
        memory_type=None,
    ):
        query = vector(embedding, dimensions)
        with self._lock:
            scores = [
                ScoredMemory(
                    m,
                    sum(a * b for a, b in zip(query, vector(m.embedding, dimensions), strict=True)),
                )
                for m in self.records.values()
                if m.owner_id == owner_id
                and scope_matches(m)
                and m.status == "active"
                and m.embedding_model == model
                and m.embedding_dimensions == dimensions
                and m.embedding_provider == provider
                and m.embedding_normalization == normalization
                and m.embedding_document_task == document_task
                and m.embedding_query_task == query_task
                and m.embedding_space_version == embedding_space_version
                and (memory_type is None or m.memory_type == memory_type)
            ]
        return sorted(scores, key=lambda s: (-s.similarity, str(s.memory.id)))[:limit]

    def get_derived(self, *, owner_id, memory_id, timeout=5):
        record = self.derived_records.get(memory_id)
        if record is None or record.owner_id != owner_id or not scope_matches(record):
            raise ResourceNotFoundError("memory not found")
        return record

    def search_derived(
        self,
        *,
        owner_id,
        embedding,
        model,
        dimensions,
        provider="google_genai",
        normalization="l2",
        document_task="RETRIEVAL_DOCUMENT",
        query_task="RETRIEVAL_QUERY",
        embedding_space_version="v1",
        limit,
        timeout=5,
    ):
        query = vector(embedding, dimensions)
        with self._lock:
            scores = [
                ScoredMemory(
                    record,
                    sum(
                        a * b
                        for a, b in zip(query, vector(record.embedding, dimensions), strict=True)
                    ),
                )
                for record in self.derived_records.values()
                if record.owner_id == owner_id
                and scope_matches(record)
                and record.embedding_model == model
                and record.embedding_dimensions == dimensions
                and record.embedding_provider == provider
                and record.embedding_normalization == normalization
                and record.embedding_document_task == document_task
                and record.embedding_query_task == query_task
                and record.embedding_space_version == embedding_space_version
            ]
        return sorted(scores, key=lambda s: (-s.similarity, str(s.memory.id)))[:limit]
