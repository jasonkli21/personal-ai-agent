"""Opt-in Postgres cascade reservation/validation/linked-decision contract."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from personal_ai.auth.scope import ApplicationScope
from personal_ai.context.builder import SOURCE_CLASSES, ContextBuilder, ContextBuildPolicy
from personal_ai.context.tokens import FakeTokenCounter
from personal_ai.llm.client import (
    ChatMessage,
    GenerationMetadata,
    GenerationResult,
    ProviderCapabilities,
    ProviderIdentity,
    TokenCount,
)
from personal_ai.persistence.postgres_routing import PostgresEndpointRegistryRepository
from personal_ai.persistence.postgres_routing_observations import PostgresRoutingDecisionRepository
from personal_ai.persistence.postgres_usage import PostgresProviderUsageAccounting
from personal_ai.routing import EndpointRegistry, RoutingDecisionService
from personal_ai.routing.cascade import (
    CascadeCoordinator,
    CascadeRejected,
    EndpointInputPreparer,
    replay_cascade,
)
from personal_ai.routing.contracts import CounterCompatibility
from personal_ai.routing.strategy import QuotaAwareDeterministicStrategy
from personal_ai.usage.profiles import EndpointProfileResolver
from tests.test_cascade_phase24 import cascade_task, validation_input, validators
from tests.test_endpoint_registry import _bucket, _profile
from tests.test_routing_phase21 import Authorization, request

pytestmark = pytest.mark.persistence_integration
pytest_plugins = ["tests.persistence.test_routing_decisions"]


@pytest.mark.parametrize("token_limit,expected_generations,expected_counts", [(192, 2, 2), (60, 0, 1)])
def test_canonical_cumulative_budget_and_validation_chain(
    database, token_limit, expected_generations, expected_counts
):
    suffix = uuid4().hex
    owner = f"cascade-owner-{suffix}"
    scope = ApplicationScope()
    endpoints = (f"weak-{suffix}", f"strong-{suffix}")
    bucket_id = f"cascade-bucket-{suffix}"
    bucket = _bucket(bucket_id, operations=frozenset({"bounded_generation", "token_counting"}))
    profiles = tuple(
        _profile(
            endpoint, quota_buckets=(bucket,),
            capabilities=frozenset({"bounded_generation", "token_counting"}),
            counter=CounterCompatibility(
                endpoint_profile_id=endpoint, endpoint_id="synthetic-endpoint-v1",
                deployment_id="synthetic-deployment-a", credential_scope_id="credential-a",
                account_scope_id="account-a", provider_id="synthetic", model_id="model-a",
                serializer_id="synthetic-chat-v1", counter_id="counter-v1",
                confidence="authoritative", approved=True, provenance_reference="test:v1",
            ),
        ) for endpoint in endpoints
    )
    catalog = PostgresEndpointRegistryRepository(database)
    registry = EndpointRegistry(profiles, repository=catalog)
    repo = PostgresRoutingDecisionRepository(database)
    usage = PostgresProviderUsageAccounting(database, endpoint_profile_resolver=EndpointProfileResolver(registry, catalog))
    service = RoutingDecisionService(registry, repo, usage=usage, authorization=Authorization())
    base = cascade_task()
    policy = base.cascade_policy.model_copy(update={
        "endpoint_order": endpoints, "quota_limits": {bucket_id: 4},
        "max_reserved_tokens": token_limit,
    })
    t = base.model_copy(update={"cascade_policy": policy})
    req = request(operation="bounded_generation").model_copy(update={"request_id": f"cascade-{suffix}"})
    sends = []
    context_policy = ContextBuildPolicy(
        global_input_tokens=4096, source_max_tokens={key: 4096 for key in SOURCE_CLASSES}
    )

    def assemble(profile, decision):
        context = ContextBuilder(FakeTokenCounter()).build(
            (ChatMessage("user", "synthetic prompt"),), (), context_policy,
            base_sensitivity=decision.request.requirements.sensitivity,
        )
        return context, validation_input()

    def resolve_runtime(profile):
        identity = ProviderIdentity(profile.provider_id, profile.model_id, profile.serializer_id)

        def count(messages, timeout_seconds, **kwargs):
            sends.append(("count", profile.ref))
            return TokenCount(32, "provider", profile.provider_id, profile.model_id,
                             profile.serializer_id, "authoritative")

        def complete(messages, **kwargs):
            sends.append(("generation", profile.ref))
            generation_count = sum(kind == "generation" for kind, _ in sends)
            text = "invalid" if generation_count == 1 else '{"answer":"valid"}'
            return GenerationResult(text, GenerationMetadata(status="success", identity=identity))

        binding = {
            "endpoint_profile": profile,
            "gateway_accounting_enabled": False,
            "transport_retries": 0,
            "max_http_requests_per_call": 1,
        }
        return (
            SimpleNamespace(identity=identity, capabilities=ProviderCapabilities(
                frozenset({"bounded_generation"})), complete=complete, **binding),
            SimpleNamespace(identity=identity, count_with_timeout=count,
                counter_id=profile.counter.counter_id, **binding),
        )

    prepare = EndpointInputPreparer(
        service, owner_id=owner, scope=scope, assemble=assemble, resolve_runtime=resolve_runtime
    )

    coordinator = CascadeCoordinator(service, validators())
    if expected_generations == 0:
        with pytest.raises(Exception, match="cascade_token_budget_exceeded"):
            coordinator.execute(owner_id=owner, scope=scope, task=t, request=req, prepare=prepare)
    else:
        result = coordinator.execute(owner_id=owner, scope=scope, task=t, request=req, prepare=prepare)
        records = repo.list(owner_id=owner, scope=scope, request_id=req.request_id)
        replay = replay_cascade(records, QuotaAwareDeterministicStrategy(), now=datetime.now(UTC))
        assert replay["final_endpoint"] == result.endpoint
        assert records[-1].events[-1].validation.accepted
    sent_before_duplicate = len(sends)
    with pytest.raises(CascadeRejected, match="already_started"):
        coordinator.execute(owner_id=owner, scope=scope, task=t, request=req, prepare=prepare)
    assert len(sends) == sent_before_duplicate
    assert sum(kind == "generation" for kind, _ in sends) == expected_generations
    assert sum(kind == "count" for kind, _ in sends) == expected_counts
    with database.transaction() as c:
        tokens = c.execute(
            "SELECT sum(a.reserved_tokens) FROM provider_attempts a JOIN provider_invocations i USING(invocation_id) WHERE i.owner_id=%s",
            (owner,),
        ).fetchone()[0]
        assert tokens is not None and tokens >= 48 * expected_generations
