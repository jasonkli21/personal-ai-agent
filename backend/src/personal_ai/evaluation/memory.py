"""Synthetic Phase 2 baseline and measured Phase 3 memory loop, entirely offline."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from personal_ai.context import ContextAssembler
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import Conversation, Message
from personal_ai.evaluation.output import emit
from personal_ai.memory.contracts import MemoryCandidate
from personal_ai.memory.fake import FakeEmbedder, FakeMemoryExtractor
from personal_ai.memory.policy import RATIONALES
from personal_ai.memory.repositories import InMemoryMemoryRepository
from personal_ai.memory.services import MemoryExtractionService, MemoryRetriever
from personal_ai.settings import Settings
from personal_ai.storage.fake import InMemoryConversationRepository, InMemoryMessageRepository


def load_fixtures():
    return json.loads(Path(__file__).with_name("memory-fixtures.json").read_text())["fixtures"]


def fixture_settings(**overrides):
    values = {
        "ai_provider": "gemini",
        "ai_model": "fake-chat",
        "memory_enabled": True,
        "memory_extraction_enabled": True,
        "memory_embedding_model": "fake-v1",
        "memory_embedding_dimensions": 3,
        "memory_max_context_tokens": 512,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def build_fixture(fixture):
    now = datetime(2026, 10, 2, tzinfo=UTC)
    uid = lambda value: uuid5(NAMESPACE_URL, fixture["name"] + ":" + value)
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    repository = InMemoryMemoryRepository(messages)
    settings = fixture_settings(memory_max_context_tokens=fixture.get("memory_budget", 512))
    source = Conversation(
        id=uid("source"), owner_id="local", title="Synthetic source", created_at=now, updated_at=now
    )
    conversations.create(source)
    turns, candidates = [], []
    parent = None
    for index, content in enumerate(fixture["statements"]):
        at = now + timedelta(minutes=index)
        user = Message(
            id=uid(f"user-{index}"),
            owner_id="local",
            conversation_id=source.id,
            role="user",
            content=content,
            status="completed",
            created_at=at,
            parent_message_id=parent,
        )
        assistant = Message(
            id=uid(f"assistant-{index}"),
            owner_id="local",
            conversation_id=source.id,
            role="assistant",
            content="Understood.",
            status="completed",
            created_at=at + timedelta(seconds=1),
            parent_message_id=user.id,
        )
        messages.create(user)
        messages.create(assistant)
        turns.append((user, assistant))
        parent = assistant.id
        kind = fixture["types"][index]
        candidates.append(
            MemoryCandidate(
                memory_type=kind,
                content=content,
                confidence=0.95,
                source_message_ids=(user.id,),
                rationale_code=RATIONALES[kind],
            )
        )
    owner = fixture.get("query_owner", "local")
    target = Conversation(
        id=uid("target"), owner_id=owner, title="Synthetic query", created_at=now, updated_at=now
    )
    conversations.create(target)
    pending = Message(
        id=uid("pending"),
        owner_id=owner,
        conversation_id=target.id,
        role="user",
        content=fixture["query"],
        status="completed",
        created_at=now,
    )
    vectors = dict(zip(fixture["statements"], fixture["vectors"], strict=True))
    vectors[fixture["query"]] = fixture["query_vector"]
    return (
        settings,
        conversations,
        messages,
        repository,
        turns,
        candidates,
        pending,
        FakeEmbedder(vectors, provider="fake", model=settings.memory_embedding_model),
    )


def evaluate():
    rows = []
    for f in load_fixtures():
        settings, _conversations, messages, repo, turns, candidates, pending, embedder = (
            build_fixture(f)
        )
        baseline = ContextAssembler(settings, FakeTokenCounter()).assemble([], pending)
        created, skipped, ids, extraction_reasons = [], [], [], []
        if f.get("embedding_failure"):
            embedder.vectors.pop(candidates[0].content, None)
        for turn, candidate in zip(turns, candidates, strict=True):
            service = MemoryExtractionService(
                settings,
                repo,
                messages,
                FakeMemoryExtractor([candidate]),
                embedder,
                clock=lambda pending=pending: pending.created_at,
            )
            result = service.run(turn[1])
            created.extend(result.created)
            extraction_reasons.extend(result.reasons)
            ids.extend(result.created)
            if f.get("repeat_extraction"):
                skipped.extend(service.run(turn[1]).skipped)
        if f.get("supersede"):
            user = turns[0][0]
            replacement = user.model_copy(
                update={
                    "id": uuid5(NAMESPACE_URL, "edited-user"),
                    "content": "I prefer quiet mountain cabins.",
                    "supersedes_message_id": user.id,
                }
            )
            messages.prepare_message_turn(
                owner_id="local",
                conversation_id=user.conversation_id,
                expected_active_ids=[m.id for t in turns for m in t],
                supersede_from_message_id=user.id,
                messages=(replacement,),
                updated_at=pending.created_at,
            )
        if f.get("retrieval_failure"):
            embedder.vectors.pop(pending.content, None)
        retrieval = MemoryRetriever(settings, repo, messages, embedder).retrieve(
            pending.owner_id, pending.content, [pending]
        )
        result = ContextAssembler(settings, FakeTokenCounter()).assemble(
            [], pending, retrieval=retrieval
        )
        expected = [ids[i] for i in f["expected_order"]]
        selected = [s.memory.id for s in retrieval.selected]
        forbidden = {ids[i] for i in f["forbidden"]}
        expected_injected = f.get("expected_injected", bool(expected))
        passed = (
            selected == expected
            and not forbidden.intersection(selected)
            and bool(result.selected_memory_ids) == expected_injected
            and not baseline.selected_memory_ids
            and result.budget.selected_total <= result.budget.input_budget
            and result.selected_message_ids[-1] == pending.id
            and len(created) == f.get("expected_created", len(candidates))
            and extraction_reasons == f.get("expected_extraction_reasons", [])
            and list(retrieval.diagnostics) == f.get("expected_retrieval_diagnostics", [])
            and (not f.get("repeat_extraction") or skipped == ids)
        )
        rows.append(
            {
                "fixture": f["name"],
                "fixture_version": 1,
                "result": "passed" if passed else "failed",
                "phase_2": {
                    "selected_message_ids": [str(i) for i in baseline.selected_message_ids],
                    "memory_ids": [],
                    "required_cross_conversation_fact_available": False,
                },
                "extraction": {
                    "created": [str(i) for i in created],
                    "skipped": [str(i) for i in skipped],
                    "reasons": extraction_reasons,
                },
                "embedding": {
                    "model": "fake-v1",
                    "dimensions": 3,
                    "configuration_class": "offline-synthetic",
                },
                "candidates": [
                    {"id": str(s.memory.id), "similarity": round(s.similarity, 6)}
                    for s in retrieval.candidates
                ],
                "selected": [str(i) for i in selected],
                "retrieval_diagnostics": retrieval.diagnostics,
                "excluded": [{"id": str(i), "reason": r} for i, r in retrieval.excluded],
                "context": {
                    "selected_memory_ids": [str(i) for i in result.selected_memory_ids],
                    "excluded": [{"id": str(i), "reason": r} for i, r in result.excluded_memories],
                    "memory_tokens": result.memory_tokens,
                    "total": result.budget.selected_total,
                    "input_budget": result.budget.input_budget,
                },
                "failure_reason": None if passed else "fixture_expectation_failed",
            }
        )
    return rows


if __name__ == "__main__":
    results = evaluate()
    emit(results)
    raise SystemExit(0 if all(r["result"] == "passed" for r in results) else 1)
