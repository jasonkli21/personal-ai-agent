"""Owner-scoped memory stores; production search is bounded indexed KNN only."""

import logging
from threading import RLock
from time import monotonic
from uuid import UUID

from google.cloud import firestore
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector

from personal_ai.context.contracts import fingerprint
from personal_ai.entities import Message
from personal_ai.memory.contracts import Memory, ScoredMemory, identity, vector
from personal_ai.storage.errors import (
    ConversationConflictError,
    ResourceNotFoundError,
    StorageUnavailableError,
)
from personal_ai.storage.firestore import FirestoreConversationRepository, _firestore_client


def validate(memory):
    record = Memory.model_validate(memory.model_dump())
    if record.id != identity(record.owner_id, record.source_fingerprint, record):
        raise ValueError("identity_invalid")
    return record.model_copy(
        update={"embedding": vector(record.embedding, record.embedding_dimensions)}
    )


class InMemoryMemoryRepository:
    def __init__(self, messages):
        self.messages = messages
        self.records: dict[UUID, Memory] = {}
        self._lock = RLock()

    def create(self, memory, *, timeout=5):
        memory = validate(memory)
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
        if record is None or record.owner_id != owner_id:
            raise ResourceNotFoundError("memory not found")
        return record

    def search(self, *, owner_id, embedding, model, dimensions, limit, timeout=5):
        query = vector(embedding, dimensions)
        with self._lock:
            scores = [
                ScoredMemory(
                    m,
                    sum(a * b for a, b in zip(query, vector(m.embedding, dimensions), strict=True)),
                )
                for m in self.records.values()
                if m.owner_id == owner_id
                and m.status == "active"
                and m.embedding_model == model
                and m.embedding_dimensions == dimensions
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
        if record.owner_id != owner_id:
            raise ResourceNotFoundError("memory not found")
        return record

    def create(self, memory, *, timeout=5):
        memory = validate(memory)
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
                if existing.owner_id != memory.owner_id:
                    raise ResourceNotFoundError("memory not found")
                return existing, False
            # Read the source and all ancestors in this transaction: a concurrent
            # root-cut edit conflicts with these reads, preventing an obsolete write.
            conversation = (
                self.client.collection("conversations")
                .document(str(memory.source_conversation_id))
                .get(transaction=transaction, retry=None, timeout=remaining())
            )
            if not conversation.exists or conversation.to_dict().get("owner_id") != memory.owner_id:
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
                or assistant.role.value != "assistant"
                or assistant.status.value != "completed"
                or assistant.parent_message_id not in memory.source_message_ids
            ):
                raise ConversationConflictError("memory source incomplete")
            sources, visited = [], set()
            for source_id in memory.source_message_ids:
                current = source_id
                first = True
                while current is not None:
                    if current in visited:
                        break
                    visited.add(current)
                    snapshot = (
                        self.client.collection("messages")
                        .document(str(current))
                        .get(transaction=transaction, retry=None, timeout=remaining())
                    )
                    if not snapshot.exists:
                        raise ConversationConflictError("memory source unavailable")
                    message = Message.model_validate(snapshot.to_dict())
                    if (
                        message.owner_id != memory.owner_id
                        or message.conversation_id != memory.source_conversation_id
                        or message.status.value == "superseded"
                    ):
                        raise ConversationConflictError("memory source inactive")
                    if first:
                        if message.role.value != "user" or message.status.value != "completed":
                            raise ConversationConflictError("memory source incomplete")
                        sources.append(message)
                        first = False
                    current = message.parent_message_id
            if fingerprint(sources) != memory.source_fingerprint:
                raise ConversationConflictError("memory source changed")
            transaction.create(reference, data)
            return memory, True

        def operation():
            # SDK transactional decorator uses unbounded default RPC retries for
            # begin/commit. Keep those SDK details here and give every RPC the
            # remaining operation deadline, without transaction retries.
            transaction = self.client.transaction(max_attempts=1)
            api = self.client._firestore_api
            response = api.begin_transaction(
                request={"database": self.client._database_string},
                metadata=self.client._rpc_metadata,
                retry=None,
                timeout=remaining(),
            )
            transaction._id = response.transaction
            try:
                result = write(transaction)
                api.commit(
                    request={
                        "database": self.client._database_string,
                        "transaction": transaction.id,
                        "writes": transaction._write_pbs,
                    },
                    metadata=self.client._rpc_metadata,
                    retry=None,
                    timeout=remaining(),
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
                except Exception:  # noqa: BLE001 - preserve original failure
                    logging.getLogger(__name__).info("Memory transaction rollback failed")
                raise
            finally:
                transaction._clean_up()

        return self._run(operation)

    def search(self, *, owner_id, embedding, model, dimensions, limit, timeout=5):
        query = self.collection
        for field, value in (
            ("owner_id", owner_id),
            ("status", "active"),
            ("embedding_model", model),
            ("embedding_dimensions", dimensions),
        ):
            query = query.where(filter=firestore.FieldFilter(field, "==", value))
        nearest = query.find_nearest(
            vector_field="embedding",
            query_vector=Vector(vector(embedding, dimensions)),
            distance_measure=DistanceMeasure.COSINE,
            limit=limit,
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
            result.append(ScoredMemory(memory, 1 - distance))
        return sorted(result, key=lambda s: (-s.similarity, str(s.memory.id)))
