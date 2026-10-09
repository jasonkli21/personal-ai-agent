"""Deterministic contract coverage for task-aware Phase 21 routing."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4, uuid5

import pytest
from pydantic import ValidationError

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres import PersistenceConflict
from personal_ai.persistence.postgres_routing_observations import (
    PostgresRoutingDecisionRepository,
    RoutingDecisionUnavailable,
)
from personal_ai.routing import (
    CounterCompatibility,
    CountRequirement,
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
    source_reference_manifest_sha256,
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
        self.auxiliary_counts = {}

    def begin(self, *, owner_id, scope, observation, initial_event):
        assert observation.owner_id == owner_id
        assert observation.application_id == scope.application_id
        assert observation.workspace_id == scope.workspace_id
        RoutingDecisionRecord(observation=observation, events=(initial_event,))
        if observation.routing_decision_id in self.records:
            if self.records[observation.routing_decision_id] != [
                observation, [initial_event]
            ]:
                raise ValueError("routing decision idempotency conflict")
            return
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
        duplicate = next((row for row in events if row.event_id == event.event_id), None)
        if duplicate is not None:
            if duplicate != event:
                raise ValueError("routing event idempotency conflict")
            return RoutingDecisionRecord(observation=observation, events=tuple(events))
        updated = RoutingDecisionRecord(observation=observation, events=(*events, event))
        events.append(event)
        return updated

    def consume_auxiliary_call(
        self, *, owner_id, scope, decision_id, max_auxiliary_calls, event
    ):
        observation, events = self.records[decision_id]
        root_id = observation.root_decision_id
        used = self.auxiliary_counts.get(root_id, 0)
        duplicate = next((row for row in events if row.event_id == event.event_id), None)
        if duplicate is not None:
            if duplicate != event:
                raise ValueError("routing event idempotency conflict")
            return used
        if used >= max_auxiliary_calls:
            raise ValueError("routing_auxiliary_call_budget_exceeded")
        self.append_event(
            owner_id=owner_id, scope=scope, decision_id=decision_id, event=event
        )
        self.auxiliary_counts[root_id] = used + 1
        return used + 1

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
                event_id=uuid5(observation.routing_decision_id, "phase21-parent-link-v1"),
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
                "auxiliary_calls_used": 0,
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
            if "auxiliary_calls_used=auxiliary_calls_used+1" in query:
                record = self.records.get(params[1])
                if (
                    record is None
                    or record["scope_id"] != params[0]
                    or record["owner_id"] != params[2]
                    or record["auxiliary_calls_used"] >= params[3]
                    or record["replay_until"] <= params[4]
                ):
                    return _SQLResult()
                record["auxiliary_calls_used"] += 1
                return _SQLResult((record["auxiliary_calls_used"],), rowcount=1)
            if "outcome_events=%s::jsonb,updated_at=%s" in query and len(params) == 7:
                record = self.records.get(params[3])
                if (
                    record is None
                    or record["scope_id"] != params[2]
                    or record["owner_id"] != params[4]
                    or record["replay_until"] <= params[5]
                ):
                    return _SQLResult()
                record["events"] = json.loads(params[0])
                return _SQLResult((params[3],), rowcount=1)
            if "outcome_events=%s::jsonb" in query:
                record = self.records.get(params[9])
                if (
                    record is None
                    or record["scope_id"] != params[8]
                    or record["owner_id"] != params[10]
                    or record["application_id"] != params[11]
                    or record["workspace_id"] != params[12]
                    or record["replay_until"] <= params[13]
                ):
                    return _SQLResult(rowcount=0)
                record["events"] = json.loads(params[0])
                if params[1] is not None:
                    record["invocation_ids"].append(params[1])
                if params[4] is not None:
                    record["attempt_ids"].append(params[4])
                if params[6] is not None:
                    record["evaluation_run_ids"].append(params[6])
                return _SQLResult((params[9],), rowcount=1)
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
            if len(params) == 6:
                scope_id, decision_id, owner_id, application_id, workspace_id, now = params
                record = self.records.get(decision_id)
                if (
                    record is None
                    or record["scope_id"] != scope_id
                    or record["owner_id"] != owner_id
                    or record["application_id"] != application_id
                    or record["workspace_id"] != workspace_id
                    or record["replay_until"] <= now
                ):
                    return _SQLResult()
                return _SQLResult((record["facts"], record["events"]))
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
        if query.startswith("SELECT decision_facts FROM routing_decisions WHERE"):
            record = self.records.get(params[1])
            if (
                record is None
                or record["scope_id"] != params[0]
                or record["owner_id"] != params[2]
                or record["application_id"] != params[3]
                or record["workspace_id"] != params[4]
                or record["replay_until"] <= params[5]
            ):
                return _SQLResult()
            return _SQLResult((record["facts"],))
        if query.startswith("SELECT auxiliary_calls_used,decision_facts,replay_until"):
            record = self.records.get(params[1])
            if record is None or record["owner_id"] != params[2]:
                return _SQLResult()
            return _SQLResult((
                record["auxiliary_calls_used"], record["facts"], record["replay_until"],
            ))
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


class _MemoryReservationAuthority:
    def __init__(self):
        self.accepted = {}

    def trust(self, reservation, facts):
        self.accepted[(reservation.invocation_id, reservation.attempt_id)] = (
            reservation, facts
        )

    def verify_routing_reservation(self, *, reservation, **facts):
        return self.accepted.get((reservation.invocation_id, reservation.attempt_id)) == (
            reservation, facts
        )


def _profile(
    endpoint_id="model-a",
    *,
    version=1,
    capabilities=frozenset({"bounded_generation", "streaming", "structured_generation"}),
    operations=frozenset({"bounded_generation", "streaming", "structured_generation"}),
    policy=None,
    schemas=("schema:proposal-v1",),
    with_counter=False,
    separate_operation_buckets=False,
):
    profile_id = f"synthetic:{endpoint_id}"
    account_id = f"account:{endpoint_id}"
    credential_id = f"credential:{endpoint_id}"
    quota_buckets = (
        (
            QuotaBucket(
                bucket_id=f"quota:{endpoint_id}:generation",
                authority_scope_id=account_id,
                operations=frozenset(operations - {"token_counting"}),
                unit="requests",
                window_seconds=3600,
                source="provider_contract",
                confidence="verified",
                evidence_reference="quota:synthetic-generation-v1",
            ),
            QuotaBucket(
                bucket_id=f"quota:{endpoint_id}:counter",
                authority_scope_id=account_id,
                operations=frozenset({"token_counting"}),
                unit="requests",
                window_seconds=3600,
                source="provider_contract",
                confidence="verified",
                evidence_reference="quota:synthetic-counter-v1",
            ),
        )
        if separate_operation_buckets else
        (QuotaBucket(
            bucket_id=f"quota:{endpoint_id}",
            authority_scope_id=account_id,
            operations=operations,
            unit="requests",
            window_seconds=3600,
            source="provider_contract",
            confidence="verified",
            evidence_reference="quota:synthetic-v1",
        ),)
    )
    counter = CounterCompatibility(
        endpoint_profile_id=profile_id,
        endpoint_id=f"endpoint:{endpoint_id}",
        deployment_id=f"deployment:{endpoint_id}",
        credential_scope_id=credential_id,
        account_scope_id=account_id,
        provider_id="synthetic-provider",
        model_id=endpoint_id,
        serializer_id="synthetic-chat-v1",
        counter_id="synthetic-counter-v1",
        confidence="authoritative",
        approved=True,
        provenance_reference="counter:synthetic-v1",
        structured_schema_ids=schemas,
    ) if with_counter else None
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
        counter=counter,
        structured_schema_ids=schemas,
        quota_membership="verified",
        quota_buckets=quota_buckets,
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
    max_reselections=1,
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
        max_reselections=max_reselections,
        max_auxiliary_calls=2,
    )


def _request(requirements=None, *, request_id="request-123", source_refs=()):
    source_refs = tuple(sorted(source_refs))
    return RoutingRequestFacts(
        request_id=request_id,
        run_id="run-123",
        requirements=requirements or _requirements(),
        policy_version="phase15-policy-v1",
        source_count=len(source_refs),
        source_manifest_sha256=source_reference_manifest_sha256(source_refs),
        source_reference_sha256s=source_refs,
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


def _service(profiles, repo=None, strategy=None, reservation_authority=True):
    repository = repo or _MemoryDecisionRepository()
    authority = (
        _MemoryReservationAuthority()
        if reservation_authority is True
        else None if reservation_authority is False else reservation_authority
    )
    return RoutingDecisionService(
        EndpointRegistry(profiles), repository, strategy, authority
    ), repository


def _reservation(service, decision, profile, *, now, operation="bounded_generation"):
    invocation_id = uuid4()
    attempt_id = uuid4()
    expected_bucket_ids = frozenset(
        bucket.bucket_id for bucket in profile.quota_buckets
        if operation in bucket.operations
    )
    reservation = QuotaReservationRef(
        invocation_id=invocation_id,
        attempt_id=attempt_id,
        send_number=1,
        operation=operation,
        reserved_at=NOW + timedelta(milliseconds=500),
        buckets=tuple((bucket_id, 0) for bucket_id in sorted(expected_bucket_ids)),
    )
    facts = {
        "owner_id": OWNER,
        "scope": SCOPE,
        "request_id": decision.observation.request.request_id,
        "run_id": decision.observation.request.run_id,
        "routing_decision_id": decision.observation.routing_decision_id,
        "endpoint_profile_id": profile.endpoint_profile_id,
        "endpoint_profile_version": profile.profile_version,
        "operation": operation,
        "expected_bucket_ids": expected_bucket_ids,
        "max_physical_attempts": decision.observation.task.max_physical_attempts,
        "now": now,
    }
    if service.reservation_authority is not None:
        service.reservation_authority.trust(reservation, facts)
    return reservation


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


def _mark_preparation_failed(repository, observation, at):
    repository.append_event(
        owner_id=observation.owner_id,
        scope=ApplicationScope(
            application_id=observation.application_id,
            workspace_id=observation.workspace_id,
        ),
        decision_id=observation.routing_decision_id,
        event=RoutingDecisionEvent(
            event_type="preparation_failed",
            occurred_at=at,
            endpoint_profile_id=observation.provisional_plan.selected_endpoint_profile_id,
            reason_code="fit-failed",
        ),
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
    service, repository = _service((second, first))
    first_run = _route(service, first, task=task, runtime=(_runtime(first), _runtime(second)))
    second_run = _route(service, first, task=task, runtime=(_runtime(first), _runtime(second)))

    assert first_run.plan.selected_endpoint_profile_id == first.endpoint_profile_id
    assert second_run.plan.selected_endpoint_profile_id == first.endpoint_profile_id
    assert first_run.observation.strategy_identity.strategy_id == "deterministic-scoring"
    assert first_run.observation.strategy_identity.tie_break_version == (
        "endpoint-profile-id-then-version-ascending-v1"
    )
    assert first_run.observation.strategy_result == second_run.observation.strategy_result
    assert first_run.observation.routing_decision_id == second_run.observation.routing_decision_id
    assert len(repository.records) == 1


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
    assert result.observation.strategy_result is None
    assert result.observation.strategy_input.candidates[0].profile.endpoint_profile_id == eligible.endpoint_profile_id
    assert len(result.observation.strategy_input.candidates) == 1
    with pytest.raises(RoutingReplayUnavailable, match="no validated strategy result"):
        replay_deterministic_decision(
            result.observation, strategy, now=NOW + timedelta(seconds=1)
        )


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


def test_replay_returns_unavailable_when_same_identity_produces_a_different_result():
    profile = _profile()
    service, _ = _service((profile,))
    decision = _route(service, profile)
    strategy = DeterministicScoringStrategy()
    strategy.select = lambda _value: decision.observation.strategy_result.model_copy(
        update={"reason_code": "changed-behavior"}
    )

    with pytest.raises(RoutingReplayUnavailable, match="outcome mismatch"):
        replay_deterministic_decision(
            decision.observation, strategy, now=NOW + timedelta(seconds=1)
        )


def test_strategy_identity_fails_closed_when_implementation_source_is_unavailable(monkeypatch):
    profile = _profile()
    service, _ = _service((profile,))
    decision = _route(service, profile)
    monkeypatch.setattr(
        "personal_ai.routing.strategy.inspect.getsource",
        lambda _value: (_ for _ in ()).throw(OSError("source unavailable")),
    )

    with pytest.raises(RoutingReplayUnavailable, match="implementation digest unavailable"):
        DeterministicScoringStrategy().identity(decision.observation.strategy_input)


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
        prepared_at=NOW,
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
    reservation = _reservation(service, decision, profile, now=NOW + timedelta(seconds=1))

    plan = service.finalize(
        owner_id=OWNER,
        scope=SCOPE,
        observation=decision.observation,
        preparation=preparation,
        reservation=reservation,
        revalidation=revalidation,
        operation="bounded_generation",
        now=NOW + timedelta(seconds=1),
    )

    assert plan.state == "ready"
    assert plan.final_fit is True
    assert plan.selected_endpoint_profile_id == profile.endpoint_profile_id
    assert plan.preparation.prepared_input_sha256 == preparation.prepared_input_sha256
    assert repository.records[decision.observation.routing_decision_id][1][-1].dispatch_revalidation == revalidation


def test_generation_reservation_uses_only_generation_operation_buckets():
    capabilities = frozenset({"bounded_generation", "token_counting"})
    profile = _profile(
        capabilities=capabilities,
        operations=capabilities,
        with_counter=True,
        separate_operation_buckets=True,
    )
    requirements = EndpointCandidateRequirements(
        execution_mode="STRICT_FREE",
        sensitivity="personal",
        required_capabilities=capabilities,
        input_tokens=500,
        output_tokens=100,
        count=CountRequirement(minimum_confidence="authoritative"),
    )
    service, _ = _service((profile,))
    decision = _route(service, profile, request=_request(requirements))
    preparation = PreparationIdentity(
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=profile.profile_version,
        serializer_id=profile.serializer_id,
        counter_id=profile.counter.counter_id,
        input_tokens=400,
        count_source="synthetic-count-v1",
        count_confidence="authoritative",
        source_manifest_sha256=SOURCE_HASH,
        prepared_input_sha256=sha256(b"counted-generation-input").hexdigest(),
        prepared_at=NOW,
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
    reservation = _reservation(
        service, decision, profile, now=NOW + timedelta(seconds=1),
        operation="bounded_generation",
    )

    ready = service.finalize(
        owner_id=OWNER, scope=SCOPE, observation=decision.observation,
        preparation=preparation, reservation=reservation,
        revalidation=revalidation, operation="bounded_generation",
        now=NOW + timedelta(seconds=1),
    )

    assert ready.physical_operation == "bounded_generation"
    assert tuple(bucket_id for bucket_id, _ in ready.reservation.buckets) == (
        f"quota:{profile.model_id}:generation",
    )


def test_finalize_reloads_canonical_decision_and_rejects_stale_or_fabricated_facts():
    profile = _profile()
    service, repository = _service((profile,))
    decision = _route(service, profile)
    forged_plan = decision.observation.provisional_plan.model_copy(update={
        "selected_endpoint_profile_id": "synthetic:forged",
    })
    forged = decision.observation.model_copy(update={"provisional_plan": forged_plan})
    preparation = PreparationIdentity(
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=1,
        serializer_id=profile.serializer_id,
        input_tokens=400,
        count_source="synthetic-count-v1",
        count_confidence="unknown",
        source_manifest_sha256=SOURCE_HASH,
        prepared_input_sha256=sha256(b"prepared").hexdigest(),
        prepared_at=NOW,
    )
    revalidation = DispatchRevalidation(
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=1,
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
    reservation = _reservation(service, decision, profile, now=NOW + timedelta(seconds=1))
    with pytest.raises(RoutingFinalizationError, match="routing_decision_facts_changed"):
        service.finalize(
            owner_id=OWNER, scope=SCOPE, observation=forged, preparation=preparation,
            reservation=reservation, revalidation=revalidation,
            operation="bounded_generation", now=NOW + timedelta(seconds=1),
        )

    _mark_preparation_failed(repository, decision.observation, NOW + timedelta(seconds=1))
    with pytest.raises(
        RoutingFinalizationError, match="routing_decision_lifecycle_not_finalizable"
    ):
        service.finalize(
            owner_id=OWNER, scope=SCOPE, observation=decision.observation,
            preparation=preparation,
            reservation=_reservation(service, decision, profile, now=NOW + timedelta(seconds=2)),
            revalidation=revalidation, operation="bounded_generation",
            now=NOW + timedelta(seconds=2),
        )


def test_fabricated_phase19_attempt_identity_cannot_authorize_a_ready_plan():
    profile = _profile()
    service, _ = _service((profile,), reservation_authority=False)
    decision = _route(service, profile)
    reservation = QuotaReservationRef(
        invocation_id=uuid4(), attempt_id=uuid4(), send_number=1,
        operation="bounded_generation", reserved_at=NOW + timedelta(milliseconds=500),
        buckets=((profile.quota_buckets[0].bucket_id, 0),),
    )
    with pytest.raises(RoutingFinalizationError, match="routing_reservation_not_authoritative"):
        service.finalize(
            owner_id=OWNER, scope=SCOPE, observation=decision.observation,
            preparation=PreparationIdentity(
                endpoint_profile_id=profile.endpoint_profile_id,
                endpoint_profile_version=1,
                serializer_id=profile.serializer_id,
                input_tokens=400,
                count_source="synthetic-count-v1",
                count_confidence="unknown",
                source_manifest_sha256=SOURCE_HASH,
                prepared_input_sha256=sha256(b"fabricated").hexdigest(),
                prepared_at=NOW,
            ),
            reservation=reservation,
            revalidation=DispatchRevalidation(
                endpoint_profile_id=profile.endpoint_profile_id,
                endpoint_profile_version=1,
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
            ),
            operation="bounded_generation", now=NOW + timedelta(seconds=1),
        )


def test_finalization_denies_stale_revalidation_revocation_fit_failure_and_incomplete_reservation():
    profile = _profile()
    service, repository = _service((profile,))
    base = {
        "endpoint_profile_id": profile.endpoint_profile_id,
        "endpoint_profile_version": profile.profile_version,
        "serializer_id": profile.serializer_id,
        "count_source": "synthetic-count-v1",
        "count_confidence": "unknown",
        "source_manifest_sha256": SOURCE_HASH,
        "prepared_input_sha256": sha256(b"prepared").hexdigest(),
        "prepared_at": NOW,
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
    })
    stale_decision = _route(
        service, profile, request=_request(request_id="request:stale-revalidation")
    )
    with pytest.raises(
        RoutingFinalizationError, match="routing_dispatch_revalidation_order_invalid"
    ):
        service.finalize(
            owner_id=OWNER,
            scope=SCOPE,
            observation=stale_decision.observation,
            preparation=PreparationIdentity(input_tokens=400, **base),
            reservation=_reservation(
                service, stale_decision, profile, now=NOW + timedelta(seconds=1)
            ),
            revalidation=stale_revalidation,
            operation="bounded_generation",
            now=NOW + timedelta(seconds=1),
        )
    revoked_decision = _route(
        service, profile, request=_request(request_id="request:revoked")
    )
    with pytest.raises(RoutingFinalizationError, match="routing_source_permission_revoked"):
        service.finalize(
            owner_id=OWNER,
            scope=SCOPE,
            observation=revoked_decision.observation,
            preparation=PreparationIdentity(input_tokens=400, **base),
            reservation=_reservation(
                service, revoked_decision, profile, now=NOW + timedelta(seconds=1)
            ),
            revalidation=revalidation,
            operation="bounded_generation",
            now=NOW + timedelta(seconds=1),
        )
    assert repository.records[revoked_decision.observation.routing_decision_id][1][-1].event_type == "preparation_failed"

    revalidation = revalidation.model_copy(update={"sources_authorized": True})
    fit_decision = _route(
        service, profile, request=_request(request_id="request:fit")
    )
    with pytest.raises(RoutingFinalizationError, match="routing_endpoint_preparation_does_not_fit"):
        service.finalize(
            owner_id=OWNER,
            scope=SCOPE,
            observation=fit_decision.observation,
            preparation=PreparationIdentity(input_tokens=501, **base),
            reservation=_reservation(
                service, fit_decision, profile, now=NOW + timedelta(seconds=1)
            ),
            revalidation=revalidation,
            operation="bounded_generation",
            now=NOW + timedelta(seconds=1),
        )
    bucket_decision = _route(
        service, profile, request=_request(request_id="request:bucket")
    )
    incomplete = _reservation(
        service, bucket_decision, profile, now=NOW + timedelta(seconds=1)
    ).model_copy(update={"buckets": ()})
    service.reservation_authority.trust(incomplete, {
        "owner_id": OWNER,
        "scope": SCOPE,
        "request_id": bucket_decision.observation.request.request_id,
        "run_id": bucket_decision.observation.request.run_id,
        "routing_decision_id": bucket_decision.observation.routing_decision_id,
        "endpoint_profile_id": profile.endpoint_profile_id,
        "endpoint_profile_version": profile.profile_version,
        "operation": "bounded_generation",
        "expected_bucket_ids": frozenset({profile.quota_buckets[0].bucket_id}),
        "max_physical_attempts": bucket_decision.observation.task.max_physical_attempts,
        "now": NOW + timedelta(seconds=1),
    })
    with pytest.raises(RoutingFinalizationError, match="routing_reservation_incomplete"):
        service.finalize(
            owner_id=OWNER,
            scope=SCOPE,
            observation=bucket_decision.observation,
            preparation=PreparationIdentity(input_tokens=400, **base),
            reservation=incomplete,
            revalidation=revalidation,
            operation="bounded_generation",
            now=NOW + timedelta(seconds=2),
        )
    assert repository.records[bucket_decision.observation.routing_decision_id][1][-1].event_type == "reservation_failed"


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
                prepared_at=NOW,
            ),
            reservation=_reservation(
                service, original, first, now=NOW + timedelta(seconds=1)
            ),
            revalidation=revalidation,
            operation="bounded_generation",
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
        "validated_at": NOW + timedelta(seconds=2),
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
                prepared_at=NOW + timedelta(seconds=2),
            ),
            reservation=_reservation(
                service, reselection, second, now=NOW + timedelta(seconds=3)
            ),
            revalidation=child_revalidation,
            operation="bounded_generation",
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


def test_reselection_preserves_security_schema_and_capability_requirements():
    profile = _profile()
    service, repository = _service((profile,))
    requirements = _requirements(
        frozenset({"bounded_generation", "streaming", "structured_generation"}),
        schema="schema:proposal-v1",
    )
    task = _task(capabilities=frozenset({"bounded_generation"}))
    original = _route(service, profile, task=task, request=_request(requirements))
    _mark_preparation_failed(repository, original.observation, NOW + timedelta(seconds=1))

    downgraded = (
        requirements.model_copy(update={"sensitivity": "public"}),
        requirements.model_copy(update={"structured_schema_id": None}),
        requirements.model_copy(update={
            "required_capabilities": frozenset({"bounded_generation", "structured_generation"})
        }),
    )
    for index, child_requirements in enumerate(downgraded):
        with pytest.raises(ValueError, match="routing_reselection_parent_not_retryable"):
            service.route(
                owner_id=OWNER,
                scope=SCOPE,
                task=task,
                request=_request(child_requirements),
                runtime_facts=(_runtime(profile),),
                parent_decision_id=original.observation.routing_decision_id,
                now=NOW + timedelta(seconds=2 + index),
            )

    count_requirements = EndpointCandidateRequirements(
        execution_mode="STRICT_FREE",
        sensitivity="personal",
        required_capabilities=frozenset({"bounded_generation", "token_counting"}),
        input_tokens=500,
        output_tokens=100,
        count=CountRequirement(minimum_confidence="reported"),
    )
    weakened_count = count_requirements.model_copy(update={
        "count": CountRequirement(minimum_confidence="unknown"),
    })
    from personal_ai.routing.phase21 import reselection_requirements_preserved

    assert not reselection_requirements_preserved(count_requirements, weakened_count)


def test_depth_two_reselection_inherits_all_prior_endpoint_exclusions():
    first, second, third = (_profile(name) for name in ("first", "second", "third"))
    task = _task(
        priorities=(
            EndpointPriority(endpoint_profile_id=first.endpoint_profile_id, priority=10),
            EndpointPriority(endpoint_profile_id=second.endpoint_profile_id, priority=5),
            EndpointPriority(endpoint_profile_id=third.endpoint_profile_id, priority=1),
        ),
        max_reselections=2,
    )
    service, repository = _service((first, second, third))
    original = service.route(
        owner_id=OWNER, scope=SCOPE, task=task, request=_request(),
        runtime_facts=(_runtime(first), _runtime(second), _runtime(third)), now=NOW,
    )
    _mark_preparation_failed(repository, original.observation, NOW + timedelta(seconds=1))
    child = service.route(
        owner_id=OWNER, scope=SCOPE, task=task, request=_request(),
        runtime_facts=(_runtime(first), _runtime(second), _runtime(third)),
        parent_decision_id=original.observation.routing_decision_id,
        now=NOW + timedelta(seconds=2),
    )
    assert child.plan.selected_endpoint_profile_id == second.endpoint_profile_id
    _mark_preparation_failed(repository, child.observation, NOW + timedelta(seconds=3))

    grandchild = service.route(
        owner_id=OWNER, scope=SCOPE, task=task, request=_request(),
        runtime_facts=(_runtime(first), _runtime(second), _runtime(third)),
        parent_decision_id=child.observation.routing_decision_id,
        now=NOW + timedelta(seconds=4),
    )

    assert grandchild.observation.reselection_depth == 2
    assert grandchild.observation.request.excluded_endpoint_profile_ids == tuple(sorted((
        first.endpoint_profile_id, second.endpoint_profile_id,
    )))
    assert grandchild.plan.selected_endpoint_profile_id == third.endpoint_profile_id


def test_source_narrowing_is_proven_and_broadening_is_rejected_at_depth_two():
    first, second = _profile("first"), _profile("second")
    task = _task(
        allow_source_narrowing=True,
        max_reselections=2,
        priorities=(
            EndpointPriority(endpoint_profile_id=first.endpoint_profile_id, priority=10),
            EndpointPriority(endpoint_profile_id=second.endpoint_profile_id, priority=1),
        ),
    )
    service, repository = _service((first, second))
    source_a, source_b, source_c = (
        sha256(value).hexdigest() for value in (b"source-a", b"source-b", b"source-c")
    )
    original = _route(
        service, first, task=task,
        request=_request(request_id="request:narrowing", source_refs=(source_a, source_b)),
        runtime=(_runtime(first), _runtime(second)),
    )
    _mark_preparation_failed(repository, original.observation, NOW + timedelta(seconds=1))
    child = service.route(
        owner_id=OWNER, scope=SCOPE, task=task,
        request=_request(request_id="request:narrowing", source_refs=(source_a,)),
        runtime_facts=(_runtime(first), _runtime(second)),
        parent_decision_id=original.observation.routing_decision_id,
        now=NOW + timedelta(seconds=2),
    )
    assert child.plan.selected_endpoint_profile_id == second.endpoint_profile_id
    assert child.observation.request.source_reference_sha256s == (source_a,)

    _mark_preparation_failed(repository, child.observation, NOW + timedelta(seconds=3))
    with pytest.raises(ValueError, match="routing_reselection_parent_not_retryable"):
        service.route(
            owner_id=OWNER, scope=SCOPE, task=task,
            request=_request(
                request_id="request:narrowing", source_refs=(source_a, source_b, source_c)
            ),
            runtime_facts=(_runtime(first), _runtime(second)),
            parent_decision_id=child.observation.routing_decision_id,
            now=NOW + timedelta(seconds=4),
        )


def test_bounded_source_manifest_fits_the_final_lifecycle_event():
    profile = _profile()
    service, repository = _service((profile,))
    source_refs = tuple(sorted(
        sha256(f"source-{index}".encode()).hexdigest() for index in range(64)
    ))
    source_manifest = source_reference_manifest_sha256(source_refs)
    request = _request(source_refs=source_refs)
    decision = _route(service, profile, request=request)
    preparation = PreparationIdentity(
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=profile.profile_version,
        serializer_id=profile.serializer_id,
        input_tokens=400,
        count_source="synthetic-count-v1",
        count_confidence="unknown",
        source_manifest_sha256=source_manifest,
        source_reference_sha256s=source_refs,
        prepared_input_sha256=sha256(b"prepared-with-bounded-sources").hexdigest(),
        prepared_at=NOW,
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
        source_manifest_sha256=source_manifest,
        source_reference_sha256s=source_refs,
    )

    plan = service.finalize(
        owner_id=OWNER,
        scope=SCOPE,
        observation=decision.observation,
        preparation=preparation,
        reservation=_reservation(service, decision, profile, now=NOW + timedelta(seconds=1)),
        revalidation=revalidation,
        operation="bounded_generation",
        now=NOW + timedelta(seconds=1),
    )

    event = repository.records[decision.observation.routing_decision_id][1][-1]
    assert plan.state == "ready"
    assert len(event.model_dump_json().encode("utf-8")) <= 16_384
    too_many_refs = tuple(sorted(
        sha256(f"source-{index}".encode()).hexdigest() for index in range(65)
    ))
    with pytest.raises(ValidationError):
        _request(source_refs=too_many_refs)


def test_root_deadline_is_inherited_and_expired_reselection_cannot_finalize():
    first, second = _profile("first"), _profile("second")
    task = _task(
        priorities=(
            EndpointPriority(endpoint_profile_id=first.endpoint_profile_id, priority=10),
            EndpointPriority(endpoint_profile_id=second.endpoint_profile_id, priority=1),
        ),
    )
    service, repository = _service((first, second))
    original = service.route(
        owner_id=OWNER, scope=SCOPE, task=task, request=_request(),
        runtime_facts=(_runtime(first), _runtime(second)), now=NOW,
    )
    _mark_preparation_failed(repository, original.observation, NOW + timedelta(seconds=1))
    child = service.route(
        owner_id=OWNER, scope=SCOPE, task=task, request=_request(),
        runtime_facts=(_runtime(first, now=NOW + timedelta(seconds=9)),
                       _runtime(second, now=NOW + timedelta(seconds=9))),
        parent_decision_id=original.observation.routing_decision_id,
        now=NOW + timedelta(seconds=9),
    )
    assert child.observation.root_deadline_at == original.observation.root_deadline_at
    assert child.plan.root_deadline_at == original.observation.root_deadline_at
    revalidation = DispatchRevalidation(
        endpoint_profile_id=second.endpoint_profile_id,
        endpoint_profile_version=1,
        validated_at=NOW + timedelta(seconds=9),
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
    reservation = _reservation(service, child, second, now=NOW + timedelta(seconds=10))
    reservation = reservation.model_copy(update={"reserved_at": NOW + timedelta(seconds=9, milliseconds=500)})
    service.reservation_authority.trust(reservation, {
        "owner_id": OWNER, "scope": SCOPE,
        "request_id": child.observation.request.request_id,
        "run_id": child.observation.request.run_id,
        "routing_decision_id": child.observation.routing_decision_id,
        "endpoint_profile_id": second.endpoint_profile_id,
        "endpoint_profile_version": second.profile_version,
        "operation": "bounded_generation",
        "expected_bucket_ids": frozenset({second.quota_buckets[0].bucket_id}),
        "max_physical_attempts": task.max_physical_attempts,
        "now": NOW + timedelta(seconds=10),
    })
    with pytest.raises(RoutingFinalizationError, match="routing_deadline_expired"):
        service.finalize(
            owner_id=OWNER, scope=SCOPE, observation=child.observation,
            preparation=PreparationIdentity(
                endpoint_profile_id=second.endpoint_profile_id,
                endpoint_profile_version=1,
                serializer_id=second.serializer_id,
                input_tokens=400,
                count_source="synthetic-count-v1",
                count_confidence="unknown",
                source_manifest_sha256=SOURCE_HASH,
                prepared_input_sha256=sha256(b"prepared-at-deadline").hexdigest(),
                prepared_at=NOW + timedelta(seconds=9),
            ),
            reservation=reservation, revalidation=revalidation,
            operation="bounded_generation", now=NOW + timedelta(seconds=10),
        )


def test_auxiliary_call_budget_is_root_scoped_and_event_retry_is_idempotent():
    profile = _profile()
    task = _task()
    task = task.model_copy(update={"max_auxiliary_calls": 1})
    service, _repository = _service((profile,))
    original = _route(service, profile, task=task)
    event = RoutingDecisionEvent(
        event_type="auxiliary_call_reserved",
        event_id=uuid4(),
        occurred_at=NOW + timedelta(seconds=1),
        outcome_code="count-call-budget-reserved",
    )

    assert service.consume_auxiliary_call(
        owner_id=OWNER, scope=SCOPE, decision_id=original.observation.routing_decision_id,
        event=event, now=NOW + timedelta(seconds=1),
    ) == 1
    assert service.consume_auxiliary_call(
        owner_id=OWNER, scope=SCOPE, decision_id=original.observation.routing_decision_id,
        event=event, now=NOW + timedelta(seconds=2),
    ) == 1
    with pytest.raises(ValueError, match="routing_auxiliary_call_budget_exceeded"):
        service.consume_auxiliary_call(
            owner_id=OWNER, scope=SCOPE, decision_id=original.observation.routing_decision_id,
            event=RoutingDecisionEvent(
                event_type="auxiliary_call_reserved",
                occurred_at=NOW + timedelta(seconds=3),
                outcome_code="summary-call-budget-reserved",
            ), now=NOW + timedelta(seconds=3),
        )


def test_postgres_auxiliary_call_budget_consumes_once_for_retried_event_id():
    database = _RoutingSQLDatabase()
    repository = PostgresRoutingDecisionRepository(database)
    profile = _profile()
    task = _task()
    task = task.model_copy(update={"max_auxiliary_calls": 1})
    service = RoutingDecisionService(EndpointRegistry((profile,)), repository)
    decision = _route(service, profile, task=task)
    event = RoutingDecisionEvent(
        event_type="auxiliary_call_reserved",
        event_id=uuid4(),
        occurred_at=NOW + timedelta(seconds=1),
        outcome_code="count-call-budget-reserved",
    )

    assert service.consume_auxiliary_call(
        owner_id=OWNER, scope=SCOPE, decision_id=decision.observation.routing_decision_id,
        event=event, now=NOW + timedelta(seconds=1),
    ) == 1
    assert service.consume_auxiliary_call(
        owner_id=OWNER, scope=SCOPE, decision_id=decision.observation.routing_decision_id,
        event=event, now=NOW + timedelta(seconds=2),
    ) == 1
    stored = repository.get(
        owner_id=OWNER, scope=SCOPE, decision_id=decision.observation.routing_decision_id
    )
    assert stored.events[-1] == event
    assert database.connection_value.records[decision.observation.routing_decision_id][
        "auxiliary_calls_used"
    ] == 1
    with pytest.raises(PersistenceConflict, match="budget_exceeded"):
        service.consume_auxiliary_call(
            owner_id=OWNER, scope=SCOPE, decision_id=decision.observation.routing_decision_id,
            event=RoutingDecisionEvent(
                event_type="auxiliary_call_reserved",
                occurred_at=NOW + timedelta(seconds=3),
                outcome_code="new-call",
            ), now=NOW + timedelta(seconds=3),
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
                endpoint_profile_id=original.observation.provisional_plan.selected_endpoint_profile_id,
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
            root_deadline_at=NOW + timedelta(seconds=5),
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
    attempt_id = uuid4()
    reservation_event = RoutingDecisionEvent(
        event_type="reservation_succeeded",
        occurred_at=now + timedelta(seconds=1),
        endpoint_profile_id=profile.endpoint_profile_id,
        invocation_id=invocation_id,
        attempt_id=attempt_id,
        outcome_code="reserved",
    )
    repository.append_event(
        owner_id=OWNER, scope=SCOPE,
        decision_id=result.observation.routing_decision_id,
        event=reservation_event,
    )
    started_event = RoutingDecisionEvent(
        event_type="dispatch_started",
        occurred_at=now + timedelta(milliseconds=1500),
        endpoint_profile_id=profile.endpoint_profile_id,
        invocation_id=invocation_id,
        attempt_id=attempt_id,
    )
    repository.append_event(
        owner_id=OWNER, scope=SCOPE,
        decision_id=result.observation.routing_decision_id,
        event=started_event,
    )
    completed_event = RoutingDecisionEvent(
        event_type="dispatch_completed",
        occurred_at=now + timedelta(seconds=2),
        endpoint_profile_id=profile.endpoint_profile_id,
        invocation_id=invocation_id,
        attempt_id=attempt_id,
        outcome_code="success",
    )

    appended = repository.append_event(
        owner_id=OWNER,
        scope=SCOPE,
        decision_id=result.observation.routing_decision_id,
        event=completed_event,
    )
    duplicate_append = repository.append_event(
        owner_id=OWNER,
        scope=SCOPE,
        decision_id=result.observation.routing_decision_id,
        event=completed_event,
    )
    with pytest.raises(PersistenceConflict, match="idempotency conflict"):
        repository.append_event(
            owner_id=OWNER,
            scope=SCOPE,
            decision_id=result.observation.routing_decision_id,
            event=completed_event.model_copy(update={"outcome_code": "different-payload"}),
        )
    with pytest.raises(ValidationError, match="routing_decision_event_transition_invalid"):
        repository.append_event(
            owner_id=OWNER,
            scope=SCOPE,
            decision_id=result.observation.routing_decision_id,
            event=RoutingDecisionEvent(
                event_type="dispatch_started",
                occurred_at=now + timedelta(seconds=3),
                endpoint_profile_id=profile.endpoint_profile_id,
            ),
        )
    loaded = repository.get(
        owner_id=OWNER,
        scope=SCOPE,
        decision_id=result.observation.routing_decision_id,
    )
    by_request = repository.list(owner_id=OWNER, scope=SCOPE, request_id="request-123")
    by_invocation = repository.list(owner_id=OWNER, scope=SCOPE, invocation_id=invocation_id)

    assert len(appended.events) == 4
    assert duplicate_append == appended
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
    lifecycle_migration = (
        Path(__file__).parents[1]
        / "src/personal_ai/persistence/migrations/021_routing_lifecycle_integrity.sql"
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
    assert "ADD COLUMN IF NOT EXISTS auxiliary_calls_used" in lifecycle_migration
    assert "CHECK (auxiliary_calls_used BETWEEN 0 AND 16)" in lifecycle_migration
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
