"""Phase 2 selection, provenance, and quality regressions on shared fixtures."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai.context import ContextAssembler, ContextError
from personal_ai.context.assembler import summary_wrapper
from personal_ai.context.contracts import ConversationSummary, SummaryDraft, fingerprint
from personal_ai.context.repositories import InMemorySummaryRepository
from personal_ai.context.tokens import EstimatedTokenCounter, FakeTokenCounter
from personal_ai.entities import MessageRole, MessageStatus
from personal_ai.evaluation.context import (
    FactSummarizer,
    build_fixture,
    evaluate,
    fixture_settings,
    load_fixtures,
)
from personal_ai.llm import ChatMessage, LLMUnavailableError
from personal_ai.storage.errors import ConversationConflictError


def named(name="old-fact"):
    return build_fixture(next(f for f in load_fixtures() if f["name"] == name))


def record(active, content="Launch color is amber.", **overrides):
    values = {
        "id": uuid4(),
        "conversation_id": active[0].conversation_id,
        "owner_id": "local",
        "content": content,
        "source_message_ids": tuple(m.id for m in active),
        "source_fingerprint": fingerprint(active),
        "covers_through_message_id": active[-1].id,
        "source_token_count": 100,
        "summary_token_count": 20,
        "model": "fake",
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return ConversationSummary(**values)


def test_fixture_suite_reproduces_baseline_and_passes_bounded_phase_2():
    rows = evaluate()
    assert all(row["result"] == "passed" for row in rows)
    long = next(row for row in rows if row["fixture"] == "beyond-fixed-cap")
    assert long["phase_1"]["result"] == "fixed_cap_rejected"
    assert long["required_facts_retained"] and long["summary_id"]
    assert all(row["provider_token_count"] is None for row in rows)
    assert rows[-1]["failure_reason"] == "context_message_too_large"


def test_chronological_complete_turns_and_deterministic_newest_selection():
    active, pending, _ = named()
    assembler = ContextAssembler(fixture_settings(), FakeTokenCounter())
    one = assembler.assemble(active, pending)
    two = assembler.assemble(active, pending)
    assert one == two
    assert one.selected_message_ids[-1] == pending.id
    assert one.selected_message_ids[-3:-1] == tuple(m.id for m in active[-2:])
    selected = [m for m in active if m.id in one.selected_message_ids]
    assert one.messages == tuple(ChatMessage(m.role, m.content) for m in [*selected, pending])
    assert len(selected) % 2 == 0
    assert one.budget.selected_total <= one.budget.input_budget


def test_failed_streaming_and_superseded_records_never_enter_context():
    active, pending, audit = named("edited-branch")
    for i, status in enumerate(
        (MessageStatus.FAILED, MessageStatus.STREAMING, MessageStatus.SUPERSEDED)
    ):
        active[i * 2 + 1] = active[i * 2 + 1].model_copy(update={"status": status})
    result = ContextAssembler(fixture_settings(), FakeTokenCounter()).assemble(active, pending)
    assert all(m.id not in result.selected_message_ids for m in active[:6] + audit)
    assert all(reason == "incomplete_turn" for _, reason in result.excluded[:6])


def test_exact_fit_and_one_token_overflow_keep_persisted_content_intact():
    active, pending, _ = named("short-control")
    counter = FakeTokenCounter()
    count = counter.count([ChatMessage(MessageRole.USER, pending.content)]).tokens
    settings = fixture_settings(
        max_context_tokens=count + 20,
        max_response_tokens=10,
        context_safety_margin_tokens=10,
        max_summary_tokens=1,
        summary_trigger_tokens=1,
    )
    result = ContextAssembler(settings, counter).assemble(active, pending)
    assert result.budget.selected_total == result.budget.input_budget
    assert result.messages[-1].content == pending.content
    smaller = settings.model_copy(update={"max_context_tokens": settings.max_context_tokens - 1})
    with pytest.raises(ContextError, match="context_message_too_large"):
        ContextAssembler(smaller, counter).assemble(active, pending)


def test_estimator_rounds_utf8_conservatively_and_labels_estimates():
    _, pending, _ = named("short-control")
    request = [ChatMessage(MessageRole.USER, pending.content + " 🌍")]
    raw = EstimatedTokenCounter(1).count(request)
    margin = EstimatedTokenCounter(1.1).count(request)
    assert margin.tokens >= raw.tokens * 1.1
    assert margin.kind == "estimated"
    with pytest.raises(ValueError):
        EstimatedTokenCounter(0.9)


@pytest.mark.parametrize(
    "values",
    [
        {"max_response_tokens": 220},
        {"context_safety_margin_tokens": 220},
        {"max_summary_tokens": 200},
        {"summary_trigger_tokens": 200},
    ],
)
def test_impossible_budgets_rejected(values):
    with pytest.raises(ValidationError, match="context_budget_invalid"):
        fixture_settings(**values)


def test_first_and_incremental_summaries_are_append_only_bounded_and_branch_safe():
    active, pending, _ = named()
    repository = InMemorySummaryRepository()
    summarizer = FactSummarizer()
    assembler = ContextAssembler(fixture_settings(), FakeTokenCounter(), repository, summarizer)
    first = assembler.assemble(active, pending)
    assert first.summary and "Launch color is amber" in first.summary.content
    assert first.messages[0].role == "system"
    assert "Historical working summary" in first.messages[0].content
    assert len(repository.records) == 1
    second = assembler.assemble(active, pending)
    assert second.summary and second.summary.id != first.summary.id
    assert len(repository.records) == 2
    assert len(second.summary.source_message_ids) > len(first.summary.source_message_ids)
    assert summarizer.calls[-1][1] == first.summary
    assert first.summary.id in repository.records
    assert second.budget.selected_total <= second.budget.input_budget
    changed = [active[0].model_copy(update={"id": uuid4(), "content": "corrected"}), *active[1:]]
    assert (
        repository.compatible(
            owner_id="local", conversation_id=pending.conversation_id, active=changed
        )
        is None
    )
    changed_content = [active[0].model_copy(update={"content": "corrected"}), *active[1:]]
    assert (
        repository.compatible(
            owner_id="local", conversation_id=pending.conversation_id, active=changed_content
        )
        is None
    )


def test_summary_owner_isolation_newest_compatible_and_duplicate_rejection():
    active, pending, _ = named()
    repo = InMemorySummaryRepository()
    older = record(active[:2], created_at=datetime.now(UTC) - timedelta(seconds=1))
    newer = record(active[:4])
    invalid = record(
        active[:2], source_fingerprint="0" * 64, created_at=datetime.now(UTC) + timedelta(seconds=1)
    )
    for summary in (older, newer, invalid):
        repo.create(summary)
    assert (
        repo.compatible(owner_id="local", conversation_id=pending.conversation_id, active=active)
        == newer
    )
    assert (
        repo.compatible(owner_id="foreign", conversation_id=pending.conversation_id, active=active)
        is None
    )
    assert repo.compatible(owner_id="local", conversation_id=uuid4(), active=active) is None
    with pytest.raises(ConversationConflictError):
        repo.create(newer)


@pytest.mark.parametrize(
    "output,diagnostic",
    [
        ("", "summary_invalid_output"),
        ("  ", "summary_invalid_output"),
        ("huge " * 100, "summary_output_too_large"),
        (None, "summary_invalid_output"),
    ],
)
def test_invalid_summary_output_is_never_persisted_and_recent_fallback_fits(output, diagnostic):
    active, pending, _ = named()

    class Summarizer:
        def summarize(self, source, prior):
            return SummaryDraft(output, "fake")

    repo = InMemorySummaryRepository()
    result = ContextAssembler(fixture_settings(), FakeTokenCounter(), repo, Summarizer()).assemble(
        active, pending
    )
    assert not repo.records and result.summary is None
    assert diagnostic in result.diagnostics
    assert result.messages[-1].content == pending.content
    assert result.budget.selected_total <= result.budget.input_budget


def test_summary_provider_failure_has_safe_diagnostic_and_no_storage_write():
    active, pending, _ = named()

    class Summarizer:
        def summarize(self, source, prior):
            raise LLMUnavailableError("private detail")

    repo = InMemorySummaryRepository()
    result = ContextAssembler(fixture_settings(), FakeTokenCounter(), repo, Summarizer()).assemble(
        active, pending
    )
    assert result.diagnostics == ("summary_failed",)
    assert not repo.records


def test_inspection_assembly_does_not_refresh_or_mutate():
    active, pending, _ = named()
    repo = InMemorySummaryRepository()
    summarizer = FactSummarizer()
    before = [m.model_dump() for m in active]
    result = ContextAssembler(fixture_settings(), FakeTokenCounter(), repo, summarizer).assemble(
        active, pending, refresh=False
    )
    assert not summarizer.calls and not repo.records
    assert before == [m.model_dump() for m in active]
    assert result.budget.counter_kind == "estimated"


def test_incompatible_summary_cannot_be_selected_after_regeneration():
    active, pending, _ = named()
    repo = InMemorySummaryRepository()
    repo.create(record(active[:2]))
    active[1] = active[1].model_copy(update={"id": uuid4()})
    result = ContextAssembler(fixture_settings(), FakeTokenCounter(), repo).assemble(
        active, pending
    )
    assert result.summary is None
    assert all(m != summary_wrapper("Launch color is amber.") for m in result.messages)
