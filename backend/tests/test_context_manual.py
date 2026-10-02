"""Opt-in synthetic long-thread provider check, never required by offline CI."""

import asyncio
import os

import pytest

from personal_ai.context import ContextAssembler
from personal_ai.context.repositories import InMemorySummaryRepository
from personal_ai.evaluation.context import build_fixture, load_fixtures
from personal_ai.llm import GeminiLLMClient
from personal_ai.llm.context import GeminiConversationSummarizer, GeminiTokenCounter
from personal_ai.settings import Settings


@pytest.mark.skipif(
    os.environ.get("RUN_CONTEXT_MANUAL_TEST") != "1",
    reason="Opt in with RUN_CONTEXT_MANUAL_TEST=1 and Gemini settings.",
)
def test_synthetic_long_thread_preserves_old_fact_with_authoritative_counts():
    settings = Settings().model_copy(
        update={
            "max_context_tokens": 1000,
            "max_response_tokens": 128,
            "context_safety_margin_tokens": 100,
            "max_summary_tokens": 256,
            "summary_trigger_tokens": 100,
        }
    )
    active, pending, _ = build_fixture(load_fixtures()[1])
    pending = pending.model_copy(
        update={"content": "What color did I choose for the launch? Answer one word."}
    )
    assembler = ContextAssembler(
        settings,
        GeminiTokenCounter(settings),
        InMemorySummaryRepository(),
        GeminiConversationSummarizer(settings),
    )
    context = assembler.assemble(active, pending)
    assert context.budget.counter_kind == "provider"
    assert context.budget.selected_total <= context.budget.input_budget
    assert context.summary and "amber" in context.summary.content.lower()
    assert tuple(m.id for m in active[-2:]) == context.selected_message_ids[-3:-1]

    async def collect():
        return "".join(
            [chunk async for chunk in GeminiLLMClient(settings).stream(context.messages)]
        )

    assert "amber" in asyncio.run(collect()).lower()
