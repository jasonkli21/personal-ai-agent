"""Provider-free planning over explicitly supplied record IDs, not semantic search."""

from datetime import UTC, datetime

from personal_ai.memory.contracts import DerivedMemory, RetrievalResult, ScoredMemory
from personal_ai.memory.lifecycle import IMPORTANCE_BY_TYPE, MemoryScore, ScorePolicy
from personal_ai.memory.policy import candidate_reason, content_reason
from personal_ai.memory.services import source_messages
from personal_ai.storage.errors import ResourceNotFoundError


def _score_metadata(record, state, policy, now):
    importance = state.importance
    if importance is None:
        importance = IMPORTANCE_BY_TYPE[record.memory_type]
    if isinstance(record, DerivedMemory):
        importance = min(importance, record.importance)
    age = max(0, (now - record.effective_at).total_seconds()) / 86400
    recency = 2 ** (-age / policy.half_life_days)
    frequency = min(state.retrieval_count / 10, 1)
    score = MemoryScore(
        memory_id=record.id,
        score=None,
        similarity=None,
        importance=importance,
        recency=recency,
        frequency=frequency,
        confidence=record.confidence,
        policy_version=policy.version,
        reason="similarity_unavailable_in_inspector",
    )
    return score


def _source_metadata(record):
    if isinstance(record, DerivedMemory):
        return [
            {
                "memory_id": str(source.memory_id),
                "conversation_id": str(source.source_conversation_id),
                "turn_id": str(source.source_turn_id),
                "message_ids": [str(item) for item in source.source_message_ids],
            }
            for source in record.sources
        ]
    return [{
        "memory_id": str(record.id),
        "conversation_id": str(record.source_conversation_id),
        "turn_id": str(record.source_turn_id),
        "message_ids": [str(item) for item in record.source_message_ids],
    }]


def inspect_records(
    settings, repository, messages, owner_id, memory_ids, lifecycle_repository=None
):
    if (
        (not settings.memory_inspection_enabled and not settings.memory_lifecycle_inspection_enabled)
        or repository is None
    ):
        raise ResourceNotFoundError("resource not found")
    candidates, selected, excluded, scores, metadata, event_ids = [], [], [], [], [], []
    now = datetime.now(UTC)
    policy = ScorePolicy(
        version=settings.memory_scoring_policy_version,
        similarity_weight=settings.memory_score_similarity_weight,
        importance_weight=settings.memory_score_importance_weight,
        recency_weight=settings.memory_score_recency_weight,
        frequency_weight=settings.memory_score_frequency_weight,
        confidence_weight=settings.memory_score_confidence_weight,
        half_life_days=settings.memory_recency_half_life_days,
    )
    for memory_id in dict.fromkeys(memory_ids):
        try:
            memory = repository.get(owner_id=owner_id, memory_id=memory_id)
        except ResourceNotFoundError:
            memory = repository.get_derived(owner_id=owner_id, memory_id=memory_id)
        scored = ScoredMemory(memory, 0)
        candidates.append(scored)
        state = (
            lifecycle_repository.get_state(owner_id=owner_id, memory_id=memory_id)
            if lifecycle_repository is not None
            else None
        )
        reason = None
        if memory.owner_id != owner_id:
            reason = "owner_mismatch"
        elif getattr(memory, "status", "active") != "active":
            reason = "inactive"
        elif (
            memory.embedding_model != settings.memory_embedding_model
            or memory.embedding_dimensions != settings.memory_embedding_dimensions
        ):
            reason = "incompatible_embedding"
        if state is not None and state.retrieval_status != "active":
            reason = state.retrieval_status
        sources_valid = True
        if isinstance(memory, DerivedMemory):
            for source in memory.sources:
                try:
                    original = repository.get(owner_id=owner_id, memory_id=source.memory_id)
                except ResourceNotFoundError:
                    sources_valid = False
                    break
                source_state = (
                    lifecycle_repository.get_state(owner_id=owner_id, memory_id=original.id)
                    if lifecycle_repository is not None
                    else None
                )
                if (
                    original.source_fingerprint != source.source_fingerprint
                    or original.source_message_ids != source.source_message_ids
                    or original.source_conversation_id != source.source_conversation_id
                    or original.source_turn_id != source.source_turn_id
                    or (source_state is not None and source_state.retrieval_status != "active")
                    or content_reason(original.content, settings)
                    or source_messages(original, messages) is None
                ):
                    sources_valid = False
                    break
            if not sources_valid:
                reason = "provenance_invalid"
        elif reason is None:
            source = source_messages(memory, messages)
            reason = (
                "branch_mismatch"
                if source is None
                else candidate_reason(
                    memory.model_copy(
                        update={
                            "effective_at": (
                                memory.effective_at
                                if memory.effective_at != memory.observed_at
                                else None
                            )
                        }
                    ),
                    source,
                    settings,
                )
            )
        if reason is None and content_reason(memory.content, settings):
            reason = "content_policy"
        if reason:
            excluded.append((memory.id, reason))
        else:
            selected.append(scored)
        if state is None:
            from personal_ai.memory.lifecycle import MemoryLifecycleState

            state = MemoryLifecycleState(owner_id=owner_id, memory_id=memory_id)
        score = _score_metadata(memory, state, policy, now)
        scores.append(score)
        events = (
            lifecycle_repository.list_events(owner_id=owner_id, memory_id=memory_id, limit=50)
            if lifecycle_repository is not None
            else ()
        )
        event_ids.extend(event.id for event in events)
        metadata.append((memory.id, {
            "source_records": _source_metadata(memory),
            "lifecycle": {
                "status": state.retrieval_status,
                "state_version": state.state_version,
                "effective_status_at": (
                    state.effective_status_at.isoformat() if state.effective_status_at else None
                ),
                "superseded_by_memory_id": (
                    str(state.superseded_by_memory_id) if state.superseded_by_memory_id else None
                ),
                "consolidated_into_memory_ids": [str(item) for item in state.consolidated_into_memory_ids],
                "retrieval_count": state.retrieval_count,
                "last_retrieved_at": (
                    state.last_retrieved_at.isoformat() if state.last_retrieved_at else None
                ),
                "importance": state.importance,
                "last_event_id": str(state.last_event_id) if state.last_event_id else None,
            },
            "events": [{
                "id": str(event.id),
                "type": event.event_type,
                "reason_code": event.reason_code,
                "policy_version": event.policy_version,
                "occurred_at": event.occurred_at.isoformat(),
                "related_memory_ids": [str(item) for item in event.related_memory_ids],
            } for event in events],
        }))
    return RetrievalResult(
        tuple(candidates), tuple(selected), tuple(excluded),
        requested_variant=settings.memory_experiment_variant,
        applied_variant=settings.memory_experiment_variant,
        policy_version=policy.version,
        scores=tuple(scores),
        lifecycle_event_ids=tuple(event_ids),
        inspection_metadata=tuple(metadata),
    )
