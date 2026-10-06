"""Versioned contracts for bounded, persisted Phase 8 research runs."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from personal_ai.agents.research.contracts import ResearchRecord
from personal_ai.decisions.contracts import Candidate, Constraint, Preference
from personal_ai.evidence.contracts import ScopedResearchRecord

POLICY_VERSION = "iterative-research-policy-v1"
BUDGET_VERSION = "evidence-quality-budget-v1"


class DecisionIntent(ResearchRecord):
    """User-authored candidates and hard constraints; never accepts model facts."""

    candidates: tuple[Candidate, ...] = Field(min_length=1, max_length=12)
    constraints: tuple[Constraint, ...] = Field(default=(), max_length=30)
    preferences: tuple[Preference, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def user_inputs_only(self):
        if any(candidate.claims for candidate in self.candidates):
            raise ValueError("iterative candidate facts must be evaluated from evidence")
        if any(item.source != "user" for item in self.constraints):
            raise ValueError("iterative constraints must come from the user")
        if len({item.id for item in self.constraints}) != len(self.constraints):
            raise ValueError("duplicate iterative constraint")
        # One assessor gap can be emitted per candidate/constraint pair.
        if len(self.candidates) * len(self.constraints) > 30:
            raise ValueError("too many candidate/constraint combinations")
        return self


class IterativeResearchRequest(ResearchRecord):
    schema_version: Literal["iterative-research-request-v1"] = "iterative-research-request-v1"
    question: str = Field(min_length=1, max_length=500)
    freshness: Literal["general", "current"] = "general"
    idempotency_key: UUID
    decision_intent: DecisionIntent | None = None

    @model_validator(mode="after")
    def normalize_question(self):
        normalized = " ".join(self.question.split())
        if not normalized or any(ord(character) < 32 for character in normalized):
            raise ValueError("invalid question")
        object.__setattr__(self, "question", normalized)
        return self

    def fingerprint(self) -> str:
        import json
        from hashlib import sha256

        payload = self.model_dump(mode="json", exclude={"idempotency_key"})
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class RunState(StrEnum):
    PENDING = "pending"
    ASSESSING = "assessing"
    PLANNING = "planning"
    SEARCHING = "searching"
    EXTRACTING = "extracting"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    INSUFFICIENT = "insufficient"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StopReason(StrEnum):
    SUFFICIENT = "sufficient"
    ITERATION_BUDGET_EXHAUSTED = "iteration_budget_exhausted"
    QUERY_BUDGET_EXHAUSTED = "query_budget_exhausted"
    SOURCE_BUDGET_EXHAUSTED = "source_budget_exhausted"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    PROVIDER_COST_BUDGET_EXHAUSTED = "provider_cost_budget_exhausted"
    ELAPSED_BUDGET_EXHAUSTED = "elapsed_budget_exhausted"
    NO_PRODUCTIVE_QUERY = "no_productive_query"
    PROVIDER_ERROR = "provider_error"
    SYNTHESIS_ERROR = "synthesis_error"
    SIDE_EFFECT_UNCERTAIN = "side_effect_uncertain"
    CANCELLED = "cancelled"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"


class EvidenceGapClass(StrEnum):
    INITIAL_COVERAGE = "initial_coverage"
    REQUIRED_FACT_MISSING = "required_fact_missing"
    EVIDENCE_STALE = "evidence_stale"
    SOURCE_CONFLICT = "source_conflict"
    CANDIDATE_COVERAGE = "candidate_coverage"
    IDENTITY_AMBIGUITY = "identity_ambiguity"
    CITATION_SUPPORT = "citation_support"


class BudgetSnapshot(ScopedResearchRecord):
    schema_version: Literal["evidence-quality-budget-v1"] = BUDGET_VERSION
    max_iterations: int = Field(ge=1, le=5)
    max_queries: int = Field(ge=1, le=3)
    max_sources: int = Field(ge=1, le=12)
    max_elapsed_seconds: int = Field(ge=1, le=300)
    max_tokens: int = Field(ge=512, le=32768)
    max_provider_cost_usd: Decimal = Field(ge=0, le=Decimal("1.00"))
    allowed_domains: tuple[str, ...] = Field(min_length=1, max_length=12)
    synthesis_reserve_tokens: int = Field(ge=128, le=8192)
    synthesis_reserve_seconds: int = Field(ge=1, le=60)
    synthesis_reserve_cost_usd: Decimal = Field(ge=0, le=Decimal("0.10"))
    search_cost_usd: Decimal = Field(default=Decimal("0.005"), ge=0, le=Decimal("0.10"))
    provider_timeout_seconds: int = Field(default=10, ge=1, le=60)
    attempt_limit: int = Field(default=2, ge=1, le=3)
    synthesis_output_tokens: int = Field(default=4096, ge=128, le=8192)

    @model_validator(mode="after")
    def valid_domains_and_reserve(self):
        import re

        normalized = tuple(domain.lower().rstrip(".") for domain in self.allowed_domains)
        if normalized != self.allowed_domains or len(set(normalized)) != len(normalized):
            raise ValueError("invalid iterative research domains")
        if any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", domain)
            or "." not in domain
            or ".." in domain
            for domain in normalized
        ):
            raise ValueError("invalid iterative research domains")
        if self.synthesis_reserve_tokens > self.max_tokens:
            raise ValueError("synthesis reserve exceeds token budget")
        if self.synthesis_reserve_seconds > self.max_elapsed_seconds:
            raise ValueError("synthesis reserve exceeds elapsed budget")
        if self.synthesis_reserve_cost_usd > self.max_provider_cost_usd:
            raise ValueError("synthesis reserve exceeds cost budget")
        if self.synthesis_output_tokens > self.synthesis_reserve_tokens:
            raise ValueError("synthesis output reserve exceeds synthesis token reserve")
        return self


class BudgetUsage(ScopedResearchRecord):
    iterations: int = Field(default=0, ge=0)
    queries: int = Field(default=0, ge=0)
    sources: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    provider_cost_usd: Decimal = Field(default=Decimal(0), ge=0)
    elapsed_seconds: Decimal = Field(default=Decimal(0), ge=0)
    allowed_domains: int = Field(default=0, ge=0)


class BudgetLedgerEntry(ScopedResearchRecord):
    id: UUID
    run_id: UUID
    iteration_id: UUID | None = None
    dimension: Literal[
        "iterations", "queries", "sources", "tokens", "provider_cost_usd",
        "elapsed_seconds", "allowed_domains",
    ]
    reserved: Decimal = Field(ge=0)
    settled: Decimal | None = Field(default=None, ge=0)
    status: Literal["reserved", "settled", "released", "uncertain"]
    idempotency_key: str = Field(min_length=1, max_length=180)
    created_at: datetime

    @model_validator(mode="after")
    def settlement_matches_status(self):
        if (self.status == "reserved") != (self.settled is None):
            raise ValueError("invalid budget ledger settlement")
        if (
            self.settled is not None and self.settled > self.reserved
            and self.dimension != "elapsed_seconds"
        ):
            raise ValueError("settlement exceeds reservation")
        if self.status == "uncertain" and self.settled != self.reserved:
            raise ValueError("uncertain work must settle its full reservation")
        if self.status == "released" and self.settled != 0:
            raise ValueError("released work must settle zero")
        return self


class IterationRecord(ScopedResearchRecord):
    id: UUID
    run_id: UUID
    sequence: int = Field(ge=0, le=4)
    state: Literal["assessing", "planning", "searching", "extracting", "synthesizing", "completed", "incomplete", "cancelled"]
    input_evidence_snapshot_id: UUID
    assessment_id: UUID | None = None
    query_ids: tuple[UUID, ...] = Field(default=(), max_length=3)
    budget_before: BudgetUsage
    budget_after: BudgetUsage
    started_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def terminal_time(self):
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("iteration completed before it started")
        if self.state in {"completed", "incomplete", "cancelled"} and self.completed_at is None:
            raise ValueError("terminal iteration requires completion time")
        return self


class EvidenceGap(ScopedResearchRecord):
    id: UUID
    run_id: UUID
    assessment_id: UUID
    iteration_id: UUID
    semantic_key: str = Field(min_length=1, max_length=300)
    gap_class: EvidenceGapClass
    target_id: UUID | None = None
    constraint_id: UUID | None = None
    attribute: str | None = Field(default=None, max_length=100)
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=12)
    required: bool
    status: Literal["open", "resolved", "unresolvable"]
    reason_code: Literal[
        "initial_coverage", "missing_required_claim", "expired_evidence",
        "competing_source_observations", "candidate_not_covered", "identity_review",
        "citation_unavailable", "unsupported_query_template",
    ]


class FollowupProposal(ScopedResearchRecord):
    """A constrained template recommendation; it never carries planner text."""

    schema_version: Literal["iterative-followup-v1"] = "iterative-followup-v1"
    gap_id: UUID
    template: Literal[
        "required_fact", "current_source", "independent_confirmation",
        "identity_model", "candidate_source",
    ]
    target_id: UUID | None = None
    attribute: str | None = Field(default=None, max_length=100)
    allowed_domains: tuple[str, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def valid_domain_policy(self):
        import re

        normalized = tuple(domain.lower().rstrip(".") for domain in self.allowed_domains)
        if normalized != self.allowed_domains or len(set(normalized)) != len(normalized):
            raise ValueError("invalid follow-up domains")
        if any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", domain)
            or "." not in domain or ".." in domain
            for domain in normalized
        ):
            raise ValueError("invalid follow-up domains")
        return self


class SufficiencyAssessment(ScopedResearchRecord):
    id: UUID
    run_id: UUID
    iteration_id: UUID
    sufficient: bool
    gap_ids: tuple[UUID, ...] = Field(default=(), max_length=512)
    reason_code: Literal[
        "evidence_covers_question", "required_fact_missing", "stale_only",
        "conflict_unresolved", "candidate_coverage_missing", "identity_ambiguous",
        "no_eligible_evidence", "decision_incomplete",
    ]
    decision_id: UUID | None = None
    created_at: datetime


class SafeEventPayload(ScopedResearchRecord):
    iteration: int | None = Field(default=None, ge=0, le=4)
    query_count: int | None = Field(default=None, ge=0, le=3)
    source_count: int | None = Field(default=None, ge=0, le=12)
    evidence_count: int | None = Field(default=None, ge=0, le=12)
    gap_count: int | None = Field(default=None, ge=0, le=160)
    citation_count: int | None = Field(default=None, ge=0, le=144)
    stop_reason: StopReason | None = None
    state: RunState | None = None
    decision_state: Literal[
        "recommended", "eligible_unranked", "research_needed", "no_verified_match",
    ] | None = None


class RunEvent(ScopedResearchRecord):
    id: UUID
    run_id: UUID
    sequence: int = Field(ge=0, le=127)
    event_type: Literal[
        "planning", "searching", "extracting", "assessing", "follow_up",
        "synthesizing", "completed", "incomplete", "cancelled", "failed",
    ]
    idempotency_key: str = Field(min_length=1, max_length=180)
    safe_payload: SafeEventPayload
    occurred_at: datetime


class ResearchRun(ScopedResearchRecord):
    schema_version: Literal["iterative-research-v1"] = "iterative-research-v1"
    id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    session_id: UUID
    state: RunState
    policy_version: Literal["iterative-research-policy-v1"] = POLICY_VERSION
    budget_version: Literal["evidence-quality-budget-v1"] = BUDGET_VERSION
    idempotency_key: UUID
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    budget: BudgetSnapshot
    decision_intent: DecisionIntent | None = None
    current_iteration: int = Field(default=0, ge=0, le=5)
    lease_owner: UUID | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    terminal_reason: StopReason | None = None
    decision_state: Literal[
        "recommended", "eligible_unranked", "research_needed", "no_verified_match",
    ] | None = None
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    iterations: tuple[IterationRecord, ...] = Field(default=(), max_length=5)
    assessments: tuple[SufficiencyAssessment, ...] = Field(default=(), max_length=6)
    gaps: tuple[EvidenceGap, ...] = Field(default=(), max_length=512)
    events: tuple[RunEvent, ...] = Field(default=(), max_length=128)
    ledger: tuple[BudgetLedgerEntry, ...] = Field(default=(), max_length=128)
    decision_ids: tuple[UUID, ...] = Field(default=(), max_length=6)
    revision: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def consistent_run(self):
        terminal = self.state in {
            RunState.COMPLETED, RunState.INSUFFICIENT, RunState.FAILED, RunState.CANCELLED,
        }
        if terminal != (self.terminal_reason is not None):
            raise ValueError("terminal run requires one stop reason")
        if (self.lease_owner is None) != (self.lease_expires_at is None):
            raise ValueError("incomplete run lease")
        if terminal and self.lease_owner is not None:
            raise ValueError("terminal run cannot hold a lease")
        if self.updated_at < self.created_at:
            raise ValueError("invalid run timestamps")
        if any(
            item.run_id != self.id for item in (
                *self.iterations, *self.assessments, *self.gaps, *self.events, *self.ledger,
            )
        ):
            raise ValueError("foreign run record")
        assessment_ids = {item.id for item in self.assessments}
        iteration_ids = {item.id for item in self.iterations}
        if any(item.assessment_id not in assessment_ids or item.iteration_id not in iteration_ids for item in self.gaps):
            raise ValueError("gap provenance is incomplete")
        if tuple(event.sequence for event in self.events) != tuple(range(len(self.events))):
            raise ValueError("event sequence must be contiguous")
        if len({event.idempotency_key for event in self.events}) != len(self.events):
            raise ValueError("event idempotency keys must be unique")
        if len({entry.idempotency_key for entry in self.ledger}) != len(self.ledger):
            raise ValueError("budget ledger keys must be unique")
        if len({gap.id for gap in self.gaps}) != len(self.gaps):
            raise ValueError("duplicate gap id")
        if len(self.decision_ids) != len(set(self.decision_ids)):
            raise ValueError("duplicate decision id")
        return self


ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.PENDING: frozenset({RunState.ASSESSING, RunState.CANCELLED, RunState.FAILED}),
    RunState.ASSESSING: frozenset({RunState.ASSESSING, RunState.PLANNING, RunState.SEARCHING, RunState.SYNTHESIZING, RunState.INSUFFICIENT, RunState.FAILED, RunState.CANCELLED}),
    RunState.PLANNING: frozenset({RunState.PLANNING, RunState.SEARCHING, RunState.ASSESSING, RunState.INSUFFICIENT, RunState.FAILED, RunState.CANCELLED}),
    RunState.SEARCHING: frozenset({RunState.SEARCHING, RunState.EXTRACTING, RunState.ASSESSING, RunState.INSUFFICIENT, RunState.FAILED, RunState.CANCELLED}),
    RunState.EXTRACTING: frozenset({RunState.ASSESSING, RunState.FAILED, RunState.CANCELLED}),
    RunState.SYNTHESIZING: frozenset({RunState.SYNTHESIZING, RunState.COMPLETED, RunState.INSUFFICIENT, RunState.FAILED, RunState.CANCELLED}),
    RunState.COMPLETED: frozenset(),
    RunState.INSUFFICIENT: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


def validate_run_transition(
    current: ResearchRun, candidate: ResearchRun, *, lease_recovery: bool = False
) -> None:
    """Reject stale writers, illegal transitions, and mutations to run policy."""
    if current.revision + 1 != candidate.revision:
        raise ValueError("stale run revision")
    if candidate.state not in ALLOWED_TRANSITIONS[current.state]:
        raise ValueError("illegal iterative research transition")
    if len(candidate.events) <= len(current.events):
        raise ValueError("every state transition must append a durable event")
    if candidate.current_iteration < current.current_iteration or candidate.current_iteration > current.current_iteration + 1:
        raise ValueError("iteration sequence cannot move backwards or skip")
    immutable = (
        "id", "owner_id", "session_id", "policy_version", "budget_version",
        "idempotency_key", "request_fingerprint", "budget", "decision_intent", "created_at",
    )
    if any(getattr(current, name) != getattr(candidate, name) for name in immutable):
        raise ValueError("immutable run policy changed")
    terminal = candidate.state in {
        RunState.COMPLETED, RunState.INSUFFICIENT, RunState.FAILED, RunState.CANCELLED,
    }
    if terminal and candidate.lease_owner is not None:
        raise ValueError("terminal run cannot keep its lease")
    if not terminal and candidate.lease_owner is None:
        raise ValueError("active run must keep its lease")
    if (
        current.lease_owner is not None
        and candidate.lease_owner not in {current.lease_owner, None}
        and not lease_recovery
    ):
        raise ValueError("run lease owner changed outside recovery claim")
    if candidate.events[: len(current.events)] != current.events:
        raise ValueError("run events are append-only")
    if candidate.ledger[: len(current.ledger)] != current.ledger:
        # Settlement can update one existing reservation exactly once.
        if len(candidate.ledger) < len(current.ledger):
            raise ValueError("budget ledger is append-only")
        for old, entry in zip(current.ledger, candidate.ledger[: len(current.ledger)], strict=True):
            if old.id != entry.id:
                raise ValueError("budget ledger is append-only")
            if entry == old:
                continue
            resized_reservation = (
                old.status == entry.status == "reserved"
                and old.settled is None and entry.settled is None
                and old.id == entry.id and old.run_id == entry.run_id
                and old.iteration_id == entry.iteration_id
                and old.dimension == entry.dimension
                and old.idempotency_key == entry.idempotency_key
                and old.created_at == entry.created_at
                and entry.reserved >= old.reserved
            )
            if resized_reservation:
                continue
            if old.status != "reserved" or entry.model_copy(update={"status": "reserved", "settled": None}) != old.model_copy(update={"status": "reserved", "settled": None}):
                raise ValueError("budget ledger is append-only")
            if entry.status == "reserved" or entry.settled is None:
                raise ValueError("budget reservation must settle exactly once")
    if candidate.iterations[: len(current.iterations)] != current.iterations:
        if len(candidate.iterations) not in {len(current.iterations), len(current.iterations) + 1}:
            raise ValueError("invalid iteration record count")
        if candidate.iterations[:-1] != current.iterations[:-1]:
            raise ValueError("iteration history is append-only")
        if len(candidate.iterations) == len(current.iterations):
            old, new = current.iterations[-1], candidate.iterations[-1]
            allowed_iteration_states = {
                "assessing": {"assessing", "planning", "searching", "synthesizing", "completed", "incomplete"},
                "planning": {"planning", "searching", "assessing", "incomplete"},
                "searching": {"searching", "extracting", "assessing", "incomplete"},
                "extracting": {"assessing", "incomplete"},
                "synthesizing": {"synthesizing", "completed", "incomplete"},
                "completed": set(), "incomplete": set(), "cancelled": set(),
            }
            if (
                old.id != new.id or old.run_id != new.run_id or old.sequence != new.sequence
                or old.input_evidence_snapshot_id != new.input_evidence_snapshot_id
                or old.started_at != new.started_at
                or new.state not in allowed_iteration_states[old.state]
            ):
                raise ValueError("illegal iteration transition")
    if candidate.assessments[: len(current.assessments)] != current.assessments:
        raise ValueError("assessment records are append-only")
    if candidate.decision_ids[: len(current.decision_ids)] != current.decision_ids:
        raise ValueError("decision references are append-only")
    if candidate.gaps[: len(current.gaps)] != current.gaps and (
        len(candidate.gaps) < len(current.gaps) or any(
            new.id != old.id or new.model_copy(update={"status": old.status}) != old
            for old, new in zip(current.gaps, candidate.gaps[: len(current.gaps)], strict=True)
        )
    ):
        raise ValueError("gap records are append-only except status")
    elapsed_overrun_recorded = terminal and candidate.state != RunState.COMPLETED
    if candidate.usage.iterations > candidate.budget.max_iterations or candidate.usage.queries > candidate.budget.max_queries or candidate.usage.sources > candidate.budget.max_sources or candidate.usage.tokens > candidate.budget.max_tokens or candidate.usage.provider_cost_usd > candidate.budget.max_provider_cost_usd or candidate.usage.elapsed_seconds > candidate.budget.max_elapsed_seconds and not elapsed_overrun_recorded or candidate.usage.allowed_domains > len(candidate.budget.allowed_domains):
        raise ValueError("budget usage exceeds immutable limits")
    dimensions = {
        "iterations": (candidate.usage.iterations, candidate.budget.max_iterations),
        "queries": (candidate.usage.queries, candidate.budget.max_queries),
        "sources": (candidate.usage.sources, candidate.budget.max_sources),
        "tokens": (candidate.usage.tokens, candidate.budget.max_tokens),
        "provider_cost_usd": (candidate.usage.provider_cost_usd, candidate.budget.max_provider_cost_usd),
        "elapsed_seconds": (candidate.usage.elapsed_seconds, candidate.budget.max_elapsed_seconds),
        "allowed_domains": (candidate.usage.allowed_domains, len(candidate.budget.allowed_domains)),
    }
    for dimension, (used, maximum) in dimensions.items():
        ledger = [entry for entry in candidate.ledger if entry.dimension == dimension]
        settled = sum((entry.settled or Decimal(0) for entry in ledger), Decimal(0))
        reserved = sum((entry.reserved for entry in ledger if entry.status == "reserved"), Decimal(0))
        if settled != Decimal(used) or (
            settled + reserved > Decimal(maximum)
            and not (dimension == "elapsed_seconds" and elapsed_overrun_recorded and reserved == 0)
        ):
            raise ValueError(f"{dimension} usage and ledger disagree")
