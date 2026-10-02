"""Provider-free planning over explicitly supplied record IDs, not semantic search."""

from personal_ai.memory.contracts import RetrievalResult, ScoredMemory
from personal_ai.memory.policy import candidate_reason
from personal_ai.memory.services import source_messages
from personal_ai.storage.errors import ResourceNotFoundError


def inspect_records(settings, repository, messages, owner_id, memory_ids):
    if not settings.memory_inspection_enabled or repository is None:
        raise ResourceNotFoundError("resource not found")
    candidates, selected, excluded = [], [], []
    for memory_id in dict.fromkeys(memory_ids):
        memory = repository.get(owner_id=owner_id, memory_id=memory_id)
        scored = ScoredMemory(memory, 0)
        candidates.append(scored)
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
        if memory.status != "active":
            reason = "inactive"
        if (
            memory.embedding_model != settings.memory_embedding_model
            or memory.embedding_dimensions != settings.memory_embedding_dimensions
        ):
            reason = "incompatible_embedding"
        if reason:
            excluded.append((memory.id, reason))
        else:
            selected.append(scored)
    return RetrievalResult(tuple(candidates), tuple(selected), tuple(excluded))
