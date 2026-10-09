"""Deterministic contract coverage for task-aware Phase 21 routing."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres_routing_observations import (
    PostgresRoutingDecisionRepository,
    RoutingDecisionUnavailable,
)
from personal_ai.routing import (
    DataUsePolicy,
    DeterministicScoringStrategy,
    DispatchRevalidation,
    EndpointCandidateRequirements,
    EndpointPriority,
    EndpointProfile,
    EndpointRegistry,
    PreparationIdentity,
    QualityEvidence,
    QualityPolicy,
    QuotaBucket,
    QuotaReservationRef,
    RoutingDecisionEvent,
    RoutingDecisionObservation,
    RoutingDecisionRecord,
    RoutingDecisionService,
    RoutingPreferences,
    RoutingReplayUnavailable,
    RoutingRequestFacts,
    RoutingSignals,
    RoutingStrategyResult,
    RoutingTaskProfile,
    RuntimeCandidateFacts,
    StrictFreeEligibilityAttestation,
    replay_deterministic_decision,
)
from personal_ai.routing.service import RoutingFinalizationError

NOW = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
SCOPE = ApplicationScope(application_id="personal_ai")
OWNER = "owner-test"
SOURCE_HASH = sha256(b"[]").hexdigest()


class _MemoryDecisionRepository:
    def __init__(self):
        self.records = {}
        self.reselection_counts = {}

    def begin(self, *, owner_id, scope, observation, initial_event):
        assert observation.owner_id == owner_id
        assert observation.application_id == scope.application_id
        assert observation.workspace_id == scope.workspace_id
        assert observation.routing_decision_id not in self.records
        self.records[observation.routing_decision_id] = [observation, [initial_event]]

    def get(self, *, owner_id, scope, decision_id):
        observation, events = self.records[decision_id]
        assert observation.owner_id == owner_id
        assert observation.application_id == scope.application_id
        return RoutingDecisionRecord(observation=observation, events=tuple(events))

    def append_event(self, *, owner_id, scope, decision_id, event):
        observation, events = self.records[decision_id]
        assert observation.owner_id == owner_id
        assert observation.application_id == scope.application_id
        events.append(event)
        return RoutingDecisionRecord(observation=observation, events=tuple(events))

    def begin_reselection(
        self,
        *,
        owner_id,
        scope,
        observation,
        initial_event,
        parent_decision_id,
        max_reselections,
    ):
        root_id = observation.root_decision_id
        if self.reselection_counts.get(root_id, 0) >= max_reselections:
            raise ValueError("routing_reselection_budget_exceeded")
        self.begin(
            owner_id=owner_id,
            scope=scope,
            observation=observation,
            initial_event=initial_event,
        )
        self.reselection_counts[root_id] = self.reselection_counts.get(root_id, 0) + 1
        self.append_event(
            owner_id=owner_id,
            scope=scope,
            decision_id=parent_decision_id,
            event=RoutingDecisionEvent(
                event_type="reselection_linked",
                occurred_at=observation.created_at,
                linked_decision_id=observation.routing_decision_id,
                outcome_code="reselection-created",
            ),
        )


class _SQLResult:
    def __init__(self, row=None, rows=None, rowcount=0):
        self.row = row
        self.rows = list(rows if rows is not None else ([] if row is None else [row]))
        self.rowcount = rowcount

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _RoutingSQLConnection:
    def __init__(self):
        self.namespace = None
        self.records = {}
        self.fenced_owners = set()

    def execute(self, query, params=None):
        query = " ".join(query.split())
        params = tuple(params or ())
        if query.startswith("SELECT pg_advisory_xact_lock"):
            return _SQLResult()
        if query.startswith("SELECT 1 FROM artifact_owner_fences"):
            return _SQLResult((1,) if params[0] in self.fenced_owners else None)
        if query.startswith("INSERT INTO scope_namespaces"):
            self.namespace = (params[1], params[2], params[3])
            return _SQLResult()
        if query.startswith("SELECT owner_id, application_id, workspace_id FROM scope_namespaces"):
            return _SQLResult(self.namespace)
        if query.startswith("SELECT root_decision_id,reselection_count,replay_until FROM routing_decisions"):
            record = self.records.get(params[1])
            if record is None or record["owner_id"] != params[2]:
                return _SQLResult()
            return _SQLResult((
                record["root_decision_id"],
                record["reselection_count"],
                record["replay_until"],
            ))
        if query.startswith("SELECT decision_facts,outcome_events,root_decision_id,reselection_depth,"):
            record = self.records.get(params[1])
            if record is None or record["owner_id"] != params[2]:
                return _SQLResult()
            return _SQLResult((
                record["facts"], record["events"], record["root_decision_id"],
                record["reselection_depth"], record["lifecycle_status"],
                record["replay_until"],
            ))
        if query.startswith("INSERT INTO routing_decisions"):
            decision_id = params[0]
            if decision_id in self.records:
                return _SQLResult()
            self.records[decision_id] = {
                "scope_id": params[1],
                "owner_id": params[2],
                "application_id": params[3],
                "workspace_id": params[4],
                "request_id": params[5],
                "run_id": params[6],
                "parent_decision_id": params[7],
                "root_decision_id": params[8],
                "reselection_depth": params[9],
                "reselection_count": 0,
                "lifecycle_status": params[10],
                "facts": json.loads(params[11]),
                "events": json.loads(params[12]),
                "created_at": params[13],
                "replay_until": params[15],
                "invocation_ids": [],
                "attempt_ids": [],
                "evaluation_run_ids": [],
            }
            return _SQLResult((decision_id,), rowcount=1)
        if query.startswith("UPDATE routing_decisions SET"):
            if "reselection_count=reselection_count+1" in query:
                record = self.records.get(params[1])
                if record is None or record["scope_id"] != params[0]:
                    return _SQLResult()
                if record["reselection_count"] >= params[3]:
                    return _SQLResult()
                record["reselection_count"] += 1
                return _SQLResult((record["reselection_count"],), rowcount=1)
            if "outcome_events=outcome_events || %s::jsonb" in query and len(params) == 7:
                record = self.records.get(params[3])
                if (
                    record is None
                    or record["scope_id"] != params[2]
                    or record["owner_id"] != params[4]
                    or record["replay_until"] <= params[5]
                    or len(record["events"]) >= 32
                ):
                    return _SQLResult(rowcount=0)
                appended = json.loads(params[0])
                record["events"].extend(appended)
                return _SQLResult(rowcount=1)
            record = self.records.get(params[9])
            if record is None or record["scope_id"] != params[8]:
                return _SQLResult()
            if record["owner_id"] != params[10] or record["application_id"] != params[11]:
                return _SQLResult()
            if record["workspace_id"] != params[12] or record["replay_until"] <= params[13]:
                return _SQLResult()
            if len(record["events"]) >= 32:
                return _SQLResult()
            appended = json.loads(params[0])
            record["events"].extend(appended)
            if params[1] is not None:
                record["invocation_ids"].append(params[1])
            if params[4] is not None:
                record["attempt_ids"].append(params[4])
            if params[6] is not None:
                record["evaluation_run_ids"].append(params[6])
            return _SQLResult((record["facts"], record["events"]), rowcount=1)
        if query.startswith("SELECT decision_facts,outcome_events FROM routing_decisions WHERE"):
            if " ORDER BY created_at DESC" in query:
                return self._list(query, params)
            scope_id, decision_id, owner_id, application_id, workspace_id, now, _fence_owner = params
            record = self.records.get(decision_id)
            if (
                record is None
                or owner_id in self.fenced_owners
                or record["scope_id"] != scope_id
                or record["owner_id"] != owner_id
                or record["application_id"] != application_id
                or record["workspace_id"] != workspace_id
                or record["replay_until"] <= now
            ):
                return _SQLResult()
            return _SQLResult((record["facts"], record["events"]))
        raise AssertionError(f"unhandled query: {query}")

    def _list(self, query, params):
        scope_id, owner_id, application_id, workspace_id, now, _fence_owner, *filters = params
        result = []
        for record in self.records.values():
            if (
                record["scope_id"] != scope_id
                or record["owner_id"] != owner_id
                or record["application_id"] != application_id
                or record["workspace_id"] != workspace_id
                or record["replay_until"] <= now
                or owner_id in self.fenced_owners
            ):
                continue
            index = 0
            if "request_id=%s" in query:
                if record["request_id"] != filters[index]:
                    continue
                index += 1
            if "run_id=%s" in query:
                if record["run_id"] != filters[index]:
                    continue
                index += 1
            if "created_at>=%s" in query:
                if record["created_at"] < filters[index]:
                    continue
                index += 1
            if "created_at<=%s" in query:
                if record["created_at"] > filters[index]:
                    continue
                index += 1
            if "invocation_ids @> ARRAY[%s::uuid]" in query:
                if filters[index] not in record["invocation_ids"]:
                    continue
                index += 1
            if "attempt_ids @> ARRAY[%s::uuid]" in query:
                if filters[index] not in record["attempt_ids"]:
                    continue
                index += 1
            if "evaluation_run_ids @> ARRAY[%s::uuid]" in query and filters[index] not in record["evaluation_run_ids"]:
                continue
            result.append((record["facts"], record["events"]))
        return _SQLResult(rows=result)


class _RoutingSQLDatabase:
    def __init__(self):
        self.connection_value = _RoutingSQLConnection()

    @contextmanager
    def connection(self, **_kwargs):
        yield self.connection_value

    @contextmanager
    def transaction(self, **_kwargs):
        yield self.connection_value


def _profile(
    endpoint_id="model-a",
    *,
    version=1,
    capabilities=frozenset({"bounded_generation", "streaming", "structured_generation"}),
    operations=frozenset({"bounded_generation", "streaming", "structured_generation"}),
    policy=None,
    schemas=("schema:proposal-v1",),
):
    profile_id = f"synthetic:{endpoint_id}"
    account_id = f"account:{endpoint_id}"
    credential_id = f"credential:{endpoint_id}"
    return EndpointProfile(
        endpoint_profile_id=profile_id,
        profile_version=version,
        provider_id="synthetic-provider",
        model_id=endpoint_id,
        endpoint_id=f"endpoint:{endpoint_id}",
        deployment_id=f"deployment:{endpoint_id}",
        credential_source="environment",
        credential_reference="env:SYNTHETIC_MODEL_KEY",
        credential_scope_id=credential_id,
        account_scope_id=account_id,
        tier_id="free",
        tier_verified=True,
        execution_mode="STRICT_FREE",
        cost_class="VERIFIED_FREE",
        billing_owner="provider_account",
        enabled=True,
        strict_free_enabled=True,
        capabilities=capabilities,
        context_limit_tokens=4096,
        max_output_tokens=1024,
        data_use_policy=policy or DataUsePolicy(
            status="approved", max_sensitivity="personal", policy_reference="policy:v1"
        ),
        strict_free_attestation=StrictFreeEligibilityAttestation(
            endpoint_profile_id=profile_id,
            provider_id="synthetic-provider",
            model_id=endpoint_id,
            endpoint_id=f"endpoint:{endpoint_id}",
            deployment_id=f"deployment:{endpoint_id}",
            account_scope_id=account_id,
            credential_scope_id=credential_id,
            tier_id="free",
            reference="preflight:synthetic-v1",
            source="synthetic_test",
            zero_cost_verified=True,
            paid_overflow_excluded=True,
        ),
        serializer_id="synthetic-chat-v1",
        runtime_id="synthetic-runtime-v1",
        structured_schema_ids=schemas,
        quota_membership="verified",
        quota_buckets=(QuotaBucket(
            bucket_id=f"quota:{endpoint_id}",
            authority_scope_id=account_id,
            operations=operations,
            unit="requests",
            window_seconds=3600,
            source="provider_contract",
            confidence="verified",
            evidence_reference="quota:synthetic-v1",
        ),),
    )


def _requirements(capabilities=frozenset({"bounded_generation"}), *, schema=None):
    return EndpointCandidateRequirements(
        execution_mode="STRICT_FREE",
        sensitivity="personal",
        required_capabilities=capabilities,
        input_tokens=500,
        output_tokens=100,
        structured_schema_id=schema,
    )


def _task(
    task_id="chat-generation",
    *,
    task_type="chat",
    capabilities=frozenset({"bounded_generation"}),
    quality=None,
    priorities=(),
    preferences=None,
    allow_source_narrowing=False,
):
    return RoutingTaskProfile(
        task_id=task_id,
        profile_id=f"task-profile:{task_id}",
        profile_version=1,
        task_type=task_type,
        required_capabilities=capabilities,
        quality=quality or QualityPolicy(),
        preferences=preferences or RoutingPreferences(),
        endpoint_priorities=priorities,
        allow_source_narrowing=allow_source_narrowing,
        deadline_ms=10_000,
        max_physical_attempts=2,
        max_reselections=1,
        max_auxiliary_calls=2,
    )


def _request(requirements=None, *, request_id="request-123"):
    return RoutingRequestFacts(
        request_id=request_id,
        run_id="run-123",
        requirements=requirements or _requirements(),
        policy_version="phase15-policy-v1",
        source_count=0,
        source_manifest_sha256=SOURCE_HASH,
        prepared_context_tokens=400,
        count_source="synthetic-counter-v1",
        count_confidence="unknown",
    )


def _runtime(
    profile,
    *,
    authorization="authorized",
    health="healthy",
    credential="usable",
    now=NOW,
):
    return RuntimeCandidateFacts(
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=profile.profile_version,
        authorization=authorization,
        authorization_reference="authorization:synthetic-v1" if authorization == "authorized" else None,
        credential_status=credential,
        health_status=health,
        health_reference="health:synthetic-v1",
        observed_at=now,
        fresh_until=now + timedelta(hours=1),
        exhausted=False,
    )


def _quality(profile, *, score=0.9, coverage=0.9, measured_at=None, fresh_until=None):
    return QualityEvidence(
        task_profile_id="task-profile:research-synthesis",
        task_profile_version=1,
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=profile.profile_version,
        quality_profile_id="quality:research-v1",
        quality_profile_version=1,
        score=score,
        coverage=coverage,
        measured_at=measured_at or NOW - timedelta(days=1),
        fresh_until=fresh_until or NOW + timedelta(days=1),
        evidence_reference="evaluation:research-v1",
    )


def _service(profiles, repo=None, strategy=None):
    repository = repo or _MemoryDecisionRepository()
    return RoutingDecisionService(EndpointRegistry(profiles), repository, strategy), repository


def _route(service, profile, *, task=None, request=None, runtime=None, evidence=(), signals=(), now=NOW):
    return service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=task or _task(),
        request=request or _request(),
        runtime_facts=runtime if runtime is not None else (_runtime(profile, now=now),),
        quality_evidence=evidence,
        routing_signals=signals,
        now=now,
    )


class _CapturingStrategy(DeterministicScoringStrategy):
    def __init__(self):
        self.visible_ids = ()

    def select(self, value):
        self.visible_ids = tuple(row.profile.endpoint_profile_id for row in value.candidates)
        return super().select(value)


class _IneligibleSelectingStrategy(DeterministicScoringStrategy):
    def __init__(self, ineligible_id):
        self.ineligible_id = ineligible_id

    def select(self, value):
        identity = self.identity(value)
        return RoutingStrategyResult(
            selected_endpoint_profile_id=self.ineligible_id,
            selected_profile_version=1,
            ranked_candidates=({
                "endpoint_profile_id": self.ineligible_id,
                "profile_version": 1,
                "score": 1,
                "reason_code": "invalid-selection",
            },),
            strategy_id=identity.strategy_id,
            strategy_version=identity.strategy_version,
            strategy_implementation_sha256=identity.strategy_implementation_sha256,
            configuration_version=identity.configuration_version,
            configuration_sha256=identity.configuration_sha256,
            tie_break_version=identity.tie_break_version,
            reason_code="invalid-selection",
        )


def test_known_task_taxonomy_routes_chat_and_two_non_chat_profiles_without_classification():
    profile = _profile()
    service, repository = _service((profile,))
    examples = (
        ("chat-generation", "chat", frozenset({"bounded_generation"}), None),
        ("research-synthesis", "research_synthesis", frozenset({"bounded_generation"}), None),
        (
            "itinerary-proposal",
            "structured_generation",
            frozenset({"structured_generation"}),
            "schema:proposal-v1",
        ),
    )
    results = []
    for task_id, task_type, capabilities, schema in examples:
        req = _requirements(capabilities, schema=schema)
        task = _task(task_id, task_type=task_type, capabilities=capabilities)
        result = _route(
            service,
            profile,
            task=task,
            request=_request(req, request_id=f"request:{task_id}"),
            now=NOW,
        )
        results.append(result)

    assert [result.observation.task.task_type for result in results] == [
        "chat", "research_synthesis", "structured_generation"
    ]
    assert all(result.plan is not None for result in results)
    assert len(repository.records) == 3
    assert all(result.plan.selected_endpoint_profile_id == profile.endpoint_profile_id for result in results)
    assert all("classifier" not in result.observation.model_dump_json().lower() for result in results)


def test_mandatory_quality_floor_and_static_admission_run_before_strategy_input():
    good = _profile("good")
    low_quality = _profile("low")
    private_denied = _profile(
        "private",
        policy=DataUsePolicy(status="denied", max_sensitivity="public"),
    )
    task = _task(
        "research-synthesis",
        task_type="research_synthesis",
        quality=QualityPolicy(
            mode="measured_floor",
            quality_profile_id="quality:research-v1",
            quality_profile_version=1,
            minimum_score=0.8,
            minimum_coverage=0.7,
            max_age_seconds=7 * 24 * 60 * 60,
        ),
        priorities=(
            EndpointPriority(endpoint_profile_id=good.endpoint_profile_id, priority=1),
            EndpointPriority(endpoint_profile_id=low_quality.endpoint_profile_id, priority=100),
        ),
    )
    strategy = _CapturingStrategy()
    service, _ = _service((good, low_quality, private_denied), strategy=strategy)
    result = service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=task,
        request=_request(),
        runtime_facts=tuple(_runtime(row) for row in (good, low_quality, private_denied)),
        quality_evidence=(
            _quality(good, score=0.91, coverage=0.88),
            _quality(low_quality, score=0.42, coverage=0.9),
        ),
        now=NOW,
    )

    assert strategy.visible_ids == (good.endpoint_profile_id,)
    assert result.plan.selected_endpoint_profile_id == good.endpoint_profile_id
    assessed = {row.profile.endpoint_profile_id: row for row in result.observation.candidates}
    assert "required_quality_floor_not_met" in assessed[low_quality.endpoint_profile_id].rejection_reasons
    assert "provider_data_use_denied" in assessed[private_denied.endpoint_profile_id].rejection_reasons


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (None, "required_quality_evidence_missing"),
        (
            "stale",
            "required_quality_evidence_stale_or_mismatched",
        ),
        ("coverage", "required_quality_coverage_insufficient"),
        ("floor", "required_quality_floor_not_met"),
    ],
)
def test_measured_only_tasks_reject_missing_stale_undercovered_and_below_floor(evidence, reason):
    profile = _profile()
    task = _task(
        "research-synthesis",
        task_type="research_synthesis",
        quality=QualityPolicy(
            mode="measured_floor",
            quality_profile_id="quality:research-v1",
            quality_profile_version=1,
            minimum_score=0.8,
            minimum_coverage=0.7,
            max_age_seconds=7 * 24 * 60 * 60,
        ),
    )
    measurement = None
    if evidence == "stale":
        measurement = _quality(
            profile,
            measured_at=NOW - timedelta(days=20),
            fresh_until=NOW - timedelta(days=1),
        )
    elif evidence == "coverage":
        measurement = _quality(profile, score=0.95, coverage=0.2)
    elif evidence == "floor":
        measurement = _quality(profile, score=0.4, coverage=0.9)
    service, _ = _service((profile,))
    result = _route(
        service,
        profile,
        task=task,
        evidence=() if measurement is None else (measurement,),
    )

    assert result.plan is None
    assert result.observation.lifecycle_status == "no_route"
    assert reason in result.observation.candidates[0].rejection_reasons


def test_stale_runtime_admission_facts_are_rejected_before_strategy_input():
    stale = _profile("stale")
    fresh = _profile("fresh")
    strategy = _CapturingStrategy()
    service, _ = _service((stale, fresh), strategy=strategy)

    result = service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=_task(),
        request=_request(),
        runtime_facts=(
            _runtime(stale, now=NOW - timedelta(hours=2)),
            _runtime(fresh, now=NOW),
        ),
        now=NOW,
    )

    stale_decision = next(
        row for row in result.observation.candidates
        if row.profile.endpoint_profile_id == stale.endpoint_profile_id
    )
    assert stale_decision.rejection_reasons == ("endpoint_runtime_admission_facts_stale",)
    assert strategy.visible_ids == (fresh.endpoint_profile_id,)


def test_deterministic_strategy_uses_task_preferences_and_stable_tie_breaks():
    first = _profile("a")
    second = _profile("b")
    task = _task(
        priorities=(
            EndpointPriority(endpoint_profile_id=first.endpoint_profile_id, priority=4),
            EndpointPriority(endpoint_profile_id=second.endpoint_profile_id, priority=4),
        )
    )
    service, _ = _service((second, first))
    first_run = _route(service, first, task=task, runtime=(_runtime(first), _runtime(second)))
    second_run = _route(service, first, task=task, runtime=(_runtime(first), _runtime(second)))

    assert first_run.plan.selected_endpoint_profile_id == first.endpoint_profile_id
    assert second_run.plan.selected_endpoint_profile_id == first.endpoint_profile_id
    assert first_run.observation.strategy_identity.strategy_id == "deterministic-scoring"
    assert first_run.observation.strategy_identity.tie_break_version == (
        "endpoint-profile-id-then-version-ascending-v1"
    )
    assert first_run.observation.strategy_result == second_run.observation.strategy_result


def test_unmeasured_baseline_uses_configured_priority_without_invented_quality():
    lower = _profile("lower")
    preferred = _profile("preferred")
    task = _task(
        priorities=(EndpointPriority(endpoint_profile_id=preferred.endpoint_profile_id, priority=7),)
    )
    service, _ = _service((lower, preferred))
    result = _route(service, lower, task=task, runtime=(_runtime(lower), _runtime(preferred)))

    assert result.plan.selected_endpoint_profile_id == preferred.endpoint_profile_id
    assert all(row.quality_evidence is None for row in result.observation.candidates)
    assert all(row.quality_score is None for row in result.observation.strategy_input.candidates)


def test_latency_preference_uses_fresh_signals_consistently_across_eligible_candidates():
    fast = _profile("fast")
    slow = _profile("slow")
    task = _task(preferences=RoutingPreferences(latency_penalty_per_second=10_000))
    service, _ = _service((slow, fast))
    signals = (
        RoutingSignals(
            endpoint_profile_id=fast.endpoint_profile_id,
            endpoint_profile_version=1,
            observed_at=NOW - timedelta(minutes=1),
            fresh_until=NOW + timedelta(minutes=5),
            latency_ms=100,
            evidence_reference="health:fast-v1",
        ),
        RoutingSignals(
            endpoint_profile_id=slow.endpoint_profile_id,
            endpoint_profile_version=1,
            observed_at=NOW - timedelta(minutes=1),
            fresh_until=NOW + timedelta(minutes=5),
            latency_ms=9_000,
            evidence_reference="health:slow-v1",
        ),
    )
    result = service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=task,
        request=_request(),
        runtime_facts=(_runtime(fast), _runtime(slow)),
        routing_signals=signals,
        now=NOW,
    )

    assert result.plan.selected_endpoint_profile_id == fast.endpoint_profile_id
    assert result.observation.strategy_result.reason_code == "priority-and-latency"


def test_strategy_receives_only_eligible_candidates_and_cannot_select_rejected_endpoint():
    eligible = _profile("eligible")
    rejected = _profile("rejected", policy=DataUsePolicy(status="denied"))
    strategy = _IneligibleSelectingStrategy(rejected.endpoint_profile_id)
    service, _ = _service((eligible, rejected), strategy=strategy)
    result = service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=_task(),
        request=_request(),
        runtime_facts=(_runtime(eligible), _runtime(rejected)),
        now=NOW,
    )

    assert result.plan is None
    assert result.observation.no_route_reason == "routing-strategy-contract-invalid"
    assert result.observation.strategy_input.candidates[0].profile.endpoint_profile_id == eligible.endpoint_profile_id
    assert len(result.observation.strategy_input.candidates) == 1


def test_strategy_input_does_not_expose_rejected_endpoint_priority_entries():
    eligible = _profile("eligible")
    rejected = _profile("rejected", policy=DataUsePolicy(status="denied"))
    task = _task(
        priorities=(
            EndpointPriority(endpoint_profile_id=eligible.endpoint_profile_id, priority=1),
            EndpointPriority(endpoint_profile_id=rejected.endpoint_profile_id, priority=100),
        )
    )
    service, _ = _service((eligible, rejected))
    result = service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=task,
        request=_request(),
        runtime_facts=(_runtime(eligible), _runtime(rejected)),
        now=NOW,
    )

    assert tuple(row.endpoint_profile_id for row in result.observation.strategy_input.task.endpoint_priorities) == (
        eligible.endpoint_profile_id,
    )


def test_observation_replays_exact_decision_after_registry_changes_and_expires_cleanly():
    first = _profile("first")
    second = _profile("second")
    service, _ = _service((first, second))
    decision = _route(service, first, runtime=(_runtime(first), _runtime(second)))
    replayed = replay_deterministic_decision(
        decision.observation, DeterministicScoringStrategy(), now=NOW + timedelta(seconds=1)
    )
    service.registry.remove(second.endpoint_profile_id)
    after_registry_update = replay_deterministic_decision(
        decision.observation, DeterministicScoringStrategy(), now=NOW + timedelta(seconds=2)
    )

    assert replayed == decision.observation.strategy_result == after_registry_update
    with pytest.raises(RoutingReplayUnavailable, match="expired"):
        replay_deterministic_decision(
            decision.observation,
            DeterministicScoringStrategy(),
            now=decision.observation.replay_until,
        )


def test_observation_overflow_is_explicit_no_route_with_candidate_digests():
    large_schemas = tuple(f"schema:{index}:" + "x" * 175 for index in range(128))
    profiles = tuple(
        _profile(f"large-{index}", schemas=large_schemas)
        for index in range(3)
    )
    service, _ = _service(profiles)
    result = service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=_task(),
        request=_request(),
        runtime_facts=tuple(_runtime(profile) for profile in profiles),
        now=NOW,
    )

    assert result.plan is None
    assert result.observation.no_route_reason == "routing-observation-overflow"
    assert result.observation.replay_completeness == "incomplete"
    assert len(result.observation.overflow_candidates) == 3
    assert len(result.observation.model_dump_json().encode("utf-8")) <= 65_536


def test_ready_plan_requires_exact_endpoint_preparation_revalidation_and_all_buckets():
    profile = _profile()
    service, repository = _service((profile,))
    decision = _route(service, profile)
    preparation = PreparationIdentity(
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=profile.profile_version,
        serializer_id=profile.serializer_id,
        input_tokens=400,
        count_source="synthetic-count-v1",
        count_confidence="unknown",
        source_manifest_sha256=SOURCE_HASH,
        prepared_input_sha256=sha256(b"prepared").hexdigest(),
    )
    revalidation = DispatchRevalidation(
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=profile.profile_version,
        validated_at=NOW,
        fresh_until=NOW + timedelta(minutes=5),
        policy_version="phase15-policy-v1",
        authorization_current=True,
        authorization_reference="authorization:phase15-v1",
        credential_usable=True,
        health_status="healthy",
        quota_not_exhausted=True,
        sources_authorized=True,
        source_permission_reference="source-policy:phase15-v1",
        source_manifest_sha256=SOURCE_HASH,
    )
    reservation = QuotaReservationRef(
        reservation_id=uuid4(),
        buckets=((profile.quota_buckets[0].bucket_id, 1),),
    )

    plan = service.finalize(
        owner_id=OWNER,
        scope=SCOPE,
        observation=decision.observation,
        preparation=preparation,
        reservation=reservation,
        revalidation=revalidation,
        now=NOW + timedelta(seconds=1),
    )

    assert plan.state == "ready"
    assert plan.final_fit is True
    assert plan.selected_endpoint_profile_id == profile.endpoint_profile_id
    assert plan.preparation.prepared_input_sha256 == preparation.prepared_input_sha256
    assert repository.records[decision.observation.routing_decision_id][1][-1].dispatch_revalidation == revalidation


def test_finalization_denies_fit_failure_revocation_and_incomplete_reservation():
    profile = _profile()
    service, repository = _service((profile,))
    decision = _route(service, profile)
    base = {
        "endpoint_profile_id": profile.endpoint_profile_id,
        "endpoint_profile_version": profile.profile_version,
        "serializer_id": profile.serializer_id,
        "count_source": "synthetic-count-v1",
        "count_confidence": "unknown",
        "source_manifest_sha256": SOURCE_HASH,
        "prepared_input_sha256": sha256(b"prepared").hexdigest(),
    }
    revalidation = DispatchRevalidation(
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=profile.profile_version,
        validated_at=NOW,
        fresh_until=NOW + timedelta(minutes=5),
        policy_version="phase15-policy-v1",
        authorization_current=True,
        authorization_reference="authorization:phase15-v1",
        credential_usable=True,
        health_status="healthy",
        quota_not_exhausted=True,
        sources_authorized=False,
        source_permission_reference="source-policy:phase15-v1",
        source_manifest_sha256=SOURCE_HASH,
    )
    stale_revalidation = revalidation.model_copy(update={
        "validated_at": NOW - timedelta(minutes=2),
        "fresh_until": NOW,
    })
    with pytest.raises(RoutingFinalizationError, match="routing_dispatch_revalidation_stale"):
        service.finalize(
            owner_id=OWNER,
            scope=SCOPE,
            observation=decision.observation,
            preparation=PreparationIdentity(input_tokens=400, **base),
            reservation=QuotaReservationRef(
                reservation_id=uuid4(), buckets=((profile.quota_buckets[0].bucket_id, 1),)
            ),
            revalidation=stale_revalidation,
            now=NOW + timedelta(seconds=1),
        )
    with pytest.raises(RoutingFinalizationError, match="routing_source_permission_revoked"):
        service.finalize(
            owner_id=OWNER,
            scope=SCOPE,
            observation=decision.observation,
            preparation=PreparationIdentity(input_tokens=400, **base),
            reservation=QuotaReservationRef(
                reservation_id=uuid4(), buckets=((profile.quota_buckets[0].bucket_id, 1),)
            ),
            revalidation=revalidation,
            now=NOW + timedelta(seconds=1),
        )
    assert repository.records[decision.observation.routing_decision_id][1][-1].event_type == "preparation_failed"

    revalidation = revalidation.model_copy(update={"sources_authorized": True})
    with pytest.raises(RoutingFinalizationError, match="routing_endpoint_preparation_does_not_fit"):
        service.finalize(
            owner_id=OWNER,
            scope=SCOPE,
            observation=decision.observation,
            preparation=PreparationIdentity(input_tokens=501, **base),
            reservation=QuotaReservationRef(
                reservation_id=uuid4(), buckets=((profile.quota_buckets[0].bucket_id, 1),)
            ),
            revalidation=revalidation,
            now=NOW + timedelta(seconds=2),
        )
    with pytest.raises(RoutingFinalizationError, match="routing_reservation_incomplete"):
        service.finalize(
            owner_id=OWNER,
            scope=SCOPE,
            observation=decision.observation,
            preparation=PreparationIdentity(input_tokens=400, **base),
            reservation=QuotaReservationRef(reservation_id=uuid4(), buckets=()),
            revalidation=revalidation,
            now=NOW + timedelta(seconds=3),
        )
    assert repository.records[decision.observation.routing_decision_id][1][-1].event_type == "reservation_failed"


def test_fit_failure_creates_linked_reselection_with_recomputed_bounds_and_finite_depth():
    first = _profile("first")
    second = _profile("second")
    task = _task(
        priorities=(
            EndpointPriority(endpoint_profile_id=first.endpoint_profile_id, priority=10),
            EndpointPriority(endpoint_profile_id=second.endpoint_profile_id, priority=1),
        ),
    )
    service, repository = _service((first, second))
    original = service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=task,
        request=_request(),
        runtime_facts=(_runtime(first), _runtime(second)),
        now=NOW,
    )
    revalidation = DispatchRevalidation(
        endpoint_profile_id=first.endpoint_profile_id,
        endpoint_profile_version=first.profile_version,
        validated_at=NOW,
        fresh_until=NOW + timedelta(minutes=5),
        policy_version="phase15-policy-v1",
        authorization_current=True,
        authorization_reference="authorization:phase15-v1",
        credential_usable=True,
        health_status="healthy",
        quota_not_exhausted=True,
        sources_authorized=True,
        source_permission_reference="source-policy:phase15-v1",
        source_manifest_sha256=SOURCE_HASH,
    )
    with pytest.raises(RoutingFinalizationError, match="routing_endpoint_preparation_does_not_fit"):
        service.finalize(
            owner_id=OWNER,
            scope=SCOPE,
            observation=original.observation,
            preparation=PreparationIdentity(
                endpoint_profile_id=first.endpoint_profile_id,
                endpoint_profile_version=1,
                serializer_id=first.serializer_id,
                input_tokens=501,
                count_source="synthetic-count-v1",
                count_confidence="unknown",
                source_manifest_sha256=SOURCE_HASH,
                prepared_input_sha256=sha256(b"does-not-fit").hexdigest(),
            ),
            reservation=QuotaReservationRef(
                reservation_id=uuid4(), buckets=((first.quota_buckets[0].bucket_id, 1),)
            ),
            revalidation=revalidation,
            now=NOW + timedelta(seconds=1),
        )
    narrowed = _requirements().model_copy(update={"input_tokens": 450})
    reselection = service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=task,
        request=_request(narrowed),
        runtime_facts=(_runtime(first), _runtime(second)),
        parent_decision_id=original.observation.routing_decision_id,
        now=NOW + timedelta(seconds=2),
    )

    assert reselection.observation.root_decision_id == original.observation.routing_decision_id
    assert reselection.observation.reselection_depth == 1
    assert reselection.observation.request.excluded_endpoint_profile_ids == (first.endpoint_profile_id,)
    assert reselection.plan.selected_endpoint_profile_id == second.endpoint_profile_id
    assert reselection.plan.input_tokens_bound == 450
    parent_record = repository.records[original.observation.routing_decision_id]
    assert parent_record[1][-1].event_type == "reselection_linked"
    assert parent_record[1][-1].linked_decision_id == reselection.observation.routing_decision_id

    child_revalidation = revalidation.model_copy(update={
        "endpoint_profile_id": second.endpoint_profile_id,
    })
    with pytest.raises(RoutingFinalizationError, match="routing_endpoint_preparation_does_not_fit"):
        service.finalize(
            owner_id=OWNER,
            scope=SCOPE,
            observation=reselection.observation,
            preparation=PreparationIdentity(
                endpoint_profile_id=second.endpoint_profile_id,
                endpoint_profile_version=1,
                serializer_id=second.serializer_id,
                input_tokens=451,
                count_source="synthetic-count-v1",
                count_confidence="unknown",
                source_manifest_sha256=SOURCE_HASH,
                prepared_input_sha256=sha256(b"still-does-not-fit").hexdigest(),
            ),
            reservation=QuotaReservationRef(
                reservation_id=uuid4(), buckets=((second.quota_buckets[0].bucket_id, 1),)
            ),
            revalidation=child_revalidation,
            now=NOW + timedelta(seconds=3),
        )
    with pytest.raises(ValueError, match="routing_reselection_budget_exceeded"):
        service.route(
            owner_id=OWNER,
            scope=SCOPE,
            task=task,
            request=_request(narrowed),
            runtime_facts=(_runtime(first), _runtime(second)),
            parent_decision_id=reselection.observation.routing_decision_id,
            now=NOW + timedelta(seconds=4),
        )


def test_postgres_reselection_appends_flat_parent_event_and_increments_root_budget():
    database = _RoutingSQLDatabase()
    repository = PostgresRoutingDecisionRepository(database)
    profile = _profile()
    second = _profile("model-b")
    task = _task(priorities=(
        EndpointPriority(endpoint_profile_id=profile.endpoint_profile_id, priority=10),
        EndpointPriority(endpoint_profile_id=second.endpoint_profile_id, priority=1),
    ))
    service = RoutingDecisionService(EndpointRegistry((profile, second)), repository)
    original = service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=task,
        request=_request(),
        runtime_facts=(_runtime(profile), _runtime(second)),
        now=NOW,
    )
    repository.append_event(
        owner_id=OWNER,
        scope=SCOPE,
        decision_id=original.observation.routing_decision_id,
        event=RoutingDecisionEvent(
            event_type="preparation_failed",
            occurred_at=NOW + timedelta(seconds=1),
            reason_code="fit-failed",
        ),
    )

    result = service.route(
        owner_id=OWNER,
        scope=SCOPE,
        task=task,
        request=_request(_requirements().model_copy(update={"input_tokens": 450})),
        runtime_facts=(_runtime(profile), _runtime(second)),
        parent_decision_id=original.observation.routing_decision_id,
        now=NOW + timedelta(seconds=2),
    )

    stored_parent = repository.get(
        owner_id=OWNER,
        scope=SCOPE,
        decision_id=original.observation.routing_decision_id,
    )
    assert stored_parent.events[-1].event_type == "reselection_linked"
    assert stored_parent.events[-1].linked_decision_id == result.observation.routing_decision_id
    assert all(isinstance(event, RoutingDecisionEvent) for event in stored_parent.events)
    assert database.connection_value.records[original.observation.routing_decision_id][
        "reselection_count"
    ] == 1


def test_execution_plan_rejects_unbounded_or_cross_endpoint_final_facts():
    with pytest.raises(ValidationError, match="ready_execution_plan_requires_fit_and_reservation"):
        from personal_ai.routing import ExecutionPlan

        ExecutionPlan(
            state="ready",
            routing_decision_id=uuid4(),
            task_id="chat-generation",
            task_profile_id="profile:chat-v1",
            task_profile_version=1,
            selected_endpoint_profile_id="model:a",
            selected_profile_version=1,
            reselection_candidate_refs=(),
            execution_mode="STRICT_FREE",
            required_capabilities=frozenset({"bounded_generation"}),
            max_physical_attempts=1,
            max_reselections=0,
            max_auxiliary_calls=0,
            deadline_ms=5000,
            input_tokens_bound=100,
            output_tokens_bound=40,
            registry_version="registry:v1",
            policy_version="policy:v1",
            strategy_id="deterministic-scoring",
            strategy_version="1",
            strategy_reason_code="configured-priority",
        )


def test_postgres_observation_repository_scopes_reads_and_appends_lifecycle_events():
    database = _RoutingSQLDatabase()
    repository = PostgresRoutingDecisionRepository(database)
    profile = _profile()
    now = datetime.now(UTC)
    service = RoutingDecisionService(EndpointRegistry((profile,)), repository)
    result = _route(service, profile, now=now)
    invocation_id = uuid4()
    event = RoutingDecisionEvent(
        event_type="dispatch_completed",
        occurred_at=now + timedelta(seconds=2),
        endpoint_profile_id=profile.endpoint_profile_id,
        invocation_id=invocation_id,
        attempt_id=uuid4(),
        outcome_code="success",
    )

    appended = repository.append_event(
        owner_id=OWNER,
        scope=SCOPE,
        decision_id=result.observation.routing_decision_id,
        event=event,
    )
    loaded = repository.get(
        owner_id=OWNER,
        scope=SCOPE,
        decision_id=result.observation.routing_decision_id,
    )
    by_request = repository.list(owner_id=OWNER, scope=SCOPE, request_id="request-123")
    by_invocation = repository.list(owner_id=OWNER, scope=SCOPE, invocation_id=invocation_id)

    assert len(appended.events) == 2
    assert loaded.observation == result.observation
    assert by_request[0].observation.routing_decision_id == result.observation.routing_decision_id
    assert by_invocation[0].events[-1].invocation_id == invocation_id
    by_time = repository.list(
        owner_id=OWNER,
        scope=SCOPE,
        created_after=now - timedelta(seconds=1),
        created_before=now + timedelta(seconds=1),
    )
    assert by_time[0].observation.routing_decision_id == result.observation.routing_decision_id
    with pytest.raises(RoutingDecisionUnavailable):
        repository.get(
            owner_id="another-owner",
            scope=SCOPE,
            decision_id=result.observation.routing_decision_id,
        )
    database.connection_value.fenced_owners.add(OWNER)
    with pytest.raises(RoutingDecisionUnavailable):
        repository.get(
            owner_id=OWNER,
            scope=SCOPE,
            decision_id=result.observation.routing_decision_id,
        )


def test_postgres_observation_repository_hides_expired_replay_inputs():
    database = _RoutingSQLDatabase()
    repository = PostgresRoutingDecisionRepository(database)
    profile = _profile()
    service = RoutingDecisionService(EndpointRegistry((profile,)), repository)
    result = _route(service, profile, now=datetime.now(UTC))
    database.connection_value.records[result.observation.routing_decision_id]["replay_until"] = (
        datetime.now(UTC) - timedelta(seconds=1)
    )

    with pytest.raises(RoutingDecisionUnavailable, match="unavailable"):
        repository.get(
            owner_id=OWNER,
            scope=SCOPE,
            decision_id=result.observation.routing_decision_id,
        )


def test_phase21_migration_and_owner_export_inventory_cover_bounded_decision_records():
    from pathlib import Path

    from personal_ai.auth.owner_data import OWNER_DATA_COLLECTIONS

    migration = (
        Path(__file__).parents[1]
        / "src/personal_ai/persistence/migrations/020_routing_decisions.sql"
    ).read_text(encoding="utf-8")
    export_repository = (
        Path(__file__).parents[1] / "src/personal_ai/persistence/postgres_auth.py"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS routing_decisions" in migration
    assert "decision_facts jsonb NOT NULL" in migration
    assert "jsonb_array_length(outcome_events) BETWEEN 1 AND 32" in migration
    assert "routing_decisions_invocation_idx" in migration
    assert "routing_decisions_attempt_idx" in migration
    assert "routing_decisions_evaluation_idx" in migration
    assert "routing_decisions_expiry_idx" in migration
    assert "FOREIGN KEY (scope_id,parent_decision_id)" in migration
    assert "FOREIGN KEY (scope_id,root_decision_id)" in migration
    assert "routing_decisions" in OWNER_DATA_COLLECTIONS
    assert "FROM routing_decisions WHERE owner_id=%s AND application_id=%s" in export_repository
    assert 'p_collection_counts["routing_decisions"]' in export_repository


def test_decision_observation_rejects_raw_prompt_retention_and_oversize_plan_refs():
    assert RoutingDecisionObservation.model_fields["request"].annotation is RoutingRequestFacts
    with pytest.raises(ValidationError):
        RoutingRequestFacts(
            request_id="request-123",
            requirements=_requirements(),
            policy_version="policy:v1",
            prompt="private prompt text",
        )
