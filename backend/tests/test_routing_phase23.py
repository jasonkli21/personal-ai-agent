"""Phase 23 scarcity policy, decision snapshot and recovery contracts."""

from datetime import UTC, datetime, timedelta

import pytest

from personal_ai.auth.scope import ApplicationScope
from personal_ai.routing import (
    EndpointRef,
    EndpointRegistry,
    PreparationIdentity,
    QuotaAwareDeterministicStrategy,
    QuotaBucketDecisionFact,
    RoutingDecisionService,
    RoutingFinalizationError,
    RoutingPreferences,
    StrategyCandidate,
    StrategyView,
)
from personal_ai.usage.contracts import UsageAdmissionDenied
from personal_ai.usage.quota import EndpointRuntimeSnapshot, QuotaLedgerBucketSnapshot
from tests.test_endpoint_registry import _bucket, _profile
from tests.test_routing_phase21 import (
    Authorization,
    MemoryRepository,
    Usage,
    request,
    task,
)

SCOPE = ApplicationScope()


def _quota_fact(
    bucket_id,
    *,
    unit="requests",
    remaining=1,
    reservation=1,
    reset_seconds=7 * 24 * 60 * 60,
    now=None,
    confidence="configured",
):
    observed = now or datetime.now(UTC)
    return QuotaBucketDecisionFact(
        bucket_id=bucket_id,
        unit=unit,
        window_seconds=7 * 24 * 60 * 60,
        window_start=observed - timedelta(days=1),
        reset_at=observed + timedelta(seconds=reset_seconds),
        time_to_reset_seconds=(reset_seconds if confidence != "unknown" else None),
        source="provider_contract",
        confidence=confidence,
        evidence_reference="quota:synthetic-v1",
        limit_units=(remaining + 99) if remaining is not None else None,
        reported_remaining_units=None,
        consumed_units=99,
        reserved_units=0,
        remaining_units=remaining if confidence != "unknown" else None,
        reservation_units=reservation,
        observed_at=observed - timedelta(minutes=1),
        fresh_until=observed + timedelta(days=1),
    )


def _candidate(endpoint_id, bucket_id, *, priority=0, health="healthy", reliability=None):
    return StrategyCandidate(
        endpoint=EndpointRef(endpoint_profile_id=endpoint_id, profile_version=1),
        configured_priority=priority,
        reliability=reliability,
        quota_bucket_ids=(bucket_id,),
        health_status=health,
    )


def test_scarcity_preserves_stronger_route_until_a_qualified_substitute_is_better():
    now = datetime.now(UTC)
    view = StrategyView(
        preferences=RoutingPreferences(quota_scarcity_weight=4_000),
        candidates=(
            _candidate("strong", "strong-bucket", priority=1),
            _candidate("substitute", "substitute-bucket"),
        ),
        quota_buckets=(
            _quota_fact("strong-bucket", remaining=1, now=now),
            _quota_fact("substitute-bucket", remaining=100, now=now),
        ),
        observed_at=now,
    )

    ranked = QuotaAwareDeterministicStrategy().select(view)

    assert ranked[0].endpoint.endpoint_profile_id == "substitute"
    assert ranked[1].reason_code.endswith("quota-scarcity")
    assert ranked[1].score < 1_000


def test_reset_relief_uses_the_recorded_window_and_unknown_capacity_stays_unknown():
    now = datetime.now(UTC)
    prefs = RoutingPreferences(quota_scarcity_weight=4_000)
    base = (
        _candidate("strong", "strong-bucket", priority=1),
        _candidate("substitute", "substitute-bucket"),
    )
    far = StrategyView(
        preferences=prefs,
        candidates=base,
        quota_buckets=(
            _quota_fact("strong-bucket", remaining=1, now=now),
            _quota_fact("substitute-bucket", remaining=100, now=now),
        ),
        observed_at=now,
    )
    near = far.model_copy(
        update={
            "quota_buckets": (
                _quota_fact("strong-bucket", remaining=1, reset_seconds=60, now=now),
                _quota_fact("substitute-bucket", remaining=100, now=now),
            )
        }
    )
    strategy = QuotaAwareDeterministicStrategy()

    far_score = next(
        row.score for row in strategy.select(far) if row.endpoint.endpoint_profile_id == "strong"
    )
    near_score = next(
        row.score for row in strategy.select(near) if row.endpoint.endpoint_profile_id == "strong"
    )

    assert near_score > far_score
    unknown = _quota_fact("strong-bucket", remaining=None, now=now, confidence="unknown")
    assert unknown.remaining_units is None
    uncertain_view = StrategyView(
        preferences=prefs,
        candidates=base,
        quota_buckets=(
            unknown,
            _quota_fact("substitute-bucket", remaining=100, now=now),
        ),
        observed_at=now,
    )
    assert "quota-uncertain" in next(
        row.reason_code
        for row in strategy.select(uncertain_view)
        if row.endpoint.endpoint_profile_id == "strong"
    )


def test_units_are_normalized_per_bucket_and_degraded_health_is_ranked():
    now = datetime.now(UTC)
    view = StrategyView(
        preferences=RoutingPreferences(
            quota_scarcity_weight=2_000,
            reliability_weight=500,
            degraded_health_penalty=300,
        ),
        candidates=(
            _candidate("tokens", "token-bucket", health="degraded", reliability=0.9),
            _candidate("requests", "request-bucket", reliability=0.9),
        ),
        quota_buckets=(
            _quota_fact("token-bucket", unit="tokens", remaining=10_000, reservation=100),
            _quota_fact("request-bucket", unit="requests", remaining=100, reservation=1),
        ),
        observed_at=now,
    )

    ranked = QuotaAwareDeterministicStrategy().select(view)

    assert [row.endpoint.endpoint_profile_id for row in ranked] == ["requests", "tokens"]
    assert "health-degraded" in ranked[1].reason_code
    assert ranked[0].score == ranked[1].score + 300


def test_zero_unit_reservation_is_not_misclassified_as_unknown_capacity():
    now = datetime.now(UTC)
    view = StrategyView(
        preferences=RoutingPreferences(),
        candidates=(_candidate("zero-use", "zero-use-bucket"),),
        quota_buckets=(
            _quota_fact("zero-use-bucket", remaining=0, reservation=0, now=now),
        ),
        observed_at=now,
    )

    ranked = QuotaAwareDeterministicStrategy().select(view)

    assert ranked[0].score == 0
    assert "quota-uncertain" not in ranked[0].reason_code


class QuotaUsage(Usage):
    def __init__(self, repository, capacities):
        super().__init__(repository)
        self.capacities = capacities
        self.window_limits = dict(capacities)

    def routing_snapshot(self, c, profile, requirements, *, operation, now, check_capacity=True):
        reasons = ()
        capacity = self.capacities[profile.endpoint_profile_id]
        if check_capacity and capacity < 1:
            reasons = ("endpoint_quota_exhausted",)
        bucket = profile.quota_buckets[0]
        snapshot = QuotaLedgerBucketSnapshot(
            bucket_id=bucket.bucket_id,
            unit=bucket.unit,
            window_seconds=bucket.window_seconds,
            window_start=now - timedelta(hours=1),
            reset_at=now + timedelta(hours=1),
            time_to_reset_seconds=3600,
            source="provider_contract",
            confidence="configured",
            evidence_reference=bucket.evidence_reference,
            limit_units=self.window_limits[profile.endpoint_profile_id],
            reported_remaining_units=None,
            consumed_units=self.window_limits[profile.endpoint_profile_id] - capacity,
            reserved_units=0,
            remaining_units=capacity,
            reservation_units=1,
            observed_at=now - timedelta(minutes=1),
            fresh_until=now + timedelta(hours=1),
        )
        return EndpointRuntimeSnapshot(
            health_status="unobserved",
            cooldown_until=None,
            failure_streak=0,
            quota_buckets=(snapshot,),
            rejection_reasons=reasons,
        )

    def runtime_rejections(
        self, c, profile, requirements, *, now, check_capacity=True, operation=None
    ):
        if check_capacity and self.capacities[profile.endpoint_profile_id] < 1:
            return ("endpoint_quota_exhausted",)
        return ()

    def reserve_attempt_in_transaction(self, c, invocation, attempt, *, max_attempts):
        endpoint_id = invocation.endpoint.endpoint_profile_id
        if self.capacities[endpoint_id] < 1:
            raise UsageAdmissionDenied("provider_quota_exhausted")
        result = super().reserve_attempt_in_transaction(
            c, invocation, attempt, max_attempts=max_attempts
        )
        self.capacities[endpoint_id] -= 1
        return result


def test_reservation_race_reselects_as_a_linked_decision_without_a_send():
    repository = MemoryRepository()
    first = _profile(
        "scarce-endpoint",
        account_scope_id="free-account-a",
        quota_buckets=(_bucket("bucket-a", authority_scope_id="free-account-a"),),
    )
    second = _profile(
        "substitute-endpoint",
        account_scope_id="free-account-b",
        quota_buckets=(_bucket("bucket-b", authority_scope_id="free-account-b"),),
    )
    registry = EndpointRegistry((first, second))
    usage = QuotaUsage(repository, {first.endpoint_profile_id: 10, second.endpoint_profile_id: 10})
    service = RoutingDecisionService(
        registry, repository, usage=usage, authorization=Authorization()
    )
    routing_task = task(
        endpoint_priorities=(),
        max_reselections=1,
        preferences=RoutingPreferences(quota_scarcity_weight=0, quota_unknown_penalty_weight=0),
    )
    facts = request()
    decision = service.route(owner_id="owner", scope=SCOPE, task=routing_task, request=facts)
    assert decision.selected.endpoint_profile_id == "scarce-endpoint"
    assert decision.schema_version == 4
    assert len(decision.quota_buckets) == 2
    assert decision.request.operation == "bounded_generation"

    # Another request consumes the last shared capacity after selection but
    # before P21 finalization reaches P19's atomic reservation.
    usage.capacities[first.endpoint_profile_id] = 0
    with pytest.raises(RoutingFinalizationError, match="provider_quota_exhausted"):
        service.finalize(
            owner_id="owner",
            scope=SCOPE,
            decision_id=decision.routing_decision_id,
            preparation=PreparationIdentity(
                endpoint=decision.selected,
                serializer_id=first.serializer_id,
                input_tokens=32,
                count_source="test-estimate",
                count_confidence="estimated",
                prepared_input_sha256="1" * 64,
                prepared_at=repository.now,
            ),
            operation="bounded_generation",
        )
    assert not repository.attempts
    assert repository.records[decision.routing_decision_id].status == "failed"

    child = service.route(
        owner_id="owner",
        scope=SCOPE,
        task=routing_task,
        request=facts,
        parent_decision_id=decision.routing_decision_id,
    )

    assert child.parent_decision_id == decision.routing_decision_id
    assert child.selected.endpoint_profile_id == "substitute-endpoint"
    assert child.request.excluded_endpoint_profile_ids == ("scarce-endpoint",)
    assert repository.records[decision.routing_decision_id].events[-1].linked_decision_id == (
        child.routing_decision_id
    )


def test_oversized_quota_snapshot_persists_bounded_no_route_outcome():
    repository = MemoryRepository()
    evidence_reference = "quota:" + ("x" * 494)
    profiles = []
    for endpoint_index in range(4):
        account_id = f"overflow-account-{endpoint_index}"
        buckets = tuple(
            _bucket(
                f"overflow-{endpoint_index}-{bucket_index}",
                authority_scope_id=account_id,
            ).model_copy(update={"evidence_reference": evidence_reference})
            for bucket_index in range(32)
        )
        profiles.append(
            _profile(
                f"overflow-endpoint-{endpoint_index}",
                account_scope_id=account_id,
                quota_buckets=buckets,
            )
        )

    class LargeSnapshotUsage(Usage):
        def routing_snapshot(self, c, profile, requirements, *, operation, now, check_capacity=True):
            snapshots = tuple(
                QuotaLedgerBucketSnapshot(
                    bucket_id=bucket.bucket_id,
                    unit=bucket.unit,
                    window_seconds=bucket.window_seconds,
                    window_start=now - timedelta(hours=1),
                    reset_at=now + timedelta(hours=1),
                    time_to_reset_seconds=3600,
                    source=bucket.source,
                    confidence="configured",
                    evidence_reference=bucket.evidence_reference,
                    limit_units=1,
                    reported_remaining_units=None,
                    consumed_units=0,
                    reserved_units=0,
                    remaining_units=1,
                    reservation_units=1,
                    observed_at=now,
                    fresh_until=now + timedelta(hours=1),
                )
                for bucket in profile.quota_buckets
            )
            return EndpointRuntimeSnapshot(
                health_status="unobserved",
                cooldown_until=None,
                failure_streak=0,
                quota_buckets=snapshots,
                rejection_reasons=(),
            )

    registry = EndpointRegistry(tuple(profiles))
    service = RoutingDecisionService(
        registry,
        repository,
        usage=LargeSnapshotUsage(repository),
        authorization=Authorization(),
    )
    decision = service.route(
        owner_id="owner",
        scope=SCOPE,
        task=task(
            endpoint_priorities=(),
            preferences=RoutingPreferences(
                quota_scarcity_weight=0, quota_unknown_penalty_weight=0
            ),
        ),
        request=request(),
    )

    assert decision.selected is None
    assert decision.no_route_reason == "routing-decision-overflow"
    assert decision.candidates == ()
    assert decision.quota_buckets == ()
    assert repository.records[decision.routing_decision_id].status == "no_route"
