"""End-to-end Phase 8 state-machine, fencing, and restart tests."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from personal_ai.agents.research.contracts import ResearchError, ResearchRequest, ResearchSession
from personal_ai.agents.research.iterative_contracts import (
    DecisionIntent,
    IterativeResearchRequest,
    ResearchRun,
    RunState,
    StopReason,
)
from personal_ai.agents.research.iterative_fakes import (
    DeterministicClock,
    FakeIterativeSearchAdapter,
)
from personal_ai.agents.research.iterative_repositories import (
    InMemoryIterativeResearchRepository,
)
from personal_ai.agents.research.iterative_service import IterativeResearchService
from personal_ai.agents.research.repositories import InMemoryResearchRepository
from personal_ai.agents.research.service import ResearchService
from personal_ai.applications.contracts import ApplicationContextRequest
from personal_ai.applications.registry import default_application_registry
from personal_ai.auth.scope import ApplicationScope, RequestScope, application_scope_context
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.providers import ContextPreparationError
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.llm.fake import FakeResearchLLMClient
from personal_ai.search.contracts import SearchResult
from personal_ai.search.providers.brave import SearchError
from personal_ai.settings import Settings
from personal_ai.storage.errors import ResourceNotFoundError

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def application_context(owner_id="local", application_id="personal_ai", workspace_id=None):
    registry = default_application_registry()
    return ApplicationContextRequest(
        definition=registry.get(application_id),
        scope=RequestScope(
            owner_id=owner_id, request_id="research-test", application_id=application_id,
            workspace_id=workspace_id,
        ),
        context_provider_capabilities=registry.registration(application_id).context_providers,
        tool_capabilities=registry.registration(application_id).tools,
    )


def without_policy_provider(context: ApplicationContextRequest, provider_id: str):
    policy = context.definition.context_policy
    definition = context.definition.model_copy(update={
        "context_policy": policy.model_copy(update={
            "provider_policies": tuple(
                item for item in policy.provider_policies if item.provider_id != provider_id
            ),
        }),
    })
    return context.model_copy(update={"definition": definition})


@pytest.fixture
def anyio_backend():
    return "asyncio"


def build_service(*, sources=(), responses=None, settings_overrides=None, owner="local", clock=None, on_search=None):
    values = {
        "_env_file": None,
        "ai_provider": "gemini",
        "ai_model": "synthetic",
        "research_enabled": True,
        "research_storage": "memory",
        "iterative_research_enabled": True,
        "iterative_progress_enabled": True,
        "iterative_allowed_domains": ("example.org",),
    }
    values.update(settings_overrides or {})
    settings = Settings(**values)
    sessions = InMemoryResearchRepository()
    runs = InMemoryIterativeResearchRepository(sessions)
    adapter = FakeIterativeSearchAdapter.queued(
        responses if responses is not None else [tuple(sources)], on_search=on_search
    )
    clock = clock or DeterministicClock(NOW)
    service = IterativeResearchService(
        settings,
        sessions,
        runs,
        adapter,
        ContextAssembler(settings, EstimatedTokenCounter()),
        FakeResearchLLMClient(),
        owner_id=owner,
        application_context=application_context(owner),
        clock=clock,
        duration_clock=clock.elapsed,
    )
    return service, adapter, clock, sessions, runs


def request(question="Synthetic observatory schedule?", *, key=None, decision_intent=None, freshness="general"):
    return IterativeResearchRequest(
        question=question,
        freshness=freshness,
        idempotency_key=key or uuid4(),
        decision_intent=decision_intent,
    )


def result(url="https://example.org/schedule", text="Synthetic observatory opens Saturday.", **values):
    return SearchResult(url=url, title="Synthetic evidence", text=text, **values)


async def execute(service, req):
    initial, token = await service.start(req)
    events = [frame async for frame in service.stream(initial, token)]
    return await service.get(initial.id), events


@pytest.mark.anyio
async def test_search_reservations_are_durable_before_adapter_and_ledgers_reconcile():
    observed = []
    service = None

    def before_search(query, limit):
        run = next(iter(service.runs.runs.values()))
        session = service.sessions.sessions[run.session_id]
        observed.append((run.state, run.usage.queries, len(session.queries), session.attempts[-1].status))

    service, adapter, _, _, _ = build_service(
        sources=(result(),), on_search=before_search
    )
    final, events = await execute(service, request())

    assert final.state == RunState.COMPLETED
    assert final.terminal_reason == StopReason.SUFFICIENT
    assert observed == [(RunState.SEARCHING, 1, 1, "started")]
    assert final.usage.queries == final.usage.sources == 1
    assert final.usage.tokens > 0
    assert final.usage.elapsed_seconds == sum(
        (entry.settled or Decimal(0) for entry in final.ledger if entry.dimension == "elapsed_seconds"),
        Decimal(0),
    )
    assert len(adapter.calls) == 1
    assert len(events) == len(final.events)
    assert all("Synthetic observatory" not in frame and "Saturday" not in frame for frame in events)


@pytest.mark.anyio
async def test_followup_has_parent_gap_domain_fence_and_deduplicates_repeats():
    intent = DecisionIntent.model_validate({
        "candidates": [{"entity_type": "object", "canonical_name": "Synthetic Widget"}],
        "constraints": [{
            "id": "30000000-0000-4000-8000-000000000001",
            "attribute": "price", "operator": "maximum",
            "value": {"kind": "money", "amount": "50", "currency": "USD"},
            "required": True, "missing_policy": "fail_closed", "source": "user",
        }],
    })
    service, adapter, _, _, _ = build_service(responses=[
        (result("https://example.org/widget", "Synthetic Widget is blue."),),
        (
            result("https://example.org/price", "Synthetic Widget price is $40."),
            result("https://unlisted.example.net/leak", "Synthetic Widget is $1."),
            result("https://other.example.org/leak", "Synthetic Widget is $2."),
        ),
    ], settings_overrides={"decision_enabled": True})
    final, _ = await execute(service, request("Synthetic Widget price?", decision_intent=intent))
    run, session = await service.detail(final.id)

    assert run.state == RunState.INSUFFICIENT  # plain snippets cannot become Phase 6 claims
    assert run.decision_state == "research_needed"
    assert len(adapter.calls) == 2  # the deterministic third plan is a repeated query and is suppressed
    assert len(session.queries) == 2
    assert session.queries[1].parent_query_id == session.queries[0].id
    assert session.queries[1].gap_id is not None
    assert "Synthetic Widget price?" in session.queries[1].normalized_query
    assert "site:example.org" in session.queries[1].normalized_query
    assert all("unlisted.example.net" not in source.canonical_url for source in session.observations)
    assert all("other.example.org" not in source.canonical_url for source in session.observations)
    assert any(gap.status == "open" for gap in run.gaps)
    repeated_open = [gap for gap in run.gaps if gap.status == "open" and gap.semantic_key.endswith(":price:")]
    assert len(repeated_open) >= 2
    assert len({gap.assessment_id for gap in repeated_open}) == len(repeated_open)
    assert final.terminal_reason == StopReason.NO_PRODUCTIVE_QUERY


@pytest.mark.anyio
async def test_idempotency_owner_scope_and_reconnect_are_read_only():
    service, adapter, _, _, _ = build_service(sources=(result(),))
    req = request()
    created = await service.create(req)
    assert await service.create(req) == created
    with pytest.raises(ResearchError, match="idempotency_conflict"):
        await service.create(request("Different question?", key=req.idempotency_key))

    final, _ = await execute(service, request("Another synthetic schedule?"))
    calls = tuple(adapter.calls)
    tail = await service.events(final.id, after=1)
    replay = [frame async for frame in service.event_stream(final.id, after=1)]
    assert [event.sequence for event in tail] == [event.sequence for event in final.events if event.sequence > 1]
    assert [int(frame.split("\n", 1)[0][4:]) for frame in replay] == [event.sequence for event in tail]
    assert tuple(adapter.calls) == calls
    other_owner = IterativeResearchService(
        service.settings, service.sessions, service.runs, adapter, service.context, service.llm,
        owner_id="other",
        application_context=application_context("other"),
    )
    with pytest.raises(ResourceNotFoundError):
        await other_owner.get(final.id)


@pytest.mark.anyio
async def test_same_owner_and_idempotency_key_create_independent_runs_per_scope():
    service, _, _, sessions, runs = build_service()
    req = request(key=uuid4())
    standalone = await service.create(req)
    scoped_runs = []
    for scope in (
        ApplicationScope(application_id="travel"),
        ApplicationScope(application_id="shopping"),
        ApplicationScope(application_id="travel", workspace_id="team-a"),
        ApplicationScope(application_id="travel", workspace_id="team-b"),
    ):
        service.application_context = application_context(
            service.owner_id, scope.application_id, scope.workspace_id
        )
        with application_scope_context(scope):
            scoped_runs.append(await service.create(req))

    all_runs = [standalone, *scoped_runs]
    assert len({item.id for item in all_runs}) == len(all_runs)
    assert len({item.session_id for item in all_runs}) == len(all_runs)
    assert len(runs.runs) == len(all_runs)
    assert len(sessions.sessions) == len(all_runs)
    for scope, expected in zip((
        ApplicationScope(application_id="travel"),
        ApplicationScope(application_id="shopping"),
        ApplicationScope(application_id="travel", workspace_id="team-a"),
        ApplicationScope(application_id="travel", workspace_id="team-b"),
    ), scoped_runs, strict=True):
        with application_scope_context(scope):
            assert runs.get_by_key(service.owner_id, req.idempotency_key) == expected
            assert runs.get(service.owner_id, expected.id) == expected
            assert runs.session(service.owner_id, expected.session_id).iterative_run_id == expected.id
    assert runs.get_by_key(service.owner_id, req.idempotency_key) == standalone


@pytest.mark.anyio
async def test_research_policy_denial_precedes_session_and_search_calls():
    service, adapter, _, sessions, runs = build_service()
    service.application_context = without_policy_provider(
        service.application_context, "external_research"
    )

    with pytest.raises(ContextPreparationError, match="context_policy_denied"):
        await service.create(request())

    assert not sessions.sessions
    assert not runs.runs
    assert not adapter.calls

    ordinary_sessions = InMemoryResearchRepository()
    ordinary = ResearchService(
        service.settings,
        ordinary_sessions,
        adapter,
        service.context,
        service.llm,
        owner_id=service.owner_id,
        application_context=service.application_context,
        clock=service.clock,
    )
    with pytest.raises(ContextPreparationError, match="context_policy_denied"):
        await ordinary.create(ResearchRequest(
            question="Synthetic observatory schedule?", idempotency_key=uuid4()
        ))
    assert not ordinary_sessions.sessions
    assert not adapter.calls

    prior_sessions = InMemoryResearchRepository()
    prior_adapter = FakeIterativeSearchAdapter.queued([tuple(result() for _ in range(1))])
    prior = ResearchService(
        service.settings,
        prior_sessions,
        prior_adapter,
        service.context,
        service.llm,
        owner_id=service.owner_id,
        application_context=application_context(service.owner_id),
        clock=service.clock,
    )
    session = await prior.create(
        ResearchRequest(question="Synthetic schedule?", idempotency_key=uuid4())
    )
    claimed = await prior.prepare_run(session.id)
    prior.application_context = service.application_context
    frames = [frame async for frame in prior.stream(claimed)]
    assert frames and '"state": "failed"' in frames[-1]
    assert not prior_adapter.calls

    resumable, resume_adapter, _, _, _ = build_service()
    run, token = await resumable.start(request())
    resumable.application_context = without_policy_provider(
        resumable.application_context, "external_research"
    )
    _ = [frame async for frame in resumable.stream(run, token)]
    assert not resume_adapter.calls
    assert (await resumable.get(run.id)).state == RunState.INSUFFICIENT


def _without_scope_envelopes(value):
    if isinstance(value, dict):
        return {
            key: _without_scope_envelopes(item)
            for key, item in value.items()
            if key not in {"application_id", "workspace_id", "scope_version"}
        }
    if isinstance(value, (tuple, list)):
        return type(value)(_without_scope_envelopes(item) for item in value)
    return value


@pytest.mark.anyio
async def test_legacy_iterative_run_and_budget_can_be_claimed_without_rewriting_history():
    service, _, clock, sessions, runs = build_service()
    initial = await service.create(request())
    legacy_run = ResearchRun.model_validate(_without_scope_envelopes(
        initial.model_dump(mode="python")
    ))
    legacy_session = ResearchSession.model_validate(_without_scope_envelopes(
        (await service.session(initial.id)).model_dump(mode="python")
    ))
    runs.runs[legacy_run.id] = legacy_run
    sessions.sessions[legacy_session.id] = legacy_session

    claimed, claimed_session = runs.claim(
        service.owner_id, legacy_run.id, uuid4(), clock(),
        clock() + timedelta(seconds=30),
        clock() + timedelta(minutes=1),
    )

    assert claimed.scope_version == 2
    assert claimed.budget.scope_version == 1
    assert claimed.events[0].scope_version == 1
    assert claimed.ledger[0].scope_version == 1
    assert claimed.events[-1].scope_version == 2
    assert claimed_session.scope_version == 1


@pytest.mark.anyio
async def test_token_budget_returns_evidence_and_visible_gaps_without_synthesis():
    class CountingLLM(FakeResearchLLMClient):
        def __init__(self):
            self.calls = 0

        async def stream(self, messages, *, inference_context=None):
            self.calls += 1
            async for delta in super().stream(messages, inference_context=inference_context):
                yield delta

    service, adapter, _, _, _ = build_service(
        sources=(result(),),
        settings_overrides={
            "iterative_max_tokens": 512,
            "iterative_synthesis_reserve_tokens": 512,
        },
    )
    llm = CountingLLM()
    service.llm = llm
    final, _ = await execute(service, request())
    session = await service.session(final.id)

    assert final.state == RunState.INSUFFICIENT
    assert final.terminal_reason == StopReason.TOKEN_BUDGET_EXHAUSTED
    assert session.evidence and session.answer is None
    assert adapter.calls and llm.calls == 0
    assert final.usage.queries <= final.budget.max_queries
    assert final.usage.tokens == 0


@pytest.mark.anyio
async def test_cancel_fences_late_adapter_result_and_disconnect_does_not_cancel():
    entered, release = asyncio.Event(), asyncio.Event()

    async def block(query, limit):
        entered.set()
        await release.wait()

    service, adapter, _, _, _ = build_service(
        responses=[(result(),)], on_search=block
    )
    initial, token = await service.start(request())
    stream = service.stream(initial, token)
    await anext(stream)  # persisted claim event
    while True:
        frame = await anext(stream)
        if "event: research.iterative.searching" in frame:
            break
    await entered.wait()
    await stream.aclose()
    assert await service.get(initial.id)  # stream disconnect alone is read-only
    assert (await service.get(initial.id)).state not in {
        RunState.COMPLETED, RunState.INSUFFICIENT, RunState.FAILED, RunState.CANCELLED,
    }
    cancelled = await service.cancel(initial.id)
    release.set()
    await asyncio.sleep(0)
    run, session = await service.detail(initial.id)

    assert cancelled.state == run.state == RunState.CANCELLED
    assert run.terminal_reason == StopReason.CANCELLED
    assert not session.observations and not session.evidence and session.answer is None
    assert len(adapter.calls) == 1


@pytest.mark.anyio
async def test_expired_lease_with_uncertain_provider_attempt_is_terminal_without_retry():
    entered, release = asyncio.Event(), asyncio.Event()

    async def block(query, limit):
        entered.set()
        await release.wait()

    clock = DeterministicClock(NOW)
    service, adapter, _, _, _ = build_service(
        responses=[(result(),)], clock=clock, on_search=block
    )
    initial, token = await service.start(request())
    stream = service.stream(initial, token)
    await anext(stream)
    while "event: research.iterative.searching" not in await anext(stream):
        pass
    await entered.wait()
    current = await service.get(initial.id)
    assert current.state == RunState.SEARCHING
    clock.advance(60)
    recovered, recovery_token = await service.resume(initial.id)
    assert recovery_token is None
    assert recovered.state == RunState.INSUFFICIENT
    assert recovered.terminal_reason == StopReason.SIDE_EFFECT_UNCERTAIN
    release.set()
    await stream.aclose()
    await asyncio.sleep(0)
    final, _ = await service.detail(initial.id)

    assert final.state == RunState.INSUFFICIENT
    assert len(adapter.calls) == 1
    assert not (await service.session(initial.id)).evidence


@pytest.mark.anyio
async def test_elapsed_limit_and_search_failure_fail_closed():
    elapsed, elapsed_adapter, _, _, _ = build_service(
        sources=(result(),),
        settings_overrides={
            "iterative_max_elapsed_seconds": 1,
            "iterative_synthesis_reserve_seconds": 1,
        },
    )
    stopped, _ = await execute(elapsed, request())
    assert stopped.terminal_reason == StopReason.ELAPSED_BUDGET_EXHAUSTED
    assert not elapsed_adapter.calls

    failed, adapter, _, _, _ = build_service(
        responses=[SearchError("search_unavailable")]
    )
    stopped, _ = await execute(failed, request("Synthetic sample availability?"))
    assert stopped.terminal_reason == StopReason.PROVIDER_ERROR
    assert stopped.state == RunState.FAILED
    assert len(adapter.calls) == 1
    assert stopped.usage.queries == 1


def constrained_widget():
    return DecisionIntent.model_validate({
        "candidates": [{"entity_type": "object", "canonical_name": "Synthetic Widget"}],
        "constraints": [{
            "id": "30000000-0000-4000-8000-000000000009",
            "attribute": "price", "operator": "maximum",
            "value": {"kind": "money", "amount": "50", "currency": "USD"},
            "required": True, "missing_policy": "fail_closed", "source": "user",
        }],
    })


@pytest.mark.anyio
async def test_iteration_source_and_provider_cost_limits_refuse_work_before_search():
    limited_iterations, adapter, _, _, _ = build_service(
        sources=(result("https://example.org/widget", "Synthetic Widget exists."),),
        settings_overrides={"iterative_max_iterations": 1, "decision_enabled": True},
    )
    iteration_run, _ = await execute(
        limited_iterations,
        request("Synthetic Widget price?", decision_intent=constrained_widget()),
    )
    assert iteration_run.terminal_reason == StopReason.ITERATION_BUDGET_EXHAUSTED
    assert iteration_run.usage.queries == len(adapter.calls) == 1

    limited_sources, source_adapter, _, _, _ = build_service(
        sources=(result("https://example.org/widget", "Synthetic Widget exists."),),
        settings_overrides={
            "iterative_max_sources": 1,
            "decision_enabled": True,
        },
    )
    source_run, _ = await execute(
        limited_sources,
        request("Synthetic Widget price?", decision_intent=constrained_widget()),
    )
    assert source_run.terminal_reason == StopReason.SOURCE_BUDGET_EXHAUSTED
    assert source_run.usage.sources == 1 and len(source_adapter.calls) == 1

    limited_cost, cost_adapter, _, _, _ = build_service(
        sources=(result(),),
        settings_overrides={
            "iterative_max_provider_cost_usd": Decimal("0.005"),
            "iterative_synthesis_cost_usd": Decimal("0.005"),
        },
    )
    cost_adapter.name = "brave"  # fake response with configured provider cost
    cost_run, _ = await execute(limited_cost, request())
    assert cost_run.terminal_reason == StopReason.PROVIDER_COST_BUDGET_EXHAUSTED
    assert cost_run.usage.queries == 0 and not cost_adapter.calls


@pytest.mark.anyio
async def test_retry_reuses_query_and_safe_lease_recovery_does_not_repeat_committed_work():
    service, adapter, clock, _, _ = build_service(responses=[
        SearchError("search_unavailable", retryable=True),
        (result(),),
    ])
    final, _ = await execute(service, request())
    session = await service.session(final.id)
    assert final.state == RunState.COMPLETED
    assert final.usage.queries == 1 and len(adapter.calls) == 2
    assert [item.status for item in session.attempts] == ["started", "failed", "started", "completed"]

    service, adapter, clock, _, _ = build_service(sources=(result(),))
    initial, _ = await service.start(request())
    clock.advance(40)  # no provider attempt exists, so reassignment is safe
    recovered, token = await service.resume(initial.id)
    final = await service.get(initial.id)
    assert token is not None and recovered.lease_owner == token
    events = [frame async for frame in service.stream(recovered, token)]
    assert (await service.get(initial.id)).state == RunState.COMPLETED
    assert len(adapter.calls) == 1
    assert len(events) == len((await service.get(initial.id)).events)


@pytest.mark.anyio
async def test_restart_at_durable_retry_boundary_dispatches_the_next_attempt_once():
    class SimulatedProcessExit(BaseException):
        pass

    service, adapter, clock, _, _ = build_service(responses=[
        SearchError("search_unavailable", retryable=True),
        (result(),),
    ])
    initial, token = await service.start(request())
    transition = service._transition

    async def exit_after_retry_is_durable(*args, **kwargs):
        committed = await transition(*args, **kwargs)
        session = kwargs.get("session")
        if (
            args[1] == RunState.SEARCHING
            and session is not None
            and session.attempts[-1].status == "failed"
            and session.queries[-1].state == "planned"
        ):
            raise SimulatedProcessExit()
        return committed

    service._transition = exit_after_retry_is_durable
    with pytest.raises(SimulatedProcessExit):
        _ = [frame async for frame in service.stream(initial, token)]
    service._transition = transition
    clock.advance(40)  # the unstarted retry is safe to dispatch under a new lease

    recovered, recovery_token = await service.resume(initial.id)
    events = [frame async for frame in service.stream(recovered, recovery_token)]
    final = await service.get(initial.id)
    session = await service.session(final.id)
    assert final.state == RunState.COMPLETED
    assert len(adapter.calls) == 2
    assert [item.status for item in session.attempts] == ["started", "failed", "started", "completed"]
    assert any('"state": "completed"' in frame for frame in events)


@pytest.mark.anyio
async def test_iterative_session_idempotency_is_separate_from_single_pass_key():
    service, _, clock, sessions, _ = build_service()
    req = request()
    single_pass_request = ResearchRequest(
        question=req.question,
        freshness=req.freshness,
        idempotency_key=req.idempotency_key,
    )
    single_pass_session = ResearchSession(
        id=uuid4(), owner_id="local", request=single_pass_request,
        request_fingerprint=single_pass_request.fingerprint(), state="pending",
        created_at=clock(), updated_at=clock(), expires_at=clock().replace(year=2027),
    )
    sessions.create(single_pass_session)

    run = await service.create(req)
    assert run.session_id != single_pass_session.id
    assert (await service.session(run.id)).request.idempotency_key != req.idempotency_key


@pytest.mark.anyio
async def test_synthesis_failure_settles_uncertainty_and_preserves_no_answer():
    class BrokenLLM:
        async def stream(self, messages, *, inference_context=None):
            del messages, inference_context
            raise RuntimeError("synthetic failure")
            yield ""

    service, _, _, _, _ = build_service(sources=(result(),))
    service.llm = BrokenLLM()
    final, _ = await execute(service, request())
    session = await service.session(final.id)
    assert final.state == RunState.INSUFFICIENT
    assert final.terminal_reason == StopReason.SYNTHESIS_ERROR
    assert session.answer is None and not session.citations
    token_entry = next(entry for entry in final.ledger if entry.idempotency_key == "reserve:synthesis:tokens")
    assert final.usage.tokens == token_entry.reserved > final.budget.synthesis_reserve_tokens
    assert token_entry.status == "uncertain"
    assert all(entry.status != "reserved" for entry in final.ledger)


@pytest.mark.anyio
async def test_expired_citations_are_withheld_after_synthesis():
    service, _, clock, _, _ = build_service(sources=(result(),))

    class EvidenceExpiresDuringSynthesis:
        async def stream(self, messages, *, inference_context=None):
            from personal_ai.llm.fake import FakeResearchLLMClient

            async for delta in FakeResearchLLMClient().stream(
                messages, inference_context=inference_context
            ):
                yield delta
            clock.advance(3601)

    service.llm = EvidenceExpiresDuringSynthesis()
    final, _ = await execute(service, request(freshness="current"))
    session = await service.session(final.id)

    assert final.state == RunState.INSUFFICIENT
    assert final.terminal_reason == StopReason.ELAPSED_BUDGET_EXHAUSTED
    assert session.answer is None and session.citations == ()


@pytest.mark.anyio
async def test_cancelled_pending_backing_session_cannot_be_started_by_phase5():
    service, _, _, sessions, _ = build_service()
    run = await service.create(request())
    session = await service.session(run.id)
    ordinary = ResearchService(
        service.settings, sessions, service.adapter, service.context, service.llm,
        clock=service.clock,
        application_context=service.application_context,
    )

    with pytest.raises(ResearchError, match="research_session_owned_by_iterative_run"):
        await ordinary.prepare_run(session.id)

    cancelled = await service.cancel(run.id)
    assert cancelled.state == RunState.CANCELLED
    assert (await service.session(run.id)).state == "insufficient"
    with pytest.raises(ResearchError, match="research_session_owned_by_iterative_run"):
        await ordinary.prepare_run(session.id)


@pytest.mark.anyio
async def test_synthesis_finishing_after_absolute_deadline_is_charged_and_withheld():
    service, _, clock, _, _ = build_service(sources=(result(),))

    class LateLLM:
        async def stream_bounded(
            self, messages, *, max_output_tokens, timeout_seconds, inference_context=None
        ):
            del inference_context
            from personal_ai.llm.fake import FakeResearchLLMClient

            clock.advance(95)
            async for delta in FakeResearchLLMClient().stream(messages):
                yield delta

    service.llm = LateLLM()
    final, _ = await execute(service, request())
    session = await service.session(final.id)

    elapsed = next(entry for entry in final.ledger if entry.idempotency_key == "reserve:run:elapsed")
    assert final.state == RunState.INSUFFICIENT
    assert final.terminal_reason == StopReason.ELAPSED_BUDGET_EXHAUSTED
    assert final.usage.elapsed_seconds == Decimal(95)
    assert elapsed.settled == Decimal(95)
    assert elapsed.status == "settled"
    assert session.answer is None and session.citations == ()


@pytest.mark.anyio
async def test_create_recovers_backing_session_after_run_write_failure():
    service, _, _, sessions, runs = build_service()
    req = request()
    original_create = runs.create

    def failed_create(*args, **kwargs):
        raise RuntimeError("synthetic interrupted run write")

    runs.create = failed_create
    with pytest.raises(RuntimeError, match="interrupted run write"):
        await service.create(req)
    backing = next(iter(sessions.sessions.values()))
    runs.create = original_create
    recovered = await service.create(req)
    assert recovered.id == backing.iterative_run_id
    assert recovered.session_id == backing.id
    assert len(sessions.sessions) == 1
    assert (await service.create(req)).id == recovered.id


@pytest.mark.anyio
async def test_smaller_output_limit_preserves_reservation_and_completes():
    service, _, _, _, _ = build_service(
        sources=(result(),), settings_overrides={"max_response_tokens": 1024}
    )
    final, _ = await execute(service, request())
    assert final.state == RunState.COMPLETED
    entry = next(item for item in final.ledger if item.idempotency_key == "reserve:synthesis:tokens")
    assert entry.reserved >= final.budget.synthesis_reserve_tokens
    assert entry.settled <= entry.reserved


def test_progress_counts_distinct_persistent_gaps():
    from types import SimpleNamespace

    service, _, _, _, _ = build_service()
    run = SimpleNamespace(
        current_iteration=1, usage=SimpleNamespace(queries=0, sources=0),
        decision_state=None,
        gaps=[SimpleNamespace(status="open", semantic_key="same") for _ in range(200)],
    )
    assert service._progress_payload(run).gap_count == 1
