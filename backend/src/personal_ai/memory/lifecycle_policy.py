"""Deterministic consolidation, contradiction, and forgetting policies."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.memory.contracts import (
    DerivedMemory,
    DerivedMemorySource,
    Memory,
    normalize,
    vector,
)
from personal_ai.memory.lifecycle import (
    IMPORTANCE_BY_TYPE,
    MemoryJob,
    MemoryLifecycleEvent,
    MemoryLifecycleRepository,
    MemoryLifecycleState,
)
from personal_ai.memory.lifecycle_repositories import event_idempotency_id
from personal_ai.memory.policy import candidate_reason, content_reason
from personal_ai.memory.services import source_messages
from personal_ai.storage.errors import ResourceNotFoundError

DERIVATION_POLICY_VERSION = "extractive-v1"
FORGETTING_POLICY_VERSION = "forget-v1"
CONTRADICTION_POLICY_VERSION = "contradiction-v1"
SUBJECT_SUFFIX = re.compile(r"\bfor\s+([^.!?]{1,100})[.!?]*$", re.IGNORECASE)
EXPLICIT_PREFIXES = (
    "correction:", "actually, i", "actually i", "i now prefer", "i now choose",
    "i no longer prefer", "i no longer choose", "i have switched to",
)


@dataclass(frozen=True)
class ConsolidationPlan:
    status: Literal["ready", "no_plan", "rejected"]
    reason: str
    derived: DerivedMemory | None = None


def _importance(memory: Memory, lifecycle: MemoryLifecycleRepository) -> float:
    state = lifecycle.get_state(owner_id=memory.owner_id, memory_id=memory.id)
    return state.importance if state.importance is not None else IMPORTANCE_BY_TYPE[memory.memory_type]


class DeterministicMemoryConsolidator:
    """Build only exact, repeated assertions. It never paraphrases source text."""

    def plan(
        self,
        *,
        owner_id: str,
        source_ids: tuple[UUID, ...],
        job: MemoryJob,
        settings,
        memories,
        messages,
        lifecycle: MemoryLifecycleRepository,
        embedder,
        now: datetime,
        timeout: float,
    ) -> ConsolidationPlan:
        if len(source_ids) < 2 or len(source_ids) > settings.memory_consolidation_max_sources:
            return ConsolidationPlan("no_plan", "source_count")
        records: list[Memory] = []
        for memory_id in source_ids:
            try:
                memory = memories.get(owner_id=owner_id, memory_id=memory_id, timeout=timeout)
                state = lifecycle.get_state(owner_id=owner_id, memory_id=memory_id)
            except ResourceNotFoundError:
                return ConsolidationPlan("rejected", "source_unavailable")
            if (not isinstance(memory, Memory) or memory.owner_id != owner_id
                    or memory.status != "active" or state.retrieval_status != "active"
                    or source_messages(memory, messages, timeout=timeout) is None):
                return ConsolidationPlan("rejected", "source_inactive")
            if content_reason(memory.content, settings):
                return ConsolidationPlan("rejected", "sensitive_or_external")
            turn = messages.list_active(
                owner_id=owner_id, conversation_id=memory.source_conversation_id, timeout=timeout
            )
            if candidate_reason(
                memory.model_copy(update={"effective_at": (
                    memory.effective_at if memory.effective_at != memory.observed_at else None
                )}),
                turn,
                settings,
            ):
                return ConsolidationPlan("rejected", "source_not_attributable")
            records.append(memory)
        records.sort(key=lambda item: str(item.id))
        if len({record.memory_type for record in records}) != 1:
            return ConsolidationPlan("no_plan", "mixed_types")
        if len({record.embedding_model for record in records}) != 1 or len(
            {record.embedding_dimensions for record in records}
        ) != 1:
            return ConsolidationPlan("rejected", "incompatible_embedding")
        if len({normalize(record.content) for record in records}) != 1:
            return ConsolidationPlan("no_plan", "different_assertions")
        source_type = records[0].memory_type
        if source_type == "preference":
            target_type = "preference"
            rationale = "repeated_explicit_preference"
            if not all(normalize(record.content).startswith((
                "i prefer", "i like", "i dislike", "i always choose"
            )) for record in records):
                return ConsolidationPlan("rejected", "preference_not_explicit")
        elif source_type == "episodic_observation":
            target_type = "semantic_summary"
            rationale = "compatible_episode_history"
            if not all(normalize(record.content).startswith((
                "i visited", "i tried", "i attended", "i experienced"
            )) for record in records):
                return ConsolidationPlan("rejected", "episode_not_explicit")
        else:
            return ConsolidationPlan("no_plan", "unsupported_source_type")
        content = "Historical personal context from repeated user statements:\n" + "\n".join(
            record.content for record in records
        )
        if len(content) > 1000 or content_reason(content, settings):
            return ConsolidationPlan("rejected", "derived_content_rejected")
        source_set = tuple(
            DerivedMemorySource(
                memory_id=record.id,
                source_fingerprint=record.source_fingerprint,
                source_conversation_id=record.source_conversation_id,
                source_turn_id=record.source_turn_id,
                source_message_ids=record.source_message_ids,
                excerpt=record.content,
            )
            for record in records
        )
        identity = hashlib.sha256(
            "\0".join(
                [owner_id, DERIVATION_POLICY_VERSION]
                + [f"{item.memory_id}:{item.source_fingerprint}" for item in source_set]
            ).encode()
        ).hexdigest()
        derived_id = uuid5(NAMESPACE_URL, "personal-ai-derived-memory:" + identity)
        canonical_ids = tuple(sorted((record.id for record in records), key=str))
        if job.candidate_memory_ids != canonical_ids:
            return ConsolidationPlan("rejected", "job_source_mismatch")
        vectors = embedder.embed([content], timeout=timeout)
        if len(vectors) != 1:
            return ConsolidationPlan("rejected", "embedding_invalid")
        dimensions = records[0].embedding_dimensions
        max_importance = max(_importance(record, lifecycle) for record in records)
        confidence = min(record.confidence for record in records)
        effective = max(record.effective_at for record in records)
        derived = DerivedMemory(
            id=derived_id,
            owner_id=owner_id,
            memory_type=target_type,
            content=content,
            normalized_content=normalize(content),
            confidence=confidence,
            importance=min(IMPORTANCE_BY_TYPE[target_type], max_importance),
            effective_at=effective,
            created_at=now.astimezone(UTC),
            embedding=vector(vectors[0], dimensions),
            embedding_model=records[0].embedding_model,
            embedding_dimensions=dimensions,
            source_memory_ids=tuple(item.memory_id for item in source_set),
            sources=source_set,
            source_set_identity=identity,
            derivation_policy_version=DERIVATION_POLICY_VERSION,
            rationale_code=rationale,
        )
        return ConsolidationPlan("ready", "extractive_exact_repeat", derived)


@dataclass(frozen=True)
class ParsedAssertion:
    subject_key: str
    value_key: str
    explicit_replacement: bool


def parse_assertion(memory: Memory) -> ParsedAssertion | None:
    """Parse the deliberately narrow '... for <subject>' statement grammar."""
    text = normalize(memory.content)
    explicit = any(text.startswith(item) for item in EXPLICIT_PREFIXES)
    body = text
    if body.startswith("correction:"):
        body = body[len("correction:"):].lstrip(" :,")
    if body.startswith("actually,"):
        body = body[len("actually,"):].lstrip()
    elif body.startswith("actually "):
        body = body[len("actually "):].lstrip()
    if body.startswith("i now prefer "):
        body = body[len("i now prefer "):]
    elif body.startswith("i prefer "):
        body = body[len("i prefer "):]
    elif body.startswith("i now choose "):
        body = body[len("i now choose "):]
    elif body.startswith("i choose "):
        body = body[len("i choose "):]
    suffix = SUBJECT_SUFFIX.search(body)
    if suffix is None:
        return None
    subject = normalize(suffix.group(1))
    value = normalize(body[: suffix.start()])
    if not subject or not value:
        return None
    return ParsedAssertion(subject, value, explicit or "now" in normalize(memory.content))


def contradiction_decision(older: Memory, newer: Memory) -> Literal["supersede", "review", "none"]:
    """Return a conservative exact-subject decision; no language model is involved."""
    if older.owner_id != newer.owner_id:
        return "none"
    if newer.effective_at <= older.effective_at or newer.confidence < 0.9:
        return "none"
    compatible = {
        ("preference", "preference"),
        ("preference", "explicit_correction"),
        ("explicit_correction", "explicit_correction"),
    }
    if (older.memory_type, newer.memory_type) not in compatible:
        return "none"
    old_assertion, new_assertion = parse_assertion(older), parse_assertion(newer)
    if old_assertion is None or new_assertion is None:
        return "review" if (newer.memory_type == "explicit_correction"
                             or any(normalize(newer.content).startswith(p) for p in EXPLICIT_PREFIXES)) else "none"
    if old_assertion.subject_key != new_assertion.subject_key:
        return "none"
    if old_assertion.value_key == new_assertion.value_key:
        return "none"
    explicit = (new_assertion.explicit_replacement
                or newer.memory_type == "explicit_correction")
    return "supersede" if explicit else "review"


@dataclass(frozen=True)
class ForgettingDecision:
    eligible: bool
    reason: str


def forgetting_decision(
    memory: Memory,
    state: MemoryLifecycleState,
    *,
    now: datetime,
    dependencies: tuple[UUID, ...] | None,
    dependency_lookup_complete: bool,
) -> ForgettingDecision:
    if dependencies is None or not dependency_lookup_complete:
        return ForgettingDecision(False, "dependencies_unknown")
    if state.retrieval_status != "active":
        return ForgettingDecision(False, "already_inactive")
    if memory.memory_type not in ("episodic_observation", "semantic_summary"):
        return ForgettingDecision(False, "protected_type")
    age_days = (now.astimezone(UTC) - memory.effective_at.astimezone(UTC)).total_seconds() / 86400
    if age_days < 365:
        return ForgettingDecision(False, "too_recent")
    if memory.confidence >= 0.5:
        return ForgettingDecision(False, "confidence_protected")
    if memory.memory_type == "explicit_correction" or state.retrieval_count != 0:
        return ForgettingDecision(False, "retrieved_or_correction")
    if dependencies:
        return ForgettingDecision(False, "active_dependent")
    return ForgettingDecision(True, "stale_low_value")


def make_event(
    *,
    owner_id: str,
    memory_id: UUID,
    event_type: str,
    reason_code: str,
    policy_version: str,
    idempotency_key: str,
    expected_state_version: int,
    occurred_at: datetime,
    related_memory_ids: tuple[UUID, ...] = (),
    job_id: UUID | None = None,
) -> MemoryLifecycleEvent:
    return MemoryLifecycleEvent(
        id=event_idempotency_id(idempotency_key), owner_id=owner_id, memory_id=memory_id,
        event_type=event_type, reason_code=reason_code, policy_version=policy_version,
        actor="system", occurred_at=occurred_at, idempotency_key=idempotency_key,
        related_memory_ids=related_memory_ids, expected_state_version=expected_state_version,
        job_id=job_id,
    )
