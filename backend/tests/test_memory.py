"""Phase 3 contracts, repositories, extraction and retrieval on shared fixtures."""

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai.context import ContextAssembler
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import MessageStatus
from personal_ai.evaluation.memory import build_fixture, evaluate, fixture_settings, load_fixtures
from personal_ai.llm import LLMUnavailableError
from personal_ai.memory.contracts import MemoryCandidate, RetrievalResult, ScoredMemory, vector
from personal_ai.memory.fake import FakeMemoryExtractor
from personal_ai.memory.services import MemoryExtractionService, MemoryRetriever
from personal_ai.storage.errors import ResourceNotFoundError


def named(name="later-preference"):
    return build_fixture(next(f for f in load_fixtures() if f["name"] == name))


def seeded(name="later-preference"):
    env = named(name)
    settings, _, messages, repo, turns, candidates, _, embedder = env
    for turn, candidate in zip(turns, candidates, strict=True):
        result = MemoryExtractionService(
            settings, repo, messages, FakeMemoryExtractor([candidate]), embedder
        ).run(turn[1])
        assert len(result.created) == 1
    return env


def test_shared_evaluation_is_repeatable_and_proves_cross_conversation_baseline():
    first = evaluate()
    assert first == evaluate()
    assert all(r["result"] == "passed" for r in first)
    assert all(not r["phase_2"]["required_cross_conversation_fact_available"] for r in first)
    assert (
        next(r for r in first if r["fixture"] == "edited-branch")["excluded"][0]["reason"]
        == "branch_mismatch"
    )


@pytest.mark.parametrize(
    "values", [[1, 0], [0, 0, 0], [float("nan"), 0, 0], [float("inf"), 0, 0], [True, 0, 0]]
)
def test_invalid_embedding_vectors(values):
    with pytest.raises(ValueError):
        vector(values, 3)


@pytest.mark.parametrize(
    "overrides",
    [
        {"memory_embedding_dimensions": 0},
        {"memory_retrieval_limit": 21},
        {"memory_max_context_tokens": 100_000},
        {"memory_min_similarity": 1.01},
    ],
)
def test_impossible_settings(overrides):
    with pytest.raises(ValidationError):
        fixture_settings(**overrides)


def test_candidate_type_source_and_time_contracts():
    _, _, _, _, _, candidates, _, _ = named()
    candidate = candidates[0]
    for changes in (
        {"memory_type": "evidence"},
        {"source_message_ids": ()},
        {"confidence": float("nan")},
        {"effective_at": datetime(2026, 1, 1, tzinfo=None)},  # noqa: DTZ001
    ):
        with pytest.raises(ValidationError):
            MemoryCandidate.model_validate({**candidate.model_dump(), **changes})


def test_repository_idempotency_owner_status_dimension_and_provenance():
    _settings, _, _, repo, _, _, _, _ = seeded()
    memory = next(iter(repo.records.values()))
    assert repo.create(memory) == (memory, False)
    assert repo.get(owner_id="local", memory_id=memory.id).source_message_ids
    with pytest.raises(ResourceNotFoundError):
        repo.get(owner_id="foreign", memory_id=memory.id)
    assert not repo.search(
        owner_id="foreign", embedding=[1, 0, 0], model="fake-v1", dimensions=3, limit=20
    )
    assert not repo.search(
        owner_id="local", embedding=[1, 0, 0], model="different", dimensions=3, limit=20
    )
    with pytest.raises(ValueError):
        repo.search(owner_id="local", embedding=[1, 0], model="fake-v1", dimensions=3, limit=20)
    repo.records[memory.id] = memory.model_copy(update={"status": "rejected"})
    assert not repo.search(
        owner_id="local", embedding=[1, 0, 0], model="fake-v1", dimensions=3, limit=20
    )
    with pytest.raises(ValidationError):
        repo.create(memory.model_copy(update={"embedding": (1, 0)}))


@pytest.mark.parametrize(
    "name", ["later-preference", "episodic-match", "semantic-summary", "explicit-correction"]
)
def test_all_four_types_grounded_and_duplicates_skip_embedding(name):
    settings, _, messages, repo, turns, candidates, _, embedder = seeded(name)
    service = MemoryExtractionService(
        settings, repo, messages, FakeMemoryExtractor(candidates[-1:]), embedder
    )
    calls = len(embedder.calls)
    assert len(service.run(turns[-1][1]).skipped) == 1
    assert len(embedder.calls) == calls


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"source_message_ids": (uuid4(),)}, "source_mismatch"),
        ({"content": "I prefer an invented unsupported fact."}, "not_source_grounded"),
        ({"confidence": 0.1}, "low_confidence"),
        ({"memory_type": "semantic_summary"}, "unsupported_type"),
    ],
)
def test_extraction_rejects_unsupported_candidates(changes, reason):
    settings, _, messages, repo, turns, candidates, _, embedder = named()
    result = MemoryExtractionService(
        settings,
        repo,
        messages,
        FakeMemoryExtractor([candidates[0].model_copy(update=changes)]),
        embedder,
    ).run(turns[0][1])
    assert result.reasons == (reason,)
    assert not embedder.calls and not repo.records


@pytest.mark.parametrize(
    "text",
    [
        "I prefer password abcdef.",
        "I prefer medical advice.",
        "I prefer an account 12345678.",
        "I prefer prices under 50.",
    ],
)
def test_sensitive_data_never_embedded(text):
    settings, _, messages, repo, turns, candidates, _, embedder = named()
    user = turns[0][0].model_copy(update={"content": text})
    messages._messages[user.id] = user
    candidate = candidates[0].model_copy(update={"content": text})
    result = MemoryExtractionService(
        settings, repo, messages, FakeMemoryExtractor([candidate]), embedder
    ).run(turns[0][1])
    assert result.reasons == ("sensitive_or_external",)
    assert not embedder.calls and not repo.records


def test_empty_disabled_incomplete_and_failed_extraction():
    settings, _, messages, repo, turns, _candidates, _, embedder = named()
    extractor = FakeMemoryExtractor()
    service = MemoryExtractionService(settings, repo, messages, extractor, embedder)
    assert service.run(turns[0][1]).created == ()
    settings.memory_enabled = False
    assert service.run(turns[0][1]).reasons == ("disabled",)
    settings.memory_enabled = True
    for status in ("failed", "streaming", "superseded"):
        assistant = turns[0][1].model_copy(update={"status": MessageStatus(status)})
        messages._messages[assistant.id] = assistant
        assert service.run(assistant).reasons == ("branch_mismatch",)
    assert len(extractor.calls) == 1


@pytest.mark.parametrize("stage", ["extract", "embed", "create", "timeout"])
def test_optional_extraction_failure_is_safe(monkeypatch, stage):
    settings, _, messages, repo, turns, candidates, _, embedder = named()
    extractor = FakeMemoryExtractor(candidates)

    def fail(*args, **kwargs):
        raise TimeoutError() if stage == "timeout" else LLMUnavailableError("safe")

    monkeypatch.setattr(
        extractor if stage in ("extract", "timeout") else embedder if stage == "embed" else repo,
        "extract" if stage in ("extract", "timeout") else stage,
        fail,
    )
    result = MemoryExtractionService(settings, repo, messages, extractor, embedder).run(turns[0][1])
    assert result.reasons == (("timeout",) if stage == "timeout" else ("extraction_failed",))
    assert not repo.records


def test_branch_rewritten_during_embedding_cannot_persist(monkeypatch):
    settings, _, messages, repo, turns, candidates, _, embedder = named()
    original = embedder.embed

    def rewrite(*args, **kwargs):
        user = turns[0][0]
        messages._messages[user.id] = user.model_copy(update={"status": MessageStatus.SUPERSEDED})
        return original(*args, **kwargs)

    monkeypatch.setattr(embedder, "embed", rewrite)
    assert MemoryExtractionService(
        settings, repo, messages, FakeMemoryExtractor(candidates), embedder
    ).run(turns[0][1]).reasons == ("branch_mismatch",)
    assert not repo.records


@pytest.mark.parametrize("name", ["explicit-correction", "temporal-change", "irrelevant-neighbor"])
def test_retrieval_order_threshold_and_old_records_preserved(name):
    settings, _, messages, repo, _, _, pending, embedder = seeded(name)
    before = dict(repo.records)
    result = MemoryRetriever(settings, repo, messages, embedder).retrieve(
        "local", pending.content, [pending]
    )
    fixture = next(f for f in load_fixtures() if f["name"] == name)
    assert [s.memory.content for s in result.selected] == [
        fixture["statements"][i] for i in fixture["expected_order"]
    ]
    assert repo.records == before


def test_malicious_index_results_revalidated(monkeypatch):
    settings, _, messages, repo, _, _, pending, embedder = seeded()
    memory = next(iter(repo.records.values()))
    for changes, reason in [
        ({"owner_id": "other"}, "owner_mismatch"),
        ({"status": "rejected"}, "inactive"),
        ({"embedding_model": "other"}, "incompatible_embedding"),
        ({"source_fingerprint": "0" * 64}, "branch_mismatch"),
    ]:
        monkeypatch.setattr(
            repo,
            "search",
            lambda changes=changes, **kwargs: [ScoredMemory(memory.model_copy(update=changes), 1)],
        )
        result = MemoryRetriever(settings, repo, messages, embedder).retrieve(
            "local", pending.content, [pending]
        )
        assert result.excluded == ((memory.id, reason),)
        assert not result.selected


def test_retrieval_failure_disabled_and_sensitive_query_fallback(monkeypatch):
    settings, _, messages, repo, _, _, pending, embedder = seeded()
    retriever = MemoryRetriever(settings, repo, messages, embedder)
    assert retriever.retrieve("local", "My password is abc", []).diagnostics == ("query_policy",)
    settings.memory_enabled = False
    calls = len(embedder.calls)
    assert retriever.retrieve("local", pending.content, []).diagnostics == ("disabled",)
    assert len(embedder.calls) == calls
    settings.memory_enabled = True
    monkeypatch.setattr(embedder, "embed", lambda *a, **kw: (_ for _ in ()).throw(ValueError()))
    assert retriever.retrieve("local", pending.content, []).diagnostics == ("retrieval_failed",)


def test_injection_preserves_phase_2_request_and_whole_record_budget():
    settings, _, messages, repo, _, _, pending, embedder = seeded("explicit-correction")
    retrieval = MemoryRetriever(settings, repo, messages, embedder).retrieve(
        "local", pending.content, []
    )
    assembler = ContextAssembler(settings, FakeTokenCounter())
    base = assembler.assemble([], pending)
    result = assembler.assemble([], pending, retrieval=retrieval)
    assert result.messages[1:] == base.messages
    assert result.messages[0].role == "system"
    assert result.messages[0].content.index("Correction:") < result.messages[0].content.index(
        "I prefer busy"
    )
    assert "embedding" not in result.messages[0].content
    assert str(retrieval.selected[0].memory.id) not in result.messages[0].content
    settings.memory_max_context_tokens = 1
    excluded = assembler.assemble([], pending, retrieval=retrieval)
    assert excluded.messages == base.messages
    assert all(reason == "budget" for _, reason in excluded.excluded_memories)
    assert not excluded.selected_memory_ids


def test_injection_foreign_and_inactive_defense():
    settings, _, _, repo, _, _, pending, _ = seeded()
    memory = next(iter(repo.records.values()))
    retrieval = RetrievalResult(
        selected=(ScoredMemory(memory.model_copy(update={"owner_id": "other"}), 1),)
    )
    assert (
        not ContextAssembler(settings, FakeTokenCounter())
        .assemble([], pending, retrieval=retrieval)
        .selected_memory_ids
    )
