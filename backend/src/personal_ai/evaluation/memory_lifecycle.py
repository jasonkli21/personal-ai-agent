"""Measured production lifecycle/worker/retrieval/context paths with synthetic boundaries."""

import json
import math
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from personal_ai.context import ContextAssembler
from personal_ai.context.contracts import fingerprint
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import Conversation, Message
from personal_ai.memory.contracts import Memory, MemoryCandidate, identity, normalize
from personal_ai.memory.fake import FakeEmbedder
from personal_ai.memory.lifecycle_jobs import MemoryLifecycleCoordinator, MemoryLifecycleWorker
from personal_ai.memory.lifecycle_policy import make_event
from personal_ai.memory.lifecycle_repositories import InMemoryMemoryLifecycleRepository
from personal_ai.memory.policy import RATIONALES
from personal_ai.memory.repositories import InMemoryMemoryRepository
from personal_ai.memory.services import MemoryRetriever
from personal_ai.settings import Settings
from personal_ai.storage.fake import InMemoryConversationRepository, InMemoryMessageRepository

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
VARIANTS = ("fixed", "scored", "consolidated")


def load_fixtures():
    return json.loads(Path(__file__).with_name("memory-lifecycle-fixtures.json").read_text())[
        "fixtures"
    ]


def build_fixture(fixture, variant="fixed"):
    """Sources live in independent conversations; identities and time are reproducible."""
    uid = lambda name: uuid5(NAMESPACE_URL, "phase4:" + fixture["name"] + ":" + name)
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="fake-chat",
        memory_enabled=True,
        memory_extraction_enabled=True,
        memory_experiment_variant=variant,
        memory_embedding_model="fake-v1",
        memory_embedding_dimensions=3,
        memory_lifecycle_worker_enabled=True,
        memory_consolidation_enabled=True,
        memory_contradiction_automation_enabled=True,
        memory_forgetting_enabled=True,
        memory_max_context_tokens=fixture.get("memory_budget", 512),
    )
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    memories = InMemoryMemoryRepository(messages)
    lifecycle = InMemoryMemoryLifecycleRepository(memories, messages, clock=lambda: NOW)
    records, originals, turns = {}, {}, {}
    for data in fixture["records"]:
        label, owner = data["label"], data.get("owner", "local")
        at = NOW - timedelta(days=data.get("age_days", 0))
        conversation = Conversation(
            id=uid(label + "-conversation"),
            owner_id=owner,
            title="Synthetic source",
            created_at=at,
            updated_at=at,
        )
        conversations.create(conversation)
        user = Message(
            id=uid(label + "-user"),
            owner_id=owner,
            conversation_id=conversation.id,
            role="user",
            status="completed",
            content=data["content"],
            created_at=at,
        )
        assistant = Message(
            id=uid(label + "-assistant"),
            owner_id=owner,
            conversation_id=conversation.id,
            role="assistant",
            status="completed",
            content="Understood.",
            parent_message_id=user.id,
            created_at=at + timedelta(seconds=1),
        )
        messages.create(user)
        messages.create(assistant)
        candidate = MemoryCandidate(
            memory_type=data["memory_type"],
            content=data["content"],
            confidence=data.get("confidence", 0.95),
            source_message_ids=(user.id,),
            rationale_code=RATIONALES[data["memory_type"]],
        )
        source_hash = fingerprint([user])
        similarity = data.get("similarity", 0.95)
        memory = Memory(
            **candidate.model_dump(exclude={"effective_at"}),
            id=identity(owner, source_hash, candidate),
            owner_id=owner,
            normalized_content=normalize(candidate.content),
            source_conversation_id=conversation.id,
            source_turn_id=assistant.id,
            source_fingerprint=source_hash,
            observed_at=at,
            effective_at=at,
            created_at=at,
            embedding=(similarity, math.sqrt(1 - similarity**2), 0),
            embedding_model="fake-v1",
            embedding_dimensions=3,
        )
        memories.create(memory)
        records[label], originals[label], turns[label] = (
            memory,
            memory.model_dump(),
            (user, assistant),
        )
        for index in range(data.get("retrieval_count", 0)):
            state = lifecycle.get_state(owner_id=owner, memory_id=memory.id)
            lifecycle.apply_event(
                make_event(
                    owner_id=owner,
                    memory_id=memory.id,
                    event_type="retrieved",
                    reason_code="synthetic_injection",
                    policy_version="score-v1",
                    idempotency_key=f"{fixture['name']}:{label}:injection:{index}",
                    expected_state_version=state.state_version,
                    occurred_at=NOW,
                )
            )
    target = Conversation(
        id=uid("target"), owner_id="local", title="Synthetic query", created_at=NOW, updated_at=NOW
    )
    conversations.create(target)
    pending = Message(
        id=uid("query"),
        owner_id="local",
        conversation_id=target.id,
        role="user",
        status="completed",
        content="Which personal preferences apply?",
        created_at=NOW,
    )
    completed = Message(
        id=uid("completed"),
        owner_id="local",
        conversation_id=target.id,
        role="assistant",
        status="completed",
        content="Understood.",
        parent_message_id=pending.id,
        created_at=NOW,
    )
    messages.create(pending)
    messages.create(completed)

    class SyntheticEmbedder(FakeEmbedder):
        def embed(self, texts, *, query=False, timeout=None):
            if query and fixture.get("query_failure"):
                raise TimeoutError("synthetic_query_failure")
            return [(1.0, 0.0, 0.0) for _ in texts]

    embedder = SyntheticEmbedder({})
    coordinator = MemoryLifecycleCoordinator(settings, lifecycle, memories)
    worker = MemoryLifecycleWorker(
        settings, lifecycle, memories, messages, embedder, clock=lambda: NOW
    )
    return {
        "settings": settings,
        "conversations": conversations,
        "messages": messages,
        "memories": memories,
        "lifecycle": lifecycle,
        "records": records,
        "originals": originals,
        "turns": turns,
        "pending": pending,
        "completed": completed,
        "embedder": embedder,
        "coordinator": coordinator,
        "worker": worker,
        "fixture": fixture,
    }


def apply_fixture(env):
    fixture = env["fixture"]
    action = fixture.get("action")
    if not action:
        return
    records = env["records"]
    ids = tuple(record.id for record in records.values() if record.owner_id == "local")
    env["coordinator"]._enqueue(
        env["completed"], "consolidation" if action == "consolidate" else "maintenance", ids
    )
    if fixture.get("rewrite"):
        original = env["turns"]["a"][0]
        replacement = original.model_copy(
            update={
                "id": uuid5(NAMESPACE_URL, fixture["name"] + ":rewrite"),
                "content": "I prefer forest cabins.",
                "supersedes_message_id": original.id,
            }
        )
        env["messages"].prepare_message_turn(
            owner_id="local",
            conversation_id=original.conversation_id,
            expected_active_ids=[m.id for m in env["turns"]["a"]],
            supersede_from_message_id=original.id,
            messages=(replacement,),
            updated_at=NOW,
        )
    for job in list(env["lifecycle"].jobs.values()):
        assert env["worker"].process(job.id) == "completed"
        if fixture.get("duplicate"):
            assert env["worker"].process(job.id) == "completed"
    if fixture.get("protect_dependency"):
        env["coordinator"]._enqueue(
            env["completed"].model_copy(
                update={"id": uuid5(NAMESPACE_URL, "dependency-maintenance")}
            ),
            "maintenance",
            ids,
        )
        for job in list(env["lifecycle"].jobs.values()):
            assert env["worker"].process(job.id) == "completed"


def evaluate_fixture(fixture, variant):
    env = build_fixture(fixture, variant)
    apply_fixture(env)
    lifecycle, records = env["lifecycle"], env["records"]
    labels = {record.id: label for label, record in records.items()}
    labels.update({record.id: "derived" for record in env["memories"].derived_records.values()})
    if fixture.get("lifecycle_failure"):

        def unavailable(**_):
            raise RuntimeError("synthetic_lifecycle_failure")

        lifecycle.get_state = unavailable
    from contextlib import nullcontext
    from unittest.mock import patch

    score_patch = (
        patch(
            "personal_ai.memory.lifecycle.score_memory",
            side_effect=RuntimeError("synthetic_score_failure"),
        )
        if fixture.get("score_failure")
        else nullcontext()
    )
    with score_patch:
        retrieval = MemoryRetriever(
            env["settings"],
            env["memories"],
            env["messages"],
            env["embedder"],
            lifecycle_repository=lifecycle,
            clock=lambda: NOW,
        ).retrieve("local", env["pending"].content, [])
    assembled = ContextAssembler(env["settings"], FakeTokenCounter()).assemble(
        [], env["pending"], retrieval=retrieval
    )
    selected = [labels[item.memory.id] for item in retrieval.selected]
    injected = [labels[item] for item in assembled.selected_memory_ids]
    expected = fixture.get("expected", {}).get(variant)
    statuses = {
        label: lifecycle.states.get(("local", record.id)).retrieval_status
        if ("local", record.id) in lifecycle.states
        else "active"
        for label, record in records.items()
    }
    forbidden = set(fixture.get("forbidden_labels", []))
    events = [event for items in lifecycle.events.values() for event in items]
    passed = (
        not forbidden.intersection(injected)
        and all(statuses[key] == value for key, value in fixture.get("statuses", {}).items())
        and (expected is None or selected == expected)
        and (
            not fixture.get("stable_tie")
            or [item.memory.id for item in retrieval.selected]
            == sorted((record.id for record in records.values()), key=str)
        )
        and ("derived" not in injected or variant == "consolidated")
        and (not fixture.get("lifecycle_failure") or not injected)
        and (not fixture.get("query_failure") or not injected)
        and (
            not fixture.get("review")
            or any(event.event_type == "review_required" for event in events)
        )
        and (
            not fixture.get("protect_dependency")
            or all(status == "active" for status in statuses.values())
        )
        and ("derived" not in injected or len(set(injected)) == 1)
        and assembled.budget.selected_total <= assembled.budget.input_budget
        and assembled.selected_message_ids[-1] == env["pending"].id
        and all(env["memories"].get(owner_id=record.owner_id, memory_id=record.id).model_dump() == env["originals"][label] for label, record in records.items())
        and len({event.id for event in events}) == len(events)
    )
    if "derived" in fixture:
        passed = passed and bool(env["memories"].derived_records) == fixture["derived"]
        if fixture["derived"] and variant == "consolidated" and not fixture.get("memory_budget"):
            passed = passed and injected == ["derived"]
    if fixture.get("memory_budget"):
        passed = passed and "derived" not in injected and bool(injected)
    return {
        "fixture": fixture["name"],
        "fixture_version": 1,
        "variant": variant,
        "policy_version": "score-v1",
        "policy_identity": retrieval.policy_identity,
        "result": "passed" if passed else "failed",
        "candidates": [str(item.memory.id) for item in retrieval.candidates],
        "selected": [str(item) for item in assembled.selected_memory_ids],
        "selected_labels": injected,
        "rank_order": [str(item.memory.id) for item in retrieval.selected],
        "scores": [
            {**asdict(score), "memory_id": str(score.memory_id)} for score in retrieval.scores
        ],
        "excluded": [
            {"id": str(identifier), "reason": reason}
            for identifier, reason in assembled.excluded_memories
        ],
        "lifecycle_event_ids": [str(event.id) for event in events],
        "derived_statuses": statuses,
        "jobs": [
            {"id": str(job.id), "attempts": job.attempt_count, "status": job.status}
            for job in lifecycle.jobs.values()
        ],
        "token_total": assembled.budget.selected_total,
        "input_budget": assembled.budget.input_budget,
        "requested_variant": retrieval.requested_variant,
        "applied_variant": retrieval.applied_variant,
        "diagnostics": retrieval.diagnostics,
        "failure_reason": None if passed else "fixture_expectation_failed",
    }


def evaluate():
    return [
        evaluate_fixture(fixture, variant) for fixture in load_fixtures() for variant in VARIANTS
    ]


if __name__ == "__main__":
    rows = evaluate()
    print(json.dumps(rows, indent=2))
    raise SystemExit(0 if all(row["result"] == "passed" for row in rows) else 1)
