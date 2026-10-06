"""Phase 4 lifecycle contracts, scoring, leases and immutable source safety."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from personal_ai.entities import MessageStatus
from personal_ai.evaluation.memory import build_fixture, load_fixtures
from personal_ai.memory.lifecycle import (
    MemoryJob,
    MemoryLifecycleEvent,
    ScorePolicy,
    score_memory,
    transition,
)
from personal_ai.memory.lifecycle_repositories import (
    InMemoryMemoryLifecycleRepository,
    event_idempotency_id,
    job_idempotency_id,
)


def seeded():
    fixture = next(item for item in load_fixtures() if item["name"] == "later-preference")
    settings, _, messages, memories, turns, candidates, _, embedder = build_fixture(fixture)
    from personal_ai.memory.fake import FakeMemoryExtractor
    from personal_ai.memory.services import MemoryExtractionService

    settings.memory_enabled = True
    for turn, candidate in zip(turns, candidates, strict=True):
        extraction = MemoryExtractionService(
            settings, memories, messages, FakeMemoryExtractor([candidate]), embedder
        ).run(turn[1])
        assert extraction.created
    return (
        settings,
        messages,
        memories,
        sorted(memories.records.values(), key=lambda m: m.created_at),
    )


def event(memory, *, kind="retrieved", key="stable", version=0, related=(), now=None, job_id=None):
    now = now or datetime.now(UTC)
    return MemoryLifecycleEvent(
        id=event_idempotency_id(key),
        owner_id=memory.owner_id,
        memory_id=memory.id,
        event_type=kind,
        reason_code="fixture",
        policy_version="score-v1",
        actor="developer_test",
        occurred_at=now,
        idempotency_key=key,
        related_memory_ids=related,
        job_id=job_id,
        expected_state_version=version,
    )


def test_score_policy_is_versioned_bounded_and_monotonic():
    _, _, _, records = seeded()
    memory = records[0]
    from personal_ai.memory.contracts import ScoredMemory
    from personal_ai.memory.lifecycle import MemoryLifecycleState

    policy = ScorePolicy()
    now = memory.effective_at + timedelta(days=90)
    base = ScoredMemory(memory, 0.8)
    state = MemoryLifecycleState(memory_id=memory.id, owner_id=memory.owner_id)
    result = score_memory(base, state, policy, now=now)
    assert result.policy_version == "score-v1"
    assert result.score is not None and 0 <= result.score <= 1
    assert result.recency == pytest.approx(0.5)
    higher_similarity = score_memory(ScoredMemory(memory, 0.9), state, policy, now=now)
    assert higher_similarity.score > result.score
    assert ScorePolicy(similarity_weight=0.4, importance_weight=0.2).identity != policy.identity
    with pytest.raises(ValueError, match="score_policy_invalid"):
        ScorePolicy(similarity_weight=float("nan"))


def test_event_replay_transition_table_and_source_preservation():
    _, messages, memories, records = seeded()
    memory = records[0]
    original = memories.get(owner_id=memory.owner_id, memory_id=memory.id)
    repo = InMemoryMemoryLifecycleRepository(memories, messages)

    first_event = event(memory, key="retrieval-1")
    applied = repo.apply_event(first_event)
    assert applied.status == "applied" and applied.state.retrieval_count == 1
    assert repo.apply_event(first_event).status == "replayed"
    assert repo.get_state(owner_id=memory.owner_id, memory_id=memory.id).retrieval_count == 1
    with pytest.raises(ValueError, match="idempotency_key_reused"):
        repo.apply_event(event(memory, key="retrieval-1", kind="review_required"))

    review = repo.apply_event(event(memory, kind="review_required", key="review-1", version=1))
    assert review.state.retrieval_status == "active"
    superseded = transition(
        review.state,
        event(memory, kind="superseded", key="superseded-1", version=2, related=(UUID(int=1),)),
    )
    assert superseded.retrieval_status == "superseded"
    with pytest.raises(ValueError, match="transition_invalid"):
        transition(superseded, event(memory, kind="reactivated", key="reactivate-1", version=3))
    assert memories.get(owner_id=memory.owner_id, memory_id=memory.id) == original


def test_missing_state_means_initial_active_but_unavailable_source_means_conflict():
    _, messages, memories, records = seeded()
    memory = records[0]
    repo = InMemoryMemoryLifecycleRepository(memories, messages)
    assert (
        repo.get_state(owner_id=memory.owner_id, memory_id=memory.id).retrieval_status == "active"
    )
    source = memory.source_message_ids[0]
    messages._messages[source] = messages._messages[source].model_copy(
        update={"status": MessageStatus.SUPERSEDED}
    )
    outcome = repo.apply_event(event(memory, key="stale-source"))
    assert outcome.status == "conflict" and outcome.reason == "source_inactive"
    assert not repo.events


def test_job_dedupe_retry_and_expired_lease_fencing():
    _, _, _, records = seeded()
    memory = records[0]
    repo = InMemoryMemoryLifecycleRepository(None, None)
    now = datetime.now(UTC)
    key = "completed-turn:fixture"
    job = MemoryJob(
        id=job_idempotency_id(key),
        owner_id=memory.owner_id,
        scope_version=2,
        job_type="maintenance",
        candidate_memory_ids=(memory.id,),
        policy_version="score-v1",
        policy_snapshot={"version": "score-v1"},
        idempotency_key=key,
        created_at=now,
        updated_at=now,
    )
    assert repo.create_job(job) == (job, True)
    assert repo.create_job(job) == (job, False)
    first = repo.claim_job(owner_id=job.owner_id, job_id=job.id, now=now, lease_seconds=60)
    assert first and first.lease_token
    later = now + timedelta(seconds=61)
    second = repo.claim_job(owner_id=job.owner_id, job_id=job.id, now=later, lease_seconds=60)
    assert second and second.lease_generation == first.lease_generation + 1
    assert (
        repo.fail_job(first, token=first.lease_token, now=later, reason="stale", retryable=True)
        is False
    )
    assert repo.fail_job(
        second, token=second.lease_token, now=later, reason="transient", retryable=True
    )
    stored = repo.get_job(owner_id=job.owner_id, job_id=job.id)
    assert stored.status == "retry" and stored.publish_pending


def test_expired_worker_lease_cannot_apply_a_lifecycle_event():
    _, messages, memories, records = seeded()
    memory = records[0]
    repo = InMemoryMemoryLifecycleRepository(memories, messages)
    now = datetime.now(UTC)
    key = "fenced-maintenance"
    job = MemoryJob(
        id=job_idempotency_id(key),
        owner_id=memory.owner_id,
        scope_version=2,
        job_type="maintenance",
        candidate_memory_ids=(memory.id,),
        policy_version="score-v1",
        policy_snapshot={},
        idempotency_key=key,
        created_at=now,
        updated_at=now,
    )
    repo.create_job(job)
    first = repo.claim_job(owner_id=job.owner_id, job_id=job.id, now=now, lease_seconds=60)
    later = now + timedelta(seconds=61)
    second = repo.claim_job(owner_id=job.owner_id, job_id=job.id, now=later, lease_seconds=60)
    assert first and second and first.lease_token != second.lease_token
    stale_event = event(
        memory,
        kind="forgotten",
        key="stale-worker-forget",
        job_id=job.id,
        now=later,
    )
    outcome = repo.apply_event(stale_event, job=first, lease_token=first.lease_token)
    assert outcome.status == "conflict" and outcome.reason == "stale_lease"
    assert not repo.events
    assert repo.get_state(owner_id=job.owner_id, memory_id=memory.id).retrieval_status == "active"


def test_invalid_job_lease_and_wrong_owner_are_rejected():
    _, _, _, records = seeded()
    memory = records[0]
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="lease_invalid"):
        MemoryJob(
            id=job_idempotency_id("bad"),
            owner_id=memory.owner_id,
            scope_version=2,
            job_type="maintenance",
            candidate_memory_ids=(),
            policy_version="score-v1",
            policy_snapshot={},
            status="leased",
            idempotency_key="bad",
            created_at=now,
            updated_at=now,
        )
    repo = InMemoryMemoryLifecycleRepository(None, None)
    key = "owner-job"
    job = MemoryJob(
        id=job_idempotency_id(key),
        owner_id=memory.owner_id,
        scope_version=2,
        job_type="maintenance",
        candidate_memory_ids=(),
        policy_version="score-v1",
        policy_snapshot={},
        idempotency_key=key,
        created_at=now,
        updated_at=now,
    )
    repo.create_job(job)
    from personal_ai.storage.errors import ResourceNotFoundError

    with pytest.raises(ResourceNotFoundError):
        repo.get_job(owner_id="foreign", job_id=job.id)
