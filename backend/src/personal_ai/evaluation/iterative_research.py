"""Paired, deterministic Phase 5 / Phase 8 evaluation (synthetic data only)."""

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from personal_ai.agents.research.contracts import ResearchRequest
from personal_ai.agents.research.iterative_contracts import (
    DecisionIntent,
    IterativeResearchRequest,
    RunState,
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
from personal_ai.auth.scope import RequestScope
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.decisions.contracts import DecisionCreateRequest
from personal_ai.decisions.repositories import InMemoryDecisionRepository
from personal_ai.decisions.service import DecisionService
from personal_ai.evaluation.output import emit
from personal_ai.llm.fake import FakeResearchLLMClient
from personal_ai.search.contracts import FakeSearchAdapter, SearchResult
from personal_ai.search.providers.brave import SearchError
from personal_ai.settings import Settings

FIXTURES = Path(__file__).with_name("iterative-research-fixtures.json")
RESULT_SCHEMA = Path(__file__).with_name("iterative-research-evaluation.schema.json")


def _application_context(owner_id="local"):
    registry = default_application_registry()
    return ApplicationContextRequest(
        definition=registry.get("personal_ai"),
        scope=RequestScope(
            owner_id=owner_id, request_id="iterative-eval", application_id="personal_ai"
        ),
        context_provider_capabilities=registry.registration("personal_ai").context_providers,
        tool_capabilities=registry.registration("personal_ai").tools,
    )


def load_fixtures():
    return json.loads(FIXTURES.read_text())


def _sources(values):
    return tuple(SearchResult.model_validate(item) for item in values)


def _intent(fixture):
    value = fixture.get("decision_intent")
    return DecisionIntent.model_validate(value) if value else None


def _settings(fixture, *, iterative):
    budget = fixture["budget"]
    max_tokens = budget["tokens"]
    max_elapsed = budget["elapsed_seconds"]
    max_cost = Decimal(budget["provider_cost_usd"])
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        research_enabled=True,
        research_storage="memory",
        research_max_queries=1,
        research_max_sources=budget["sources"],
        research_attempt_limit=1,
        research_max_evidence_context_tokens=max_tokens,
        decision_enabled=bool(_intent(fixture)),
        iterative_research_enabled=iterative,
        iterative_progress_enabled=iterative,
        iterative_max_iterations=budget["iterations"],
        iterative_max_queries=budget["queries"],
        iterative_max_sources=budget["sources"],
        iterative_max_elapsed_seconds=max_elapsed,
        iterative_max_tokens=max_tokens,
        iterative_max_provider_cost_usd=max_cost,
        iterative_allowed_domains=tuple(budget["allowed_domains"]),
        iterative_synthesis_reserve_tokens=budget.get(
            "synthesis_reserve_tokens", min(4096, max_tokens)
        ),
        iterative_synthesis_reserve_seconds=min(20, max_elapsed),
        iterative_search_cost_usd=min(Decimal("0.005"), max_cost),
        iterative_synthesis_cost_usd=min(Decimal("0.005"), max_cost),
    )
    return settings


async def _decision_state(settings, session, intent, clock):
    if intent is None or session.state != "completed" or session.selection is None:
        return "not_requested" if intent is None else "research_needed"
    service = DecisionService(
        settings,
        InMemoryDecisionRepository(),
        research_repository=InMemoryResearchRepository(),
        owner_id=session.owner_id,
        clock=clock,
    )
    class SessionView:
        def get(self, owner_id, session_id):
            if owner_id != session.owner_id or session_id != session.id:
                from personal_ai.storage.errors import ResourceNotFoundError

                raise ResourceNotFoundError("research not found")
            return session

    service.research_repository = SessionView()
    result = service.create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        research_session_id=session.id,
        candidates=intent.candidates,
        constraints=intent.constraints,
        preferences=intent.preferences,
    ))
    return result.decision.state


async def _run_single_pass(fixture):
    settings = _settings(fixture, iterative=False)
    clock = DeterministicClock(datetime.fromisoformat(fixture["clock"]))
    sessions = InMemoryResearchRepository()
    error = SearchError(fixture["adapter_error"]) if fixture.get("adapter_error") else None
    adapter = FakeSearchAdapter(_sources(fixture["initial_sources"]), error=error)
    service = ResearchService(
        settings,
        sessions,
        adapter,
        ContextAssembler(settings, EstimatedTokenCounter()),
        FakeResearchLLMClient(),
        application_context=_application_context(),
        clock=clock,
    )
    request = ResearchRequest(
        question=fixture["question"],
        freshness=fixture.get("freshness", "general"),
        idempotency_key=uuid4(),
    )
    session = await service.create(request)
    claimed = await service.prepare_run(session.id)
    _ = [event async for event in service.stream(claimed)]
    session = await service.detail(session.id)
    selection = session.selection
    decision_state = await _decision_state(settings, session, _intent(fixture), clock)
    return {
        "state": session.state,
        "query_count": len(session.queries),
        "source_count": len(session.observations),
        "accepted_source_count": sum(item.status == "accepted" for item in session.observations),
        "stale_source_count": sum(item.status == "stale" for item in session.observations),
        "selected_evidence": len(selection.evidence_ids) if selection else 0,
        "tokens": selection.token_count if selection else 0,
        # All calls use deterministic fakes. This is realized provider spend.
        "provider_cost_usd": "0",
        "decision_state": decision_state,
    }


class _FixturePlanner:
    def __init__(self, override):
        self.override = override

    def propose(self, request, gap, candidates, domains):
        if self.override is not None:
            return self.override
        from personal_ai.agents.research.iterative_service import FollowupPlanner

        return FollowupPlanner().propose(request, gap, candidates, domains)


async def _run_iterative(fixture):
    settings = _settings(fixture, iterative=True)
    clock = DeterministicClock(datetime.fromisoformat(fixture["clock"]))
    sessions = InMemoryResearchRepository()
    runs = InMemoryIterativeResearchRepository(sessions)
    responses = [
        _sources(fixture["initial_sources"]),
        *[_sources(group) for group in fixture.get("followup_sources", [])],
    ]
    if fixture.get("adapter_error"):
        responses[0] = SearchError(fixture["adapter_error"])

    entered, release = asyncio.Event(), asyncio.Event()

    async def on_search(query, limit):
        if fixture.get("clock_advance_before_search"):
            clock.advance(fixture["clock_advance_before_search"])
        if fixture.get("cancel_after_event") or fixture.get("adapter_cancellation"):
            entered.set()
            if fixture.get("adapter_cancellation"):
                raise asyncio.CancelledError
            await release.wait()

    adapter = FakeIterativeSearchAdapter.queued(responses, on_search=on_search)
    service = IterativeResearchService(
        settings,
        sessions,
        runs,
        adapter,
        ContextAssembler(settings, EstimatedTokenCounter()),
        FakeResearchLLMClient(),
        application_context=_application_context(),
        clock=clock,
        duration_clock=clock.elapsed,
        planner=_FixturePlanner(fixture.get("planner_query_override")),
    )
    req = IterativeResearchRequest(
        question=fixture["question"],
        freshness=fixture.get("freshness", "general"),
        idempotency_key=uuid4(),
        decision_intent=_intent(fixture),
    )
    run, token = await service.start(req)
    events = []
    if fixture.get("cancel_after_event"):
        stream = service.stream(run, token)
        events.append(await anext(stream))
        while True:
            frame = await anext(stream)
            events.append(frame)
            if "event: research.iterative.searching" in frame:
                break
        await entered.wait()
        await service.cancel(run.id)
        release.set()
        events.extend([frame async for frame in stream])
    elif fixture.get("adapter_cancellation"):
        stream = service.stream(run, token)
        try:
            events.extend([frame async for frame in stream])
        except asyncio.CancelledError:
            pass
        clock.advance(settings.iterative_max_elapsed_seconds + 1)
        await service.resume(run.id)
    else:
        events = [frame async for frame in service.stream(run, token)]
    run = await service.get(run.id)
    session = await service.session(run.id)
    return run, session, events, adapter, service.decision_repository


def _baseline_matches(fixture, actual):
    snapshot = fixture.get("single_pass", {})
    aliases = {
        "queries": "query_count",
        "sources": "source_count",
        "selected_evidence": "selected_evidence",
        "tokens": "tokens",
        "provider_cost_usd": "provider_cost_usd",
        "state": "state",
        "decision_state": "decision_state",
    }
    return all(
        str(snapshot[key]) == str(actual[field])
        for key, field in aliases.items()
        if key in snapshot
    )


def _result_record(fixture, baseline, run, session, events, adapter, decision_repository):
    expected = fixture["expected"]
    latest_gaps = {}
    for gap in run.gaps:
        latest_gaps[gap.semantic_key] = gap
    unresolved_gaps = tuple(gap for gap in latest_gaps.values() if gap.status in {"open", "unresolvable"})
    verified_claim_count = sum(
        claim.claim_status == "verified"
        for decision_id in run.decision_ids
        for claim in decision_repository.get("local", decision_id).claims
    )
    followups = tuple(query for query in session.queries if query.rationale_code != "question")
    actual = {
        "state": run.state.value,
        "stop_reason": run.terminal_reason.value,
        "query_count": run.usage.queries,
        "source_count": run.usage.sources,
        "accepted_source_count": sum(item.status == "accepted" for item in session.observations),
        "stale_source_count": sum(item.status == "stale" for item in session.observations),
        "selected_evidence_count": len(session.selection.evidence_ids) if session.selection else 0,
        "token_count": run.usage.tokens,
        "provider_cost_usd": str(run.usage.provider_cost_usd),
        "open_gap_count": sum(gap.status == "open" for gap in run.gaps),
        "unresolved_gap_count": len(unresolved_gaps),
        "gap_classes": sorted({gap.gap_class.value for gap in unresolved_gaps}),
        "iteration_count": run.current_iteration,
        "assessment_count": len(run.assessments),
        "followup_query_count": len(followups),
        "followup_queries": [query.normalized_query for query in followups],
        "decision_state": run.decision_state,
        "verified_claim_count": verified_claim_count,
        "event_count": len(run.events),
        "observed_adapter_calls": len(adapter.calls),
        "answer_present": session.answer is not None,
        "started_attempt_count": sum(item.status == "started" for item in session.attempts),
        "uncertain_ledger_count": sum(item.status == "uncertain" for item in run.ledger),
    }
    passed = _baseline_matches(fixture, baseline)
    for key, field in (
        ("state", "state"),
        ("stop_reason", "stop_reason"),
        ("queries", "query_count"),
        ("unresolved_gaps", "unresolved_gap_count"),
        ("iteration_count", "iteration_count"),
        ("followup_query_count", "followup_query_count"),
    ):
        if key in expected:
            passed = passed and expected[key] == actual[field]
    if "max_assessments" in expected:
        passed = passed and actual["assessment_count"] <= expected["max_assessments"]
    if "decision_state" in expected:
        passed = passed and expected["decision_state"] == actual["decision_state"]
    if "gap_classes" in expected:
        passed = passed and expected["gap_classes"] == actual["gap_classes"]
    if "followup_query_contains" in expected:
        query = actual["followup_queries"][0] if actual["followup_queries"] else ""
        passed = passed and all(part.casefold() in query.casefold() for part in expected["followup_query_contains"])

    expectation = fixture["comparison_expectation"]
    comparison_passed = {
        "no_extra_search": (
            actual["query_count"] <= baseline["query_count"]
            and actual["followup_query_count"] == 0
            and actual["selected_evidence_count"] >= baseline["selected_evidence"]
        ),
        "followup_adds_coverage_without_recommendation": (
            actual["accepted_source_count"] > baseline["accepted_source_count"]
            and actual["decision_state"] == "research_needed"
            and actual["state"] == "insufficient"
        ),
        "followup_improves_verified_decision": (
            baseline["decision_state"] == "research_needed"
            and actual["decision_state"] == "recommended"
            and actual["verified_claim_count"] > 0
            and actual["state"] == "completed"
            and actual["followup_query_count"] > 0
            and actual["unresolved_gap_count"] == 0
        ),
        "unsupported_claim_fails_closed": (
            actual["state"] == "insufficient"
            and actual["decision_state"] == "research_needed"
            and actual["verified_claim_count"] == 0
        ),
        "stale_claim_fails_closed": (
            actual["state"] == "insufficient"
            and actual["decision_state"] == "research_needed"
            and actual["verified_claim_count"] == 0
            and actual["stale_source_count"] > 0
        ),
        "fresh_evidence_recovers_answer": (
            baseline["state"] == "insufficient"
            and actual["state"] == "completed"
            and actual["accepted_source_count"] > baseline["accepted_source_count"]
            and actual["unresolved_gap_count"] == 0
        ),
        "conflict_remains_visible": (
            actual["state"] == "insufficient"
            and "source_conflict" in actual["gap_classes"]
            and actual["accepted_source_count"] >= baseline["accepted_source_count"]
        ),
        "three_query_gap_history_bounded": (
            actual["query_count"] == actual["observed_adapter_calls"] == 3
            and actual["state"] == "insufficient"
            and actual["stop_reason"] != "provider_error"
            and actual["decision_state"] == "research_needed"
            and actual["assessment_count"] <= 6
            and len(run.gaps) <= 512
        ),
        "ambiguous_identity_fails_closed": (
            actual["state"] == "insufficient"
            and actual["decision_state"] == "research_needed"
            and {"candidate_coverage", "required_fact_missing"} <= set(actual["gap_classes"])
        ),
        "provider_failure_fails_closed": (
            baseline["state"] == actual["state"] == "failed"
            and actual["decision_state"] == "research_needed"
        ),
        "repeat_is_not_dispatched": (
            actual["query_count"] == actual["observed_adapter_calls"] == 1
            and actual["followup_query_count"] == 0
        ),
        "query_budget_refuses_followup": (
            actual["stop_reason"] == "query_budget_exhausted"
            and actual["query_count"] <= run.budget.max_queries
            and actual["followup_query_count"] == 0
        ),
        "unlisted_source_is_excluded": (
            actual["accepted_source_count"] == 0
            and actual["selected_evidence_count"] == 0
            and not actual["answer_present"]
        ),
        "token_budget_refuses_synthesis": (
            actual["stop_reason"] == "token_budget_exhausted"
            and actual["token_count"] == 0
            and not actual["answer_present"]
        ),
        "elapsed_budget_refuses_dispatch": (
            actual["stop_reason"] == "elapsed_budget_exhausted"
            and actual["query_count"] == actual["observed_adapter_calls"] == 0
        ),
        "cancel_fences_late_evidence": (
            actual["state"] == "cancelled"
            and not session.observations
            and actual["observed_adapter_calls"] == 1
        ),
        "uncertain_attempt_is_not_replayed": (
            actual["stop_reason"] == "side_effect_uncertain"
            and actual["observed_adapter_calls"] == 1
            and actual["started_attempt_count"] == 1
            and actual["uncertain_ledger_count"] >= 1
            and not session.observations
        ),
    }.get(expectation, False)
    comparison = {
        "expectation": expectation,
        "claim": fixture["meaningful_improvement"],
        "passed": bool(comparison_passed),
        "query_delta": actual["query_count"] - baseline["query_count"],
        "accepted_source_delta": actual["accepted_source_count"] - baseline["accepted_source_count"],
        "selected_evidence_delta": actual["selected_evidence_count"] - baseline["selected_evidence"],
    }
    passed = passed and comparison["passed"]
    passed = passed and (
        actual["query_count"] <= run.budget.max_queries
        and actual["source_count"] <= run.budget.max_sources
        and actual["token_count"] <= run.budget.max_tokens
        and run.usage.provider_cost_usd <= run.budget.max_provider_cost_usd
        and (
            run.usage.elapsed_seconds <= run.budget.max_elapsed_seconds
            or run.state == RunState.INSUFFICIENT
            and run.terminal_reason.value in {"side_effect_uncertain", "elapsed_budget_exhausted"}
        )
        and run.usage.allowed_domains <= len(run.budget.allowed_domains)
        and len(run.events) <= 128
        and (run.state != RunState.COMPLETED or not any(g.status == "open" and g.required for g in run.gaps))
    )
    return {
        "name": fixture["name"],
        "passed": bool(passed),
        "single_pass": baseline,
        "iterative": actual,
        "comparison": comparison,
    }


def _validate_schema(report):
    schema = json.loads(RESULT_SCHEMA.read_text())
    required = set(schema["required"])
    if set(report) != required:
        raise ValueError("evaluation report does not match required schema fields")
    if report["schema_version"] != schema["properties"]["schema_version"]["const"]:
        raise ValueError("unsupported evaluation schema version")
    if not report["synthetic"] or report["single_pass_baseline"] != "research-v1":
        raise ValueError("evaluation report must compare synthetic fixtures to Phase 5")
    if report["paired_count"] != len(report["results"]) or report["paired_count"] < 10:
        raise ValueError("at least ten complete paired fixtures are required")
    if not isinstance(report["passed"], bool):
        raise TypeError("invalid evaluation pass state")
    required_iterative = set(schema["properties"]["results"]["items"]["properties"]["iterative"]["required"])
    for result in report["results"]:
        if set(result) != {"name", "passed", "single_pass", "iterative", "comparison"}:
            raise ValueError("invalid paired result fields")
        if not isinstance(result["single_pass"], dict) or set(result["iterative"]) != required_iterative:
            raise ValueError("invalid paired result payload")
        if set(result["comparison"]) != {
            "expectation", "claim", "passed", "query_delta", "accepted_source_delta",
            "selected_evidence_delta",
        }:
            raise ValueError("invalid comparative outcome")
        if not result["comparison"]["passed"]:
            raise ValueError("fixture did not meet its comparative acceptance assertion")
        item = result["iterative"]
        if item["state"] not in schema["properties"]["results"]["items"]["properties"]["iterative"]["properties"]["state"]["enum"]:
            raise ValueError("invalid iterative terminal state")
        if item["event_count"] < 1 or item["event_count"] > 128:
            raise ValueError("invalid persisted event count")


async def evaluate():
    results = []
    for fixture in load_fixtures():
        baseline = await _run_single_pass(fixture)
        run, session, events, adapter, decision_repository = await _run_iterative(fixture)
        results.append(_result_record(fixture, baseline, run, session, events, adapter, decision_repository))
    report = {
        "schema_version": "iterative-research-evaluation-v1",
        "synthetic": True,
        "single_pass_baseline": "research-v1",
        "paired_count": len(results),
        "passed": all(item["passed"] for item in results),
        "results": results,
    }
    _validate_schema(report)
    return report


if __name__ == "__main__":
    result = asyncio.run(evaluate())
    emit(result)
    raise SystemExit(0 if result["passed"] else 1)
