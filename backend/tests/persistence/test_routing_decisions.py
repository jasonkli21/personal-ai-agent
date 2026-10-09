"""Opt-in Postgres migration, scope, replay retention, and fence checks."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres import PostgresDatabase
from personal_ai.persistence.postgres_artifacts import PostgresArtifactMetadataRepository
from personal_ai.persistence.postgres_routing_observations import (
    PostgresRoutingDecisionRepository,
    RoutingDecisionUnavailable,
)
from personal_ai.routing.contracts import EndpointCandidateRequirements
from personal_ai.routing.phase21 import (
    RoutingDecisionEvent,
    RoutingDecisionObservation,
    RoutingRequestFacts,
    RoutingStrategyIdentity,
    RoutingTaskProfile,
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
