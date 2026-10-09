"""Bounded iterative research state machine built on Phase 5 and Phase 6 services."""

import asyncio
import json
import logging
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5

import anyio

from personal_ai.agents.research.contracts import (
    ResearchError,
    ResearchRequest,
    ResearchSession,
)
from personal_ai.agents.research.contracts import (
    evolve as evolve_session,
)
from personal_ai.agents.research.iterative_contracts import (
    BudgetLedgerEntry,
    BudgetSnapshot,
    EvidenceGap,
    EvidenceGapClass,
    FollowupProposal,
    IterationRecord,
    IterativeResearchRequest,
    ResearchRun,
    RunEvent,
    RunState,
    SafeEventPayload,
    StopReason,
    SufficiencyAssessment,
)
from personal_ai.applications.contracts import ApplicationContextRequest
from personal_ai.auth.scope import current_application_scope
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.authorization import (
    authorize_base_disclosure,
    authorize_context_selection,
)
from personal_ai.context.providers import ContextPreparationError, ContextSelection
from personal_ai.decisions.contracts import ClaimProposal, DecisionCreateRequest, DecisionResult
from personal_ai.decisions.repositories import InMemoryDecisionRepository
from personal_ai.decisions.service import DecisionService
from personal_ai.entities.research import MoneyValue
from personal_ai.evidence.contracts import AdapterAttempt, EvidenceSelection, SearchQuery
from personal_ai.evidence.pipeline import extract_evidence, select_evidence, validate_synthesis
from personal_ai.llm.attribution import log_generation_attribution
from personal_ai.llm.preparation import require_matching_endpoint
from personal_ai.search.contracts import SearchResult
from personal_ai.search.policy import SnippetExtractor, canonical_url
from personal_ai.settings import Settings
from personal_ai.storage.async_io import io_call
from personal_ai.storage.errors import ResourceNotFoundError
from personal_ai.usage.context import bind_usage_task

TERMINAL_STATES = {RunState.COMPLETED, RunState.INSUFFICIENT, RunState.FAILED, RunState.CANCELLED}
logger = logging.getLogger(__name__)
GAP_PRIORITY = {
    EvidenceGapClass.REQUIRED_FACT_MISSING: 0,
    EvidenceGapClass.EVIDENCE_STALE: 1,
    EvidenceGapClass.SOURCE_CONFLICT: 2,
    EvidenceGapClass.IDENTITY_AMBIGUITY: 3,
    EvidenceGapClass.CANDIDATE_COVERAGE: 4,
    EvidenceGapClass.CITATION_SUPPORT: 5,
    EvidenceGapClass.INITIAL_COVERAGE: 6,
}


def iterative_run_id(owner_id: str, idempotency_key: UUID, scope=None) -> UUID:
    """Scope durable run identity while retaining historical standalone IDs."""
    scope = scope or current_application_scope()
    suffix = (
        "" if scope.application_id == "personal_ai" and scope.workspace_id is None
        else f":{scope.application_id}:{scope.workspace_id or ''}"
    )
    return uuid5(idempotency_key, f"phase8-run:{owner_id}{suffix}")


def _snapshot_id(session: ResearchSession) -> UUID:
    identity = ":".join(str(item.id) for item in session.evidence)
    identity += "|" + ":".join(str(item.id) for item in session.observations)
    return uuid5(session.id, sha256(identity.encode()).hexdigest())


def _host_allowed(url: str, domains: tuple[str, ...]) -> bool:
    try:
        host = urlsplit(canonical_url(url)).hostname or ""
    except ValueError:
        return False
    return host in domains


def _normalized_query(query: str) -> str:
    return " ".join(query.casefold().split())


def _evidence_conflicts(session: ResearchSession, now: datetime) -> tuple[UUID, ...]:
    evidence = [item for item in session.evidence if item.expires_at > now]
    conflicting_ids: set[UUID] = set()
    for index, first in enumerate(evidence):
        first_words = set(re.findall(r"\w+", first.passage.casefold()))
        first_numbers = set(re.findall(r"(?<!\w)[+-]?\d+(?:\.\d+)?", first.passage))
        first_negated = bool(re.search(r"\b(no|not|never|without|cannot|can't)\b", first.passage, re.IGNORECASE))
        for second in evidence[index + 1 :]:
            second_words = set(re.findall(r"\w+", second.passage.casefold()))
            union = first_words | second_words
            overlap = len(first_words & second_words) / max(1, len(union))
            if overlap < 0.7:
                continue
            second_numbers = set(re.findall(r"(?<!\w)[+-]?\d+(?:\.\d+)?", second.passage))
            second_negated = bool(re.search(r"\b(no|not|never|without|cannot|can't)\b", second.passage, re.IGNORECASE))
            if first_numbers != second_numbers or first_negated != second_negated:
                conflicting_ids.update((first.id, second.id))
    # Store one immutable conflict finding per assessment with all participating
    # evidence IDs. This keeps the bounded run record small as the evidence set
    # grows while preserving the complete provenance for review.
    return tuple(sorted(conflicting_ids, key=str))


class _DecisionSessionView:
    """Provide the live evidence snapshot to the existing Phase 6 decision service."""

    def __init__(self, session: ResearchSession, selection: EvidenceSelection):
        self.session, self.selection = session, selection

    def get(self, owner_id: str, session_id: UUID):
        if owner_id != self.session.owner_id or session_id != self.session.id:
            raise ResourceNotFoundError("research not found")
        # This ephemeral projection gives the Phase 6 service its normal completed,
        # selected-evidence contract without persisting a premature session result.
        return self.session.model_copy(
            update={"state": "completed", "selection": self.selection, "answer": "evidence snapshot"}
        )


class FollowupPlanner:
    """Return a bounded template action for one validated, named evidence gap."""

    def propose(
        self,
        request: IterativeResearchRequest,
        gap: EvidenceGap,
        candidates: dict[UUID, str],
        domains: tuple[str, ...],
    ) -> FollowupProposal | None:
        template = {
            EvidenceGapClass.REQUIRED_FACT_MISSING: "required_fact",
            EvidenceGapClass.EVIDENCE_STALE: "current_source",
            EvidenceGapClass.SOURCE_CONFLICT: "independent_confirmation",
            EvidenceGapClass.IDENTITY_AMBIGUITY: "identity_model",
            EvidenceGapClass.CANDIDATE_COVERAGE: "candidate_source",
        }.get(gap.gap_class)
        if template is None:
            return None
        return FollowupProposal(
            gap_id=gap.id,
            template=template,
            target_id=gap.target_id,
            attribute=gap.attribute,
            allowed_domains=domains,
        )


class IterativeResearchService:
    def __init__(
        self,
        settings: Settings,
        session_repository,
        run_repository,
        adapter,
        context: ContextAssembler,
        llm,
        *,
        owner_id: str = "local",
        application_context: ApplicationContextRequest | None = None,
        clock=lambda: datetime.now(UTC),
        duration_clock=monotonic,
        planner=None,
        extractor=None,
        decision_repository=None,
        reranker=None,
    ):
        self.settings = settings
        self.sessions = session_repository
        self.runs = run_repository
        self.adapter = adapter
        self.context = context
        self.llm = llm
        self.owner_id = owner_id
        self.application_context = application_context
        self.clock = clock
        self.duration_clock = duration_clock
        self.planner = planner or FollowupPlanner()
        self.extractor = extractor or SnippetExtractor()
        self.decision_repository = decision_repository or InMemoryDecisionRepository()
        self.reranker = reranker
        self._listeners: dict[UUID, set[asyncio.Queue]] = {}
        self._execution_tasks: dict[tuple[UUID, UUID], asyncio.Task] = {}

    def _budget(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            max_iterations=self.settings.iterative_max_iterations,
            max_queries=self.settings.iterative_max_queries,
            max_sources=self.settings.iterative_max_sources,
            max_elapsed_seconds=self.settings.iterative_max_elapsed_seconds,
            max_tokens=self.settings.iterative_max_tokens,
            max_provider_cost_usd=self.settings.iterative_max_provider_cost_usd,
            allowed_domains=self.settings.iterative_allowed_domains,
            synthesis_reserve_tokens=self.settings.iterative_synthesis_reserve_tokens,
            synthesis_reserve_seconds=self.settings.iterative_synthesis_reserve_seconds,
            synthesis_reserve_cost_usd=self.settings.iterative_synthesis_cost_usd,
            search_cost_usd=self.settings.iterative_search_cost_usd,
            provider_timeout_seconds=self.settings.research_provider_timeout_seconds,
            attempt_limit=self.settings.research_attempt_limit,
            synthesis_output_tokens=min(
                self.settings.max_response_tokens,
                self.settings.iterative_synthesis_reserve_tokens,
            ),
        )

    async def create(self, request: IterativeResearchRequest) -> ResearchRun:
        if not self.settings.iterative_research_enabled or not self.settings.iterative_progress_enabled:
            raise ResourceNotFoundError("research run not found")
        if request.decision_intent is not None and not self.settings.decision_enabled:
            raise ResourceNotFoundError("decision support is unavailable")
        self._authorize_research_context()
        fingerprint = request.fingerprint()
        try:
            existing = await self._io(self.runs.get_by_key, self.owner_id, request.idempotency_key)
        except ResourceNotFoundError:
            existing = None
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ResearchError("idempotency_conflict", 409)
            return existing

        now = self.clock()
        # Keep historical standalone run IDs stable while partitioning the same
        # owner/idempotency pair across application and workspace namespaces.
        run_id = iterative_run_id(
            self.owner_id, request.idempotency_key, self.application_context.scope
        )
        phase5_request = ResearchRequest(
            question=request.question,
            freshness=request.freshness,
            # Keep the iterative session's Phase 5 key in its own namespace so
            # an ordinary single-pass request with the same client key cannot
            # be adopted as this run's backing session.
            idempotency_key=uuid5(request.idempotency_key, "phase8-research-session"),
        )
        session = ResearchSession(
            id=uuid4(),
            owner_id=self.owner_id,
            request=phase5_request,
            request_fingerprint=phase5_request.fingerprint(),
            state="pending",
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=24),
            iterative_run_id=run_id,
            application_id=self.application_context.scope.application_id,
            workspace_id=self.application_context.scope.workspace_id,
        )
        session = await self._io(self.sessions.create, session)
        budget = self._budget()
        event = RunEvent(
            id=uuid4(),
            run_id=run_id,
            sequence=0,
            event_type="planning",
            idempotency_key="run-created",
            safe_payload=SafeEventPayload(state=RunState.PENDING),
            occurred_at=now,
        )
        ledger = (
            BudgetLedgerEntry(
                id=uuid4(), run_id=run_id, dimension="tokens",
                reserved=Decimal(budget.synthesis_reserve_tokens),
                status="reserved", idempotency_key="reserve:synthesis:tokens", created_at=now,
            ),
            BudgetLedgerEntry(
                id=uuid4(), run_id=run_id, dimension="provider_cost_usd",
                reserved=budget.synthesis_reserve_cost_usd,
                status="reserved", idempotency_key="reserve:synthesis:cost", created_at=now,
            ),
            BudgetLedgerEntry(
                id=uuid4(), run_id=run_id, dimension="elapsed_seconds",
                reserved=Decimal(budget.max_elapsed_seconds),
                status="reserved", idempotency_key="reserve:run:elapsed", created_at=now,
            ),
        )
        run = ResearchRun(
            id=run_id,
            owner_id=self.owner_id,
            session_id=session.id,
            state=RunState.PENDING,
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
            budget=budget,
            decision_intent=request.decision_intent,
            created_at=now,
            updated_at=now,
            events=(event,),
            ledger=ledger,
        )
        return await self._io(self.runs.create, run)

    async def start(self, request: IterativeResearchRequest, after: int = -1) -> tuple[ResearchRun, UUID | None]:
        if after < -1:
            raise ResearchError("research_event_cursor_invalid", 422)
        try:
            existing = await self._io(self.runs.get_by_key, self.owner_id, request.idempotency_key)
        except ResourceNotFoundError:
            existing = None
        if existing is None and after != -1:
            raise ResearchError("research_event_cursor_invalid", 422)
        if existing is not None:
            self._validate_cursor(existing, after)
        run = await self.create(request)
        if run.state in TERMINAL_STATES:
            return run, None
        now = self.clock()
        token = uuid4()
        deadline = now + timedelta(seconds=run.budget.max_elapsed_seconds)
        lease = min(deadline, now + timedelta(seconds=max(30, run.budget.provider_timeout_seconds + 5)))
        try:
            claimed, _ = await self._io(
                self.runs.claim, self.owner_id, run.id, token, now, lease, deadline
            )
            return claimed, token
        except ResearchError as error:
            if error.code == "research_run_busy":
                return await self._io(self.runs.get, self.owner_id, run.id), None
            raise

    async def get(self, run_id: UUID) -> ResearchRun:
        return await self._io(self.runs.get, self.owner_id, run_id)

    async def session(self, run_id: UUID) -> ResearchSession:
        run = await self.get(run_id)
        return await self._io(self.runs.session, self.owner_id, run.session_id)

    async def detail(self, run_id: UUID) -> tuple[ResearchRun, ResearchSession]:
        run = await self.get(run_id)
        session = await self._io(self.runs.session, self.owner_id, run.session_id)
        return run, session

    async def events(self, run_id: UUID, after: int = -1) -> tuple[RunEvent, ...]:
        run = await self.get(run_id)
        self._validate_cursor(run, after)
        return tuple(event for event in run.events if event.sequence > after)

    async def event_stream(self, run_id: UUID, after: int = -1):
        run = await self.get(run_id)
        self._validate_cursor(run, after)
        for item in run.events:
            if item.sequence > after:
                yield self._frame(run.session_id, item)

    async def cancel(self, run_id: UUID) -> ResearchRun:
        run = await self.get(run_id)
        if run.state in TERMINAL_STATES:
            return run
        session = await self._io(self.runs.session, self.owner_id, run.session_id)
        unresolved = any(
            attempt.status == "started"
            and not any(child.parent_attempt_id == attempt.id for child in session.attempts)
            for attempt in session.attempts
        )
        uncertain = run.state in {RunState.EXTRACTING, RunState.SYNTHESIZING} or unresolved
        return await self._stop(
            run, session, StopReason.CANCELLED, RunState.CANCELLED,
            session_state="insufficient", uncertain=uncertain,
        )

    async def resume(self, run_id: UUID, after: int = -1) -> tuple[ResearchRun, UUID | None]:
        run = await self.get(run_id)
        self._validate_cursor(run, after)
        if run.state in TERMINAL_STATES:
            return run, None
        now = self.clock()
        if run.lease_expires_at is not None and run.lease_expires_at > now:
            return run, None
        session = await self._io(self.runs.session, self.owner_id, run.session_id)
        unresolved = [
            attempt for attempt in session.attempts
            if attempt.status == "started"
            and not any(item.parent_attempt_id == attempt.id for item in session.attempts)
        ]
        uncertain = run.state in {RunState.EXTRACTING, RunState.SYNTHESIZING} or bool(unresolved)
        if uncertain:
            ledger, usage = self._settle_pending_for_stop(run, uncertain=True)
            candidate_session = evolve_session(
                session,
                state="insufficient",
                failure_code="side_effect_uncertain",
                answer=None,
                citations=(),
                updated_at=now,
                revision=session.revision + 1,
            )
            run = await self._transition(
                run,
                RunState.INSUFFICIENT,
                "incomplete",
                session=candidate_session,
                updates={
                    "terminal_reason": StopReason.SIDE_EFFECT_UNCERTAIN,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "ledger": ledger,
                    "usage": usage,
                },
                now=now,
                allow_expired_lease=True,
            )
            return run, None
        if self._remaining_elapsed(run) <= 0:
            run = await self._stop(
                run, session, StopReason.ELAPSED_BUDGET_EXHAUSTED,
                RunState.INSUFFICIENT, session_state="insufficient",
            )
            return run, None
        token = uuid4()
        deadline = run.created_at + timedelta(seconds=run.budget.max_elapsed_seconds)
        lease = min(deadline, now + timedelta(seconds=max(30, run.budget.provider_timeout_seconds + 5)))
        claimed, _ = await self._io(
            self.runs.claim, self.owner_id, run.id, token, now, lease, deadline
        )
        return claimed, token

    @staticmethod
    def _validate_cursor(run: ResearchRun, after: int) -> None:
        if after < -1 or after >= len(run.events):
            raise ResearchError("research_event_cursor_invalid", 422)

    async def stream(self, run: ResearchRun, lease_token: UUID | None, after: int = -1):
        if after < -1:
            raise ResearchError("research_event_cursor_invalid", 422)
        cursor = after
        for item in run.events:
            if item.sequence > cursor:
                yield self._frame(run.session_id, item)
                cursor = item.sequence
        if lease_token is None or run.lease_owner != lease_token:
            return
        key = (run.id, lease_token)
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.setdefault(run.id, set()).add(queue)
        task = self._execution_tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self._execute(run, lease_token))
            self._execution_tasks[key] = task
            task.add_done_callback(
                lambda completed, execution_key=key: self._execution_tasks.pop(execution_key, None)
            )
        try:
            while not task.done():
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.25)
                except TimeoutError:
                    continue
                if item.sequence > cursor:
                    yield self._frame(run.session_id, item)
                    cursor = item.sequence
            await task
            current = await self.get(run.id)
            for item in current.events:
                if item.sequence > cursor:
                    yield self._frame(current.session_id, item)
                    cursor = item.sequence
        finally:
            self._listeners.get(run.id, set()).discard(queue)

    def _frame(self, session_id: UUID, item: RunEvent) -> str:
        payload = {
            "schema_version": "iterative-research-v1",
            "session_id": str(session_id),
            "run_id": str(item.run_id),
            "sequence": item.sequence,
            "event_type": item.event_type,
            **item.safe_payload.model_dump(mode="json", exclude_none=True),
        }
        return f"id: {item.sequence}\nevent: research.iterative.{item.event_type}\ndata: {json.dumps(payload)}\n\n"

    async def _execute(self, run: ResearchRun, token: UUID):
        try:
            await self._execute_loop(run, token)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - unexpected failures close safely if the fence remains current
            try:
                current = await self.get(run.id)
                if current.lease_owner == token and current.state not in TERMINAL_STATES:
                    session = await self._io(self.runs.session, self.owner_id, current.session_id)
                    unresolved = any(
                        attempt.status == "started"
                        and not any(child.parent_attempt_id == attempt.id for child in session.attempts)
                        for attempt in session.attempts
                    )
                    uncertain = current.state in {
                        RunState.SEARCHING, RunState.EXTRACTING, RunState.SYNTHESIZING,
                    } and (unresolved or current.state in {RunState.EXTRACTING, RunState.SYNTHESIZING})
                    elapsed = self._remaining_elapsed(current) <= 0
                    await self._stop(
                        current,
                        session,
                        StopReason.SIDE_EFFECT_UNCERTAIN if uncertain else StopReason.ELAPSED_BUDGET_EXHAUSTED if elapsed else StopReason.PROVIDER_ERROR,
                        RunState.INSUFFICIENT,
                        session_state="insufficient",
                        uncertain=uncertain,
                    )
            except Exception:  # noqa: BLE001 - durable state will be reconciled by lease recovery
                return

    async def _execute_loop(self, run: ResearchRun, token: UUID):
        while run.state not in TERMINAL_STATES:
            self._assert_lease(run, token)
            session = await self._io(self.runs.session, self.owner_id, run.session_id)
            if run.state == RunState.PLANNING:
                run, session = await self._dispatch_planned(run, session)
                if run.state in TERMINAL_STATES:
                    return
                continue
            if run.state in {RunState.SEARCHING, RunState.EXTRACTING, RunState.SYNTHESIZING}:
                # These states are executed in the same lease. A restarted lease
                # is handled by resume(), which rejects uncertain side effects.
                if run.state == RunState.SEARCHING:
                    latest = self._current_query(run, session)
                    if latest is None:
                        await self._stop(run, session, StopReason.NO_PRODUCTIVE_QUERY, RunState.INSUFFICIENT)
                        return
                    attempts = [item for item in session.attempts if item.query_id == latest.id]
                    unresolved = any(
                        item.status == "started"
                        and not any(child.parent_attempt_id == item.id for child in attempts)
                        for item in attempts
                    )
                    if unresolved:
                        await self._stop(
                            run, session, StopReason.SIDE_EFFECT_UNCERTAIN,
                            RunState.INSUFFICIENT, uncertain=True,
                        )
                        return
                    if latest.state == "planned":
                        run, session = await self._dispatch_planned(run, session)
                        continue
                    # A retryable provider error is durably recorded with a
                    # still-planned query before the next attempt. If the
                    # process stops at that boundary, continue the next
                    # numbered attempt; a terminal query is assessed without
                    # repeating its side effect.
                    run = await self._transition(
                        run, RunState.ASSESSING, "assessing",
                        updates={
                            "iterations": (
                                *run.iterations[:-1],
                                run.iterations[-1].model_copy(update={"state": "assessing"}),
                            ),
                        },
                    )
                    continue
                return
            if run.state == RunState.ASSESSING:
                if not run.iterations or run.iterations[-1].state in {"completed", "incomplete", "cancelled"}:
                    run = await self._begin_iteration(run)
                    if run.state in TERMINAL_STATES:
                        return
                session = await self._io(self.runs.session, self.owner_id, run.session_id)
                assessment, gaps, selection, decision_state, decision_id = await self._assess(run, session)
                self._assert_lease(run, token)
                latest_iteration = run.iterations[-1]
                updated_iteration = latest_iteration.model_copy(update={
                    "assessment_id": assessment.id, "state": "assessing",
                    "budget_after": run.usage,
                })
                run = await self._transition(
                    run,
                    RunState.ASSESSING,
                    "assessing",
                    updates={
                        "assessments": (*run.assessments, assessment),
                        "gaps": self._merge_gaps(run, gaps),
                        "iterations": (*run.iterations[:-1], updated_iteration),
                        "decision_state": decision_state,
                        "decision_ids": (
                            (*run.decision_ids, decision_id)
                            if decision_id is not None and decision_id not in run.decision_ids
                            else run.decision_ids
                        ),
                    },
                    event_payload=self._progress_payload(run, gap_count=len(gaps)),
                )
                if assessment.sufficient:
                    await self._finish(run, session, selection, StopReason.SUFFICIENT, True)
                    return
                if latest_iteration.query_ids:
                    if run.current_iteration >= run.budget.max_iterations:
                        await self._finish(
                            run, session, selection,
                            StopReason.ITERATION_BUDGET_EXHAUSTED, False,
                        )
                        return
                    if run.usage.queries + self._pending(run, "queries") >= run.budget.max_queries:
                        await self._finish(
                            run, session, selection,
                            StopReason.QUERY_BUDGET_EXHAUSTED, False,
                        )
                        return
                    closed = run.iterations[-1].model_copy(update={
                        "state": "completed", "completed_at": self.clock(),
                        "budget_after": run.usage,
                    })
                    run = await self._transition(
                        run, RunState.ASSESSING, "assessing",
                        updates={"iterations": (*run.iterations[:-1], closed)},
                    )
                    continue
                gap = self._select_gap(gaps)
                if gap is None:
                    await self._finish(run, session, selection, StopReason.EVIDENCE_INSUFFICIENT, False)
                    return
                remaining_sources = min(
                    run.budget.max_sources - run.usage.sources,
                    12 - len(session.observations),
                )
                if remaining_sources <= 0:
                    await self._finish(run, session, selection, StopReason.SOURCE_BUDGET_EXHAUSTED, False)
                    return
                search_cost = Decimal(0) if self.adapter.name == "fake" else run.budget.search_cost_usd
                if search_cost + self._reserved_or_used(run, "provider_cost_usd") > run.budget.max_provider_cost_usd:
                    await self._finish(run, session, selection, StopReason.PROVIDER_COST_BUDGET_EXHAUSTED, False)
                    return
                if self._remaining_elapsed(run) <= 0:
                    await self._finish(run, session, selection, StopReason.ELAPSED_BUDGET_EXHAUSTED, False)
                    return
                if run.usage.queries + self._pending(run, "queries") >= run.budget.max_queries:
                    await self._finish(run, session, selection, StopReason.QUERY_BUDGET_EXHAUSTED, False)
                    return
                query_text, rationale = self._plan_followup(run, session, gap)
                if not session.queries:
                    query_text, rationale = session.request.question, "question"
                if query_text is None or _normalized_query(query_text) in {
                    _normalized_query(query.normalized_query) for query in session.queries
                }:
                    unresolvable = gap.model_copy(update={"status": "unresolvable"})
                    new_gaps = tuple(unresolvable if item.id == gap.id else item for item in run.gaps)
                    run = await self._transition(
                        run,
                        RunState.ASSESSING,
                        "assessing",
                        updates={"gaps": new_gaps},
                    )
                    await self._finish(run, session, selection, StopReason.NO_PRODUCTIVE_QUERY, False)
                    return
                await self._plan_query(run, session, query_text, rationale, gap)
                run = await self.get(run.id)
                continue
            return

    async def _begin_iteration(self, run: ResearchRun) -> ResearchRun:
        now = self.clock()
        if run.usage.iterations >= run.budget.max_iterations:
            session = await self._io(self.runs.session, self.owner_id, run.session_id)
            await self._finish(run, session, None, StopReason.ITERATION_BUDGET_EXHAUSTED, False)
            return await self.get(run.id)
        iteration_id = uuid5(run.id, f"iteration:{run.usage.iterations}")
        before = run.usage
        entry = BudgetLedgerEntry(
            id=uuid5(run.id, f"iteration-ledger:{run.usage.iterations}"),
            run_id=run.id,
            iteration_id=iteration_id,
            dimension="iterations",
            reserved=Decimal(1),
            settled=Decimal(1),
            status="settled",
            idempotency_key=f"iteration:{run.usage.iterations}",
            created_at=now,
        )
        usage = before.model_copy(update={"iterations": before.iterations + 1})
        iteration = IterationRecord(
            id=iteration_id,
            run_id=run.id,
            sequence=run.usage.iterations,
            state="assessing",
            input_evidence_snapshot_id=_snapshot_id(await self._io(self.runs.session, self.owner_id, run.session_id)),
            budget_before=before,
            budget_after=usage,
            started_at=now,
        )
        return await self._transition(
            run,
            RunState.ASSESSING,
            "assessing",
            updates={
                "current_iteration": run.current_iteration + 1,
                "usage": usage,
                "iterations": (*run.iterations, iteration),
                "ledger": (*run.ledger, entry),
            },
            event_payload=self._progress_payload(run, iteration=run.current_iteration),
            now=now,
        )

    async def _assess(self, run: ResearchRun, session: ResearchSession):
        now = self.clock()
        iteration = run.iterations[-1]
        gaps: list[EvidenceGap] = []
        decision_id = None
        assessment_id = uuid5(run.id, f"assessment:{len(run.assessments)}")
        accepted_sources = {source.id: source for source in session.observations if source.status == "accepted"}
        eligible = tuple(
            item for item in session.evidence
            if item.expires_at > now
            and any(source_id in accepted_sources for source_id in item.source_observation_ids)
            and any(
                _host_allowed(accepted_sources[source_id].canonical_url, run.budget.allowed_domains)
                for source_id in item.source_observation_ids if source_id in accepted_sources
            )
        )
        stale_sources = tuple(source for source in session.observations if source.status == "stale")
        conflicts = _evidence_conflicts(session, now)
        if conflicts:
            gaps.append(self._gap(
                run, iteration, EvidenceGapClass.SOURCE_CONFLICT, None, None,
                conflicts, True, "competing_source_observations",
            ))

        relevance = self._relevant_evidence(session.request.question, eligible)
        if stale_sources and not relevance:
            gaps.append(self._gap(
                run, iteration, EvidenceGapClass.EVIDENCE_STALE, None, None,
                (), True, "expired_evidence",
            ))
        decision_state = None
        if run.decision_intent is not None:
            try:
                proposed_candidates = self._propose_supported_claims(run, eligible)
                if not all(candidate.claims for candidate in proposed_candidates):
                    # Do not ask Phase 6 to persist anonymous candidate entities
                    # without evidence-backed identity/claims. Such provisional
                    # records can make a later exact candidate look ambiguous.
                    raise ValueError("candidate claims are not yet supported")
                selection = self._decision_selection(session, eligible, now)
                decision_request = DecisionCreateRequest(
                    idempotency_key=uuid5(run.id, f"assessment:{len(run.assessments)}"),
                    research_session_id=session.id,
                    candidates=proposed_candidates,
                    constraints=run.decision_intent.constraints,
                    preferences=run.decision_intent.preferences,
                )
                decision_service = DecisionService(
                    self.settings,
                    self.decision_repository,
                    research_repository=_DecisionSessionView(session, selection),
                    owner_id=self.owner_id,
                    clock=self.clock,
                )
                result: DecisionResult = await self._io(decision_service.create, decision_request)
                decision_state = result.decision.state
                decision_id = result.decision.id
                candidate_names = {entity.id: entity.canonical_name for entity in result.entities}
                stable_candidate_ids = {
                    " ".join(candidate.canonical_name.casefold().split()): uuid5(
                        run.id, f"candidate:{index}"
                    )
                    for index, candidate in enumerate(run.decision_intent.candidates)
                }
                stable_entity_ids = {
                    entity.id: stable_candidate_ids.get(
                        " ".join(entity.canonical_name.casefold().split()), entity.id
                    )
                    for entity in result.entities
                }
                constraints = {constraint.id: constraint for constraint in run.decision_intent.constraints}
                for evaluation in result.evaluations:
                    stable_target_id = stable_entity_ids.get(evaluation.entity_id, evaluation.entity_id)
                    if evaluation.identity_outcome == "review":
                        gaps.append(self._gap(
                            run, iteration, EvidenceGapClass.IDENTITY_AMBIGUITY,
                            stable_target_id, None, evaluation.identity_candidate_entity_ids,
                            True, "identity_review",
                        ))
                    if "candidate_no_current_evidence" in evaluation.exclusion_reasons or "identity_evidence_missing" in evaluation.exclusion_reasons:
                        gaps.append(self._gap(
                            run, iteration, EvidenceGapClass.CANDIDATE_COVERAGE,
                            stable_target_id, None, (), True, "candidate_not_covered",
                        ))
                    for outcome in evaluation.constraint_outcomes:
                        if outcome.outcome != "unknown":
                            continue
                        constraint = constraints.get(outcome.constraint_id)
                        if constraint is None or not constraint.required:
                            continue
                        gap_class = EvidenceGapClass.EVIDENCE_STALE if outcome.reason == "stale" else EvidenceGapClass.SOURCE_CONFLICT if outcome.reason == "conflicting" else EvidenceGapClass.REQUIRED_FACT_MISSING
                        reason = "expired_evidence" if gap_class == EvidenceGapClass.EVIDENCE_STALE else "competing_source_observations" if gap_class == EvidenceGapClass.SOURCE_CONFLICT else "missing_required_claim"
                        gaps.append(self._gap(
                            run, iteration, gap_class, stable_target_id,
                            outcome.attribute, outcome.evidence_ids, True, reason,
                            constraint_id=outcome.constraint_id,
                        ))
                # No model or planner claim is copied into this evaluation. Names
                # are used only to form a bounded query for a named gap.
                self._candidate_names = getattr(self, "_candidate_names", {})
                self._candidate_names.update(candidate_names)
            except Exception:  # noqa: BLE001 - fail closed to explicit insufficiency
                decision_state = "research_needed"
                self._candidate_names = getattr(self, "_candidate_names", {})
                for index, candidate in enumerate(run.decision_intent.candidates):
                    target_id = uuid5(run.id, f"candidate:{index}")
                    self._candidate_names[target_id] = candidate.canonical_name
                    gaps.append(self._gap(
                        run, iteration, EvidenceGapClass.CANDIDATE_COVERAGE,
                        target_id, None, (), True, "candidate_not_covered",
                    ))
                    for constraint in run.decision_intent.constraints:
                        if constraint.required:
                            gaps.append(self._gap(
                                run, iteration, EvidenceGapClass.REQUIRED_FACT_MISSING,
                                target_id, constraint.attribute, (), True,
                                "missing_required_claim", constraint_id=constraint.id,
                            ))

        if not gaps and (
            run.decision_intent is None and bool(relevance)
            or run.decision_intent is not None and decision_state == "recommended"
        ):
            sufficient, reason = True, "evidence_covers_question"
        else:
            sufficient = False
            if decision_state is not None:
                reason = "decision_incomplete"
            elif conflicts:
                reason = "conflict_unresolved"
            elif stale_sources and not relevance:
                reason = "stale_only"
            elif not relevance:
                reason = "no_eligible_evidence"
            elif run.decision_intent is not None:
                reason = "candidate_coverage_missing"
            else:
                reason = "conflict_unresolved"
            if not gaps:
                gap_class = EvidenceGapClass.CANDIDATE_COVERAGE if run.decision_intent else EvidenceGapClass.INITIAL_COVERAGE
                gaps.append(self._gap(
                    run, iteration, gap_class, None, None,
                    tuple(item.id for item in relevance), bool(run.decision_intent),
                    "candidate_not_covered" if run.decision_intent else "initial_coverage",
                ))

        assessment = SufficiencyAssessment(
            id=assessment_id,
            run_id=run.id,
            iteration_id=iteration.id,
            sufficient=sufficient,
            gap_ids=tuple(item.id for item in gaps),
            reason_code=reason,
            decision_id=decision_id,
            created_at=now,
        )
        selection = await self._select(session, deadline=monotonic() + max(1, self._remaining_elapsed(run)))
        return assessment, tuple(gaps), selection, decision_state, decision_id

    def _decision_selection(self, session, evidence, now):
        return EvidenceSelection(
            id=uuid4(),
            session_id=session.id,
            owner_id=session.owner_id,
            evidence_ids=tuple(item.id for item in evidence),
            excluded={},
            scores={},
            token_count=0,
            counter_kind="estimated",
            created_at=now,
        )

    def _propose_supported_claims(self, run, evidence):
        """Extract only explicit, unambiguous money literals for user candidates.

        Phase 6 remains the sole verifier: this creates ordinary claim proposals
        with exact evidence IDs and lets its subject/literal/identity policies
        decide whether they become verified claims.
        """
        intent = run.decision_intent
        if intent is None:
            return ()
        price_requested = any(item.attribute == "price" for item in intent.constraints)
        if not price_requested:
            return intent.candidates
        price_scopes = {item.scope for item in intent.constraints if item.attribute == "price"}
        # A single proposal cannot establish which of multiple price scopes a
        # passage refers to. Preserve user claims and fail closed in that case.
        if len(price_scopes) > 1:
            return intent.candidates
        currency_pattern = re.compile(
            r"\b(USD|EUR|GBP|CAD|AUD)\s*\$?\s*(\d[\d,]*(?:\.\d{1,2})?)"
            r"|\$?\s*(\d[\d,]*(?:\.\d{1,2})?)\s*\b(USD|EUR|GBP|CAD|AUD)\b",
            re.IGNORECASE,
        )
        negation = re.compile(r"\b(?:not|no|never|without|free|unavailable|discontinued)\b", re.IGNORECASE)
        result = []
        for candidate in intent.candidates:
            subject = re.compile(r"(?<![\w])" + re.escape(candidate.canonical_name) + r"(?![\w])", re.IGNORECASE)
            values: dict[tuple[str, Decimal], list[UUID]] = {}
            originals: dict[tuple[str, Decimal], str] = {}
            for item in evidence:
                if not subject.search(item.passage):
                    continue
                identifier_values = [
                    value for key, value in candidate.identifiers.items()
                    if key.casefold() != "url"
                ]
                if any(
                    not re.search(r"(?<![\w])" + re.escape(value) + r"(?![\w])", item.passage, re.IGNORECASE)
                    for value in identifier_values
                ):
                    continue
                scoped_constraints = [
                    constraint for constraint in intent.constraints
                    if constraint.attribute == "price" and constraint.scope
                ]
                if scoped_constraints:
                    passage_words = set(re.findall(r"[a-z0-9]+", item.passage.casefold()))
                    if not any(
                        set(re.findall(r"[a-z0-9]+", constraint.scope.casefold())) <= passage_words
                        for constraint in scoped_constraints
                    ):
                        continue
                # If another candidate is named in the same passage, subject
                # attribution is ambiguous and no proposal is made from it.
                other_candidate_named = any(
                    other is not candidate
                    and re.search(r"(?<![\w])" + re.escape(other.canonical_name) + r"(?![\w])", item.passage, re.IGNORECASE)
                    for other in intent.candidates
                )
                if other_candidate_named:
                    continue
                for match in currency_pattern.finditer(item.passage):
                    left_currency, left_amount, right_amount, right_currency = match.groups()
                    currency = (left_currency or right_currency).upper()
                    amount = Decimal((left_amount or right_amount).replace(",", ""))
                    between = item.passage[match.start():match.end()]
                    subject_start = subject.search(item.passage).start()
                    after_subject = item.passage[subject_start:match.start()]
                    local_assertion = after_subject[-100:] + between
                    if (
                        negation.search(local_assertion)
                        or not re.search(r"\b(price|cost|costs|priced|retails?)\b", after_subject, re.IGNORECASE)
                        or any(ord(char) < 32 for char in match.group())
                    ):
                        continue
                    key = (currency, amount)
                    values.setdefault(key, []).append(item.id)
                    originals[key] = match.group().strip()
            # Multiple values or currencies are a conflict. Let the ordinary
            # Phase 6 evaluation report missing/conflicting evidence instead.
            proposals = list(candidate.claims)
            if len(values) == 1:
                (currency, amount), evidence_ids = next(iter(values.items()))
                proposals.append(ClaimProposal(
                    attribute="price",
                    typed_value=MoneyValue(amount=amount, currency=currency),
                    original_value=originals[(currency, amount)],
                    currency=currency,
                    evidence_ids=tuple(sorted(set(evidence_ids), key=str)),
                    scope=next(iter(price_scopes), None),
                ))
            result.append(candidate.model_copy(update={"claims": tuple(proposals)}))
        return tuple(result)

    async def _select(self, session, deadline):
        selection, messages, inference_context = await self._io(
            select_evidence,
            session,
            self.context,
            self.clock(),
            deadline,
            self.reranker,
            clock=self.clock,
            application_context=self.application_context,
            expected_counter_identity=(
                self.llm.identity
                if getattr(self.llm, "requires_inference_context", False)
                else None
            ),
        )
        return selection, messages, inference_context

    def _relevant_evidence(self, question: str, evidence):
        ignored = {"what", "which", "when", "where", "does", "with", "from", "that", "this", "have", "about", "show", "find", "tell", "give", "for", "the", "and", "are", "is", "of", "to", "in", "on", "a", "an", "current"}
        words = {word for word in re.findall(r"[a-z0-9]+", question.casefold()) if len(word) > 1 and word not in ignored}
        if len(words) < 2:
            return ()
        aliases = {
            "schedule": {"schedule", "open", "opens", "opening", "hours", "time", "times"},
            "hours": {"hours", "open", "opens", "opening", "time", "times"},
            "current": {"current", "today", "latest", "updated", "new"},
            "price": {"price", "cost", "costs", "priced", "retails", "usd", "eur", "gbp"},
            "availability": {"available", "availability", "in-stock", "stock"},
        }
        groups = [aliases.get(word, {word}) for word in sorted(words)]
        return tuple(
            item for item in evidence
            if all(group & set(re.findall(r"[a-z0-9]+", item.passage.casefold())) for group in groups)
        )

    def _gap(
        self, run, iteration, gap_class, target_id, attribute, evidence_ids,
        required, reason, *, constraint_id=None,
    ):
        semantic_key = f"{gap_class}:{target_id}:{constraint_id}:{attribute}:"
        assessment_id = uuid5(run.id, f"assessment:{len(run.assessments)}")
        identity = f"{assessment_id}:{semantic_key}"
        return EvidenceGap(
            id=uuid5(run.id, identity),
            run_id=run.id,
            assessment_id=assessment_id,
            iteration_id=iteration.id,
            semantic_key=semantic_key,
            gap_class=gap_class,
            target_id=target_id,
            constraint_id=constraint_id,
            attribute=attribute,
            evidence_ids=tuple(sorted(set(evidence_ids), key=str)),
            required=required,
            status="open",
            reason_code=reason,
        )

    def _merge_gaps(self, run, fresh):
        fresh_keys = {item.semantic_key for item in fresh}
        open_indexes: dict[str, list[int]] = {}
        for index, item in enumerate(run.gaps):
            if item.status == "open":
                open_indexes.setdefault(item.semantic_key, []).append(index)
        old = list(run.gaps)
        for semantic_key, indexes in open_indexes.items():
            if semantic_key not in fresh_keys:
                for index in indexes:
                    old[index] = old[index].model_copy(update={"status": "resolved"})
        seen = set()
        additions = []
        for item in fresh:
            if item.semantic_key in seen:
                continue
            seen.add(item.semantic_key)
            additions.append(item)
        return (*old, *additions)

    def _select_gap(self, gaps):
        open_gaps = [item for item in gaps if item.status == "open" and item.required]
        if not open_gaps:
            open_gaps = [item for item in gaps if item.status == "open"]
        return min(
            open_gaps,
            key=lambda item: (GAP_PRIORITY[item.gap_class], item.semantic_key),
        ) if open_gaps else None

    def _plan_followup(self, run, session, gap):
        request = IterativeResearchRequest(
            question=session.request.question,
            freshness=session.request.freshness,
            idempotency_key=run.idempotency_key,
            decision_intent=run.decision_intent,
        )
        names = getattr(self, "_candidate_names", {})
        if run.decision_intent:
            names.update({
                uuid5(run.id, f"candidate:{index}"): item.canonical_name
                for index, item in enumerate(run.decision_intent.candidates)
            })
        rationale = {
            EvidenceGapClass.REQUIRED_FACT_MISSING: "required_fact_missing",
            EvidenceGapClass.EVIDENCE_STALE: "evidence_stale",
            EvidenceGapClass.SOURCE_CONFLICT: "source_conflict",
            EvidenceGapClass.CANDIDATE_COVERAGE: "candidate_coverage",
            EvidenceGapClass.IDENTITY_AMBIGUITY: "identity_ambiguity",
        }.get(gap.gap_class)
        try:
            proposal = self.planner.propose(request, gap, names, run.budget.allowed_domains)
            if proposal is None:
                return None, rationale or "question"
            proposal = FollowupProposal.model_validate(proposal)
        except (TypeError, ValueError):
            return None, rationale or "question"
        expected_template = {
            EvidenceGapClass.REQUIRED_FACT_MISSING: "required_fact",
            EvidenceGapClass.EVIDENCE_STALE: "current_source",
            EvidenceGapClass.SOURCE_CONFLICT: "independent_confirmation",
            EvidenceGapClass.IDENTITY_AMBIGUITY: "identity_model",
            EvidenceGapClass.CANDIDATE_COVERAGE: "candidate_source",
        }.get(gap.gap_class)
        if (
            expected_template is None
            or proposal.gap_id != gap.id
            or proposal.template != expected_template
            or proposal.target_id != gap.target_id
            or proposal.attribute != gap.attribute
            or proposal.allowed_domains != run.budget.allowed_domains
        ):
            return None, rationale or "question"
        target = names.get(proposal.target_id) if proposal.target_id else None
        qualifier = " ".join(part for part in (target, proposal.attribute) if part)
        if proposal.template == "required_fact":
            qualifier = "required " + (qualifier or "fact")
        elif proposal.template == "current_source":
            qualifier = "current " + (qualifier or "source observation")
        elif proposal.template == "independent_confirmation":
            qualifier = "independent source " + (qualifier or "confirmation")
        elif proposal.template == "identity_model":
            qualifier = "model identifier " + (qualifier or "candidate identity")
        elif proposal.template == "candidate_source":
            qualifier = "candidate source " + (qualifier or "coverage")
        if proposal.target_id is not None and target is None:
            return None, rationale or "question"
        query_parts = (
            session.request.question,
            qualifier,
            " OR ".join(f"site:{domain}" for domain in proposal.allowed_domains),
        )
        query = " ".join(" ".join(query_parts).split())
        if (
            len(query) > 500
            or not set(session.request.question.casefold().split()) <= set(query.casefold().split())
        ):
            return None, rationale or "question"
        return query, rationale

    async def _plan_query(self, run, session, query_text, rationale, gap):
        now = self.clock()
        parent = session.queries[-1].id if session.queries else None
        query_id = uuid5(run.id, f"query:{run.usage.queries + self._pending(run, 'queries')}:{_normalized_query(query_text)}")
        query = SearchQuery(
            id=query_id,
            session_id=session.id,
            owner_id=session.owner_id,
            normalized_query=query_text,
            rationale_code=rationale,
            parent_query_id=parent,
            gap_id=gap.id if rationale != "question" else None,
            sequence=len(session.queries),
            state="planned",
            created_at=now,
        )
        entry = BudgetLedgerEntry(
            id=uuid5(run.id, f"query-ledger:{query.id}"), run_id=run.id,
            iteration_id=run.iterations[-1].id, dimension="queries",
            reserved=Decimal(1), status="reserved",
            idempotency_key=f"query:{query.id}", created_at=now,
        )
        iteration = run.iterations[-1].model_copy(update={
            "state": "planning", "query_ids": (*run.iterations[-1].query_ids, query.id),
        })
        session_candidate = evolve_session(
            session,
            queries=(*session.queries, query),
            updated_at=now,
            revision=session.revision + 1,
        )
        await self._transition(
            run,
            RunState.PLANNING,
            "planning" if not run.usage.queries else "follow_up",
            session=session_candidate,
            updates={
                "ledger": (*run.ledger, entry),
                "iterations": (*run.iterations[:-1], iteration),
            },
            event_payload=self._progress_payload(run, query_count=len(session_candidate.queries), gap_count=len({g.semantic_key for g in run.gaps if g.status == "open"})),
            now=now,
        )

    async def _dispatch_planned(self, run, session):
        if run.lease_owner is None:
            return run, session
        self._authorize_research_context()
        query = self._current_query(run, session)
        if query is None:
            stopped = await self._stop(run, session, StopReason.NO_PRODUCTIVE_QUERY, RunState.INSUFFICIENT)
            return stopped, session
        existing_attempts = [attempt for attempt in session.attempts if attempt.query_id == query.id]
        if any(attempt.status == "completed" for attempt in existing_attempts):
            # The Phase 5 session and run are atomically committed; this branch is
            # defensive and refuses a duplicate provider call.
            iteration = run.iterations[-1].model_copy(update={"state": "assessing"})
            resumed = await self._transition(
                run,
                RunState.ASSESSING,
                "assessing",
                updates={"iterations": (*run.iterations[:-1], iteration)},
            )
            return resumed, session
        if any(
            attempt.status == "started"
            and not any(item.parent_attempt_id == attempt.id for item in existing_attempts)
            for attempt in existing_attempts
        ):
            stopped = await self._stop(run, session, StopReason.SIDE_EFFECT_UNCERTAIN, RunState.INSUFFICIENT, uncertain=True)
            return stopped, session
        attempt_number = 1 + sum(attempt.status == "failed" for attempt in existing_attempts)
        attempt_number = min(attempt_number, run.budget.attempt_limit)
        remaining_sources = min(
            int(run.budget.max_sources - run.usage.sources - self._pending(run, "sources")),
            12 - len(session.observations),
        )
        if remaining_sources <= 0:
            stopped = await self._stop(run, session, StopReason.SOURCE_BUDGET_EXHAUSTED, RunState.INSUFFICIENT)
            return stopped, session
        remaining_elapsed = self._remaining_elapsed(run)
        if remaining_elapsed <= 0:
            stopped = await self._stop(run, session, StopReason.ELAPSED_BUDGET_EXHAUSTED, RunState.INSUFFICIENT)
            return stopped, session
        search_cost = Decimal(0) if self.adapter.name == "fake" else run.budget.search_cost_usd
        if search_cost + self._reserved_or_used(run, "provider_cost_usd") > run.budget.max_provider_cost_usd:
            stopped = await self._stop(run, session, StopReason.PROVIDER_COST_BUDGET_EXHAUSTED, RunState.INSUFFICIENT)
            return stopped, session
        call_elapsed = Decimal(str(min(float(remaining_elapsed), run.budget.provider_timeout_seconds)))
        if call_elapsed <= 0:
            stopped = await self._stop(run, session, StopReason.ELAPSED_BUDGET_EXHAUSTED, RunState.INSUFFICIENT)
            return stopped, session
        source_reserve = min(remaining_sources, 12)
        used_domains = run.usage.allowed_domains + self._pending(run, "allowed_domains")
        domain_reserve = max(0, len(run.budget.allowed_domains) - used_domains)
        now = self.clock()
        entries = []
        if not any(entry.idempotency_key == f"query:{query.id}" for entry in run.ledger):
            query_entry = next((entry for entry in run.ledger if entry.idempotency_key == f"query:{query.id}"), None)
        else:
            query_entry = next(entry for entry in run.ledger if entry.idempotency_key == f"query:{query.id}")
        usage = run.usage
        ledger = list(run.ledger)
        if query_entry and query_entry.status == "reserved":
            ledger = self._settle(ledger, query_entry.idempotency_key, Decimal(1))
            usage = usage.model_copy(update={"queries": usage.queries + 1})
        prefix = f"attempt:{query.id}:{attempt_number}"
        for dimension, reserve in (
            ("sources", Decimal(source_reserve)),
            ("provider_cost_usd", search_cost),
            ("allowed_domains", Decimal(domain_reserve)),
        ):
            entries.append(BudgetLedgerEntry(
                id=uuid5(run.id, f"{prefix}:{dimension}"),
                run_id=run.id,
                iteration_id=run.iterations[-1].id,
                dimension=dimension,
                reserved=reserve,
                status="reserved",
                idempotency_key=f"{prefix}:{dimension}",
                created_at=now,
            ))
        ledger.extend(entries)
        started = AdapterAttempt(
            id=uuid5(run.id, f"{prefix}:started"),
            session_id=session.id,
            query_id=query.id,
            owner_id=self.owner_id,
            adapter=self.adapter.name,
            idempotency_key=f"{run.id}:{query.id}:{attempt_number}:started",
            attempt_number=attempt_number,
            status="started",
            started_at=now,
        )
        session_candidate = evolve_session(
            session,
            attempts=(*session.attempts, started),
            updated_at=now,
            revision=session.revision + 1,
        )
        iteration = run.iterations[-1].model_copy(update={"state": "searching"})
        run = await self._transition(
            run,
            RunState.SEARCHING,
            "searching",
            session=session_candidate,
            updates={
                "usage": usage,
                "ledger": tuple(ledger),
                "iterations": (*run.iterations[:-1], iteration),
            },
            event_payload=self._progress_payload(run, query_count=len(session_candidate.queries)),
            now=now,
        )
        self._assert_lease(run, run.lease_owner)
        call_start = self.duration_clock()
        error = None
        try:
            timeout_seconds = max(0.001, float(call_elapsed))
            async with asyncio.timeout(timeout_seconds):
                with bind_usage_task(
                    "iterative_research_search", run_id=str(run.id)
                ):
                    fetched = await self.adapter.search(query.normalized_query, source_reserve)
            if not isinstance(fetched, (tuple, list)) or len(fetched) > source_reserve:
                raise ResearchError("search_invalid_response")
            if any(not isinstance(item, SearchResult) for item in fetched):
                raise ResearchError("search_invalid_response")
        except asyncio.CancelledError:
            raise
        except Exception as caught:  # noqa: BLE001 - only safe codes are persisted
            error = caught
            fetched = ()
        duration = Decimal(str(min(float(call_elapsed), max(0.0, self.duration_clock() - call_start))))
        # The started attempt and every reservation are durable before the
        # adapter call. A cancelled/stale writer cannot commit a late result.
        current_run = await self.get(run.id)
        if current_run.state == RunState.CANCELLED:
            return current_run, await self._io(self.runs.session, self.owner_id, run.session_id)
        self._assert_lease(current_run, run.lease_owner)
        if error is not None:
            return await self._complete_attempt_error(
                current_run, session_candidate, query, started, error,
                duration, attempt_number, prefix,
            )
        run = await self._transition(
            current_run,
            RunState.EXTRACTING,
            "extracting",
            updates={
                "iterations": (
                    *current_run.iterations[:-1],
                    current_run.iterations[-1].model_copy(update={"state": "extracting"}),
                ),
            },
            event_payload=self._progress_payload(current_run),
        )
        terminal_attempt = AdapterAttempt(
            id=uuid5(run.id, f"{prefix}:result"),
            session_id=session.id,
            query_id=query.id,
            owner_id=self.owner_id,
            adapter=self.adapter.name,
            idempotency_key=f"{run.id}:{query.id}:{attempt_number}:result",
            attempt_number=attempt_number,
            status="completed",
            parent_attempt_id=started.id,
            started_at=started.started_at,
            completed_at=self.clock(),
        )
        scoped = tuple(
            item for item in fetched
            if _host_allowed(item.url, run.budget.allowed_domains)
        )
        observations, evidence = extract_evidence(
            session_candidate,
            tuple((query.id, item) for item in scoped),
            {query.id: terminal_attempt},
            self.extractor,
            self.clock(),
            self.settings,
        )
        completed_query = query.model_copy(update={"state": "completed", "executed_at": self.clock()})
        queries = tuple(completed_query if item.id == query.id else item for item in session_candidate.queries)
        final_session = evolve_session(
            session_candidate,
            queries=queries,
            attempts=(*session_candidate.attempts, terminal_attempt),
            observations=(*session_candidate.observations, *observations),
            evidence=(*session_candidate.evidence, *evidence),
            updated_at=self.clock(),
            revision=session_candidate.revision + 1,
        )
        all_hosts = {
            host for host in (
                urlsplit(canonical_url(item.url)).hostname
                for item in fetched
                if _host_allowed(item.url, run.budget.allowed_domains)
            ) if host
        }
        prior_hosts = {
            urlsplit(source.canonical_url).hostname
            for source in session.observations
            if _host_allowed(source.canonical_url, run.budget.allowed_domains)
        }
        new_domains = Decimal(len(all_hosts - prior_hosts))
        source_total = Decimal(len(fetched))
        used = run.usage.model_copy(update={
            "sources": run.usage.sources + int(source_total),
            "provider_cost_usd": run.usage.provider_cost_usd + search_cost,
            "elapsed_seconds": run.usage.elapsed_seconds,
            "allowed_domains": run.usage.allowed_domains + int(new_domains),
        })
        settled_ledger = list(run.ledger)
        settled_ledger = self._settle(settled_ledger, f"{prefix}:sources", source_total)
        settled_ledger = self._settle(settled_ledger, f"{prefix}:provider_cost_usd", search_cost)
        settled_ledger = self._settle(settled_ledger, f"{prefix}:allowed_domains", new_domains)
        iteration = run.iterations[-1].model_copy(update={"state": "assessing"})
        run = await self._transition(
            run,
            RunState.ASSESSING,
            "assessing",
            session=final_session,
            updates={
                "usage": used,
                "ledger": tuple(settled_ledger),
                "iterations": (*run.iterations[:-1], iteration),
            },
            event_payload=self._progress_payload(
                run,
                source_count=len(final_session.observations),
                evidence_count=len(final_session.evidence),
            ),
        )
        return run, final_session

    async def _complete_attempt_error(
        self, run, session, query, started, error, duration, attempt_number, prefix,
    ):
        code = getattr(error, "code", "search_failed")
        if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,80}", code):
            code = "search_failed"
        error_code = code if code in {
            "search_quota", "search_timeout", "search_unavailable", "search_rejected",
            "search_invalid_response", "search_response_oversized", "research_configuration_invalid",
        } else "search_failed"
        terminal_attempt = AdapterAttempt(
            id=uuid5(run.id, f"{prefix}:result"),
            session_id=session.id,
            query_id=query.id,
            owner_id=self.owner_id,
            adapter=self.adapter.name,
            idempotency_key=f"{run.id}:{query.id}:{attempt_number}:result",
            attempt_number=attempt_number,
            status="failed",
            parent_attempt_id=started.id,
            started_at=started.started_at,
            completed_at=self.clock(),
            error_code=error_code,
        )
        retryable = bool(getattr(error, "retryable", False)) and attempt_number < run.budget.attempt_limit
        failed_query = query.model_copy(update={
            "state": "planned" if retryable else "failed",
            "executed_at": None if retryable else self.clock(),
        })
        queries = tuple(failed_query if item.id == query.id else item for item in session.queries)
        final_session = evolve_session(
            session,
            queries=queries,
            attempts=(*session.attempts, terminal_attempt),
            updated_at=self.clock(),
            revision=session.revision + 1,
        )
        used = run.usage.model_copy(update={
            "provider_cost_usd": run.usage.provider_cost_usd + (Decimal(0) if self.adapter.name == "fake" else run.budget.search_cost_usd),
            "elapsed_seconds": run.usage.elapsed_seconds,
        })
        ledger = list(run.ledger)
        ledger = self._settle(ledger, f"{prefix}:sources", Decimal(0))
        cost = Decimal(0) if self.adapter.name == "fake" else run.budget.search_cost_usd
        ledger = self._settle(ledger, f"{prefix}:provider_cost_usd", cost)
        ledger = self._settle(ledger, f"{prefix}:allowed_domains", Decimal(0))
        if retryable:
            run = await self._transition(
                run,
                RunState.SEARCHING,
                "searching",
                session=final_session,
                updates={"usage": used, "ledger": tuple(ledger)},
                event_payload=self._progress_payload(run),
            )
            return await self._dispatch_planned(run, final_session)
        iteration = run.iterations[-1].model_copy(update={"state": "assessing"})
        run = await self._transition(
            run,
            RunState.ASSESSING,
            "assessing",
            session=final_session,
            updates={
                "usage": used,
                "ledger": tuple(ledger),
                "iterations": (*run.iterations[:-1], iteration),
            },
        )
        assessment, gaps, selection, decision_state, decision_id = await self._assess(run, final_session)
        run = await self._transition(
            run,
            RunState.ASSESSING,
            "assessing",
            updates={
                "assessments": (*run.assessments, assessment),
                "gaps": self._merge_gaps(run, gaps),
                "decision_state": decision_state,
                "decision_ids": (
                    (*run.decision_ids, decision_id)
                    if decision_id is not None and decision_id not in run.decision_ids
                    else run.decision_ids
                ),
                "iterations": (*run.iterations[:-1], run.iterations[-1].model_copy(
                    update={"assessment_id": assessment.id, "budget_after": run.usage}
                )),
            },
            event_payload=self._progress_payload(run, gap_count=len(gaps)),
        )
        if selection[0].evidence_ids:
            await self._finish(run, final_session, selection, StopReason.PROVIDER_ERROR, False)
            return await self.get(run.id), final_session
        stopped = await self._stop(
            run, final_session, StopReason.PROVIDER_ERROR, RunState.FAILED,
            session_state="failed",
        )
        return stopped, final_session

    async def _finish(self, run, session, selection_data, stop_reason, sufficient):
        self._assert_lease(run, run.lease_owner)
        if selection_data is None:
            remaining = self._remaining_elapsed(run)
            if remaining <= 0:
                await self._stop(run, session, StopReason.ELAPSED_BUDGET_EXHAUSTED, RunState.INSUFFICIENT)
                return
            selection, messages, inference_context = await self._select(
                session,
                deadline=monotonic() + remaining,
            )
        else:
            selection, messages, inference_context = selection_data
        try:
            self._assert_lease(run, run.lease_owner)
        except ResearchError:
            await self._stop(run, session, StopReason.ELAPSED_BUDGET_EXHAUSTED, RunState.INSUFFICIENT)
            return
        if not selection.evidence_ids or any(reason == "budget" for reason in selection.excluded.values()):
            await self._stop(
                run, session,
                StopReason.TOKEN_BUDGET_EXHAUSTED if any(reason == "budget" for reason in selection.excluded.values()) else stop_reason,
                RunState.INSUFFICIENT,
                session_state="insufficient",
            )
            return
        token_entry = next(
            (entry for entry in run.ledger if entry.idempotency_key == "reserve:synthesis:tokens"),
            None,
        )
        if token_entry is None or token_entry.status != "reserved":
            await self._stop(run, session, StopReason.TOKEN_BUDGET_EXHAUSTED, RunState.INSUFFICIENT)
            return
        other_reserved_tokens = self._pending(run, "tokens") - token_entry.reserved
        token_capacity = run.budget.max_tokens - run.usage.tokens - other_reserved_tokens
        output_tokens = min(
            run.budget.synthesis_output_tokens,
            int(token_capacity - selection.token_count),
        )
        if selection.token_count <= 0 or output_tokens <= 0:
            await self._stop(
                run, session, StopReason.TOKEN_BUDGET_EXHAUSTED,
                RunState.INSUFFICIENT, session_state="insufficient",
            )
            return
        synthesis_token_reservation = Decimal(selection.token_count + output_tokens)
        if self._remaining_elapsed(run) <= 0:
            await self._stop(run, session, StopReason.ELAPSED_BUDGET_EXHAUSTED, RunState.INSUFFICIENT)
            return
        ledger = tuple(
            entry.model_copy(update={"reserved": max(entry.reserved, synthesis_token_reservation)})
            if entry.idempotency_key == token_entry.idempotency_key
            else entry
            for entry in run.ledger
        )
        iteration = run.iterations[-1].model_copy(update={"state": "synthesizing"}) if run.iterations else None
        run = await self._transition(
            run,
            RunState.SYNTHESIZING,
            "synthesizing",
            updates={
                "iterations": (*run.iterations[:-1], iteration) if iteration else run.iterations,
                "ledger": ledger,
            },
            event_payload=self._progress_payload(
                run, evidence_count=len(selection.evidence_ids),
            ),
        )
        response = ""
        iterator = None
        try:
            synth_timeout = min(
                run.budget.provider_timeout_seconds,
                run.budget.synthesis_reserve_seconds,
                self._remaining_elapsed(run),
            )
            bounded_stream = getattr(self.llm, "stream_bounded", None)
            iterator = (
                bounded_stream(
                    messages,
                    max_output_tokens=output_tokens,
                    timeout_seconds=synth_timeout,
                    inference_context=inference_context,
                )
                if bounded_stream
                else self.llm.stream(messages, inference_context=inference_context)
            )
            async with asyncio.timeout(synth_timeout):
                with bind_usage_task(
                    "iterative_research_synthesis", run_id=str(run.id)
                ):
                    async for delta in iterator:
                        if not isinstance(delta, str) or len(response) + len(delta) > min(20000, output_tokens * 4):
                            raise ResearchError("synthesis_oversized")
                        response += delta
            self._assert_lease(run, run.lease_owner)
            answer, citations = validate_synthesis(
                session.model_copy(update={"selection": selection}), response
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - retain evidence but withhold unsupported output
            expired = self._remaining_elapsed(run) <= 0
            await self._stop(
                run, session,
                StopReason.ELAPSED_BUDGET_EXHAUSTED if expired else StopReason.SYNTHESIS_ERROR,
                RunState.INSUFFICIENT,
                session_state="insufficient", uncertain=True,
            )
            return
        finally:
            if iterator is not None:
                close = getattr(iterator, "aclose", None)
                if close is not None:
                    with anyio.CancelScope(shield=True):
                        with anyio.move_on_after(1):
                            try:
                                await close()
                            except (Exception, asyncio.CancelledError):  # noqa: BLE001
                                logger.info("Iterative synthesis stream cleanup failed")
            log_generation_attribution(
                logger,
                "iterative_research_synthesis",
                getattr(iterator, "metadata", None),
                fallback_identity=getattr(self.llm, "identity", None),
            )
        if any(citation.expires_at <= self.clock() for citation in citations):
            await self._stop(run, session, StopReason.EVIDENCE_INSUFFICIENT, RunState.INSUFFICIENT)
            return
        now = self.clock()
        final_state = RunState.COMPLETED if sufficient else RunState.INSUFFICIENT
        final_reason = StopReason.SUFFICIENT if sufficient else stop_reason
        session_state = "completed"
        expiry = min(citation.expires_at for citation in citations)
        final_session = evolve_session(
            session,
            state=session_state,
            selection=selection,
            answer=answer,
            citations=citations,
            expires_at=expiry,
            failure_code=None if sufficient else "iterative_research_incomplete",
            updated_at=now,
            revision=session.revision + 1,
        )
        ledger = list(run.ledger)
        token_key, cost_key = "reserve:synthesis:tokens", "reserve:synthesis:cost"
        ledger = self._settle(ledger, token_key, synthesis_token_reservation)
        synthesis_cost = run.budget.synthesis_reserve_cost_usd
        ledger = self._settle(ledger, cost_key, synthesis_cost)
        wall_elapsed = Decimal(str(max(0.0, (now - run.created_at).total_seconds())))
        ledger = self._settle(ledger, "reserve:run:elapsed", wall_elapsed)
        used = run.usage.model_copy(update={
            "tokens": run.usage.tokens + int(synthesis_token_reservation),
            "provider_cost_usd": run.usage.provider_cost_usd + synthesis_cost,
            "elapsed_seconds": wall_elapsed,
        })
        closed = run.iterations[-1].model_copy(update={
            "state": "completed" if sufficient else "incomplete",
            "completed_at": now,
            "budget_after": used,
        }) if run.iterations else None
        await self._transition(
            run,
            final_state,
            "completed" if sufficient else "incomplete",
            session=final_session,
            updates={
                "terminal_reason": final_reason,
                "lease_owner": None,
                "lease_expires_at": None,
                "usage": used,
                "ledger": tuple(ledger),
                "iterations": (*run.iterations[:-1], closed) if closed else run.iterations,
            },
            event_payload=self._progress_payload(
                run,
                stop_reason=final_reason,
                citation_count=len(citations),
                evidence_count=len(selection.evidence_ids),
            ),
            now=now,
        )

    async def _stop(
        self, run, session, reason, state, *, session_state="insufficient",
        uncertain=False, usage=None, ledger=None, updates=None,
    ):
        now = self.clock()
        ledger_values, new_usage = self._settle_pending_for_stop(run, uncertain=uncertain)
        if ledger is not None:
            merged = {entry.idempotency_key: entry for entry in ledger_values}
            for entry in ledger:
                merged[entry.idempotency_key] = entry
            ledger_values = list(merged.values())
            totals = Counter()
            for entry in ledger_values:
                totals[entry.dimension] += entry.settled or Decimal(0)
            new_usage = (usage or run.usage).model_copy(update={
                "iterations": int(totals["iterations"]),
                "queries": int(totals["queries"]),
                "sources": int(totals["sources"]),
                "tokens": int(totals["tokens"]),
                "provider_cost_usd": totals["provider_cost_usd"],
                "elapsed_seconds": totals["elapsed_seconds"],
                "allowed_domains": int(totals["allowed_domains"]),
            })
        if session is not None and session.state in {"pending", "running"}:
            if session.iterative_run_id != run.id:
                raise ResearchError("research_conflict", 409)
            session = evolve_session(
                session,
                state=session_state,
                failure_code=reason.value,
                answer=None,
                citations=(),
                updated_at=now,
                revision=session.revision + 1,
            )
        else:
            session = None
        iteration_updates = run.iterations
        if iteration_updates and iteration_updates[-1].state not in {"completed", "incomplete", "cancelled"}:
            last = iteration_updates[-1].model_copy(update={
                "state": "incomplete", "completed_at": now,
                "budget_after": new_usage,
            })
            iteration_updates = (*iteration_updates[:-1], last)
        return await self._transition(
            run,
            state,
            "incomplete" if state == RunState.INSUFFICIENT else "failed" if state == RunState.FAILED else "cancelled",
            session=session,
            updates={
                "terminal_reason": reason,
                "lease_owner": None,
                "lease_expires_at": None,
                "usage": new_usage,
                "ledger": tuple(ledger_values),
                "iterations": iteration_updates,
                **(updates or {}),
            },
            event_payload=self._progress_payload(run, stop_reason=reason),
            now=now,
            allow_expired_lease=state in TERMINAL_STATES,
        )

    async def _transition(
        self, run, state, event_type, *, session=None, updates=None,
        event_payload=None, now=None, allow_expired_lease=False,
    ):
        now = now or self.clock()
        deadline = run.created_at + timedelta(seconds=run.budget.max_elapsed_seconds)
        if state not in TERMINAL_STATES and now >= deadline:
            raise ResearchError("research_elapsed_budget_exhausted", 409)
        values = run.model_dump()
        values.update(updates or {})
        payload = event_payload or self._progress_payload(run)
        event = RunEvent(
            id=uuid4(),
            run_id=run.id,
            sequence=len(run.events),
            event_type=event_type,
            idempotency_key=f"transition:{run.revision + 1}:{event_type}",
            safe_payload=payload.model_copy(update={"state": state}),
            occurred_at=now,
        )
        values.update({
            "state": state,
            "updated_at": now,
            "revision": run.revision + 1,
            "events": (*run.events, event),
        })
        if state in TERMINAL_STATES:
            values["lease_owner"] = None
            values["lease_expires_at"] = None
        elif run.lease_owner is not None:
            values["lease_expires_at"] = min(
                deadline,
                now + timedelta(seconds=max(30, run.budget.provider_timeout_seconds + 5)),
            )
        candidate = ResearchRun.model_validate(values)
        committed = await self._io(
            self.runs.commit, self.owner_id, candidate, session,
            now=now, allow_expired_lease=allow_expired_lease,
        )
        for queue in self._listeners.get(run.id, ()):
            queue.put_nowait(committed.events[-1])
        return committed

    def _progress_payload(self, run, **changes):
        values = {
            "iteration": max(0, run.current_iteration - 1),
            "query_count": run.usage.queries,
            "source_count": run.usage.sources,
            "evidence_count": 0,
            "gap_count": len({item.semantic_key for item in run.gaps if item.status == "open"}),
            "decision_state": run.decision_state,
        }
        values.update(changes)
        return SafeEventPayload(**values)

    def _current_query(self, run, session):
        if not session.queries:
            return None
        current_ids = set(run.iterations[-1].query_ids) if run.iterations else set()
        candidates = [query for query in session.queries if query.id in current_ids]
        return candidates[-1] if candidates else None

    def _pending(self, run, dimension):
        return sum(
            (entry.reserved for entry in run.ledger if entry.dimension == dimension and entry.status == "reserved"),
            Decimal(0),
        )

    def _reserved_or_used(self, run, dimension):
        return sum(
            (entry.settled if entry.settled is not None else entry.reserved for entry in run.ledger if entry.dimension == dimension),
            Decimal(0),
        )

    def _remaining_elapsed(self, run):
        wall_used = max(0.0, (self.clock() - run.created_at).total_seconds())
        reserved_synthesis = (
            0 if run.state == RunState.SYNTHESIZING
            else run.budget.synthesis_reserve_seconds
        )
        return max(0.0, run.budget.max_elapsed_seconds - wall_used - reserved_synthesis)

    def _settle_pending_for_stop(self, run, *, uncertain):
        new_ledger = []
        totals = Counter()
        for entry in run.ledger:
            if entry.status != "reserved":
                new_ledger.append(entry)
                if entry.settled is not None:
                    totals[entry.dimension] += entry.settled
                continue
            if entry.idempotency_key == "reserve:run:elapsed":
                settled = Decimal(str(max(0.0, (self.clock() - run.created_at).total_seconds())))
                updated = entry.model_copy(update={"settled": settled, "status": "settled"})
                new_ledger.append(updated)
                totals[entry.dimension] += settled
                continue
            affected = uncertain and (
                entry.idempotency_key.startswith("attempt:")
                and run.state in {RunState.SEARCHING, RunState.EXTRACTING}
                or entry.idempotency_key.startswith("reserve:synthesis:")
                and run.state == RunState.SYNTHESIZING
            )
            if affected:
                settled, status = entry.reserved, "uncertain"
            else:
                settled, status = Decimal(0), "released"
            updated = entry.model_copy(update={"settled": settled, "status": status})
            new_ledger.append(updated)
            totals[entry.dimension] += settled
        usage = run.usage.model_copy(update={
            "iterations": int(totals["iterations"]),
            "queries": int(totals["queries"]),
            "sources": int(totals["sources"]),
            "tokens": int(totals["tokens"]),
            "provider_cost_usd": totals["provider_cost_usd"],
            "elapsed_seconds": totals["elapsed_seconds"],
            "allowed_domains": int(totals["allowed_domains"]),
        })
        return new_ledger, usage

    def _settle(self, ledger, idempotency_key, settled):
        result = []
        matched = False
        for entry in ledger:
            if entry.idempotency_key != idempotency_key:
                result.append(entry)
                continue
            if entry.status != "reserved" or matched:
                raise ResearchError("research_conflict", 409)
            matched = True
            status = "settled" if settled else "released"
            result.append(entry.model_copy(update={"settled": settled, "status": status}))
        if not matched:
            raise ResearchError("research_conflict", 409)
        return result

    def _assert_lease(self, run, token):
        now = self.clock()
        deadline = run.created_at + timedelta(seconds=run.budget.max_elapsed_seconds)
        if (
            run.state in TERMINAL_STATES or token is None or run.lease_owner != token
            or run.lease_expires_at is None or run.lease_expires_at <= now
            or deadline <= now
        ):
            raise ResearchError("research_conflict", 409)

    async def _io(self, function, *args, **kwargs):
        return await io_call(function, *args, **kwargs)

    def _authorize_research_context(self):
        if self.application_context is None:
            raise ContextPreparationError("application_context_required")
        authorize_base_disclosure(self.application_context)
        require_matching_endpoint(self.llm, self.context.counter)
        authorize_context_selection(
            self.application_context,
            ContextSelection(
                provider_id="external_research",
                operation="search",
                fields=("evidence_record",),
            ),
        )
