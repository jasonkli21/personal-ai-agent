"""Real-engine routing authority/migration/atomicity/race tests; opt-in DSN."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, get_ident
from uuid import uuid4

import pytest

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence import postgres_usage as postgres_usage_module
from personal_ai.persistence.postgres import PersistenceConflict, PostgresDatabase
from personal_ai.persistence.postgres_artifacts import PostgresArtifactMetadataRepository
from personal_ai.persistence.postgres_owner_lifecycle import OwnerFenced
from personal_ai.persistence.postgres_routing import PostgresEndpointRegistryRepository
from personal_ai.persistence.postgres_routing_observations import (
    PostgresRoutingDecisionRepository,
    RoutingDecisionUnavailable,
)
from personal_ai.persistence.postgres_usage import PostgresProviderUsageAccounting
from personal_ai.routing import (
    DeterministicScoringStrategy,
    EndpointPriority,
    EndpointRegistry,
    PreparationIdentity,
    QuotaAwareDeterministicStrategy,
    QuotaBucket,
    RoutingDecisionService,
    RoutingFinalizationError,
    RoutingPreferences,
    RoutingRequestFacts,
    RoutingTaskProfile,
    replay_deterministic_decision,
)
from personal_ai.usage.contracts import (
    AttemptResult,
    UsageAdmissionDenied,
)
from personal_ai.usage.profiles import EndpointProfileResolver
from tests.test_endpoint_registry import _profile, _requirements
from tests.test_routing_phase21 import Authorization

pytestmark = pytest.mark.persistence_integration
SCOPE = ApplicationScope()


@pytest.fixture
def database():
    dsn = os.environ.get("PERSISTENCE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set isolated PERSISTENCE_TEST_POSTGRES_DSN")
    db = PostgresDatabase(dsn, environment="test", min_size=1, max_size=8)
    db.migrate()
    try:
        yield db
    finally:
        db.close()


def setup(database, *, owner_id=None, scope=SCOPE, request_id=None, strategy=None, **task_changes):
    owner = owner_id or f"route-owner-{uuid4()}"
    p = _profile(f"route-endpoint-{uuid4()}")
    catalog = PostgresEndpointRegistryRepository(database)
    registry = EndpointRegistry((p,), repository=catalog)
    repo = PostgresRoutingDecisionRepository(database)
    usage = PostgresProviderUsageAccounting(
        database, endpoint_profile_resolver=EndpointProfileResolver(registry, catalog)
    )
    auth = Authorization()
    service = RoutingDecisionService(
        registry, repo, strategy=strategy, usage=usage, authorization=auth
    )
    t = RoutingTaskProfile(
        task_id="chat",
        profile_id="task:test",
        profile_version=1,
        task_type="chat",
        required_capabilities=frozenset({"bounded_generation"}),
        deadline_ms=600000,
        **task_changes,
    )
    request = RoutingRequestFacts(
        request_id=request_id or f"request-{uuid4()}",
        policy_version="policy:v1",
        requirements=_requirements(input_tokens=64, output_tokens=16),
    )
    d = service.route(owner_id=owner, scope=scope, task=t, request=request)
    assert d.selected
    prep = PreparationIdentity(
        endpoint=d.selected,
        serializer_id=p.serializer_id,
        input_tokens=32,
        count_source="test-estimate",
        count_confidence="estimated",
        prepared_input_sha256="1" * 64,
        prepared_at=datetime.now(UTC),
    )
    return owner, service, d, prep, repo, usage, auth


def finalize(system):
    owner, service, d, prep, *_ = system
    return service.finalize(
        owner_id=owner,
        scope=SCOPE,
        decision_id=d.routing_decision_id,
        preparation=prep,
        operation="bounded_generation",
    )


def test_quota_snapshot_is_frozen_and_capacity_loss_reselects_without_dispatch(database):
    owner = f"quota-route-owner-{uuid4()}"
    suffix = uuid4().hex
    strong_id = f"quota-strong-{suffix}"
    substitute_id = f"quota-substitute-{suffix}"
    strong_bucket_id = f"quota-account-a-{suffix}:generation-requests"
    profiles = []
    for profile_id, account_id, bucket_id in (
        (strong_id, f"quota-account-a-{suffix}", strong_bucket_id),
        (substitute_id, f"quota-account-b-{suffix}", f"quota-account-b-{suffix}:generation-requests"),
    ):
        bucket = QuotaBucket(
            bucket_id=bucket_id,
            authority_scope_id=account_id,
            operations=frozenset({"bounded_generation"}),
            unit="requests",
            window_seconds=3600,
            source="provider_contract",
            confidence="verified",
            reservation_units_per_request=1,
            evidence_reference="quota:phase23-test",
            limit=100,
        )
        profiles.append(
            _profile(
                profile_id,
                account_scope_id=account_id,
                quota_buckets=(bucket,),
            )
        )
    catalog = PostgresEndpointRegistryRepository(database)
    registry = EndpointRegistry(tuple(profiles), repository=catalog)
    repository = PostgresRoutingDecisionRepository(database)
    usage = PostgresProviderUsageAccounting(
        database, endpoint_profile_resolver=EndpointProfileResolver(registry, catalog)
    )
    service = RoutingDecisionService(
        registry, repository, usage=usage, authorization=Authorization()
    )
    routing_task = RoutingTaskProfile(
        task_id="chat",
        profile_id="task:phase23-quota",
        profile_version=1,
        task_type="chat",
        required_capabilities=frozenset({"bounded_generation"}),
        endpoint_priorities=(EndpointPriority(endpoint_profile_id=strong_id, priority=10),),
        preferences=RoutingPreferences(
            quota_scarcity_weight=0, quota_unknown_penalty_weight=0
        ),
        max_reselections=1,
        deadline_ms=600000,
    )
    request_facts = RoutingRequestFacts(
        request_id=f"quota-route-request-{uuid4()}",
        policy_version="policy:v1",
        requirements=_requirements(input_tokens=64, output_tokens=16),
    )
    decision = service.route(
        owner_id=owner,
        scope=SCOPE,
        task=routing_task,
        request=request_facts,
    )

    assert decision.selected.endpoint_profile_id == strong_id
    assert len(decision.quota_buckets) == 2
    first_snapshot = next(
        fact for fact in decision.quota_buckets if fact.bucket_id == strong_bucket_id
    )
    assert first_snapshot.confidence == "derived"
    assert first_snapshot.remaining_units == 100
    selected_candidate = next(row for row in decision.candidates if row.endpoint == decision.selected)
    assert selected_candidate.quota_requirements[0].reservation_units == 1
    assert first_snapshot.reset_at is not None

    with database.transaction() as connection:
        connection.execute(
            "UPDATE provider_quota_bucket_windows SET limit_units=0 "
            "WHERE bucket_id=%s",
            (strong_bucket_id,),
        )
    preparation = PreparationIdentity(
        endpoint=decision.selected,
        serializer_id="synthetic-chat-v1",
        input_tokens=32,
        count_source="test-estimate",
        count_confidence="estimated",
        prepared_input_sha256="2" * 64,
        prepared_at=service.current_time(owner_id=owner),
    )
    with pytest.raises(RoutingFinalizationError, match="provider_quota_exhausted"):
        service.finalize(
            owner_id=owner,
            scope=SCOPE,
            decision_id=decision.routing_decision_id,
            preparation=preparation,
            operation="bounded_generation",
        )
    with database.connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM provider_attempts a JOIN provider_invocations i USING(invocation_id) "
            "WHERE i.request_id=%s AND i.owner_id=%s",
            (request_facts.request_id, owner),
        ).fetchone()[0] == 0

    child = service.route(
        owner_id=owner,
        scope=SCOPE,
        task=routing_task,
        request=request_facts,
        parent_decision_id=decision.routing_decision_id,
    )
    assert child.parent_decision_id == decision.routing_decision_id
    assert child.selected.endpoint_profile_id == substitute_id
    assert child.request.excluded_endpoint_profile_ids == (strong_id,)


def test_shared_bucket_candidate_costs_score_and_reserve_independently(database):
    owner = f"shared-cost-owner-{uuid4()}"
    suffix = uuid4().hex
    authority = f"shared-cost-account-{suffix}"
    bucket_id = f"shared-cost-bucket-{suffix}"
    profiles = []
    for profile_id, cost in ((f"low-cost-{suffix}", 10), (f"high-cost-{suffix}", 20)):
        bucket = QuotaBucket(
            bucket_id=bucket_id,
            authority_scope_id=authority,
            operations=frozenset({"bounded_generation"}),
            unit="neurons",
            window_seconds=3600,
            source="provider_contract",
            confidence="verified",
            reservation_units_per_request=cost,
            evidence_reference="quota:shared-cost-test",
            limit=200,
        )
        profiles.append(
            _profile(
                profile_id,
                account_scope_id=authority,
                quota_buckets=(bucket,),
            )
        )

    catalog = PostgresEndpointRegistryRepository(database)
    registry = EndpointRegistry(tuple(profiles), repository=catalog)
    repository = PostgresRoutingDecisionRepository(database)
    usage = PostgresProviderUsageAccounting(
        database, endpoint_profile_resolver=EndpointProfileResolver(registry, catalog)
    )
    service = RoutingDecisionService(
        registry, repository, usage=usage, authorization=Authorization()
    )
    routing_task = RoutingTaskProfile(
        task_id="chat",
        profile_id="task:shared-cost",
        profile_version=1,
        task_type="chat",
        required_capabilities=frozenset({"bounded_generation"}),
        preferences=RoutingPreferences(quota_scarcity_weight=4_000),
        deadline_ms=600000,
    )
    request_facts = RoutingRequestFacts(
        request_id=f"shared-cost-request-{suffix}",
        policy_version="policy:v1",
        requirements=_requirements(input_tokens=64, output_tokens=16),
    )
    decision = service.route(
        owner_id=owner, scope=SCOPE, task=routing_task, request=request_facts
    )

    assert decision.selected.endpoint_profile_id == f"low-cost-{suffix}"
    assert len(decision.quota_buckets) == 1
    assert decision.quota_buckets[0].reservation_units is None
    candidate_requirements = {
        row.endpoint.endpoint_profile_id: row.quota_requirements[0].reservation_units
        for row in decision.candidates
    }
    assert candidate_requirements == {
        f"low-cost-{suffix}": 10,
        f"high-cost-{suffix}": 20,
    }
    assert decision.ranking[0].score > decision.ranking[1].score
    assert replay_deterministic_decision(
        decision, QuotaAwareDeterministicStrategy()
    ) == decision.ranking

    preparation = PreparationIdentity(
        endpoint=decision.selected,
        serializer_id=registry.historical(decision.selected).serializer_id,
        input_tokens=32,
        count_source="test-estimate",
        count_confidence="estimated",
        prepared_input_sha256="3" * 64,
        prepared_at=service.current_time(owner_id=owner),
    )
    permit = service.finalize(
        owner_id=owner,
        scope=SCOPE,
        decision_id=decision.routing_decision_id,
        preparation=preparation,
        operation="bounded_generation",
    )
    with database.connection() as connection:
        reserved = connection.execute(
            "SELECT reserved_units FROM provider_quota_reservations "
            "WHERE attempt_id=%s AND bucket_id=%s",
            (permit.attempt_id, bucket_id),
        ).fetchone()[0]
    assert reserved == 10


def test_batch_route_snapshot_orders_overlapping_buckets_before_settlement_and_finalize(
    database, monkeypatch
):
    owner = f"overlapping-route-owner-{uuid4()}"
    suffix = uuid4().hex
    authority = f"overlapping-account-{suffix}"
    bucket_a = QuotaBucket(
        bucket_id=f"a-{suffix}", authority_scope_id=authority,
        operations=frozenset({"bounded_generation"}), unit="requests", window_seconds=3600,
        source="provider_contract", confidence="verified", reservation_units_per_request=1,
        evidence_reference="quota:overlap-test", limit=100,
    )
    bucket_z = QuotaBucket(
        bucket_id=f"z-{suffix}", authority_scope_id=authority,
        operations=frozenset({"bounded_generation"}), unit="requests", window_seconds=3600,
        source="provider_contract", confidence="verified", reservation_units_per_request=1,
        evidence_reference="quota:overlap-test", limit=100,
    )
    first_id = f"a-route-first-{suffix}"
    second_id = f"b-route-second-{suffix}"
    profiles = (
        _profile(first_id, account_scope_id=authority, quota_buckets=(bucket_z,)),
        _profile(second_id, account_scope_id=authority, quota_buckets=(bucket_a, bucket_z)),
    )
    catalog = PostgresEndpointRegistryRepository(database)
    registry = EndpointRegistry(profiles, repository=catalog)
    repository = PostgresRoutingDecisionRepository(database)
    usage = PostgresProviderUsageAccounting(
        database, endpoint_profile_resolver=EndpointProfileResolver(registry, catalog)
    )
    service = RoutingDecisionService(
        registry, repository, usage=usage, authorization=Authorization()
    )
    routing_task = RoutingTaskProfile(
        task_id="chat",
        profile_id="task:overlapping-quota",
        profile_version=1,
        task_type="chat",
        required_capabilities=frozenset({"bounded_generation"}),
        endpoint_priorities=(EndpointPriority(endpoint_profile_id=second_id, priority=10),),
        deadline_ms=600000,
    )
    first_request = RoutingRequestFacts(
        request_id=f"overlap-seed-request-{suffix}",
        policy_version="policy:v1",
        requirements=_requirements(input_tokens=64, output_tokens=16),
    )
    seed = service.route(owner_id=owner, scope=SCOPE, task=routing_task, request=first_request)
    assert seed.selected.endpoint_profile_id == second_id
    prep = PreparationIdentity(
        endpoint=seed.selected,
        serializer_id=registry.historical(seed.selected).serializer_id,
        input_tokens=32,
        count_source="test-estimate",
        count_confidence="estimated",
        prepared_input_sha256="4" * 64,
        prepared_at=service.current_time(owner_id=owner),
    )
    permit = service.finalize(
        owner_id=owner,
        scope=SCOPE,
        decision_id=seed.routing_decision_id,
        preparation=prep,
        operation="bounded_generation",
    )
    _profile_ref, invocation, attempt = service.claim(
        owner_id=owner, scope=SCOPE, permit=permit, operation="bounded_generation"
    )

    snapshot_ready = Event()
    release_route = Event()
    original_snapshots = usage.routing_snapshots

    def held_snapshots(*args, **kwargs):
        result = original_snapshots(*args, **kwargs)
        if len(args[1]) > 1:
            snapshot_ready.set()
            if not release_route.wait(timeout=10):
                raise TimeoutError("route_snapshot_release_timeout")
        return result

    usage.routing_snapshots = held_snapshots
    settled = Event()
    original_settle = usage.settle_attempt

    def tracked_settle(*args, **kwargs):
        settled.set()
        return original_settle(*args, **kwargs)

    usage.settle_attempt = tracked_settle
    next_request = RoutingRequestFacts(
        request_id=f"overlap-concurrent-request-{suffix}",
        policy_version="policy:v1",
        requirements=_requirements(input_tokens=64, output_tokens=16),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        route_future = pool.submit(
            service.route,
            owner_id=owner,
            scope=SCOPE,
            task=routing_task,
            request=next_request,
        )
        assert snapshot_ready.wait(timeout=10)
        settlement_future = pool.submit(
            usage.settle_attempt,
            invocation,
            attempt,
            AttemptResult(
                outcome="success",
                completed_at=attempt.started_at + timedelta(seconds=1),
                latency_ms=1,
                input_tokens=32,
                output_tokens=8,
                total_tokens=40,
                usage_source="provider",
                usage_confidence="exact",
            ),
        )
        assert settled.wait(timeout=10)
        release_route.set()
        next_decision = route_future.result(timeout=15)
        settlement_future.result(timeout=15)
    assert next_decision.selected is not None
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT bucket_id,consumed_units,reserved_units FROM provider_quota_bucket_windows "
            "WHERE bucket_id IN (%s,%s) ORDER BY bucket_id",
            (bucket_a.bucket_id, bucket_z.bucket_id),
        ).fetchall()
    assert rows == [(bucket_a.bucket_id, 1, 0), (bucket_z.bucket_id, 1, 0)]

    snapshot_ready.clear()
    release_route.clear()
    final_request = RoutingRequestFacts(
        request_id=f"overlap-final-request-{suffix}",
        policy_version="policy:v1",
        requirements=_requirements(input_tokens=64, output_tokens=16),
    )
    usage.routing_snapshots = original_snapshots
    final_preparation = PreparationIdentity(
        endpoint=next_decision.selected,
        serializer_id=registry.historical(next_decision.selected).serializer_id,
        input_tokens=32,
        count_source="test-estimate",
        count_confidence="estimated",
        prepared_input_sha256="5" * 64,
        prepared_at=service.current_time(owner_id=owner),
    )
    route_buckets_locked = Event()
    route_thread_id = []
    finalizer_thread_id = []
    finalizer_bucket_attempt = Event()
    original_health_lock = postgres_usage_module._lock_endpoint_health
    original_select_bucket = postgres_usage_module._select_quota_window

    def pause_route_before_health(connection, endpoint):
        if route_thread_id and get_ident() == route_thread_id[0] and not release_route.is_set():
            route_buckets_locked.set()
            if not release_route.wait(timeout=10):
                raise TimeoutError("route_health_lock_release_timeout")
        return original_health_lock(connection, endpoint)

    monkeypatch.setattr(
        postgres_usage_module, "_lock_endpoint_health", pause_route_before_health
    )

    def track_finalizer_bucket_attempt(connection, bucket, now):
        if finalizer_thread_id and get_ident() == finalizer_thread_id[0]:
            finalizer_bucket_attempt.set()
        return original_select_bucket(connection, bucket, now)

    monkeypatch.setattr(
        postgres_usage_module, "_select_quota_window", track_finalizer_bucket_attempt
    )

    def make_final_route():
        route_thread_id.append(get_ident())
        return service.route(
            owner_id=owner,
            scope=SCOPE,
            task=routing_task,
            request=final_request,
        )

    def finalize_next_decision():
        finalizer_thread_id.append(get_ident())
        return service.finalize(
            owner_id=owner,
            scope=SCOPE,
            decision_id=next_decision.routing_decision_id,
            preparation=final_preparation,
            operation="bounded_generation",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        route_future = pool.submit(make_final_route)
        try:
            assert route_buckets_locked.wait(timeout=10)
            reserve_future = pool.submit(finalize_next_decision)
            assert finalizer_bucket_attempt.wait(timeout=10)
        finally:
            release_route.set()
        final_decision = route_future.result(timeout=15)
        final_permit = reserve_future.result(timeout=15)
    assert final_decision.selected is not None
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT bucket_id,consumed_units,reserved_units FROM provider_quota_bucket_windows "
            "WHERE bucket_id IN (%s,%s) ORDER BY bucket_id",
            (bucket_a.bucket_id, bucket_z.bucket_id),
        ).fetchall()
    assert rows == [(bucket_a.bucket_id, 1, 1), (bucket_z.bucket_id, 1, 1)]
    assert final_permit.attempt_id is not None


def test_concurrent_authorization_one_reservation_and_single_send_claim(database):
    system = setup(database)
    owner, service, d, _prep, repo, _usage, _auth = system
    barrier = Barrier(2)

    def authorize(_):
        barrier.wait(timeout=5)
        return finalize(system)

    with ThreadPoolExecutor(max_workers=2) as pool:
        permits = list(pool.map(authorize, range(2)))
    assert permits[0] == permits[1]
    with database.connection() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM provider_attempts WHERE invocation_id=%s",
                (permits[0].invocation_id,),
            ).fetchone()[0]
            == 1
        )
    barrier = Barrier(2)

    def claim(_):
        barrier.wait(timeout=5)
        try:
            return service.claim(
                owner_id=owner, scope=SCOPE, permit=permits[0], operation="bounded_generation"
            )
        except RoutingFinalizationError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, range(2)))
    assert sum(r is not None for r in results) == 1
    assert (
        repo.get(owner_id=owner, scope=SCOPE, decision_id=d.routing_decision_id).status
        == "dispatched"
    )


def test_reservation_and_event_rollback_together(database, monkeypatch):
    system = setup(database)
    owner, _service, d, _prep, repo, _usage, _auth = system
    original = repo.append_in_transaction

    def fail_authorization(c, **kwargs):
        if kwargs["event"].kind == "authorized":
            raise RuntimeError("publication-unavailable")
        return original(c, **kwargs)

    monkeypatch.setattr(repo, "append_in_transaction", fail_authorization)
    with pytest.raises(RoutingFinalizationError):
        finalize(system)
    with database.connection() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM provider_invocations WHERE routing_decision_id=%s",
                (str(d.routing_decision_id),),
            ).fetchone()[0]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) FROM provider_quota_reservations r JOIN provider_attempts a USING(attempt_id) "
                "JOIN provider_invocations i USING(invocation_id) WHERE i.owner_id=%s",
                (owner,),
            ).fetchone()[0]
            == 0
        )
    assert (
        repo.get(owner_id=owner, scope=SCOPE, decision_id=d.routing_decision_id).status == "failed"
    )


@pytest.mark.parametrize(
    "change", ["revoke", "delete", "profile", "reservation", "expired", "tokens"]
)
def test_direct_authority_changes_between_reserve_and_claim_deny(database, change):
    system = setup(database)
    owner, service, d, _prep, _repo, _usage, auth = system
    permit = finalize(system)
    if change == "revoke":
        auth.deny = True
    if change == "delete":
        PostgresArtifactMetadataRepository(database).fence(owner)
    if change == "profile":
        service.registry.remove(d.selected.endpoint_profile_id)
    if change == "reservation":
        with database.transaction() as c:
            c.execute(
                "UPDATE provider_quota_reservations SET state='uncertain' WHERE attempt_id=%s",
                (permit.attempt_id,),
            )
    if change == "tokens":
        with database.transaction() as c:
            c.execute(
                "UPDATE provider_attempts SET reserved_tokens=0 WHERE attempt_id=%s",
                (permit.attempt_id,),
            )
    if change == "expired":
        permit = permit.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    with pytest.raises((RoutingFinalizationError, UsageAdmissionDenied, OwnerFenced, RuntimeError)):
        service.claim(owner_id=owner, scope=SCOPE, permit=permit, operation="bounded_generation")
    with database.connection() as c:
        assert (
            c.execute(
                "SELECT dispatch_claimed_at FROM provider_attempts WHERE attempt_id=%s",
                (permit.attempt_id,),
            ).fetchone()[0]
            is None
        )


def test_source_scope_replay_immutable_history_and_corrupt_state(database):
    system = setup(database)
    owner, service, d, _prep, repo, _usage, _auth = system
    service.registry.remove(d.selected.endpoint_profile_id)
    assert service.registry.historical(d.selected).ref == d.selected
    assert replay_deterministic_decision(d, QuotaAwareDeterministicStrategy()) == d.ranking
    baseline_system = setup(database, strategy=DeterministicScoringStrategy())
    baseline_decision = baseline_system[2]
    assert replay_deterministic_decision(
        baseline_decision, DeterministicScoringStrategy()
    ) == baseline_decision.ranking
    with pytest.raises(LookupError):
        repo.get(owner_id="other-owner", scope=SCOPE, decision_id=d.routing_decision_id)
    with database.transaction() as c:
        c.execute(
            "UPDATE routing_decisions SET status='authorized' WHERE decision_id=%s",
            (d.routing_decision_id,),
        )
    with pytest.raises(RuntimeError, match="record_invalid"):
        repo.get(owner_id=owner, scope=SCOPE, decision_id=d.routing_decision_id)


def test_auxiliary_root_budget_concurrent_single_winner_and_idempotency(database):
    owner, service, d, _prep, _repo, _usage, _auth = setup(database, max_auxiliary_calls=1)
    barrier = Barrier(2)
    ids = [uuid4(), uuid4()]

    def consume(i):
        barrier.wait(timeout=5)
        try:
            return service.consume_auxiliary_call(
                owner_id=owner, scope=SCOPE, decision_id=d.routing_decision_id, event_id=ids[i]
            )
        except PersistenceConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(consume, range(2)))
    assert values.count(1) == 1
    winner = values.index(1)
    assert (
        service.consume_auxiliary_call(
            owner_id=owner, scope=SCOPE, decision_id=d.routing_decision_id, event_id=ids[winner]
        )
        == 1
    )


def test_maximum_attempt_and_auxiliary_budgets_fit_postgres_event_sequence(database):
    system = setup(database, max_physical_attempts=32, max_auxiliary_calls=16)
    owner, service, decision, _prep, repo, _usage, _auth = system
    for _ in range(16):
        service.consume_auxiliary_call(
            owner_id=owner,
            scope=SCOPE,
            decision_id=decision.routing_decision_id,
            event_id=uuid4(),
        )

    def failed_send(_profile, _invocation, _attempt):
        return None, AttemptResult(
            outcome="failure", completed_at=datetime.now(UTC), latency_ms=1
        )

    for _ in range(32):
        permit = finalize(system)
        service.dispatch(
            owner_id=owner,
            scope=SCOPE,
            permit=permit,
            operation="bounded_generation",
            send=failed_send,
        )

    record = repo.get(owner_id=owner, scope=SCOPE, decision_id=decision.routing_decision_id)
    assert record.status == "failed"
    assert len(record.events) == 113


def test_reselection_unresolved_send_fence_isolated_by_application_scope(database):
    owner = f"route-owner-{uuid4()}"
    request_id = f"shared-request-{uuid4()}"
    first_scope = ApplicationScope(application_id="application-a")
    second_scope = ApplicationScope(application_id="application-b")
    first = setup(
        database,
        owner_id=owner,
        scope=first_scope,
        request_id=request_id,
        max_reselections=1,
    )
    first_permit = first[1].finalize(
        owner_id=owner,
        scope=first_scope,
        decision_id=first[2].routing_decision_id,
        preparation=first[3],
        operation="bounded_generation",
    )
    first[1].claim(
        owner_id=owner,
        scope=first_scope,
        permit=first_permit,
        operation="bounded_generation",
    )

    second = setup(
        database,
        owner_id=owner,
        scope=second_scope,
        request_id=request_id,
        max_reselections=1,
    )
    second[1].finish(
        owner_id=owner,
        scope=second_scope,
        decision_id=second[2].routing_decision_id,
    )
    child = second[1].route(
        owner_id=owner,
        scope=second_scope,
        task=second[2].task,
        request=second[2].request,
        parent_decision_id=second[2].routing_decision_id,
    )
    assert child.parent_decision_id == second[2].routing_decision_id


def test_dispatch_callback_runs_after_commit_and_settles_exact_attempt(database):
    system = setup(database)
    owner, service, d, _prep, repo, _usage, _auth = system
    permit = finalize(system)

    def send(profile, invocation, attempt):
        with database.connection() as c:
            assert (
                c.execute(
                    "SELECT dispatch_claimed_at FROM provider_attempts WHERE attempt_id=%s",
                    (attempt.attempt_id,),
                ).fetchone()[0]
                is not None
            )
        assert profile.ref == d.selected
        return "synthetic-result", AttemptResult(
            outcome="success", completed_at=datetime.now(UTC), latency_ms=1
        )

    assert (
        service.dispatch(
            owner_id=owner, scope=SCOPE, permit=permit, operation="bounded_generation", send=send
        )
        == "synthetic-result"
    )
    assert (
        repo.get(owner_id=owner, scope=SCOPE, decision_id=d.routing_decision_id).status == "closed"
    )


def test_owner_fence_and_finalization_race_orders_authorization(database):
    system = setup(database)
    owner, service, _d, _prep, _repo, _usage, _auth = system
    barrier = Barrier(2)

    def fence():
        barrier.wait(timeout=5)
        PostgresArtifactMetadataRepository(database).fence(owner)

    def authorize():
        barrier.wait(timeout=5)
        try:
            return finalize(system)
        except OwnerFenced:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        f = pool.submit(fence)
        permit = pool.submit(authorize).result()
        f.result()
    if permit:
        with pytest.raises(OwnerFenced):
            service.claim(
                owner_id=owner, scope=SCOPE, permit=permit, operation="bounded_generation"
            )


def test_concurrent_reselection_consumes_one_root_budget(database):
    owner, service, d, _prep, repo, _usage, _auth = setup(database, max_reselections=1)
    service.finish(
        owner_id=owner, scope=SCOPE, decision_id=d.routing_decision_id, reason="fit-failed"
    )
    barrier = Barrier(2)

    def reselect(_):
        barrier.wait(timeout=5)
        return service.route(
            owner_id=owner,
            scope=SCOPE,
            task=d.task,
            request=d.request,
            parent_decision_id=d.routing_decision_id,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        children = list(pool.map(reselect, range(2)))
    assert children[0] == children[1]
    with database.connection() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM routing_decisions WHERE parent_decision_id=%s",
                (d.routing_decision_id,),
            ).fetchone()[0]
            == 1
        )
    parent = repo.get(owner_id=owner, scope=SCOPE, decision_id=d.routing_decision_id)
    assert parent.status == "reselected"
    assert len([e for e in parent.events if e.kind == "reselected"]) == 1


def test_expired_decisions_purge_normalized_events(database):
    owner, _service, d, _prep, repo, _usage, _auth = setup(database)
    decision_id = uuid4()
    created = datetime.now(UTC) - timedelta(days=2)
    expired = d.model_copy(
        update={
            "routing_decision_id": decision_id,
            "root_decision_id": decision_id,
            "created_at": created,
            "root_deadline_at": created + timedelta(milliseconds=d.task.deadline_ms),
            "replay_until": created + timedelta(days=1),
        }
    )
    repo.begin(owner_id=owner, scope=SCOPE, decision=expired)
    with pytest.raises(RoutingDecisionUnavailable):
        repo.get(owner_id=owner, scope=SCOPE, decision_id=decision_id)
    assert repo.purge_expired(limit=100) >= 1
    with database.connection() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM routing_decision_events WHERE decision_id=%s", (decision_id,)
            ).fetchone()[0]
            == 0
        )


def test_staged_migration_preserves_legacy_audit_and_transfers_quota(database):
    import json
    from importlib.resources import files

    from personal_ai.persistence.routing_migration import migrate_routing_authorities
    from tests.test_routing_migration import old_snapshot

    schema = f"routing_migration_{uuid4().hex}"
    migrations = files("personal_ai.persistence").joinpath("migrations")
    snapshot = old_snapshot()
    profile = snapshot["profiles"][0]
    decision_id = uuid4()
    now = datetime.now(UTC)
    until = now + timedelta(days=1)
    facts = {
        "schema_version": "routing-decision-v1",
        "routing_decision_id": str(decision_id),
        "owner_id": "audit-owner",
        "application_id": "personal_ai",
        "workspace_id": None,
        "candidates": [{"profile": profile}],
    }
    events = [{"event_type": "decision_preparing", "occurred_at": now.isoformat()}]
    with database.transaction() as c:
        # A transaction-local schema exercises the actual SQL cutover without
        # downgrading or modifying the shared isolated integration database.
        c.execute(f"CREATE SCHEMA {schema}")
        c.execute(f"SET LOCAL search_path TO {schema},public")
        c.execute("CREATE TABLE scope_namespaces(scope_id text PRIMARY KEY)")
        for version in (16, 17, 18, 19, 20, 21):
            resource = next(p for p in migrations.iterdir() if p.name.startswith(f"{version:03}_"))
            c.execute(resource.read_text(), prepare=False)
        c.execute("INSERT INTO scope_namespaces VALUES ('system'),('owner')")
        c.execute(
            "INSERT INTO endpoint_registry_snapshots(scope_id,record_id,owner_id,application_id,"
            "revision,registry_version,created_at,updated_at,payload) "
            "VALUES ('system','endpoint-registry-v1','personal-ai-system','personal_ai',1,%s,%s,%s,%s::jsonb)",
            (snapshot["registry_version"], now, now, json.dumps(snapshot)),
        )
        c.execute(
            "INSERT INTO endpoint_profile_version_history VALUES ('system',%s,1,%s)",
            (profile["endpoint_profile_id"], now),
        )
        c.execute(
            "INSERT INTO routing_decisions(scope_id,decision_id,owner_id,application_id,request_id,"
            "root_decision_id,lifecycle_status,decision_facts,outcome_events,created_at,updated_at,replay_until) "
            "VALUES ('owner',%s,'audit-owner','personal_ai','audit-request',%s,'preparing',%s::jsonb,%s::jsonb,%s,%s,%s)",
            (decision_id, decision_id, json.dumps(facts), json.dumps(events), now, now, until),
        )
        c.execute("INSERT INTO artifact_owner_fences(owner_id) VALUES ('fenced-owner')")
        sql = migrations.joinpath("022_routing_authorities.sql").read_text()
        c.execute(sql, prepare=False)
        migrate_routing_authorities(c)
        assert c.execute(
            "SELECT decision_facts,outcome_events,replay_until FROM routing_decisions_legacy WHERE decision_id=%s",
            (decision_id,),
        ).fetchone() == (facts, events, until)
        assert c.execute("SELECT count(*) FROM routing_decisions").fetchone()[0] == 0
        assert (
            c.execute("SELECT owner_id FROM owner_lifecycle_fences").fetchone()[0] == "fenced-owner"
        )
        definitions = c.execute(
            "SELECT profile_version,payload FROM endpoint_profile_definitions ORDER BY profile_version"
        ).fetchall()
        assert [row[0] for row in definitions] == [1, 2]
        assert definitions[0][1]["quota_buckets"][0]["remaining"] == 0
        assert "remaining" not in definitions[1][1]["quota_buckets"][0]
        assert (
            c.execute("SELECT reported_remaining FROM provider_quota_bucket_windows").fetchone()[0]
            == 0
        )
        upgraded = c.execute("SELECT payload FROM endpoint_registry_snapshots").fetchone()[0]
        assert upgraded["schema_version"] == "endpoint-registry-v2"
        assert upgraded["profiles"][0]["profile_version"] == 2
        c.execute(f"DROP SCHEMA {schema} CASCADE")
