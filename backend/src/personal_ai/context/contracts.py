"""Provider-neutral, immutable context and conversation-summary contracts."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from itertools import pairwise
from typing import Literal, Protocol
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from personal_ai.context.providers import ContextItem, ContextProviderFailure
from personal_ai.entities import Message
from personal_ai.entities.conversation import TimestampedRecord
from personal_ai.llm.client import ChatMessage


class ContextError(Exception):
    """A safe preparation failure that happens before an assistant is created."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class TokenCount:
    tokens: int
    kind: Literal["provider", "estimated"]

    def __post_init__(self) -> None:
        if self.tokens < 0:
            raise ValueError("negative token count")


class TokenCounter(Protocol):
    def count(self, messages: Sequence[ChatMessage]) -> TokenCount: ...


@dataclass(frozen=True)
class SummaryDraft:
    content: str
    model: str


class ConversationSummarizer(Protocol):
    def summarize(
        self,
        source_messages: Sequence[Message],
        prior_summary: "ConversationSummary | None",
    ) -> SummaryDraft: ...


class ConversationSummary(TimestampedRecord):
    """Append-only lossy working context, never durable user memory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    conversation_id: UUID
    owner_id: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=20_000)
    source_message_ids: tuple[UUID, ...]
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Coverage includes skipped incomplete turns; sources contain only complete turns.
    # Empty coverage preserves compatibility with existing contiguous summaries.
    coverage_message_ids: tuple[UUID, ...] = ()
    coverage_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    covers_through_message_id: UUID
    source_token_count: int = Field(ge=0)
    summary_token_count: int = Field(ge=0)
    counter_kind: Literal["provider", "estimated"] = "estimated"
    model: str = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_coverage(self) -> "ConversationSummary":
        if not self.content.strip() or not self.source_message_ids:
            raise ValueError("empty summary")
        if self.source_message_ids[-1] != self.covers_through_message_id:
            raise ValueError("summary coverage mismatch")
        if bool(self.coverage_message_ids) != bool(self.coverage_fingerprint):
            raise ValueError("incomplete coverage provenance")
        if self.coverage_message_ids and (
            self.coverage_message_ids[-1] != self.covers_through_message_id
            or not set(self.source_message_ids).issubset(self.coverage_message_ids)
        ):
            raise ValueError("summary coverage mismatch")
        return self


class ConversationSummaryRepository(Protocol):
    def create(self, summary: ConversationSummary) -> ConversationSummary: ...
    def compatible(
        self,
        *,
        owner_id: str,
        conversation_id: UUID,
        active: Sequence[Message],
    ) -> ConversationSummary | None: ...


def fingerprint(messages: Sequence[Message], *, include_state: bool = False) -> str:
    payload = [
        (str(m.id), m.role.value, m.content)
        + ((m.status.value, str(m.parent_message_id)) if include_state else ())
        for m in messages
    ]
    return sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def complete_turns(messages: Sequence[Message]) -> list[tuple[Message, Message]]:
    return [
        (user, assistant)
        for user, assistant in pairwise(messages)
        if user.role.value == "user" and assistant.role.value == "assistant"
        and user.status.value == assistant.status.value == "completed"
        and assistant.parent_message_id == user.id
    ]


def is_compatible(summary: ConversationSummary, active: Sequence[Message]) -> bool:
    coverage = summary.coverage_message_ids or summary.source_message_ids
    prefix = active[: len(coverage)]
    sources = [m for turn in complete_turns(prefix) for m in turn]
    return (
        tuple(m.id for m in prefix) == coverage
        and tuple(m.id for m in sources) == summary.source_message_ids
        and all(
            m.status.value != "superseded"
            and m.owner_id == summary.owner_id
            and m.conversation_id == summary.conversation_id
            for m in prefix
        )
        and fingerprint(sources) == summary.source_fingerprint
        and (not summary.coverage_fingerprint
             or fingerprint(prefix, include_state=True) == summary.coverage_fingerprint)
    )


@dataclass(frozen=True)
class BudgetReport:
    capacity: int
    response_reserve: int
    safety_margin: int
    input_budget: int
    mandatory_tokens: int
    summary_tokens: int
    history_tokens: int
    selected_total: int
    counter_kind: str
    memory_tokens: int = 0


@dataclass(frozen=True)
class AssembledContext:
    messages: tuple[ChatMessage, ...]
    selected_message_ids: tuple[UUID, ...]
    excluded: tuple[tuple[UUID, str], ...]
    summary: ConversationSummary | None
    budget: BudgetReport
    diagnostics: tuple[str, ...] = ()
    selected_memory_ids: tuple[UUID, ...] = ()
    excluded_memories: tuple[tuple[UUID, str], ...] = ()
    memory_tokens: int = 0
    source_items: tuple[ContextItem, ...] = ()
    source_failures: tuple[ContextProviderFailure, ...] = ()
