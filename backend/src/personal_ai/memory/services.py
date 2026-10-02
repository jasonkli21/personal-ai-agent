"""Bounded extraction and advisory semantic retrieval; no lifecycle mutations."""

import logging
import math
from datetime import UTC, datetime
from time import monotonic

from personal_ai.context.contracts import complete_turns, fingerprint
from personal_ai.memory.contracts import (
    DerivedMemory,
    ExtractionResult,
    Memory,
    RetrievalResult,
    identity,
    normalize,
    vector,
)
from personal_ai.memory.policy import candidate_reason, content_reason
from personal_ai.storage.errors import ResourceNotFoundError

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
        stage = "storage"

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
            stage = "extraction"
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

                stage = "storage"
                try:
                    self.repository.get(
                        owner_id=completed.owner_id, memory_id=memory_id, timeout=remaining()
                    )
                    skipped.append(memory_id)
                    continue
                except ResourceNotFoundError:
                    pass
                stage = "embedding"
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
                stage = "storage"
                if source_messages(memory, self.messages, timeout=remaining()) is None:
                    reasons.append("branch_mismatch")
                    continue
                _, fresh = self.repository.create(memory, timeout=remaining())
                (created if fresh else skipped).append(memory.id)
        except Exception as error:  # noqa: BLE001 - optional work must never affect chat
            reasons.append("timeout" if isinstance(error, TimeoutError) else stage + "_failed")
        result = ExtractionResult(tuple(created), tuple(skipped), tuple(reasons))
        logger.info(
            "Memory extraction created=%s skipped=%s reasons=%s",
            len(created),
            len(skipped),
            result.reasons,
        )
        return result


class MemoryRetriever:
    def __init__(self, settings, repository, messages, embedder, lifecycle_repository=None):
        self.settings, self.repository, self.messages = settings, repository, messages
        self.embedder = embedder
        self.lifecycle = lifecycle_repository

    def _state(self, owner_id, memory_id):
        from personal_ai.memory.lifecycle import MemoryLifecycleState

        if self.lifecycle is None:
            return MemoryLifecycleState(owner_id=owner_id, memory_id=memory_id)
        return self.lifecycle.get_state(owner_id=owner_id, memory_id=memory_id)

    def _valid_derived(self, record, owner_id, deadline):
        if not isinstance(record, DerivedMemory) or record.owner_id != owner_id:
            return False, "malformed_record"
        if record.embedding_model != self.settings.memory_embedding_model or record.embedding_dimensions != self.settings.memory_embedding_dimensions:
            return False, "incompatible_embedding"
        if content_reason(record.content, self.settings):
            return False, "sensitive_or_external"
        for source in record.sources:
            if monotonic() >= deadline:
                raise TimeoutError("memory_timeout")
            try:
                memory = self.repository.get(owner_id=owner_id, memory_id=source.memory_id,
                                             timeout=max(0.001, deadline - monotonic()))
            except ResourceNotFoundError:
                return False, "source_unavailable"
            if (memory.source_fingerprint != source.source_fingerprint
                    or memory.source_conversation_id != source.source_conversation_id
                    or memory.source_turn_id != source.source_turn_id
                    or memory.source_message_ids != source.source_message_ids
                    or memory.memory_type not in ("preference", "episodic_observation")
                    or content_reason(memory.content, self.settings)):
                return False, "source_mismatch"
            state = self._state(owner_id, memory.id)
            if state.retrieval_status != "active":
                return False, "source_inactive"
            if source.excerpt != memory.content or source_messages(
                memory, self.messages, timeout=max(0.001, deadline - monotonic())
            ) is None:
                return False, "branch_mismatch"
        return True, None

    def retrieve(self, owner_id, query, active_messages, *, timeout=None):
        if not self.settings.memory_enabled:
            return RetrievalResult(diagnostics=("disabled",))
        deadline = monotonic() + min(
            timeout or self.settings.memory_timeout_seconds, self.settings.memory_timeout_seconds
        )
        requested = self.settings.memory_experiment_variant
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
            originals = tuple(
                self.repository.search(
                    owner_id=owner_id,
                    embedding=embedding,
                    model=self.settings.memory_embedding_model,
                    dimensions=self.settings.memory_embedding_dimensions,
                    limit=self.settings.memory_retrieval_candidate_limit,
                    timeout=max(0.001, deadline - monotonic()),
                )
            )[: self.settings.memory_retrieval_candidate_limit]
            candidates = list(originals)
            if requested == "consolidated" and hasattr(self.repository, "search_derived"):
                candidates.extend(
                    self.repository.search_derived(
                        owner_id=owner_id,
                        embedding=embedding,
                        model=self.settings.memory_embedding_model,
                        dimensions=self.settings.memory_embedding_dimensions,
                        limit=self.settings.memory_retrieval_candidate_limit,
                        timeout=max(0.001, deadline - monotonic()),
                    )
                )
            candidates = tuple(sorted(candidates, key=lambda s: (-s.similarity, str(s.memory.id)))
                               [: self.settings.memory_retrieval_candidate_limit * (2 if requested == "consolidated" else 1)])
            valid, excluded = [], []
            states = {}
            for scored in candidates:
                if monotonic() >= deadline:
                    raise TimeoutError("memory_timeout")
                m, reason = scored.memory, None
                if m.owner_id != owner_id:
                    reason = "owner_mismatch"
                elif getattr(m, "status", "active") != "active":
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
                elif isinstance(m, DerivedMemory):
                    if requested != "consolidated":
                        reason = "variant_excludes_derived"
                    else:
                        reason = self._valid_derived(m, owner_id, deadline)[1]
                else:
                    try:
                        Memory.model_validate(m.model_dump())
                        vector(m.embedding, self.settings.memory_embedding_dimensions)
                    except (ValueError, TypeError):
                        excluded.append((m.id, "malformed_record"))
                        continue
                    source = source_messages(m, self.messages,
                                             timeout=max(0.001, deadline - monotonic()))
                    reason = (
                        "branch_mismatch" if source is None else candidate_reason(
                            m.model_copy(update={"effective_at": (
                                m.effective_at if m.effective_at != m.observed_at else None
                            )}), source, self.settings,
                        )
                    )
                if reason is None:
                    state = self._state(owner_id, m.id)
                    states[m.id] = state
                    if state.retrieval_status != "active":
                        reason = state.retrieval_status
                if reason:
                    excluded.append((m.id, reason))
                else:
                    valid.append(scored)
            # Fixed ordering exactly preserves Phase 3's similarity-band policy.
            valid.sort(key=lambda s: (
                -math.floor(s.similarity / 0.05 + 1e-8),
                s.memory.memory_type != "explicit_correction",
                -s.memory.effective_at.timestamp(), -s.similarity, str(s.memory.id),
            ))
            fixed_order = tuple(valid)
            policy_version = self.settings.memory_scoring_policy_version
            scores = ()
            applied = requested
            if requested in ("scored", "consolidated"):
                try:
                    from personal_ai.memory.lifecycle import ScorePolicy, score_memory

                    policy = ScorePolicy(
                        version=self.settings.memory_scoring_policy_version,
                        similarity_weight=self.settings.memory_score_similarity_weight,
                        importance_weight=self.settings.memory_score_importance_weight,
                        recency_weight=self.settings.memory_score_recency_weight,
                        frequency_weight=self.settings.memory_score_frequency_weight,
                        confidence_weight=self.settings.memory_score_confidence_weight,
                        half_life_days=self.settings.memory_recency_half_life_days,
                    )
                    score_rows = [score_memory(item, states[item.memory.id], policy,
                                               now=datetime.now(UTC)) for item in valid]
                    if any(row.score is None for row in score_rows):
                        raise ValueError("score_input_invalid")
                    by_id = {row.memory_id: row for row in score_rows}
                    if requested == "scored":
                        valid.sort(key=lambda item: (-by_id[item.memory.id].score,
                                                     str(item.memory.id)))
                    else:
                        valid.sort(key=lambda item: (
                            0 if item.memory.memory_type == "explicit_correction" else
                            1 if isinstance(item.memory, DerivedMemory) else 2,
                            -by_id[item.memory.id].score, str(item.memory.id),
                        ))
                    scores = tuple(by_id[item.memory.id] for item in valid)
                except Exception as error:  # noqa: BLE001 - fixed fallback stays provenance-checked
                    logger.info("Memory scoring fallback error_class=%s", type(error).__name__)
                    valid = [item for item in fixed_order if not isinstance(item.memory, DerivedMemory)]
                    applied = "fixed"
            selected = valid[: self.settings.memory_retrieval_limit]
            excluded.extend(
                (s.memory.id, "retrieval_limit")
                for s in valid[self.settings.memory_retrieval_limit :]
            )
            if monotonic() > deadline:
                raise TimeoutError("memory_timeout")
            return RetrievalResult(tuple(candidates), tuple(selected), tuple(excluded),
                                   diagnostics=(("scorer_failed_fixed_fallback",)
                                                if applied == "fixed" and requested != "fixed" else ()),
                                   requested_variant=requested, applied_variant=applied,
                                   policy_version=policy_version, scores=scores)
        except Exception as error:  # noqa: BLE001 - retrieval is advisory
            logger.info("Memory retrieval failed error_class=%s", type(error).__name__)
            return RetrievalResult(diagnostics=("retrieval_failed",))
