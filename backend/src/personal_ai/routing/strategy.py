"""Pure replaceable strategy over admitted, least-knowledge candidate features."""

from datetime import UTC, datetime
from typing import Protocol

from personal_ai.routing.phase21 import RankedCandidate, RoutingDecision, StrategyRef, StrategyView


class RoutingStrategy(Protocol):
    ref: StrategyRef

    def select(self, view: StrategyView) -> tuple[RankedCandidate, ...]: ...


class RoutingReplayUnavailable(LookupError):
    pass


class DeterministicScoringStrategy:
    # Deliberate semantic identity: formatting/comments do not change replay.
    # Bump when scoring, rounding, missing-value or tie-break semantics change.
    ref = StrategyRef(
        strategy_id="deterministic-scoring",
        semantic_version="1",
        artifact_id="priority-complete-signals-lexical-v1",
    )

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
    if decision.no_route_reason == "routing-strategy-contract-invalid":
        raise RoutingReplayUnavailable("routing_strategy_result_unavailable")
    result = strategy.select(decision.strategy_view()) if decision.selected else ()
    if result != decision.ranking:
        raise RoutingReplayUnavailable("routing_replay_outcome_mismatch")
    return result
