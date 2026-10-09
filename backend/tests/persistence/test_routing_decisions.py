"""Opt-in Postgres migration, scope, replay retention, and fence checks."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres import PersistenceConflict, PostgresDatabase
from personal_ai.persistence.postgres_artifacts import PostgresArtifactMetadataRepository
from personal_ai.persistence.postgres_routing_observations import (
    PostgresRoutingDecisionRepository,
    RoutingDecisionUnavailable,
)
from personal_ai.routing import EndpointRegistry, RoutingDecisionService
from personal_ai.routing.contracts import (
    DataUsePolicy,
    EndpointCandidateRequirements,
    EndpointProfile,
    QuotaBucket,
    StrictFreeEligibilityAttestation,
)
from personal_ai.routing.phase21 import (
    RoutingDecisionEvent,
    RoutingDecisionObservation,
    RoutingRequestFacts,
    RoutingStrategyIdentity,
    RoutingTaskProfile,
    RuntimeCandidateFacts,
)

pytestmark = pytest.mark.persistence_integration


@pytest.fixture
def database():
    dsn = os.environ.get("PERSISTENCE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set PERSISTENCE_TEST_POSTGRES_DSN for isolated local Postgres")
    database = PostgresDatabase(dsn, environment="test", min_size=1, max_size=4)
    database.migrate()
    try:
        yield database
    finally:
        database.close()


def _no_route_observation(owner_id: str, scope: ApplicationScope, *, created_at: datetime):
    policy_version = "policy:phase21-integration-v1"
    decision_id = uuid4()
    task = RoutingTaskProfile(
        task_id="integration-chat",
        profile_id="task-profile:integration-chat-v1",
        profile_version=1,
        task_type="chat",
        required_capabilities=frozenset({"bounded_generation"}),
    )
    request = RoutingRequestFacts(
        request_id=f"request-{uuid4()}",
        requirements=EndpointCandidateRequirements(
            input_tokens=32,
            output_tokens=16,
        ),
        policy_version=policy_version,
    )
    return RoutingDecisionObservation(
        routing_decision_id=decision_id,
        root_decision_id=decision_id,
        owner_id=owner_id,
        application_id=scope.application_id,
        workspace_id=scope.workspace_id,
        created_at=created_at,
        root_deadline_at=created_at + timedelta(seconds=30),
        replay_until=created_at + timedelta(days=30),
        request=request,
        task=task,
        registry_version="registry:phase21-integration-v1",
        policy_version=policy_version,
        strategy_identity=RoutingStrategyIdentity(
            strategy_id="deterministic-scoring",
            strategy_version="1",
            strategy_implementation_sha256="0" * 64,
            configuration_version="task-profile:integration-chat-v1",
            configuration_sha256="1" * 64,
            tie_break_version="profile-id-v1",
        ),
        lifecycle_status="no_route",
        no_route_reason="no-eligible-endpoint",
    )


def _preparing_profile() -> EndpointProfile:
    profile_id = f"integration:{uuid4()}"
    account_id = f"account:{profile_id}"
    credential_id = f"credential:{profile_id}"
    provider_id = "synthetic-provider"
    model_id = "synthetic-model"
    endpoint_id = "synthetic-endpoint"
    deployment_id = "synthetic-deployment"
    return EndpointProfile(
        endpoint_profile_id=profile_id,
        profile_version=1,
        provider_id=provider_id,
        model_id=model_id,
        endpoint_id=endpoint_id,
        deployment_id=deployment_id,
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
        capabilities=frozenset({"bounded_generation"}),
        context_limit_tokens=4096,
        max_output_tokens=1024,
        data_use_policy=DataUsePolicy(
            status="approved", max_sensitivity="personal", policy_reference="policy:v1"
        ),
        strict_free_attestation=StrictFreeEligibilityAttestation(
            endpoint_profile_id=profile_id,
            provider_id=provider_id,
            model_id=model_id,
            endpoint_id=endpoint_id,
            deployment_id=deployment_id,
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
        quota_membership="verified",
        quota_buckets=(QuotaBucket(
            bucket_id=f"quota:{profile_id}",
            authority_scope_id=account_id,
            operations=frozenset({"bounded_generation"}),
            unit="requests",
            window_seconds=3600,
            source="provider_contract",
            confidence="verified",
            evidence_reference="quota:synthetic-v1",
        ),),
    )


def test_real_postgres_routing_decision_scope_and_owner_fence(database):
    scope = ApplicationScope(application_id="personal_ai")
    owner_id = f"phase21-test-{uuid4()}"
    observation = _no_route_observation(
        owner_id, scope, created_at=datetime.now(UTC)
    )
    repository = PostgresRoutingDecisionRepository(database)
    repository.begin(
        owner_id=owner_id,
        scope=scope,
        observation=observation,
        initial_event=RoutingDecisionEvent(
            event_type="decision_no_route",
            occurred_at=observation.created_at,
            reason_code="no-eligible-endpoint",
        ),
    )

    stored = repository.get(
        owner_id=owner_id,
        scope=scope,
        decision_id=observation.routing_decision_id,
    )
    listed = repository.list(
        owner_id=owner_id,
        scope=scope,
        request_id=observation.request.request_id,
    )
    assert stored.observation == observation
    assert listed[0].observation.routing_decision_id == observation.routing_decision_id
    with pytest.raises(RoutingDecisionUnavailable):
        repository.get(
            owner_id=f"other-{uuid4()}",
            scope=scope,
            decision_id=observation.routing_decision_id,
        )

    PostgresArtifactMetadataRepository(database).fence(owner_id)
    with pytest.raises(RoutingDecisionUnavailable):
        repository.get(
            owner_id=owner_id,
            scope=scope,
            decision_id=observation.routing_decision_id,
        )


def test_real_postgres_expired_routing_replay_is_unavailable_and_purged(database):
    scope = ApplicationScope(application_id="personal_ai")
    owner_id = f"phase21-expired-{uuid4()}"
    created_at = datetime.now(UTC) - timedelta(days=31)
    observation = _no_route_observation(owner_id, scope, created_at=created_at)
    repository = PostgresRoutingDecisionRepository(database)
    repository.begin(
        owner_id=owner_id,
        scope=scope,
        observation=observation,
        initial_event=RoutingDecisionEvent(
            event_type="decision_no_route",
            occurred_at=created_at,
            reason_code="no-eligible-endpoint",
        ),
    )

    with pytest.raises(RoutingDecisionUnavailable):
        repository.get(
            owner_id=owner_id,
            scope=scope,
            decision_id=observation.routing_decision_id,
        )
    assert repository.purge_expired(limit=10) >= 1


def test_real_postgres_concurrent_duplicate_event_append_is_idempotent(database):
    scope = ApplicationScope(application_id="personal_ai")
    owner_id = f"phase21-events-{uuid4()}"
    created_at = datetime.now(UTC)
    observation = _no_route_observation(owner_id, scope, created_at=created_at)
    repository = PostgresRoutingDecisionRepository(database)
    repository.begin(
        owner_id=owner_id,
        scope=scope,
        observation=observation,
        initial_event=RoutingDecisionEvent(
            event_type="decision_no_route",
            occurred_at=created_at,
            reason_code="no-eligible-endpoint",
        ),
    )
    event = RoutingDecisionEvent(
        event_type="replay_unavailable",
        event_id=uuid4(),
        occurred_at=created_at + timedelta(seconds=1),
        outcome_code="expired-decision-context",
    )
    barrier = Barrier(2)

    def append_same_event():
        barrier.wait(timeout=5)
        return repository.append_event(
            owner_id=owner_id,
            scope=scope,
            decision_id=observation.routing_decision_id,
            event=event,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(lambda _index: append_same_event(), range(2)))
    assert records[0] == records[1]
    assert len(records[0].events) == 2
    with pytest.raises(PersistenceConflict, match="idempotency conflict"):
        repository.append_event(
            owner_id=owner_id,
            scope=scope,
            decision_id=observation.routing_decision_id,
            event=event.model_copy(update={"outcome_code": "different-payload"}),
        )


def test_real_postgres_concurrent_reselection_consumes_one_root_budget(database):
    scope = ApplicationScope(application_id="personal_ai")
    owner_id = f"phase21-reselection-{uuid4()}"
    now = datetime.now(UTC)
    profile = _preparing_profile()
    task = RoutingTaskProfile(
        task_id="integration-chat",
        profile_id="task-profile:integration-chat-v1",
        profile_version=1,
        task_type="chat",
        required_capabilities=frozenset({"bounded_generation"}),
        max_reselections=1,
    )
    request = RoutingRequestFacts(
        request_id=f"request-{uuid4()}",
        requirements=EndpointCandidateRequirements(input_tokens=32, output_tokens=16),
        policy_version="policy:phase21-integration-v1",
    )
    runtime = RuntimeCandidateFacts(
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=profile.profile_version,
        authorization="authorized",
        authorization_reference="authorization:integration-v1",
        credential_status="usable",
        health_status="healthy",
        observed_at=now,
        fresh_until=now + timedelta(minutes=5),
        exhausted=False,
    )
    repository = PostgresRoutingDecisionRepository(database)
    service = RoutingDecisionService(EndpointRegistry((profile,)), repository)
    parent = service.route(
        owner_id=owner_id,
        scope=scope,
        task=task,
        request=request,
        runtime_facts=(runtime,),
        now=now,
    )
    repository.append_event(
        owner_id=owner_id,
        scope=scope,
        decision_id=parent.observation.routing_decision_id,
        event=RoutingDecisionEvent(
            event_type="preparation_failed",
            occurred_at=now + timedelta(seconds=1),
            endpoint_profile_id=profile.endpoint_profile_id,
            reason_code="fit-failed",
        ),
    )
    barrier = Barrier(2)

    def reselect():
        barrier.wait(timeout=5)
        return service.route(
            owner_id=owner_id,
            scope=scope,
            task=task,
            request=request,
            runtime_facts=(runtime.model_copy(update={
                "observed_at": now + timedelta(seconds=2),
                "fresh_until": now + timedelta(minutes=6),
            }),),
            parent_decision_id=parent.observation.routing_decision_id,
            now=now + timedelta(seconds=2),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: reselect(), range(2)))
    assert results[0].observation.routing_decision_id == results[1].observation.routing_decision_id
    assert results[0].observation.reselection_depth == 1
    root = repository.get(
        owner_id=owner_id,
        scope=scope,
        decision_id=parent.observation.routing_decision_id,
    )
    assert len([event for event in root.events if event.event_type == "reselection_linked"]) == 1
    rows = repository.list(owner_id=owner_id, scope=scope, request_id=request.request_id)
    assert len(rows) == 2


def test_real_postgres_concurrent_auxiliary_calls_share_root_budget(database):
    scope = ApplicationScope(application_id="personal_ai")
    owner_id = f"phase21-auxiliary-{uuid4()}"
    now = datetime.now(UTC)
    profile = _preparing_profile()
    task = RoutingTaskProfile(
        task_id="integration-chat",
        profile_id="task-profile:integration-chat-v1",
        profile_version=1,
        task_type="chat",
        required_capabilities=frozenset({"bounded_generation"}),
        max_auxiliary_calls=1,
    )
    request = RoutingRequestFacts(
        request_id=f"request-{uuid4()}",
        requirements=EndpointCandidateRequirements(input_tokens=32, output_tokens=16),
        policy_version="policy:phase21-integration-v1",
    )
    runtime = RuntimeCandidateFacts(
        endpoint_profile_id=profile.endpoint_profile_id,
        endpoint_profile_version=profile.profile_version,
        authorization="authorized",
        authorization_reference="authorization:integration-v1",
        credential_status="usable",
        health_status="healthy",
        observed_at=now,
        fresh_until=now + timedelta(minutes=5),
        exhausted=False,
    )
    repository = PostgresRoutingDecisionRepository(database)
    service = RoutingDecisionService(EndpointRegistry((profile,)), repository)
    decision = service.route(
        owner_id=owner_id,
        scope=scope,
        task=task,
        request=request,
        runtime_facts=(runtime,),
        now=now,
    )
    barrier = Barrier(2)
    event_time = now + timedelta(seconds=1)

    def consume(_index):
        event = RoutingDecisionEvent(
            event_type="auxiliary_call_reserved",
            occurred_at=event_time,
            outcome_code="counter-call",
        )
        barrier.wait(timeout=5)
        try:
            return service.consume_auxiliary_call(
                owner_id=owner_id,
                scope=scope,
                decision_id=decision.observation.routing_decision_id,
                event=event,
                now=event_time,
            )
        except PersistenceConflict as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(consume, range(2)))
    assert outcomes.count(1) == 1
    assert outcomes.count("routing_auxiliary_call_budget_exceeded") == 1
    stored = repository.get(
        owner_id=owner_id,
        scope=scope,
        decision_id=decision.observation.routing_decision_id,
    )
    assert len([event for event in stored.events if event.event_type == "auxiliary_call_reserved"]) == 1
    with database.connection() as connection:
        used = connection.execute(
            "SELECT auxiliary_calls_used FROM routing_decisions WHERE decision_id=%s",
            (decision.observation.root_decision_id,),
        ).fetchone()[0]
    assert used == 1
