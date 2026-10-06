"""Owner-scoped memory stores with bounded, scope-correct retrieval."""

import math
from threading import RLock
from time import monotonic
from uuid import UUID

from google.cloud import firestore
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector

from personal_ai.auth.scope import (
    current_application_scope,
    data_scope_matches,
    scope_matches,
    scope_query,
    scoped_record,
)
from personal_ai.context.contracts import fingerprint
from personal_ai.entities import Message
from personal_ai.memory.contracts import DerivedMemory, Memory, ScoredMemory, identity, vector
from personal_ai.storage.errors import (
    ConversationConflictError,
    ResourceNotFoundError,
    StorageUnavailableError,
)
from personal_ai.storage.firestore import FirestoreConversationRepository, _firestore_client
from personal_ai.storage.transactions import bounded_transaction


def _standalone_scoped_vector_scan(collection, *, owner_id, embedding, model, dimensions,
                                   limit, timeout, memory_type=None, derived=False):
    """Rank eligible standalone records before applying the result limit.

    Firestore cannot query legacy documents whose scope fields are absent. A
    bounded owner scan preserves legacy recall without letting foreign vectors
    consume the KNN top-k window.
    """
    query = collection.where(filter=firestore.FieldFilter("owner_id", "==", owner_id))
    for field, value in (("embedding_model", model), ("embedding_dimensions", dimensions)):
        query = query.where(filter=firestore.FieldFilter(field, "==", value))
    if not derived:
        query = query.where(filter=firestore.FieldFilter("status", "==", "active"))
        if memory_type is not None:
            query = query.where(filter=firestore.FieldFilter("memory_type", "==", memory_type))
    cursor = None
    scanned = 0
    deadline = monotonic() + timeout
    scored = []
    target = vector(embedding, dimensions)
    target_norm = math.sqrt(sum(value * value for value in target))
    while scanned < 5_000:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("memory scope scan deadline exceeded")
        page_query = query.order_by("__name__").limit(min(250, 5_000 - scanned))
        if cursor is not None:
            page_query = page_query.start_after(cursor)
        page = list(page_query.stream(retry=None, timeout=remaining))
        if not page:
            break
        scanned += len(page)
        cursor = page[-1]
        for snapshot in page:
            data = snapshot.to_dict()
            if not data_scope_matches(data):
                continue
            data["embedding"] = tuple(data["embedding"])
            record = (DerivedMemory if derived else Memory).model_validate(data)
            values = vector(record.embedding, dimensions)
            norm = math.sqrt(sum(value * value for value in values))
            similarity = sum(a * b for a, b in zip(values, target, strict=True)) / (norm * target_norm)
            scored.append(ScoredMemory(record, similarity))
        if len(page) < min(250, 5_000 - scanned + len(page)):
            break
    if scanned >= 5_000 and cursor is not None:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("memory scope scan deadline exceeded")
        probe = list(
            query.order_by("__name__").start_after(cursor).limit(1).stream(
                retry=None, timeout=remaining
            )
        )
        if probe:
            raise StorageUnavailableError("memory scope scan exceeded its record bound")
    return sorted(scored, key=lambda item: (-item.similarity, str(item.memory.id)))[:limit]


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

    def search(self, *, owner_id, embedding, model, dimensions, limit, timeout=5, memory_type=None):
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
                and (memory_type is None or m.memory_type == memory_type)
            ]
        return sorted(scores, key=lambda s: (-s.similarity, str(s.memory.id)))[:limit]

    def get_derived(self, *, owner_id, memory_id, timeout=5):
        record = self.derived_records.get(memory_id)
        if record is None or record.owner_id != owner_id or not scope_matches(record):
            raise ResourceNotFoundError("memory not found")
        return record

    def search_derived(self, *, owner_id, embedding, model, dimensions, limit, timeout=5):
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
            ]
        return sorted(scores, key=lambda s: (-s.similarity, str(s.memory.id)))[:limit]


class FirestoreMemoryRepository:
    def __init__(self, client=None, *, project_id=None, emulator_host=None):
        self.client = client or _firestore_client(project_id, emulator_host)
        self.collection = self.client.collection("memories")
        self._run = FirestoreConversationRepository._run

    @staticmethod
    def _record(snapshot):
        try:
            data = snapshot.to_dict()
            data["embedding"] = tuple(data["embedding"])
            return validate(Memory.model_validate(data))
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("memory record invalid") from error

    def get(self, *, owner_id, memory_id, timeout=5):
        snapshot = self._run(
            lambda: self.collection.document(str(memory_id)).get(retry=None, timeout=timeout)
        )
        if not snapshot.exists:
            raise ResourceNotFoundError("memory not found")
        record = self._record(snapshot)
        if record.owner_id != owner_id or not scope_matches(record):
            raise ResourceNotFoundError("memory not found")
        return record

    def create(self, memory, *, timeout=5):
        memory = validate(scoped_record(memory))
        reference = self.collection.document(str(memory.id))
        data = memory.model_dump(mode="json")
        data.update(
            embedding=Vector(memory.embedding),
            created_at=memory.created_at,
            observed_at=memory.observed_at,
            effective_at=memory.effective_at,
        )

        deadline = monotonic() + timeout

        def remaining():
            left = deadline - monotonic()
            if left <= 0:
                raise TimeoutError("memory_timeout")
            return left

        def write(transaction):
            snapshot = reference.get(transaction=transaction, retry=None, timeout=remaining())
            if snapshot.exists:
                existing = self._record(snapshot)
                if existing.owner_id != memory.owner_id or not scope_matches(existing):
                    raise ResourceNotFoundError("memory not found")
                return existing, False
            # Read the source and all ancestors in this transaction: a concurrent
            # root-cut edit conflicts with these reads, preventing an obsolete write.
            conversation = (
                self.client.collection("conversations")
                .document(str(memory.source_conversation_id))
                .get(transaction=transaction, retry=None, timeout=remaining())
            )
            if (not conversation.exists or conversation.to_dict().get("owner_id") != memory.owner_id
                    or not data_scope_matches(conversation.to_dict())):
                raise ResourceNotFoundError("memory source not found")
            if conversation.to_dict().get("context_preparation_id"):
                raise ConversationConflictError("memory source changing")
            assistant_snapshot = (
                self.client.collection("messages")
                .document(str(memory.source_turn_id))
                .get(transaction=transaction, retry=None, timeout=remaining())
            )
            if not assistant_snapshot.exists:
                raise ConversationConflictError("memory source incomplete")
            assistant = Message.model_validate(assistant_snapshot.to_dict())
            if (
                assistant.owner_id != memory.owner_id
                or assistant.conversation_id != memory.source_conversation_id
                or not scope_matches(assistant)
                or assistant.role.value != "assistant"
                or assistant.status.value != "completed"
                or assistant.parent_message_id not in memory.source_message_ids
            ):
                raise ConversationConflictError("memory source incomplete")
            sources, ancestors = [], {}
            for source_id in memory.source_message_ids:
                current = source_id
                first = True
                path = set()
                while current is not None:
                    if current in path:
                        raise ConversationConflictError("memory source ancestry invalid")
                    path.add(current)
                    if current in ancestors:
                        if first:
                            source = ancestors[current]
                            if source.role.value != "user" or source.status.value != "completed":
                                raise ConversationConflictError("memory source incomplete")
                            sources.append(source)
                        break
                    snapshot = (
                        self.client.collection("messages")
                        .document(str(current))
                        .get(transaction=transaction, retry=None, timeout=remaining())
                    )
                    if not snapshot.exists:
                        raise ConversationConflictError("memory source unavailable")
                    message = Message.model_validate(snapshot.to_dict())
                    if (
                        message.id != current
                        or message.owner_id != memory.owner_id
                        or message.conversation_id != memory.source_conversation_id
                        or not scope_matches(message)
                        or message.status.value == "superseded"
                    ):
                        raise ConversationConflictError("memory source inactive")
                    if first:
                        if message.role.value != "user" or message.status.value != "completed":
                            raise ConversationConflictError("memory source incomplete")
                        sources.append(message)
                        first = False
                    ancestors[current] = message
                    current = message.parent_message_id
            if fingerprint(sources) != memory.source_fingerprint:
                raise ConversationConflictError("memory source changed")
            transaction.create(reference, data)
            return memory, True

        def operation():
            return bounded_transaction(
                self.client, lambda transaction, _: write(transaction), seconds=remaining()
            )

        return self._run(operation)

    def search(self, *, owner_id, embedding, model, dimensions, limit, timeout=5, memory_type=None):
        requested_scope = current_application_scope()
        if requested_scope.application_id == "personal_ai" and requested_scope.workspace_id is None:
            return self._run(lambda: _standalone_scoped_vector_scan(
                self.collection, owner_id=owner_id, embedding=embedding, model=model,
                dimensions=dimensions, limit=limit, timeout=timeout, memory_type=memory_type,
            ))
        query = self.collection
        for field, value in (
            ("owner_id", owner_id),
            ("status", "active"),
            ("embedding_model", model),
            ("embedding_dimensions", dimensions),
        ):
            query = query.where(filter=firestore.FieldFilter(field, "==", value))
        query = scope_query(query)
        candidate_limit = limit
        if memory_type is not None:
            query = query.where(filter=firestore.FieldFilter("memory_type", "==", memory_type))
        nearest = query.find_nearest(
            vector_field="embedding",
            query_vector=Vector(vector(embedding, dimensions)),
            distance_measure=DistanceMeasure.COSINE,
            limit=candidate_limit,
            distance_result_field="vector_distance",
        )
        result = []
        for snapshot in self._run(lambda: list(nearest.stream(retry=None, timeout=timeout))):
            data = snapshot.to_dict()
            distance = data.pop("vector_distance")
            # The distance is query metadata, never a persisted memory field.
            data["embedding"] = tuple(data["embedding"])
            try:
                memory = validate(Memory.model_validate(data))
            except (ValueError, TypeError, KeyError) as error:
                raise StorageUnavailableError("memory record invalid") from error
            if scope_matches(memory):
                result.append(ScoredMemory(memory, 1 - distance))
        return sorted(result, key=lambda s: (-s.similarity, str(s.memory.id)))[:limit]

    def get_derived(self, *, owner_id, memory_id, timeout=5):
        snapshot = self._run(
            lambda: (
                self.client.collection("derived_memories")
                .document(str(memory_id))
                .get(retry=None, timeout=timeout)
            )
        )
        if not snapshot.exists:
            raise ResourceNotFoundError("memory not found")
        data = snapshot.to_dict()
        data["embedding"] = tuple(data["embedding"])
        try:
            record = DerivedMemory.model_validate(data)
        except (ValueError, TypeError, KeyError) as error:
            raise StorageUnavailableError("derived memory record invalid") from error
        if record.owner_id != owner_id or not scope_matches(record):
            raise ResourceNotFoundError("memory not found")
        return record

    def search_derived(self, *, owner_id, embedding, model, dimensions, limit, timeout=5):
        requested_scope = current_application_scope()
        derived_collection = self.client.collection("derived_memories")
        if requested_scope.application_id == "personal_ai" and requested_scope.workspace_id is None:
            return self._run(lambda: _standalone_scoped_vector_scan(
                derived_collection, owner_id=owner_id, embedding=embedding, model=model,
                dimensions=dimensions, limit=limit, timeout=timeout, derived=True,
            ))
        query = self.client.collection("derived_memories")
        for field, value in (
            ("owner_id", owner_id),
            ("embedding_model", model),
            ("embedding_dimensions", dimensions),
        ):
            query = query.where(filter=firestore.FieldFilter(field, "==", value))
        query = scope_query(query)
        candidate_limit = limit
        nearest = query.find_nearest(
            vector_field="embedding",
            query_vector=Vector(vector(embedding, dimensions)),
            distance_measure=DistanceMeasure.COSINE,
            limit=candidate_limit,
            distance_result_field="vector_distance",
        )
        result = []
        for snapshot in self._run(lambda: list(nearest.stream(retry=None, timeout=timeout))):
            data = snapshot.to_dict()
            distance = data.pop("vector_distance")
            data["embedding"] = tuple(data["embedding"])
            try:
                record = DerivedMemory.model_validate(data)
            except (ValueError, TypeError, KeyError) as error:
                raise StorageUnavailableError("derived memory record invalid") from error
            if scope_matches(record):
                result.append(ScoredMemory(record, 1 - distance))
        return sorted(result, key=lambda s: (-s.similarity, str(s.memory.id)))[:limit]
