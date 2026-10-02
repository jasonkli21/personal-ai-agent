"""Shared Phase 4 fixtures assert real service outcomes, never model-judged quality."""

from datetime import timedelta
from uuid import UUID

import pytest

from personal_ai.evaluation.memory_lifecycle import (
    NOW,
    VARIANTS,
    apply_fixture,
    build_fixture,
    evaluate,
    evaluate_fixture,
    load_fixtures,
)
from personal_ai.memory.lifecycle_policy import make_event
from personal_ai.memory.recovery import recover_pending
from personal_ai.memory.services import MemoryRetriever
from personal_ai.storage.errors import ResourceNotFoundError

FIXTURES = load_fixtures()


def named(name):
    return next(item for item in FIXTURES if item["name"] == name)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["name"])
def test_shared_lifecycle_outcomes(fixture, variant):
    row = evaluate_fixture(fixture, variant)
    assert row["result"] == "passed", row


def test_all_variant_results_are_exactly_reproducible():
    assert evaluate() == evaluate()


def test_worker_crash_after_atomic_apply_reclaims_without_duplicate_memory_or_events(monkeypatch):
    env = build_fixture(named("duplicate-job-delivery"), "consolidated")
    ids = tuple(record.id for record in env["records"].values())
    env["coordinator"]._enqueue(env["completed"], "consolidation", ids)
    job = next(iter(env["lifecycle"].jobs.values()))
    original_complete = env["lifecycle"].complete_job

    def crash(*args, **kwargs):
        raise SystemExit("simulated_process_death")

    monkeypatch.setattr(env["lifecycle"], "complete_job", crash)
    with pytest.raises(SystemExit):
        env["worker"].process(job.id)
    before = (dict(env["memories"].derived_records), dict(env["lifecycle"].events_by_key))
    assert len(before[0]) == 1 and len(before[1]) == 2
    later = NOW + timedelta(seconds=61)
    env["worker"].clock = lambda: later
    env["lifecycle"].clock = lambda: later
    monkeypatch.setattr(env["lifecycle"], "complete_job", original_complete)
    assert env["worker"].process(job.id) == "completed"
    assert before == (env["memories"].derived_records, env["lifecycle"].events_by_key)
    assert env["lifecycle"].get_job_by_id(job_id=job.id).attempt_count == 2


def test_forgotten_record_can_reactivate_only_with_valid_user_source():
    env = build_fixture(named("stale-low-value-memory"))
    apply_fixture(env)
    record = env["records"]["stale"]
    state = env["lifecycle"].get_state(owner_id="local", memory_id=record.id)
    assert state.retrieval_status == "forgotten"
    event = make_event(
        owner_id="local",
        memory_id=record.id,
        event_type="reactivated",
        reason_code="developer_fixture",
        policy_version="forget-v1",
        idempotency_key="reactivate",
        expected_state_version=state.state_version,
        occurred_at=NOW,
    )
    assert env["lifecycle"].apply_event(event).status == "applied"
    assert (
        env["lifecycle"].rebuild_state(owner_id="local", memory_id=record.id).retrieval_status
        == "active"
    )


def test_atomic_forgetting_rejects_dependency_added_after_policy_preflight():
    env = build_fixture(named("stale-low-value-memory"))
    memory = env["records"]["stale"]
    env["lifecycle"].derived_sources[("local", memory.id)] = {UUID(int=1)}
    event = make_event(
        owner_id="local",
        memory_id=memory.id,
        event_type="forgotten",
        reason_code="stale_low_value",
        policy_version="forget-v1",
        idempotency_key="forget-dependent",
        expected_state_version=0,
        occurred_at=NOW,
    )
    result = env["lifecycle"].apply_event(event)
    assert result.status == "conflict" and result.reason == "protected_memory"
    assert not env["lifecycle"].events


def test_active_conversation_reservation_prevents_source_lifecycle_mutation():
    env = build_fixture(named("repeated-explicit-preference"))
    memory = env["records"]["a"]
    conversation = env["conversations"].get(
        owner_id="local", conversation_id=memory.source_conversation_id
    )
    env["conversations"].update(
        conversation.model_copy(
            update={"context_preparation_id": UUID(int=2), "context_preparation_started_at": NOW}
        )
    )
    apply_fixture(env)
    assert not env["memories"].derived_records
    assert not env["lifecycle"].events


def test_scoring_failure_preserves_supersession_exclusion(monkeypatch):
    env = build_fixture(named("clear-explicit-correction"), "scored")
    apply_fixture(env)
    monkeypatch.setattr("personal_ai.memory.lifecycle.score_memory", lambda *a, **kw: 1 / 0)
    result = MemoryRetriever(
        env["settings"],
        env["memories"],
        env["messages"],
        env["embedder"],
        lifecycle_repository=env["lifecycle"],
        clock=lambda: NOW,
    ).retrieve("local", "query", [])
    assert result.applied_variant == "fixed"
    assert [item.memory.id for item in result.selected] == [env["records"]["newer"].id]
    assert (env["records"]["older"].id, "superseded") in result.excluded


def test_publisher_recovery_and_intent_replay_after_job_state_changes():
    env = build_fixture(named("duplicate-job-delivery"))
    recovered = []

    class Publisher:
        def publish(self, job, *, timeout):
            assert timeout <= 5
            recovered.append(job.id)

    env["coordinator"].publisher = Publisher()
    env["coordinator"]._enqueue(
        env["completed"], "consolidation", tuple(r.id for r in env["records"].values())
    )
    job = next(iter(env["lifecycle"].jobs.values()))
    assert env["worker"].process(job.id) == "completed"
    env["coordinator"]._enqueue(
        env["completed"], "consolidation", tuple(r.id for r in env["records"].values())
    )
    assert len(env["lifecycle"].jobs) == 1
    assert (
        recover_pending(env["settings"], limit=1, coordinator=env["coordinator"])["published"] == 0
    )
    with pytest.raises(ResourceNotFoundError):
        env["lifecycle"].get_job(owner_id="foreign", job_id=job.id)


@pytest.mark.parametrize("variant", VARIANTS)
def test_variant_memory_summary_and_recent_turns_keep_one_total_budget(variant):
    from personal_ai.context import ContextAssembler
    from personal_ai.context.repositories import InMemorySummaryRepository
    from personal_ai.context.tokens import FakeTokenCounter
    from personal_ai.evaluation.context import FactSummarizer
    from personal_ai.evaluation.context import build_fixture as build_context
    from personal_ai.evaluation.context import load_fixtures as context_fixtures

    env = build_fixture(named("repeated-explicit-preference"), variant)
    apply_fixture(env)
    retrieval = MemoryRetriever(
        env["settings"],
        env["memories"],
        env["messages"],
        env["embedder"],
        lifecycle_repository=env["lifecycle"],
        clock=lambda: NOW,
    ).retrieve("local", "query", [])
    fixture = next(item for item in context_fixtures() if item["name"] == "beyond-fixed-cap")
    active, pending, _ = build_context({**fixture, "words_per_message": 80})
    settings = env["settings"].model_copy(
        update={
            "max_context_tokens": 550,
            "max_response_tokens": 30,
            "context_safety_margin_tokens": 20,
            "max_summary_tokens": 75,
            "summary_trigger_tokens": 100,
            "memory_max_context_tokens": 150,
        }
    )
    assembler = ContextAssembler(
        settings, FakeTokenCounter(), InMemorySummaryRepository(), FactSummarizer()
    )
    base = assembler.assemble(active, pending)
    result = assembler.assemble(active, pending, refresh=False, retrieval=retrieval)
    assert result.summary and result.selected_memory_ids
    assert result.selected_message_ids == base.selected_message_ids
    assert result.messages[-1].content == pending.content
    assert result.budget.selected_total == FakeTokenCounter().count(result.messages).tokens
    assert result.budget.selected_total <= result.budget.input_budget
