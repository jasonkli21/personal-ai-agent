"""Owner-scoped append-only summary repositories."""

from collections.abc import Sequence
from threading import RLock
from uuid import UUID

from personal_ai.auth.scope import scope_matches, scoped_record
from personal_ai.context.contracts import ConversationSummary, is_compatible
from personal_ai.entities import Message
from personal_ai.storage.errors import ConversationConflictError


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
