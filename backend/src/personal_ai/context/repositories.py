"""Owner-scoped append-only summary repositories."""

from collections.abc import Sequence
from threading import RLock
from typing import Any
from uuid import UUID

from google.cloud import firestore

from personal_ai.auth.scope import scope_matches, scope_query, scoped_record
from personal_ai.context.contracts import ConversationSummary, is_compatible
from personal_ai.entities import Message
from personal_ai.storage.errors import ConversationConflictError
from personal_ai.storage.firestore import FirestoreConversationRepository, _firestore_client


def newest_compatible(
    summaries: Sequence[ConversationSummary],
    active: Sequence[Message],
) -> ConversationSummary | None:
    usable = [s for s in summaries if is_compatible(s, active)]
    return max(usable, key=lambda s: (s.created_at, str(s.id)), default=None)


class InMemorySummaryRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, ConversationSummary] = {}
        self._lock = RLock()

    def create(self, summary: ConversationSummary) -> ConversationSummary:
        summary = scoped_record(summary)
        with self._lock:
            if summary.id in self.records:
                raise ConversationConflictError("summary already exists")
            self.records[summary.id] = summary
        return summary

    def compatible(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        active: Sequence[Message],
    ) -> ConversationSummary | None:
        with self._lock:
            return newest_compatible(
                [
                    s
                    for s in self.records.values()
                    if s.owner_id == owner_id and s.conversation_id == conversation_id
                    and scope_matches(s)
                ],
                active,
            )


class FirestoreSummaryRepository:
    def __init__(
        self,
        client: Any = None,
        *,
        project_id: str | None = None,
        emulator_host: str | None = None,
    ) -> None:
        self._client = (
            client if client is not None else _firestore_client(project_id, emulator_host)
        )
        self._collection = self._client.collection("conversation_summaries")
        self._conversations = FirestoreConversationRepository(self._client)

    def create(self, summary: ConversationSummary) -> ConversationSummary:
        summary = scoped_record(summary)
        self._conversations.get(owner_id=summary.owner_id, conversation_id=summary.conversation_id)
        data = summary.model_dump(mode="json")
        data["created_at"] = summary.created_at
        self._conversations._run(lambda: self._collection.document(str(summary.id)).create(data))
        return summary

    def compatible(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        active: Sequence[Message],
    ) -> ConversationSummary | None:
        self._conversations.get(owner_id=owner_id, conversation_id=conversation_id)
        def fetch():
            query = scope_query(
                self._collection.where(filter=firestore.FieldFilter("owner_id", "==", owner_id))
                .where(filter=firestore.FieldFilter("conversation_id", "==", str(conversation_id)))
            )
            return list(query.stream())

        snapshots = self._conversations._run(fetch)
        summaries = [
            summary for snapshot in snapshots
            if scope_matches(summary := ConversationSummary.model_validate(snapshot.to_dict()))
        ]
        return newest_compatible(summaries, active)
