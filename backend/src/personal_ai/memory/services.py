"""Bounded extraction and advisory semantic retrieval; no lifecycle mutations."""

import logging
import math
from datetime import UTC, datetime
from time import monotonic

from personal_ai.context.contracts import complete_turns, fingerprint
from personal_ai.memory.contracts import (
    ExtractionResult,
    Memory,
    RetrievalResult,
    identity,
    normalize,
    vector,
)
from personal_ai.memory.policy import candidate_reason, content_reason

logger = logging.getLogger(__name__)


def source_messages(memory, messages, *, timeout=5):
    active = messages.list_active(
        owner_id=memory.owner_id, conversation_id=memory.source_conversation_id, timeout=timeout
    )
    source = [m for m in active if m.id in memory.source_message_ids]
    if (
        tuple(m.id for m in source) != memory.source_message_ids
        or not all(m.role.value == "user" and m.status.value == "completed" for m in source)
        or fingerprint(source) != memory.source_fingerprint
    ):
        return None
    completed_users = {u.id for u, a in complete_turns(active)}
    return source if set(memory.source_message_ids) <= completed_users else None


class MemoryExtractionService:
    def __init__(self, settings, repository, messages, extractor, embedder, *, clock=None):
        self.settings, self.repository, self.messages = settings, repository, messages
        self.extractor, self.embedder = extractor, embedder
        self.clock = clock or (lambda: datetime.now(UTC))

    def run(self, completed):
        if not self.settings.memory_enabled or not self.settings.memory_extraction_enabled:
            return ExtractionResult(reasons=("disabled",))
        deadline = monotonic() + self.settings.memory_timeout_seconds
        created, skipped, reasons = [], [], []

        def remaining():
            left = deadline - monotonic()
            if left <= 0:
                raise TimeoutError("memory_timeout")
            return left

        try:
            active = self.messages.list_active(
                owner_id=completed.owner_id,
                conversation_id=completed.conversation_id,
                timeout=remaining(),
            )
            turn = next((t for t in complete_turns(active) if t[1].id == completed.id), None)
            if turn is None:
                return ExtractionResult(reasons=("branch_mismatch",))
            if any(
                content_reason(m.content, self.settings) for m in turn if m.role.value == "user"
            ):
                return ExtractionResult(reasons=("sensitive_or_external",))
            candidates = self.extractor.extract(turn, timeout=remaining())
            for candidate in candidates[: self.settings.memory_max_candidates_per_turn]:
                remaining()
                reason = candidate_reason(candidate, turn, self.settings)
                if reason:
                    reasons.append(reason)
                    continue
                source = [m for m in turn if m.id in candidate.source_message_ids]
                source_hash = fingerprint(source)
                memory_id = identity(completed.owner_id, source_hash, candidate)
                from personal_ai.storage.errors import ResourceNotFoundError

                try:
                    self.repository.get(
                        owner_id=completed.owner_id, memory_id=memory_id, timeout=remaining()
                    )
                    skipped.append(memory_id)
                    continue
                except ResourceNotFoundError:
                    pass
                embeddings = self.embedder.embed([candidate.content], timeout=remaining())
                if len(embeddings) != 1:
                    raise ValueError("embedding_invalid")
                memory = Memory(
                    **candidate.model_dump(exclude={"effective_at"}),
                    id=memory_id,
                    owner_id=completed.owner_id,
                    normalized_content=normalize(candidate.content),
                    source_conversation_id=completed.conversation_id,
                    source_turn_id=completed.id,
                    source_fingerprint=source_hash,
                    observed_at=source[-1].created_at,
                    effective_at=candidate.effective_at or source[-1].created_at,
                    created_at=self.clock(),
                    embedding=vector(embeddings[0], self.settings.memory_embedding_dimensions),
                    embedding_model=self.settings.memory_embedding_model,
                    embedding_dimensions=self.settings.memory_embedding_dimensions,
                )
                remaining()
                if source_messages(memory, self.messages, timeout=remaining()) is None:
                    reasons.append("branch_mismatch")
                    continue
                _, fresh = self.repository.create(memory, timeout=remaining())
                (created if fresh else skipped).append(memory.id)
        except Exception as error:  # noqa: BLE001 - optional work must never affect chat
            reasons.append("timeout" if isinstance(error, TimeoutError) else "extraction_failed")
        result = ExtractionResult(tuple(created), tuple(skipped), tuple(reasons))
        logger.info(
            "Memory extraction created=%s skipped=%s reasons=%s",
            len(created),
            len(skipped),
            result.reasons,
        )
        return result


class MemoryRetriever:
    def __init__(self, settings, repository, messages, embedder):
        self.settings, self.repository, self.messages = settings, repository, messages
        self.embedder = embedder

    def retrieve(self, owner_id, query, active_messages, *, timeout=None):
        if not self.settings.memory_enabled:
            return RetrievalResult(diagnostics=("disabled",))
        deadline = monotonic() + min(
            timeout or self.settings.memory_timeout_seconds, self.settings.memory_timeout_seconds
        )
        try:
            # Sensitive queries are not sent to an embedding provider either.
            if content_reason(query, self.settings):
                return RetrievalResult(diagnostics=("query_policy",))
            embeddings = self.embedder.embed(
                [query], query=True, timeout=max(0.001, deadline - monotonic())
            )
            if len(embeddings) != 1:
                raise ValueError("embedding_invalid")
            embedding = vector(embeddings[0], self.settings.memory_embedding_dimensions)
            candidates = tuple(
                self.repository.search(
                    owner_id=owner_id,
                    embedding=embedding,
                    model=self.settings.memory_embedding_model,
                    dimensions=self.settings.memory_embedding_dimensions,
                    limit=self.settings.memory_retrieval_candidate_limit,
                    timeout=max(0.001, deadline - monotonic()),
                )
            )[: self.settings.memory_retrieval_candidate_limit]
            valid, excluded = [], []
            for scored in candidates:
                if monotonic() >= deadline:
                    raise TimeoutError("memory_timeout")
                m, reason = scored.memory, None
                if m.owner_id != owner_id:
                    reason = "owner_mismatch"
                elif m.status != "active":
                    reason = "inactive"
                elif (
                    m.embedding_model != self.settings.memory_embedding_model
                    or m.embedding_dimensions != self.settings.memory_embedding_dimensions
                ):
                    reason = "incompatible_embedding"
                elif (
                    not math.isfinite(scored.similarity)
                    or scored.similarity < self.settings.memory_min_similarity
                ):
                    reason = "low_similarity"
                else:
                    try:
                        Memory.model_validate(m.model_dump())
                        vector(m.embedding, self.settings.memory_embedding_dimensions)
                    except (ValueError, TypeError):
                        excluded.append((m.id, "malformed_record"))
                        continue
                    source = source_messages(
                        m, self.messages, timeout=max(0.001, deadline - monotonic())
                    )
                    reason = (
                        "branch_mismatch"
                        if source is None
                        else candidate_reason(
                            m.model_copy(
                                update={
                                    "effective_at": (
                                        m.effective_at if m.effective_at != m.observed_at else None
                                    )
                                }
                            ),
                            source,
                            self.settings,
                        )
                    )
                if reason:
                    excluded.append((m.id, reason))
                else:
                    valid.append(scored)
            # Similarity bands of width .05 permit small correction/time preferences.
            valid.sort(
                key=lambda s: (
                    -math.floor(s.similarity / 0.05 + 1e-8),
                    s.memory.memory_type != "explicit_correction",
                    -s.memory.effective_at.timestamp(),
                    -s.similarity,
                    str(s.memory.id),
                )
            )
            selected = valid[: self.settings.memory_retrieval_limit]
            excluded.extend(
                (s.memory.id, "retrieval_limit")
                for s in valid[self.settings.memory_retrieval_limit :]
            )
            if monotonic() > deadline:
                raise TimeoutError("memory_timeout")
            return RetrievalResult(candidates, tuple(selected), tuple(excluded))
        except Exception as error:  # noqa: BLE001 - retrieval is advisory
            logger.info("Memory retrieval failed error_class=%s", type(error).__name__)
            return RetrievalResult(diagnostics=("retrieval_failed",))
