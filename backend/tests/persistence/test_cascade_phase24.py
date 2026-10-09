"""Opt-in Postgres cascade reservation/validation/linked-decision contract."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from personal_ai.auth.scope import ApplicationScope
from personal_ai.llm.client import GenerationMetadata, GenerationResult, ProviderIdentity
from personal_ai.persistence.postgres_routing import PostgresEndpointRegistryRepository
from personal_ai.persistence.postgres_routing_observations import PostgresRoutingDecisionRepository
from personal_ai.persistence.postgres_usage import PostgresProviderUsageAccounting
from personal_ai.routing import EndpointRegistry, RoutingDecisionService
from personal_ai.routing.cascade import CascadeCoordinator, PreparedCascadeInput, replay_cascade
from personal_ai.routing.phase21 import PreparationIdentity
from personal_ai.routing.strategy import QuotaAwareDeterministicStrategy
from personal_ai.usage.contracts import AttemptResult
from personal_ai.usage.profiles import EndpointProfileResolver
from tests.test_cascade_phase24 import cascade_task, validation_input, validators
from tests.test_endpoint_registry import _bucket, _profile
from tests.test_routing_phase21 import Authorization, request

pytestmark = pytest.mark.persistence_integration
pytest_plugins = ["tests.persistence.test_routing_decisions"]


@pytest.mark.parametrize("token_limit,expected_sends", [(192, 2), (60, 1)])
def test_canonical_cumulative_budget_and_validation_chain(database, token_limit, expected_sends):
    suffix = uuid4().hex
    owner = f"cascade-owner-{suffix}"
    scope = ApplicationScope()
    endpoints = (f"weak-{suffix}", f"strong-{suffix}")
    bucket_id = f"cascade-bucket-{suffix}"
    bucket = _bucket(bucket_id)
    profiles = tuple(_profile(endpoint, quota_buckets=(bucket,)) for endpoint in endpoints)
    catalog = PostgresEndpointRegistryRepository(database)
    registry = EndpointRegistry(profiles, repository=catalog)
    repo = PostgresRoutingDecisionRepository(database)
    usage = PostgresProviderUsageAccounting(database, endpoint_profile_resolver=EndpointProfileResolver(registry, catalog))
    service = RoutingDecisionService(registry, repo, usage=usage, authorization=Authorization())
    base = cascade_task()
    policy = base.cascade_policy.model_copy(update={
        "endpoint_order": endpoints, "quota_limits": {bucket_id: 2},
        "max_reserved_tokens": token_limit,
    })
    t = base.model_copy(update={"cascade_policy": policy})
    req = request(operation="bounded_generation").model_copy(update={"request_id": f"cascade-{suffix}"})
    sends = []

    def prepare(decision, remaining):
        profile = next(p for p in profiles if p.ref == decision.selected)
        identity = PreparationIdentity(
            endpoint=profile.ref, serializer_id=profile.serializer_id, input_tokens=32,
            count_source="fixture", count_confidence="estimated",
            prepared_input_sha256=sha256(profile.endpoint_profile_id.encode()).hexdigest(),
            prepared_at=service.current_time(owner_id=owner),
        )

        def send(profile, invocation, attempt):
            sends.append(attempt.attempt_id)
            text = "invalid" if len(sends) == 1 else '{"answer":"valid"}'
            return GenerationResult(text, GenerationMetadata(
                status="success", identity=ProviderIdentity(profile.provider_id, profile.model_id, profile.serializer_id),
            )), AttemptResult(outcome="success", completed_at=datetime.now(UTC), latency_ms=1)

        return PreparedCascadeInput(identity, validation_input(), send, synthetic=True)

    coordinator = CascadeCoordinator(service, validators())
    if expected_sends == 1:
        with pytest.raises(Exception, match="cascade_token_budget_exceeded"):
            coordinator.execute(owner_id=owner, scope=scope, task=t, request=req, prepare=prepare)
    else:
        result = coordinator.execute(owner_id=owner, scope=scope, task=t, request=req, prepare=prepare)
        records = repo.list(owner_id=owner, scope=scope, request_id=req.request_id)
        replay = replay_cascade(records, QuotaAwareDeterministicStrategy(), now=datetime.now(UTC))
        assert replay["final_endpoint"] == result.endpoint
        assert records[-1].events[-1].validation.accepted
    assert len(sends) == expected_sends
    with database.transaction() as c:
        tokens = c.execute(
            "SELECT sum(a.reserved_tokens) FROM provider_attempts a JOIN provider_invocations i USING(invocation_id) WHERE i.owner_id=%s",
            (owner,),
        ).fetchone()[0]
        assert tokens == 48 * expected_sends
