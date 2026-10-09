"""Invariant tests for compact decisions and direct dispatch authority.

The in-memory adapters test coordination; engine locking is tested separately.
"""

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres import PersistenceConflict
from personal_ai.persistence.postgres_owner_lifecycle import OwnerFenced
from personal_ai.routing import (
    AuthorizationEvidence,
    DeterministicScoringStrategy,
    DispatchPermit,
    EndpointPriority,
    EndpointRegistry,
    PreparationIdentity,
    QualityEvidence,
    QualityPolicy,
    RankedCandidate,
    RoutingDecision,
    RoutingDecisionService,
    RoutingEvent,
    RoutingFinalizationError,
    RoutingPreferences,
    RoutingRecord,
    RoutingReplayUnavailable,
    RoutingRequestFacts,
    RoutingTaskProfile,
    StrategyRef,
    replay_deterministic_decision,
    source_reference_manifest_sha256,
)
from personal_ai.routing.phase21 import (
    endpoint_configuration_sha256,
    quality_identity_sha256,
    reselection_requirements_preserved,
    sources_allowed,
    task_configuration_sha256,
    transition,
)
from personal_ai.usage.contracts import AttemptResult, UsageAdmissionDenied
from tests.test_endpoint_registry import _profile, _requirements

SCOPE = ApplicationScope()


class MemoryRepository:
    def __init__(self):
        self.now = datetime.now(UTC)
        self.records = {}
        self.attempts = {}
        self.claimed = set()
        self.auxiliary = {}
        self.fenced = False
        self.fail_append = False
        self.in_transaction = False
        self.lock = RLock()

    def execute(self, sql):
        assert sql == "SELECT clock_timestamp()"
        return SimpleNamespace(fetchone=lambda: (self.now,))

    @contextmanager
    def transaction(self, *, owner_id=None):
        with self.lock:
            if self.fenced:
                raise OwnerFenced("owner_deletion_fenced")
            prior = copy.deepcopy((self.records, self.attempts, self.claimed, self.auxiliary))
            old = self.in_transaction
            self.in_transaction = True
            try:
                yield self
            except BaseException:
                self.records, self.attempts, self.claimed, self.auxiliary = prior
                raise
            finally:
                self.in_transaction = old

    def get_in_transaction(self, c, *, owner_id, scope, decision_id, **_):
        if decision_id not in self.records:
            raise LookupError()
        record = self.records[decision_id]
        if (
            record.decision.owner_id != owner_id
            or record.decision.application_id != scope.application_id
            or record.decision.workspace_id != scope.workspace_id
            or record.decision.replay_until <= self.now
        ):
            raise LookupError()
        return RoutingRecord.model_validate(record.model_dump())

    def lock_root(self, c, **kwargs):
        return self.get_in_transaction(c, **kwargs)

    def begin_in_transaction(self, c, *, owner_id, scope, decision):
        if decision.parent_decision_id:
            parent = self.records[decision.parent_decision_id]
            p = parent.decision
            if (
                parent.status != "failed"
                or not reselection_requirements_preserved(
                    p.request.requirements, decision.request.requirements
                )
                or not sources_allowed(p, decision.request.source_reference_sha256s)
            ):
                raise PersistenceConflict("routing_reselection_parent_not_retryable")
            if self.now >= p.root_deadline_at:
                raise PersistenceConflict("routing_deadline_expired")
            if any(
                i.request_id == decision.request.request_id
                and (result is None or result.outcome in {"unknown", "timeout"})
                for i, _, result in self.attempts.values()
            ):
                raise PersistenceConflict("provider_outcome_unresolved")
            self.append_in_transaction(
                c,
                scope=scope,
                record=parent,
                event=RoutingEvent(
                    kind="reselected",
                    occurred_at=self.now,
                    linked_decision_id=decision.routing_decision_id,
                ),
            )
        status = "selected" if decision.selected else "no_route"
        self.records[decision.routing_decision_id] = RoutingRecord(
            decision=decision,
            status=status,
            events=(RoutingEvent(kind=status, occurred_at=decision.created_at),),
        )

    def append_in_transaction(self, c, *, scope, record, event):
        if self.fail_append and event.kind == "authorized":
            raise RuntimeError("publication failed")
        updated = RoutingRecord(
            decision=record.decision,
            status=transition(record.status, event.kind),
            events=(*record.events, event),
        )
        self.records[record.decision.routing_decision_id] = updated
        return updated

    def consume_auxiliary_call(self, *, owner_id, scope, decision_id, event_id):
        with self.transaction(owner_id=owner_id):
            record = self.records[decision_id]
            root = record.decision.root_decision_id
            if any(e.event_id == event_id for e in record.events):
                return self.auxiliary[root]
            used = self.auxiliary.get(root, 0)
            if (
                record.status != "selected"
                or self.now >= record.decision.root_deadline_at
                or used >= record.decision.task.max_auxiliary_calls
            ):
                raise PersistenceConflict("routing_auxiliary_call_budget_exceeded")
            self.auxiliary[root] = used + 1
            self.append_in_transaction(
                self,
                scope=scope,
                record=record,
                event=RoutingEvent(kind="auxiliary", event_id=event_id, occurred_at=self.now),
            )
            return used + 1


class Authorization:
    def __init__(self):
        self.deny = False
        self.stale = False
        self.calls = []

    def authorize(self, **kwargs):
        self.calls.append(kwargs)
        if self.deny:
            raise RuntimeError("revoked")
        now = kwargs["now"]
        return AuthorizationEvidence(
            reference="grant:v1",
            checked_at=now,
            valid_until=now + timedelta(seconds=-1 if self.stale else 60),
        )


class Usage:
    def __init__(self, repo):
        self.repo = repo
        self.exhausted = False
        self.health = False
        self.denied = False
        self.reserve_calls = 0

    def runtime_rejections(self, c, profile, requirements, *, now, check_capacity=True):
        return (
            ("quota-exhausted",)
            if self.exhausted and check_capacity
            else ("cooldown",)
            if self.health
            else ()
        )

    def reserve_attempt_in_transaction(self, c, invocation, attempt, *, max_attempts):
        self.reserve_calls += 1
        if self.denied or self.exhausted:
            raise UsageAdmissionDenied("provider_quota_exhausted")
        if any(
            i.request_id == invocation.request_id
            and (r is None or r.outcome in {"unknown", "timeout"})
            for i, _, r in c.attempts.values()
        ):
            raise UsageAdmissionDenied("provider_outcome_unresolved")
        if (
            len([i for i, _, _ in c.attempts.values() if i.request_id == invocation.request_id])
            >= max_attempts
        ):
            raise UsageAdmissionDenied("provider_attempt_budget_exceeded")
        c.attempts[attempt.attempt_id] = (invocation, attempt, None)
        return attempt

    def reserved_attempt_in_transaction(
        self, c, invocation, attempt_id, *, expected_units, max_attempts, now
    ):
        if attempt_id not in c.attempts:
            raise UsageAdmissionDenied("routing_reservation_not_authoritative")
        stored, attempt, result = c.attempts[attempt_id]
        if result is not None or stored != invocation:
            raise UsageAdmissionDenied("routing_reservation_not_authoritative")
        return attempt

    def claim_attempt_in_transaction(self, c, attempt_id, *, now):
        if attempt_id in c.claimed:
            raise UsageAdmissionDenied("already_claimed")
        c.claimed.add(attempt_id)

    def settle_attempt(self, invocation, attempt, result):
        self.repo.attempts[attempt.attempt_id] = (invocation, attempt, result)

    def attempt_outcome_in_transaction(self, c, invocation_id, attempt_id):
        invocation, _, result = c.attempts[attempt_id]
        if invocation.invocation_id != invocation_id or result is None:
            raise UsageAdmissionDenied("provider_outcome_unresolved")
        return result.outcome

    def complete_invocation(self, *args, **kwargs):
        pass


@pytest.fixture
def system():
    repo = MemoryRepository()
    profiles = (_profile("endpoint-a"), _profile("endpoint-b"))
    registry = EndpointRegistry(profiles)
    usage, auth = Usage(repo), Authorization()
    service = RoutingDecisionService(registry, repo, usage=usage, authorization=auth)
    return service, repo, usage, auth


def task(**changes):
    return RoutingTaskProfile(
        task_id="chat",
        profile_id="task:chat",
        profile_version=1,
        task_type="chat",
        required_capabilities=frozenset({"bounded_generation"}),
        **changes,
    )


def request(**changes):
    return RoutingRequestFacts(
        request_id="request:test",
        requirements=_requirements(input_tokens=64, output_tokens=16),
        policy_version="policy:v1",
        **changes,
    )


def route(system, **kwargs):
    return system[0].route(
        owner_id="owner",
        scope=SCOPE,
        task=kwargs.pop("task", task()),
        request=kwargs.pop("request", request()),
        **kwargs,
    )


def prepare(decision, repo, **changes):
    return PreparationIdentity(
        endpoint=decision.selected,
        serializer_id="synthetic-chat-v1",
        input_tokens=32,
        count_source="estimate:v1",
        count_confidence="estimated",
        source_reference_sha256s=decision.request.source_reference_sha256s,
        prepared_input_sha256=sha256(b"synthetic-input").hexdigest(),
        prepared_at=repo.now,
        **changes,
    )


def finalize(system, decision, preparation=None):
    return system[0].finalize(
        owner_id="owner",
        scope=SCOPE,
        decision_id=decision.routing_decision_id,
        preparation=preparation or prepare(decision, system[1]),
        operation="bounded_generation",
    )


@pytest.mark.parametrize(
    "task_type", ["chat", "summary", "extraction", "research_synthesis", "rewrite"]
)
def test_known_tasks_route_without_classification(system, task_type):
    t = task().model_copy(update={"task_type": task_type})
    decision = route(system, task=t)
    assert decision.selected.endpoint_profile_id == "endpoint-a"
    assert (
        replay_deterministic_decision(decision, DeterministicScoringStrategy(), now=system[1].now)
        == decision.ranking
    )


def test_least_knowledge_strategy_and_hard_ineligible_isolation(system):
    system[2].exhausted = True
    decision = route(system)
    assert decision.selected is None
    assert not decision.strategy_view().candidates
    system[2].exhausted = False
    other = route(system, request=request().model_copy(update={"request_id": "request:other"}))
    view = other.strategy_view().model_dump_json()
    for forbidden in (
        "credential",
        "account",
        "quota",
        "privacy",
        "policy_version",
        "serializer",
        "registry",
    ):
        assert forbidden not in view


@pytest.mark.parametrize(
    "authority", ["missing_auth", "missing_usage", "revoked", "stale", "unhealthy"]
)
def test_missing_stale_denied_authority_fails_closed(system, authority):
    if authority == "missing_auth":
        system[0].authorization = None
    if authority == "missing_usage":
        system[0].usage = None
    if authority == "revoked":
        system[3].deny = True
    if authority == "stale":
        system[3].stale = True
    if authority == "unhealthy":
        system[2].health = True
    assert route(system).selected is None
    assert not system[1].attempts


def test_semantic_identity_replay_retention_and_registry_changes(system):
    decision = route(system)
    system[0].registry.remove("endpoint-a")
    assert (
        replay_deterministic_decision(decision, DeterministicScoringStrategy(), now=system[1].now)
        == decision.ranking
    )
    changed = DeterministicScoringStrategy()
    changed.ref = StrategyRef(
        strategy_id="deterministic-scoring", semantic_version="2", artifact_id="new-policy"
    )
    with pytest.raises(RoutingReplayUnavailable, match="historical_strategy_unavailable"):
        replay_deterministic_decision(decision, changed, now=system[1].now)
    with pytest.raises(RoutingReplayUnavailable, match="expired"):
        replay_deterministic_decision(
            decision, DeterministicScoringStrategy(), now=decision.replay_until
        )
    assert system[0].registry.historical(decision.selected).ref == decision.selected


def test_maximum_attempt_and_auxiliary_budgets_fit_bounded_lifecycle_storage(system):
    decision = route(
        system,
        task=task(max_physical_attempts=32, max_auxiliary_calls=16, deadline_ms=600_000),
    )
    preparation = prepare(decision, system[1])
    events = [RoutingEvent(kind="selected", occurred_at=decision.created_at)]
    for index in range(16):
        events.append(
            RoutingEvent(
                kind="auxiliary",
                occurred_at=decision.created_at + timedelta(milliseconds=index + 1),
            )
        )
    for index in range(32):
        started = decision.created_at + timedelta(milliseconds=100 + index * 3)
        attempt_id = uuid4()
        permit = DispatchPermit(
            decision_id=decision.routing_decision_id,
            invocation_id=uuid4(),
            attempt_id=attempt_id,
            expires_at=started + timedelta(seconds=1),
        )
        events.extend(
            (
                RoutingEvent(
                    kind="authorized",
                    occurred_at=started,
                    preparation=preparation,
                    permit=permit,
                    authorization_reference="grant:v1",
                    attempt_id=attempt_id,
                ),
                RoutingEvent(
                    kind="dispatched",
                    occurred_at=started + timedelta(milliseconds=1),
                    attempt_id=attempt_id,
                    authorization_reference="grant:v1",
                ),
                RoutingEvent(
                    kind="failed",
                    occurred_at=started + timedelta(milliseconds=2),
                    attempt_id=attempt_id,
                    reason="attempt-failed",
                ),
            )
        )

    record = RoutingRecord(decision=decision, status="failed", events=tuple(events))
    assert len(record.events) == 113

    migration = (
        Path(__file__).parents[1]
        / "src/personal_ai/persistence/migrations/022_routing_authorities.sql"
    ).read_text(encoding="utf-8")
    assert "sequence BETWEEN 1 AND 128" in migration


def test_finalization_does_not_reserve_when_required_followup_events_cannot_fit(system):
    decision = route(
        system,
        task=task(max_physical_attempts=32, max_auxiliary_calls=16, deadline_ms=600_000),
    )
    preparation = prepare(decision, system[1])
    events = [RoutingEvent(kind="selected", occurred_at=decision.created_at)]
    for index in range(16):
        events.append(
            RoutingEvent(
                kind="auxiliary",
                occurred_at=decision.created_at + timedelta(milliseconds=index + 1),
            )
        )
    for index in range(36):
        started = decision.created_at + timedelta(milliseconds=100 + index * 3)
        attempt_id = uuid4()
        permit = DispatchPermit(
            decision_id=decision.routing_decision_id,
            invocation_id=uuid4(),
            attempt_id=attempt_id,
            expires_at=started + timedelta(seconds=1),
        )
        events.extend(
            (
                RoutingEvent(
                    kind="authorized",
                    occurred_at=started,
                    preparation=preparation,
                    permit=permit,
                    authorization_reference="grant:v1",
                    attempt_id=attempt_id,
                ),
                RoutingEvent(
                    kind="dispatched",
                    occurred_at=started + timedelta(milliseconds=1),
                    attempt_id=attempt_id,
                    authorization_reference="grant:v1",
                ),
                RoutingEvent(
                    kind="failed",
                    occurred_at=started + timedelta(milliseconds=2),
                    attempt_id=attempt_id,
                    reason="attempt-failed",
                ),
            )
        )
    last_started = decision.created_at + timedelta(milliseconds=300)
    last_attempt_id = uuid4()
    last_permit = DispatchPermit(
        decision_id=decision.routing_decision_id,
        invocation_id=uuid4(),
        attempt_id=last_attempt_id,
        expires_at=last_started + timedelta(seconds=1),
    )
    events.extend(
        (
            RoutingEvent(
                kind="authorized",
                occurred_at=last_started,
                preparation=preparation,
                permit=last_permit,
                authorization_reference="grant:v1",
                attempt_id=last_attempt_id,
            ),
            RoutingEvent(
                kind="failed",
                occurred_at=last_started + timedelta(milliseconds=1),
                reason="attempt-failed",
            ),
        )
    )
    assert len(events) == 127
    system[1].records[decision.routing_decision_id] = RoutingRecord(
        decision=decision, status="failed", events=tuple(events)
    )

    with pytest.raises(RoutingFinalizationError, match="routing_event_capacity_exhausted"):
        finalize(system, decision, preparation)
    assert system[2].reserve_calls == 0
    assert not system[1].attempts


def test_unrelated_profile_change_does_not_invalidate_dispatch(system):
    decision = route(system)
    profile = system[0].registry.profiles[1]
    system[0].registry.upsert(
        profile.model_copy(update={"profile_version": 2, "max_output_tokens": 2000})
    )
    assert finalize(system, decision).attempt_id in system[1].attempts


@pytest.mark.parametrize(
    "change", ["version", "remove", "revoked", "stale", "quota", "fit", "fence", "deadline"]
)
def test_final_authority_revalidation_and_no_send_on_denial(system, change):
    decision = route(system)
    prep = prepare(decision, system[1])
    if change == "version":
        profile = system[0].registry.profiles[0]
        system[0].registry.upsert(profile.model_copy(update={"profile_version": 2}))
    if change == "remove":
        system[0].registry.remove("endpoint-a")
    if change == "revoked":
        system[3].deny = True
    if change == "stale":
        system[3].stale = True
    if change == "quota":
        system[2].denied = True
    if change == "fit":
        prep = prep.model_copy(update={"input_tokens": 999999})
    if change == "fence":
        system[1].fenced = True
    if change == "deadline":
        system[1].now = decision.root_deadline_at
    with pytest.raises((RoutingFinalizationError, OwnerFenced)):
        finalize(system, decision, prep)
    assert not system[1].attempts


def test_atomic_reservation_publication_rollback(system):
    decision = route(system)
    system[1].fail_append = True
    with pytest.raises(RoutingFinalizationError):
        finalize(system, decision)
    assert not system[1].attempts
    assert system[1].records[decision.routing_decision_id].status == "failed"


def test_concurrent_finalization_is_idempotent_and_claim_is_single_use(system):
    decision = route(system)
    with ThreadPoolExecutor(max_workers=2) as pool:
        permits = list(pool.map(lambda _: finalize(system, decision), range(2)))
    assert permits[0] == permits[1]
    assert system[2].reserve_calls == 1
    sends = []

    def send(profile, invocation, attempt):
        assert not system[1].in_transaction
        assert attempt.attempt_id in system[1].claimed
        assert invocation.routing_decision_id == str(decision.routing_decision_id)
        sends.append(profile.ref)
        return "ok", AttemptResult(outcome="success", completed_at=system[1].now, latency_ms=1)

    assert (
        system[0].dispatch(
            owner_id="owner",
            scope=SCOPE,
            permit=permits[0],
            operation="bounded_generation",
            send=send,
        )
        == "ok"
    )
    with pytest.raises(RoutingFinalizationError):
        system[0].dispatch(
            owner_id="owner",
            scope=SCOPE,
            permit=permits[1],
            operation="bounded_generation",
            send=send,
        )
    assert sends == [decision.selected]


@pytest.mark.parametrize("change", ["revoked", "expired", "settled", "forged", "deleted"])
def test_dispatch_claim_rechecks_current_authority(system, change):
    decision = route(system)
    permit = finalize(system, decision)
    if change == "revoked":
        system[3].deny = True
    if change == "expired":
        system[1].now = permit.expires_at
    if change == "settled":
        i, a, _ = system[1].attempts[permit.attempt_id]
        system[2].settle_attempt(
            i, a, AttemptResult(outcome="unknown", completed_at=system[1].now, latency_ms=0)
        )
    if change == "forged":
        permit = permit.model_copy(update={"attempt_id": uuid4()})
    if change == "deleted":
        system[1].fenced = True
    with pytest.raises((RoutingFinalizationError, UsageAdmissionDenied, OwnerFenced)):
        system[0].claim(
            owner_id="owner", scope=SCOPE, permit=permit, operation="bounded_generation"
        )
    assert not system[1].claimed


def test_reselection_narrowing_exclusions_monotonicity_and_root_deadline(system):
    refs = tuple(sorted(sha256(s.encode()).hexdigest() for s in ("a", "b")))
    t = task(max_reselections=1, allow_source_narrowing=True)
    parent = route(system, task=t, request=request(source_reference_sha256s=refs))
    system[0].finish(
        owner_id="owner", scope=SCOPE, decision_id=parent.routing_decision_id, reason="fit-failed"
    )
    child = route(
        system,
        task=t,
        request=request(source_reference_sha256s=refs[:1]),
        parent_decision_id=parent.routing_decision_id,
    )
    assert child.selected.endpoint_profile_id == "endpoint-b"
    assert child.request.excluded_endpoint_profile_ids == ("endpoint-a",)
    assert child.root_deadline_at == parent.root_deadline_at
    assert child.replay_until <= parent.replay_until
    assert (
        route(
            system,
            task=t,
            request=request(source_reference_sha256s=refs[:1]),
            parent_decision_id=parent.routing_decision_id,
        )
        == child
    )
    loosened = child.request.model_copy(
        update={
            "requirements": child.request.requirements.model_copy(
                update={"sensitivity": "public", "input_tokens": 100000}
            )
        }
    )
    with pytest.raises(ValueError):
        route(system, task=t, request=loosened, parent_decision_id=parent.routing_decision_id)


def test_auxiliary_budget_idempotency_and_concurrency(system):
    decision = route(system, task=task(max_auxiliary_calls=1))
    event_id = uuid4()
    args = {"owner_id": "owner", "scope": SCOPE, "decision_id": decision.routing_decision_id}
    assert system[0].consume_auxiliary_call(**args, event_id=event_id) == 1
    assert system[0].consume_auxiliary_call(**args, event_id=event_id) == 1
    with pytest.raises(PersistenceConflict):
        system[0].consume_auxiliary_call(**args, event_id=uuid4())


def test_canonical_sources_and_bounded_privacy_safe_decision(system):
    digest = sha256(b"synthetic-source").hexdigest()
    r = request(source_reference_sha256s=(digest, digest))
    assert r.source_reference_sha256s == (digest,)
    assert r.source_count == 1
    assert r.source_manifest_sha256 == source_reference_manifest_sha256((digest,))
    decision = route(system, request=r)
    for field in (
        "prompt",
        "raw_input",
        "credential",
        "account",
        "provisional_plan",
        "strategy_input",
    ):
        assert field not in decision.model_dump_json()
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate({**decision.model_dump(), "prompt": "private"})
    system[1].records[decision.routing_decision_id] = (
        system[1].records[decision.routing_decision_id].model_copy(update={"status": "authorized"})
    )
    with pytest.raises(ValidationError):
        finalize(system, decision)


def test_measured_quality_floor_before_strategy(system):
    t = task(
        quality=QualityPolicy(
            mode="measured_floor",
            quality_profile_id="quality:chat",
            quality_profile_version=1,
            minimum_score=0.8,
            minimum_coverage=0.5,
        )
    )
    assert route(system, task=t).selected is None
    profile = next(
        item for item in system[0].registry.profiles if item.endpoint_profile_id == "endpoint-b"
    )
    endpoint_digest = endpoint_configuration_sha256(profile)
    task_digest = task_configuration_sha256(t)
    q = QualityEvidence(
        quality_evidence_id=uuid4(),
        quality_evidence_version=1,
        task_profile_id=t.profile_id,
        task_profile_version=1,
        endpoint_profile_id="endpoint-b",
        endpoint_profile_version=1,
        provider_id=profile.provider_id,
        model_id=profile.model_id,
        endpoint_id=profile.endpoint_id,
        deployment_id=profile.deployment_id,
        account_scope_id=profile.account_scope_id,
        credential_scope_id=profile.credential_scope_id,
        serializer_id=profile.serializer_id,
        runtime_id=profile.runtime_id,
        counter_id=profile.counter.counter_id if profile.counter else None,
        counter_confidence=profile.counter.confidence if profile.counter else "unknown",
        quality_profile_id="quality:chat",
        quality_profile_version=1,
        policy_version="policy:v1",
        endpoint_configuration_sha256=endpoint_digest,
        task_configuration_sha256=task_digest,
        quality_identity_sha256=quality_identity_sha256(
            endpoint_digest=endpoint_digest,
            task_digest=task_digest,
            policy_version="policy:v1",
            quality_profile_id="quality:chat",
            quality_profile_version=1,
            scoring_policy_id="deterministic-task-matrix",
            scoring_policy_version=1,
            tested_revision="a1b2c3d",
        ),
        scoring_policy_id="deterministic-task-matrix",
        scoring_policy_version=1,
        tested_revision="a1b2c3d",
        score=0.9,
        coverage=1,
        confidence=0.9,
        sample_count=20,
        measured_at=system[1].now,
        fresh_until=system[1].now + timedelta(minutes=1),
        evidence_reference="quality:evaluation",
    )
    decision = route(
        system,
        task=t,
        request=request().model_copy(update={"request_id": "quality-request"}),
        quality_evidence=(q,),
    )
    assert decision.selected.endpoint_profile_id == "endpoint-b"


def test_priority_and_missing_signal_do_not_invent_measurements(system):
    t = task(
        preferences=RoutingPreferences(quality_weight=1000),
        endpoint_priorities=(EndpointPriority(endpoint_profile_id="endpoint-b", priority=1),),
    )
    decision = route(system, task=t)
    assert decision.selected.endpoint_profile_id == "endpoint-b"
    assert all(r.reason_code == "priority" for r in decision.ranking)


def test_strategy_cannot_rank_ineligible_or_duplicate_endpoint(system):
    class Bad:
        ref = DeterministicScoringStrategy.ref

        def select(self, view):
            return (
                RankedCandidate(endpoint=_profile("not-admitted").ref, score=1, reason_code="bad"),
            )

    system[0].strategy = Bad()
    assert route(system).no_route_reason == "routing-strategy-contract-invalid"


def test_source_broadening_at_dispatch_is_denied(system):
    one, two = (sha256(s.encode()).hexdigest() for s in ("one", "two"))
    decision = route(
        system,
        task=task(allow_source_narrowing=True),
        request=request(source_reference_sha256s=(one,)),
    )
    prep = prepare(decision, system[1]).model_copy(
        update={"source_reference_sha256s": tuple(sorted((one, two)))}
    )
    with pytest.raises(RoutingFinalizationError):
        finalize(system, decision, prep)
    assert not system[1].attempts


def test_depth_two_inherits_exclusions_and_cannot_expand_sources(system):
    system[0].registry.upsert(_profile("endpoint-c"))
    refs = tuple(sorted(sha256(s.encode()).hexdigest() for s in ("a", "b")))
    t = task(max_reselections=2, allow_source_narrowing=True)
    parent = route(system, task=t, request=request(source_reference_sha256s=refs))
    system[0].finish(owner_id="owner", scope=SCOPE, decision_id=parent.routing_decision_id)
    first = route(
        system,
        task=t,
        request=request(source_reference_sha256s=refs[:1]),
        parent_decision_id=parent.routing_decision_id,
    )
    system[0].finish(owner_id="owner", scope=SCOPE, decision_id=first.routing_decision_id)
    with pytest.raises(ValueError):
        route(
            system,
            task=t,
            request=request(source_reference_sha256s=refs),
            parent_decision_id=first.routing_decision_id,
        )
    second = route(
        system,
        task=t,
        request=request(source_reference_sha256s=refs[:1]),
        parent_decision_id=first.routing_decision_id,
    )
    assert second.request.excluded_endpoint_profile_ids == ("endpoint-a", "endpoint-b")
    assert second.selected.endpoint_profile_id == "endpoint-c"
    assert second.root_deadline_at == parent.root_deadline_at


def test_unknown_outcome_fences_retry_and_reselection(system):
    decision = route(system, task=task(max_reselections=1, max_physical_attempts=3))
    permit = finalize(system, decision)

    def fail(*_):
        raise TimeoutError("unknown provider outcome")

    with pytest.raises(TimeoutError):
        system[0].dispatch(
            owner_id="owner", scope=SCOPE, permit=permit, operation="bounded_generation", send=fail
        )
    with pytest.raises(RoutingFinalizationError, match="provider_outcome_unresolved"):
        finalize(system, decision)
    with pytest.raises(PersistenceConflict, match="provider_outcome_unresolved"):
        route(
            system,
            task=decision.task,
            request=decision.request,
            parent_decision_id=decision.routing_decision_id,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("sensitivity", "public"),
        ("input_tokens", 65),
        ("output_tokens", 17),
        ("automatic", False),
        ("execution_mode", "EXPLICIT_BYOK"),
    ],
)
def test_reselection_requirement_monotonicity(field, value):
    parent = _requirements(input_tokens=64, output_tokens=16, sensitivity="sensitive")
    assert not reselection_requirements_preserved(parent, parent.model_copy(update={field: value}))


def test_maximum_candidate_set_is_compact_without_profile_amplification(system):
    profiles = tuple(_profile(f"endpoint-{i:02}") for i in range(32))
    system[0].registry.reconcile(profiles)
    decision = route(system)
    assert len(decision.candidates) == 32
    assert len(decision.model_dump_json().encode()) < 32768


@pytest.mark.parametrize(
    "health,eligible",
    [
        (None, True),
        (("healthy", None), True),
        (("unknown", None), False),
        (("degraded", None), False),
        (("cooldown", None), False),
    ],
)
def test_runtime_health_bootstrap_and_missing_evidence(health, eligible):
    from personal_ai.persistence.postgres_usage import _health_unavailable

    assert _health_unavailable(health, datetime.now(UTC)) is not eligible


def test_expired_cooldown_allows_probe_without_claiming_measured_health():
    from personal_ai.persistence.postgres_usage import _health_unavailable

    now = datetime.now(UTC)
    assert not _health_unavailable(("degraded", now - timedelta(seconds=1)), now)
    assert _health_unavailable(("healthy", now + timedelta(seconds=1)), now)


def test_reselection_cannot_drop_counter_schema_or_capabilities():
    from personal_ai.routing import CountRequirement

    parent = _requirements(
        input_tokens=64,
        output_tokens=16,
        required_capabilities=frozenset(
            {"bounded_generation", "structured_generation", "token_counting"}
        ),
        structured_schema_id="schema:a",
        count=CountRequirement(minimum_confidence="authoritative", structured_schema_id="schema:a"),
    )
    for updates in (
        {"count": None},
        {"count": parent.count.model_copy(update={"minimum_confidence": "estimated"})},
        {"structured_schema_id": "schema:b"},
        {"required_capabilities": frozenset({"bounded_generation"})},
    ):
        assert not reselection_requirements_preserved(parent, parent.model_copy(update=updates))


def test_closure_requires_settled_phase19_outcome(system):
    decision = route(system)
    permit = finalize(system, decision)
    system[0].claim(owner_id="owner", scope=SCOPE, permit=permit, operation="bounded_generation")
    with pytest.raises(UsageAdmissionDenied, match="provider_outcome_unresolved"):
        system[0].finish(owner_id="owner", scope=SCOPE, decision_id=decision.routing_decision_id)
    assert system[1].records[decision.routing_decision_id].status == "dispatched"
    invocation, attempt, _ = system[1].attempts[permit.attempt_id]
    system[2].settle_attempt(
        invocation,
        attempt,
        AttemptResult(outcome="success", completed_at=system[1].now, latency_ms=1),
    )
    system[0].finish(owner_id="owner", scope=SCOPE, decision_id=decision.routing_decision_id)
    assert system[1].records[decision.routing_decision_id].status == "closed"


def test_malformed_transport_result_keeps_conservative_unknown_outcome(system):
    decision = route(system)
    permit = finalize(system, decision)
    with pytest.raises(TypeError, match="routing_transport_result_invalid"):
        system[0].dispatch(
            owner_id="owner",
            scope=SCOPE,
            permit=permit,
            operation="bounded_generation",
            send=lambda *_: ("untrusted", {"outcome": "success"}),
        )
    assert system[1].attempts[permit.attempt_id][2].outcome == "unknown"
    assert system[1].records[decision.routing_decision_id].status == "failed"


def test_corrupt_dispatch_event_cannot_claim_an_unrelated_attempt(system):
    decision = route(system)
    permit = finalize(system, decision)
    system[0].claim(owner_id="owner", scope=SCOPE, permit=permit, operation="bounded_generation")
    record = system[1].records[decision.routing_decision_id]
    raw = record.model_dump()
    raw["events"][-1]["attempt_id"] = uuid4()
    with pytest.raises(ValidationError, match="routing_dispatch_receipt_mismatch"):
        RoutingRecord.model_validate(raw)


def test_corrupt_ranking_cannot_silently_omit_an_eligible_candidate(system):
    decision = route(system)
    assert len(decision.ranking) == 2
    raw = decision.model_dump()
    raw["ranking"] = raw["ranking"][:1]
    with pytest.raises(ValidationError, match="ranked_ineligible"):
        RoutingDecision.model_validate(raw)


def test_reselection_budget_is_bounded_by_single_chain_depth(system):
    system[0].registry.upsert(_profile("endpoint-c"))
    t = task(max_reselections=1)
    root = route(system, task=t)
    system[0].finish(owner_id="owner", scope=SCOPE, decision_id=root.routing_decision_id)
    child = route(system, task=t, parent_decision_id=root.routing_decision_id)
    system[0].finish(owner_id="owner", scope=SCOPE, decision_id=child.routing_decision_id)
    with pytest.raises(ValidationError, match="reselection_lineage"):
        route(system, task=t, parent_decision_id=child.routing_decision_id)
    assert len(system[1].records) == 2


@pytest.mark.parametrize("field", ["root_deadline_at", "replay_until"])
def test_corrupt_root_cannot_extend_task_deadline_or_retention(system, field):
    decision = route(system, task=task(replay_retention_seconds=60))
    raw = decision.model_dump()
    raw[field] += timedelta(seconds=60)
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(raw)
