"""Synthetic offline Phase 1/2 comparison; no provider, credentials, or judge."""

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from personal_ai.context import ContextAssembler, ContextError
from personal_ai.context.contracts import SummaryDraft
from personal_ai.context.repositories import InMemorySummaryRepository
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import Conversation, Message, MessageRole, MessageStatus
from personal_ai.evaluation.output import emit
from personal_ai.llm import FakeLLMClient
from personal_ai.services import ChatTurnService
from personal_ai.settings import Settings
from personal_ai.storage import InMemoryConversationRepository, InMemoryMessageRepository

FIXTURE_PATH = Path(__file__).with_name("context-fixtures.json")


class FactSummarizer:
    """Deterministic fixture compressor that retains explicit FACT: sentences."""

    def __init__(self) -> None:
        self.calls = []

    def summarize(self, source_messages, prior_summary, *, inference_context=None):
        del inference_context
        self.calls.append((tuple(m.id for m in source_messages), prior_summary))
        facts = [prior_summary.content] if prior_summary else []
        for message in source_messages:
            for sentence in message.content.split("."):
                if "FACT:" in sentence:
                    facts.append(sentence.split("FACT:", 1)[1].strip() + ".")
        return SummaryDraft(" ".join(facts) or "Earlier synthetic discussion.", "fixture-summary")


def fixture_settings(**overrides) -> Settings:
    values = {
        "ai_provider": "gemini",
        "ai_model": "fixture-model",
        "max_context_tokens": 220,
        "max_response_tokens": 30,
        "context_safety_margin_tokens": 10,
        "summary_trigger_tokens": 50,
        "max_summary_tokens": 75,
    }
    values.update(overrides)
    return Settings(**values)


def load_fixtures() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())["fixtures"]


def build_fixture(fixture: dict) -> tuple[list[Message], Message, list[Message]]:
    conversation = uuid5(NAMESPACE_URL, fixture["name"])
    now = datetime(2026, 10, 1, tzinfo=UTC)
    active = []
    parent = None
    for i in range(fixture["turns"]):
        for role in (MessageRole.USER, MessageRole.ASSISTANT):
            text = " ".join([f"synthetic-{i}"] * fixture.get("words_per_message", 12))
            if i == 0 and role is MessageRole.USER and fixture["required_old_facts"]:
                text = "FACT: " + ". FACT: ".join(fixture["required_old_facts"]) + ". " + text
            message = Message(
                id=uuid5(conversation, f"{i}-{role}"),
                conversation_id=conversation,
                owner_id="local",
                scope_version=2,
                role=role,
                content=text,
                status=MessageStatus.COMPLETED,
                created_at=now + timedelta(seconds=len(active)),
                parent_message_id=parent,
            )
            active.append(message)
            parent = message.id
    pending = Message(
        id=uuid5(conversation, "pending"),
        conversation_id=conversation,
        owner_id="local",
        scope_version=2,
        role=MessageRole.USER,
        content=" ".join(["question"] * fixture.get("pending_words", 5)),
        status=MessageStatus.COMPLETED,
        created_at=now + timedelta(seconds=len(active)),
        parent_message_id=parent,
    )
    audit = []
    if fixture.get("branch"):
        audit = [
            active[0].model_copy(
                update={
                    "id": uuid5(conversation, "obsolete"),
                    "content": "obsolete city Lisbon",
                    "status": MessageStatus.SUPERSEDED,
                }
            )
        ]
    return active, pending, audit


def evaluate() -> list[dict]:
    rows = []
    settings = fixture_settings()
    safe_configuration = {
        "max_context_tokens": settings.max_context_tokens,
        "max_response_tokens": settings.max_response_tokens,
        "context_safety_margin_tokens": settings.context_safety_margin_tokens,
        "summary_trigger_tokens": settings.summary_trigger_tokens,
        "max_summary_tokens": settings.max_summary_tokens,
        "token_counter": "fake-estimated",
    }
    for fixture in load_fixtures():
        active, pending, audit = build_fixture(fixture)
        summaries = InMemorySummaryRepository()
        branch_verified = None
        if fixture.get("branch"):
            active, audit, branch_verified = rewrite_fixture_branch(active, pending, summaries)
        assembler = ContextAssembler(
            fixture_settings(), FakeTokenCounter(), summaries, FactSummarizer()
        )
        base = {
            "fixture": fixture["name"],
            "fixture_version": 2,
            "configuration": safe_configuration,
            "phase_1": {
                "input_message_count": len(active) + 1,
                "result": "fixed_cap_rejected" if len(active) + 1 > 40 else "accepted",
                "known_limitation": "no token-budget gate or working summary",
            },
            "provider_token_count": None,
            "branch_rewrite_verified": branch_verified,
        }
        try:
            context = assembler.assemble(active, pending)
            text = " ".join(m.content for m in context.messages)
            retained = all(fact in text for fact in fixture["required_old_facts"])
            obsolete_excluded = not fixture.get("branch") or "Original city is Lisbon" not in text
            excluded_audit = all(m.id not in context.selected_message_ids for m in audit)
            expected = all(
                str(uuid5(pending.conversation_id, key))
                in [str(i) for i in context.selected_message_ids]
                for key in fixture["expected_included_keys"]
            )
            excluded_ids = {str(i) for i, _ in context.excluded} | {str(m.id) for m in audit}
            expected_excluded = all(
                str(uuid5(pending.conversation_id, key)) in excluded_ids
                for key in fixture["expected_excluded_keys"]
            )
            passed = (
                not fixture["reject"]
                and retained
                and excluded_audit
                and obsolete_excluded
                and expected
                and expected_excluded
                and context.budget.selected_total <= context.budget.input_budget
                and (branch_verified is not False)
            )
            base.update(
                {
                    "result": "passed" if passed else "failed",
                    "failure_reason": None if passed else "selection_or_fact_retention",
                    "summary_id": str(context.summary.id) if context.summary else None,
                    "selected_message_ids": [str(i) for i in context.selected_message_ids],
                    "excluded_message_ids": [str(i) for i, _ in context.excluded]
                    + [str(m.id) for m in audit],
                    "estimated_token_count": context.budget.selected_total,
                    "budget": asdict(context.budget),
                    "required_facts_retained": retained,
                    "obsolete_facts_excluded": obsolete_excluded,
                }
            )
        except ContextError as error:
            base.update(
                {
                    "result": "passed"
                    if fixture["reject"] and error.code == "context_message_too_large"
                    else "failed",
                    "failure_reason": error.code,
                    "summary_id": None,
                    "selected_message_ids": [],
                    "excluded_message_ids": [],
                    "estimated_token_count": None,
                }
            )
        rows.append(base)
    return rows


def rewrite_fixture_branch(active, pending, summaries):
    """Seed an original summary, then execute a real edit/retry and append turns."""
    conversations = InMemoryConversationRepository()
    messages = InMemoryMessageRepository(conversations)
    conversations.create(Conversation(
        id=pending.conversation_id, owner_id="local", scope_version=2,
        title="Synthetic branch fixture",
        created_at=active[0].created_at, updated_at=active[-1].created_at,
    ))
    original_ids = {
        m.id: uuid5(pending.conversation_id, "obsolete" if i == 0 else f"original-{i}")
        for i, m in enumerate(active)
    }
    original = [m.model_copy(update={
        "id": original_ids[m.id],
        "parent_message_id": original_ids.get(m.parent_message_id),
        "content": m.content.replace("Corrected city is Bergen", "Original city is Lisbon"),
    }) for i, m in enumerate(active)]
    for message in original:
        messages.create(message)
    settings = fixture_settings()
    assembler = ContextAssembler(settings, FakeTokenCounter(), summaries, FactSummarizer())
    assembler.assemble(original, pending)
    original_summaries = set(summaries.records)
    service = ChatTurnService(
        conversations, messages, FakeLLMClient(["Acknowledged corrected city is Bergen."]),
        owner_id="local", model="fixture-model", context_assembler=assembler,
    )
    stream = service.edit_and_retry(
        pending.conversation_id, original[0].id, active[0].content, request_id="fixture-edit",
    )

    async def consume():
        async for _ in stream:
            pass

    asyncio.run(consume())
    branch = messages.list_active(owner_id="local", conversation_id=pending.conversation_id)
    invalidated = bool(original_summaries) and summaries.compatible(
        owner_id="local", conversation_id=pending.conversation_id, active=branch,
    ) is None
    parent = branch[-1].id
    for message in active[2:]:
        copied = message.model_copy(update={"parent_message_id": parent})
        messages.create(copied)
        parent = copied.id
    branch = messages.list_active(owner_id="local", conversation_id=pending.conversation_id)
    audit = [messages.get(owner_id="local", conversation_id=pending.conversation_id,
                          message_id=m.id) for m in original]
    verified = invalidated and all(m.status is MessageStatus.SUPERSEDED for m in audit)
    return branch, audit, verified


if __name__ == "__main__":
    results = evaluate()
    emit(results, default=str)
    raise SystemExit(0 if all(r["result"] == "passed" for r in results) else 1)
