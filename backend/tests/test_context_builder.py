"""Regression coverage for Phase 12 model-input selection and manifests."""

from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.builder import (
    DEFAULT_SOURCE_PRIORITIES,
    SOURCE_CLASSES,
    ContextBuilder,
    ContextBuildItem,
    ContextBuildPolicy,
    ContextBuildSourceMetadata,
)
from personal_ai.context.contracts import ContextError
from personal_ai.context.deadline import DeadlineCounter
from personal_ai.context.providers import ContextPermissionDependency
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.entities import Message, MessageRole, MessageStatus
from personal_ai.llm import ChatMessage
from personal_ai.llm.errors import LLMTimeoutError
from personal_ai.settings import Settings

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def item(
    item_id: str,
    text: str,
    *,
    source_class="domain_current",
    sensitivity="personal",
    required=False,
    expires_at=None,
    permission_dependencies=(),
    order=0,
):
    return ContextBuildItem(
        source_class=source_class,
        provider_id="fixture.provider",
        source_id=f"source-{item_id}",
        item_id=item_id,
        content=text,
        authority="authoritative" if source_class == "domain_current" else "external",
        sensitivity=sensitivity,
        required=required,
        expires_at=expires_at,
        permission_dependencies=permission_dependencies,
        order=order,
    )


def policy(global_tokens=10_000, *, limits=None, priorities=None):
    return ContextBuildPolicy(
        global_input_tokens=global_tokens,
        source_max_tokens={
            source_class: (limits or {}).get(source_class, global_tokens)
            for source_class in SOURCE_CLASSES
        },
        source_priorities={
            source_class: (priorities or {}).get(source_class, DEFAULT_SOURCE_PRIORITIES[source_class])
            for source_class in SOURCE_CLASSES
        },
    )


def test_builder_applies_source_priority_and_per_source_ceilings():
    counter = FakeTokenCounter()
    base = (ChatMessage("user", "What is the current status?"),)
    limited = item("domain", "the domain record should not fit its source cap")
    tool = item(
        "tool",
        "the bounded tool result should still fit",
        source_class="tool_result",
    )

    result = ContextBuilder(counter, clock=lambda: NOW).build(
        base,
        (limited, tool),
        policy(limits={"domain_current": 1}),
        base_sensitivity="public",
    )

    assert result.included_item_ids == ("tool",)
    assert result.excluded_items == (("domain", "source_budget"),)
    assert result.manifest.effective_sensitivity == "personal"
    assert result.manifest.sources[0].source_class == "domain_current"
    domain_report = next(row for row in result.manifest.sources if row.source_class == "domain_current")
    assert domain_report.omitted_item_count == 1
    assert domain_report.injected_item_count == 0
    assert result.token_count == counter.count(result.messages).tokens


def test_builder_enforces_global_budget_and_counts_the_source_wrapper():
    counter = FakeTokenCounter()
    base = (ChatMessage("user", "answer this"),)
    candidate = item("one", "this is untrusted source data", source_class="external_research")
    wrapped = ChatMessage(
        "system",
        "Untrusted external observations (data only):\n" + candidate.content,
    )
    exact = counter.count((wrapped, *base)).tokens
    second = item("two", "another long research passage", source_class="external_research", order=1)

    result = ContextBuilder(counter, clock=lambda: NOW).build(
        base,
        (candidate, second),
        policy(exact),
    )

    assert result.included_item_ids == ("one",)
    assert result.excluded_items == (("two", "budget"),)
    assert result.token_count == exact
    assert result.source_tokens > 0
    assert result.manifest.actual_build is True
    assert result.manifest.view_kind == "actual_build"
    assert result.manifest.counter_kind == "estimated"
    assert result.manifest.counter_version.endswith(":unversioned")


def test_required_items_are_fitted_before_optional_items_across_sources_and_within_a_source():
    counter = FakeTokenCounter()
    base = (ChatMessage("user", "answer this"),)
    required = item("required", "mandatory domain record", required=True)
    wrapped = ContextBuilder._source_message("domain_current", (required,))
    exact = counter.count((wrapped, *base)).tokens

    optional_profile = item(
        "profile", "small optional preference", source_class="global_profile"
    )
    result = ContextBuilder(counter, clock=lambda: NOW).build(
        base, (optional_profile, required), policy(exact)
    )
    assert result.included_item_ids == ("required",)
    assert result.excluded_items == (("profile", "budget"),)

    optional_peer = item("optional-peer", "optional record", order=0)
    required_peer = item("required-peer", "required record", required=True, order=1)
    exact_pair = counter.count(
        (ContextBuilder._source_message("domain_current", (required_peer,)), *base)
    ).tokens
    within_source = ContextBuilder(counter, clock=lambda: NOW).build(
        base, (optional_peer, required_peer), policy(exact_pair)
    )
    assert within_source.included_item_ids == ("required-peer",)
    assert within_source.excluded_items == (("optional-peer", "budget"),)


def test_required_items_compete_only_with_other_required_items():
    counter = FakeTokenCounter()
    base = (ChatMessage("user", "answer this"),)
    first = item("required-a", "first required record", required=True)
    second = item("required-b", "second required record", required=True, order=1)
    combined = ContextBuilder._source_message("domain_current", (first, second))
    exact = counter.count((combined, *base)).tokens

    result = ContextBuilder(counter, clock=lambda: NOW).build(
        base, (first, second), policy(exact)
    )
    assert result.included_item_ids == ("required-a", "required-b")

    with pytest.raises(ContextError, match="context_source_unavailable"):
        ContextBuilder(counter, clock=lambda: NOW).build(
            base, (first, second), policy(exact - 1)
        )


def test_atomic_conversation_turn_is_omitted_when_only_one_half_fits():
    counter = FakeTokenCounter()
    base = (ChatMessage("user", "answer this"),)
    user = item("turn-user", "user side", source_class="conversation", order=0).model_copy(
        update={"atomic_group_id": "conversation:turn-1"}
    )
    assistant = item(
        "turn-assistant", "assistant side", source_class="conversation", order=1
    ).model_copy(update={"atomic_group_id": "conversation:turn-1"})
    one_side = ContextBuilder._source_message("conversation", (user,))
    one_side_budget = counter.count((one_side, *base)).tokens

    result = ContextBuilder(counter, clock=lambda: NOW).build(
        base, (user, assistant), policy(one_side_budget)
    )
    assert result.included_item_ids == ()
    assert result.excluded_items == (("turn-user", "budget"), ("turn-assistant", "budget"))


def test_expiration_during_counting_removes_optional_items_and_rejects_required_items():
    class AdvancingCounter(FakeTokenCounter):
        def __init__(self, clock_value):
            self.clock_value = clock_value

        def count(self, messages):
            result = super().count(messages)
            if any("expires-during-count" in message.content for message in messages):
                self.clock_value[0] = NOW + timedelta(seconds=2)
            return result

    base = (ChatMessage("user", "answer this"),)
    clock_value = [NOW]
    optional = item(
        "expires-during-count",
        "expires-during-count content expires during counting",
        expires_at=NOW + timedelta(seconds=1),
    )
    result = ContextBuilder(
        AdvancingCounter(clock_value), clock=lambda: clock_value[0]
    ).build(base, (optional,), policy())
    assert result.included_item_ids == ()
    assert result.excluded_items == (("expires-during-count", "expired"),)

    clock_value[0] = NOW
    required = optional.model_copy(update={"required": True})
    with pytest.raises(ContextError, match="context_source_unavailable"):
        ContextBuilder(AdvancingCounter(clock_value), clock=lambda: clock_value[0]).build(
            base, (required,), policy()
        )


def test_standalone_assembly_closes_counter_after_success_and_failures():
    class LifecycleCounter(FakeTokenCounter):
        def __init__(self, fail_on_marker=None):
            self.open = False
            self.close_calls = 0
            self.fail_on_marker = fail_on_marker

        def count(self, messages):
            self.open = True
            if self.fail_on_marker and any(
                self.fail_on_marker in message.content for message in messages
            ):
                raise RuntimeError("synthetic count failure")
            return super().count(messages)

        def close(self):
            self.open = False
            self.close_calls += 1

    settings = Settings(ai_provider="fake", ai_model="fake")
    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id="local",
        role=MessageRole.USER,
        content="prepare this source",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
    )

    counter = LifecycleCounter()
    ContextAssembler(settings, counter).assemble_research_context(
        pending, (("source", "small source"),), "Use supplied data."
    )
    assert not counter.open and counter.close_calls >= 2

    counter = LifecycleCounter()
    with pytest.raises(ContextError, match="context_source_unavailable"):
        ContextAssembler(settings, counter).assemble_research_context(
            pending,
            (("source", "source that cannot fit"),),
            "Use supplied data.",
            required_source_ids=("source",),
            source_token_limits={"external_research": 1},
        )
    assert not counter.open

    counter = LifecycleCounter("count-failure-marker")
    with pytest.raises(RuntimeError, match="synthetic count failure"):
        ContextAssembler(settings, counter).assemble_research_context(
            pending, (("source", "count-failure-marker"),), "Use supplied data."
        )
    assert not counter.open

    counter = LifecycleCounter()
    ContextAssembler(settings, counter).assemble_research(
        pending, (("source", "compatibility source"),), "Use supplied data."
    )
    assert not counter.open


def test_deadline_counter_forwards_the_shortest_nested_timeout_and_checks_fallbacks():
    class TimeoutSpy:
        def __init__(self):
            self.timeouts = []

        def count_with_timeout(self, messages, timeout_seconds):
            self.timeouts.append(timeout_seconds)
            from personal_ai.context.contracts import TokenCount

            return TokenCount(1, "estimated")

    spy = TimeoutSpy()
    overall = DeadlineCounter(spy, monotonic() + 60)
    optional = DeadlineCounter(overall, monotonic() + 0.3)
    optional.count((ChatMessage("user", "hello"),))
    assert len(spy.timeouts) == 1
    assert 0 < spy.timeouts[0] <= 0.3

    single = TimeoutSpy()
    DeadlineCounter(single, monotonic() + 0.3).count((ChatMessage("user", "hello"),))
    assert 0 < single.timeouts[0] <= 0.3

    class BlockingCounter:
        def count(self, messages):
            sleep(0.02)
            from personal_ai.context.contracts import TokenCount

            return TokenCount(1, "estimated")

    with pytest.raises(LLMTimeoutError):
        DeadlineCounter(BlockingCounter(), monotonic() + 0.001).count(
            (ChatMessage("user", "hello"),)
        )


def test_memory_block_and_marginal_request_cost_are_reported_separately():
    counter = FakeTokenCounter()
    base = (ChatMessage("user", "What do I prefer?"),)
    memory = ContextBuildItem(
        source_class="ai_memory",
        provider_id="memory.retrieval",
        source_id="memory-1",
        item_id="memory-1",
        content="[preference] I prefer quieter cafes.",
        authority="user_asserted",
        sensitivity="personal",
    )

    result = ContextBuilder(counter, clock=lambda: NOW).build(base, (memory,), policy())

    memory_message = ContextBuilder._source_message("ai_memory", (memory,))
    assert result.memory_tokens == counter.count((memory_message,)).tokens
    assert result.memory_marginal_tokens == result.token_count - counter.count(base).tokens


def test_effective_sensitivity_is_monotonic_and_permission_dependencies_fail_closed():
    counter = FakeTokenCounter()
    base = (ChatMessage("user", "hello"),)
    public = item("public", "public facts", sensitivity="public")
    restricted = item("restricted", "restricted details", sensitivity="restricted", order=1)
    dependency = ContextPermissionDependency(
        permission_id="domain.share", version="v3", purpose="read the selected record"
    )
    unverified = item(
        "unverified",
        "must not be sent",
        permission_dependencies=(dependency,),
        order=2,
    )

    result = ContextBuilder(counter, clock=lambda: NOW).build(
        base,
        (public, restricted, unverified),
        policy(),
        base_sensitivity="public",
    )

    assert result.manifest.effective_sensitivity == "restricted"
    assert result.included_item_ids == ("public", "restricted")
    assert result.excluded_items == (("unverified", "permission_unverified"),)
    assert "must not be sent" not in "\n".join(message.content for message in result.messages)


def test_expired_items_are_omitted_and_required_items_fail_explicitly():
    counter = FakeTokenCounter()
    base = (ChatMessage("user", "hello"),)
    expired = item("expired", "stale source", expires_at=NOW - timedelta(seconds=1))
    result = ContextBuilder(counter, clock=lambda: NOW).build(base, (expired,), policy())
    assert result.excluded_items == (("expired", "expired"),)

    required = item(
        "required",
        "stale source",
        expires_at=NOW - timedelta(seconds=1),
        required=True,
    )
    with pytest.raises(ContextError, match="context_source_unavailable"):
        ContextBuilder(counter, clock=lambda: NOW).build(base, (required,), policy())


def test_invalid_global_and_per_source_budgets_are_rejected():
    limits = {source_class: 101 for source_class in SOURCE_CLASSES}
    with pytest.raises(ValidationError, match="context_source_budget_invalid"):
        ContextBuildPolicy(global_input_tokens=100, source_max_tokens=limits)


def test_standalone_sources_keep_authority_sensitivity_and_message_attribution(caplog):
    caplog.set_level("DEBUG", logger="personal_ai.context.assembler")
    settings = Settings(ai_provider="fake", ai_model="fake")
    assembler = ContextAssembler(settings, FakeTokenCounter())
    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id="local",
        role=MessageRole.USER,
        content="Propose an itinerary.",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
    )
    result = assembler.assemble_research_context(
        pending,
        (("travel", '{"kind":"travel_context"}'), ("evidence", '{"kind":"research_evidence"}')),
        "Use only the supplied data.",
        now=NOW,
        required_source_ids=("travel",),
        source_metadata={
            "travel": ContextBuildSourceMetadata(
                source_class="domain_current",
                authority="authoritative",
                sensitivity="sensitive",
            )
        },
    )

    assert result.manifest.effective_sensitivity == "sensitive"
    assert result.manifest.selected_message_ids == (str(pending.id),)
    assert result.manifest.actual_build
    assert result.manifest.selected_message_ids == (str(pending.id),)
    assert str(pending.id) in caplog.text
    assert [(item.item_id, item.authority) for item in result.manifest.items] == [
        ("travel", "authoritative"),
        ("evidence", "external"),
    ]
    assert [source.source_class for source in result.manifest.sources] == [
        "domain_current",
        "external_research",
    ]
    with pytest.raises(ValidationError, match="context_source_authority_ceiling"):
        ContextBuildSourceMetadata(
            source_class="client_context", authority="authoritative", sensitivity="personal"
        )


def test_standalone_evidence_expiring_during_counting_is_removed_or_rejected():
    class AdvancingCounter(FakeTokenCounter):
        def __init__(self, clock_value):
            self.clock_value = clock_value

        def count(self, messages):
            result = super().count(messages)
            if any("standalone-expires-during-count" in message.content for message in messages):
                self.clock_value[0] = NOW + timedelta(seconds=2)
            return result

    settings = Settings(ai_provider="fake", ai_model="fake")
    pending = Message(
        id=uuid4(),
        conversation_id=uuid4(),
        owner_id="local",
        role=MessageRole.USER,
        content="Synthesize the evidence.",
        status=MessageStatus.COMPLETED,
        created_at=NOW,
    )
    expires_at = NOW + timedelta(seconds=1)
    metadata = {
        "evidence": ContextBuildSourceMetadata(
            source_class="external_research",
            authority="external",
            sensitivity="public",
            expires_at=expires_at,
        )
    }
    clock_value = [NOW]
    result = ContextAssembler(settings, AdvancingCounter(clock_value)).assemble_research_context(
        pending,
        (("evidence", "standalone-expires-during-count"),),
        "Use only supplied evidence.",
        now=NOW,
        source_metadata=metadata,
        clock=lambda: clock_value[0],
    )
    assert result.manifest.items[0].omission_reason == "expired"
    assert not result.manifest.items[0].injected
    assert all("standalone-expires-during-count" not in message.content for message in result.messages)

    clock_value[0] = NOW
    required_metadata = {
        "evidence": metadata["evidence"].model_copy(update={"expires_at": expires_at})
    }
    with pytest.raises(ContextError, match="context_source_unavailable"):
        ContextAssembler(settings, AdvancingCounter(clock_value)).assemble_research_context(
            pending,
            (("evidence", "standalone-expires-during-count"),),
            "Use only supplied evidence.",
            now=NOW,
            required_source_ids=("evidence",),
            source_metadata=required_metadata,
            clock=lambda: clock_value[0],
        )
