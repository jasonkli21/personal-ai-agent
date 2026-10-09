"""Pure replaceable strategy over admitted, least-knowledge candidate features."""

import hashlib
import inspect
from datetime import UTC, datetime
from typing import Protocol

from personal_ai.routing.phase21 import (
    RankedCandidate,
    RoutingDecision,
    StrategyRef,
    StrategyView,
)


class RoutingStrategy(Protocol):
    ref: StrategyRef

    def select(self, view: StrategyView) -> tuple[RankedCandidate, ...]: ...


class RoutingReplayUnavailable(LookupError):
    pass


class DeterministicScoringStrategy:
    tie_break_version = "score-then-endpoint-id-version-ascending-v1"
    # Manual replay identity, not a source/build digest. Bump semantic_version
    # when externally visible scoring semantics change; bump artifact_id for
    # every implementation behavior change, including bug fixes that preserve
    # the declared policy. Build-level provenance is not mechanically enforced.
    ref = StrategyRef(
        strategy_id="deterministic-scoring",
        semantic_version="1",
        artifact_id="priority-complete-signals-lexical-v1",
    )

    @property
    def dependencies(self) -> tuple[StrategyRef, ...]:
        return ()

    @property
    def implementation_sha256(self) -> str:
        return _implementation_sha256(self.select)

    def select(self, view: StrategyView) -> tuple[RankedCandidate, ...]:
        preferences = view.preferences
        quality = bool(
            preferences.quality_weight and all(c.quality_score is not None for c in view.candidates)
        )
        reliability = bool(
            preferences.reliability_weight
            and all(c.reliability is not None for c in view.candidates)
        )
        latency = bool(
            preferences.latency_penalty_per_second
            and all(c.latency_ms is not None for c in view.candidates)
        )
        ranked = []
        for c in view.candidates:
            score = c.configured_priority * 1000
            components = ["priority"]
            if quality:
                score += round(c.quality_score * 1000) * preferences.quality_weight // 1000
                components.append("quality")
            if reliability:
                score += round(c.reliability * 1000) * preferences.reliability_weight // 1000
                components.append("reliability")
            if latency:
                score -= c.latency_ms * preferences.latency_penalty_per_second // 1000
                components.append("latency")
            ranked.append(
                RankedCandidate(
                    endpoint=c.endpoint, score=score, reason_code="-and-".join(components)
                )
            )
        return tuple(
            sorted(
                ranked,
                key=lambda r: (
                    -r.score,
                    r.endpoint.endpoint_profile_id,
                    r.endpoint.profile_version,
                ),
            )
        )


class QuotaAwareDeterministicStrategy:
    tie_break_version = "score-then-endpoint-id-version-ascending-v1"
    """Deterministic scarcity ranking over Phase 19's frozen decision facts.

    Capacity is converted to equivalent sends of the current operation before
    scoring, so request, token, neuron, and other declared units are never
    compared directly. Unknown capacity receives an explicit configured
    uncertainty penalty; it never becomes a fabricated numeric estimate.
    """

    ref = StrategyRef(
        strategy_id="quota-scarcity",
        semantic_version="1",
        artifact_id="remaining-sends-reset-relief-health-v1",
    )

    @property
    def dependencies(self) -> tuple[StrategyRef, ...]:
        return (DeterministicScoringStrategy.ref,)

    @property
    def implementation_sha256(self) -> str:
        return _implementation_sha256(
            DeterministicScoringStrategy.select,
            self.select,
            _quota_scarcity_penalty,
        )

    def select(self, view: StrategyView) -> tuple[RankedCandidate, ...]:
        base = DeterministicScoringStrategy().select(view)
        buckets = {bucket.bucket_id: bucket for bucket in view.quota_buckets}
        preferences = view.preferences
        adjusted = []
        for row in base:
            candidate = next(c for c in view.candidates if c.endpoint == row.endpoint)
            penalty, scarcity_kind = _quota_scarcity_penalty(candidate, buckets, view)
            degraded_penalty = (
                preferences.degraded_health_penalty
                if candidate.health_status == "degraded"
                else 0
            )
            components = [row.reason_code]
            if scarcity_kind == "known":
                components.append("quota-scarcity")
            elif scarcity_kind == "unknown":
                components.append("quota-uncertain")
            elif scarcity_kind == "mixed":
                components.append("quota-mixed")
            if degraded_penalty:
                components.append("health-degraded")
            adjusted.append(
                RankedCandidate(
                    endpoint=row.endpoint,
                    score=row.score - penalty - degraded_penalty,
                    reason_code="-and-".join(components),
                )
            )
        return tuple(
            sorted(
                adjusted,
                key=lambda row: (
                    -row.score,
                    row.endpoint.endpoint_profile_id,
                    row.endpoint.profile_version,
                ),
            )
        )


def _quota_scarcity_penalty(candidate, buckets, view):
    """Return one bounded penalty, using the tightest applicable bucket."""
    preferences = view.preferences
    if preferences.quota_scarcity_weight == 0 and preferences.quota_unknown_penalty_weight == 0:
        return 0, "none"
    requirements = {row.bucket_id: row.reservation_units for row in candidate.quota_requirements}
    observations = [
        (buckets[bucket_id], requirements.get(bucket_id))
        for bucket_id in candidate.quota_bucket_ids
    ]
    if not observations:
        return 0, "none"
    penalties: list[tuple[str, int]] = []
    for bucket, reservation_units in observations:
        if reservation_units == 0:
            # A quota dimension this operation does not consume cannot make
            # its capacity uncertain or scarce.
            continue
        if (
            bucket.confidence == "unknown"
            or bucket.remaining_units is None
            or reservation_units is None
        ):
            if preferences.quota_unknown_penalty_weight:
                penalties.append(("unknown", preferences.quota_unknown_penalty_weight))
            continue
        sends_remaining = bucket.remaining_units // reservation_units
        pressure_milli = 1000 // (sends_remaining + 1)
        if bucket.time_to_reset_seconds is not None:
            reset_relief = min(
                1.0,
                bucket.time_to_reset_seconds / preferences.quota_reset_relief_seconds,
            )
            pressure_milli = round(pressure_milli * reset_relief)
        penalty = (preferences.quota_scarcity_weight * pressure_milli + 500) // 1000
        if penalty:
            penalties.append(("known", penalty))
    if not penalties:
        return 0, "none"
    maximum = max(amount for _, amount in penalties)
    winners = {kind for kind, amount in penalties if amount == maximum}
    kind = next(iter(winners)) if len(winners) == 1 else "mixed"
    return maximum, kind


def replay_deterministic_decision(
    decision: RoutingDecision, strategy: RoutingStrategy, *, now=None
):
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("routing_timestamp_must_be_aware")
    # Revalidate even instances constructed/copied without normal Pydantic validation.
    decision = RoutingDecision.model_validate(decision.model_dump())
    if instant >= decision.replay_until:
        raise RoutingReplayUnavailable("routing_replay_expired")
    if strategy.ref != decision.strategy:
        raise RoutingReplayUnavailable("historical_strategy_unavailable")
    if decision.no_route_reason in {"quota-snapshot-overflow", "routing-decision-overflow"}:
        raise RoutingReplayUnavailable("routing_replay_facts_unavailable")
    if decision.schema_version == 5:
        dependencies = strategy_dependencies(strategy)
        if dependencies != decision.strategy_dependencies:
            raise RoutingReplayUnavailable("historical_strategy_dependency_unavailable")
        if implementation_sha256_for(strategy) != decision.strategy_implementation_sha256:
            raise RoutingReplayUnavailable("historical_strategy_implementation_unavailable")
        if getattr(strategy, "tie_break_version", "custom-tie-break-unspecified") != (
            decision.strategy_tie_break_version
        ):
            raise RoutingReplayUnavailable("historical_strategy_tie_break_unavailable")
    if decision.no_route_reason == "routing-strategy-contract-invalid":
        raise RoutingReplayUnavailable("routing_strategy_result_unavailable")
    result = strategy.select(decision.strategy_view()) if decision.selected else ()
    if result != decision.ranking:
        raise RoutingReplayUnavailable("routing_replay_outcome_mismatch")
    return result


def _implementation_sha256(*callables) -> str:
    source = "\n\n".join(inspect.getsource(function) for function in callables)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def strategy_dependencies(strategy) -> tuple[StrategyRef, ...]:
    return tuple(getattr(strategy, "dependencies", ()))


def implementation_sha256_for(strategy) -> str:
    declared = getattr(strategy, "implementation_sha256", None)
    if declared is not None:
        return declared
    identity = (
        f"{type(strategy).__module__}.{type(strategy).__qualname__}:"
        f"{strategy.ref.model_dump_json()}"
    )
    return hashlib.sha256(identity.encode()).hexdigest()
