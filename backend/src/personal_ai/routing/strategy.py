"""Replaceable, provider-free Phase 21 routing strategies."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import UTC, datetime
from typing import Protocol

from personal_ai.routing.phase21 import (
    RankedCandidate,
    RoutingDecisionObservation,
    RoutingStrategyIdentity,
    RoutingStrategyInput,
    RoutingStrategyResult,
)


class RoutingStrategy(Protocol):
    """A strategy sees typed eligible endpoint facts and returns selection data."""

    def identity(self, value: RoutingStrategyInput) -> RoutingStrategyIdentity: ...

    def select(self, value: RoutingStrategyInput) -> RoutingStrategyResult: ...


class RoutingReplayUnavailable(LookupError):
    """Required decision-time facts or the exact recorded strategy are unavailable."""


class DeterministicScoringStrategy:
    """Baseline scorer using task-configured preferences and stable lexical ties."""

    strategy_id = "deterministic-scoring"
    strategy_version = "1"
    tie_break_version = "endpoint-profile-id-then-version-ascending-v1"

    def identity(self, value: RoutingStrategyInput) -> RoutingStrategyIdentity:
        task_configuration = {
            "task_profile_id": value.task.profile_id,
            "task_profile_version": value.task.profile_version,
            "endpoint_priorities": [
                row.model_dump(mode="json") for row in value.task.endpoint_priorities
            ],
            "preferences": value.task.preferences.model_dump(mode="json"),
            "tie_break_version": self.tie_break_version,
        }
        configuration_payload = json.dumps(
            task_configuration, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        try:
            implementation = inspect.getsource(type(self)).encode("utf-8")
        except (OSError, TypeError) as error:
            raise RoutingReplayUnavailable(
                "deterministic routing implementation digest unavailable"
            ) from error
        return RoutingStrategyIdentity(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            strategy_implementation_sha256=hashlib.sha256(implementation).hexdigest(),
            configuration_version=f"{value.task.profile_id}:{value.task.profile_version}",
            configuration_sha256=hashlib.sha256(configuration_payload).hexdigest(),
            tie_break_version=self.tie_break_version,
        )

    def select(self, value: RoutingStrategyInput) -> RoutingStrategyResult:
        if not value.candidates:
            raise ValueError("routing_strategy_requires_eligible_candidates")
        identity = self.identity(value)
        preferences = value.task.preferences
        use_quality = bool(
            preferences.quality_weight
            and all(candidate.quality_score is not None for candidate in value.candidates)
        )
        use_reliability = bool(
            preferences.reliability_weight
            and all(candidate.reliability is not None for candidate in value.candidates)
        )
        use_latency = bool(
            preferences.latency_penalty_per_second
            and all(candidate.latency_ms is not None for candidate in value.candidates)
        )
        ranked: list[RankedCandidate] = []
        for candidate in value.candidates:
            # The priority is explicit task configuration. Missing measurements
            # contribute no numeric score and are never represented as zero-quality.
            score = candidate.configured_priority * 1_000
            if use_quality:
                score += round(candidate.quality_score * 1_000) * preferences.quality_weight // 1_000
            if use_reliability:
                score += round(candidate.reliability * 1_000) * preferences.reliability_weight // 1_000
            if use_latency:
                score -= candidate.latency_ms * preferences.latency_penalty_per_second // 1_000
            components = ["priority"]
            if use_quality:
                components.append("quality")
            if use_reliability:
                components.append("reliability")
            if use_latency:
                components.append("latency")
            reason = "-and-".join(components)
            ranked.append(RankedCandidate(
                endpoint_profile_id=candidate.profile.endpoint_profile_id,
                profile_version=candidate.profile.profile_version,
                score=score,
                reason_code=reason,
            ))
        ranked.sort(key=lambda item: (
            -item.score,
            item.endpoint_profile_id,
            item.profile_version,
        ))
        return RoutingStrategyResult(
            selected_endpoint_profile_id=ranked[0].endpoint_profile_id,
            selected_profile_version=ranked[0].profile_version,
            ranked_candidates=tuple(ranked),
            strategy_id=identity.strategy_id,
            strategy_version=identity.strategy_version,
            strategy_implementation_sha256=identity.strategy_implementation_sha256,
            configuration_version=identity.configuration_version,
            configuration_sha256=identity.configuration_sha256,
            tie_break_version=identity.tie_break_version,
            reason_code=ranked[0].reason_code,
        )


def replay_deterministic_decision(
    observation: RoutingDecisionObservation,
    strategy: RoutingStrategy,
    *,
    now: datetime | None = None,
) -> RoutingStrategyResult | None:
    """Rerun the recorded eligible set without reading current registry or prompt data."""
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("routing_timestamp_must_be_aware")
    if instant.astimezone(UTC) >= observation.replay_until:
        raise RoutingReplayUnavailable("routing decision replay expired")
    if observation.lifecycle_status != "preparing" or observation.strategy_result is None:
        raise RoutingReplayUnavailable("recorded decision has no validated strategy result")
    if observation.replay_completeness != "complete" or observation.strategy_input is None:
        raise RoutingReplayUnavailable("routing decision replay facts incomplete")
    identity = strategy.identity(observation.strategy_input)
    if identity != observation.strategy_identity:
        raise RoutingReplayUnavailable("recorded routing strategy version unavailable")
    result = strategy.select(observation.strategy_input)
    if (
        result.strategy_id != identity.strategy_id
        or result.strategy_version != identity.strategy_version
        or result.strategy_implementation_sha256 != identity.strategy_implementation_sha256
        or result.configuration_version != identity.configuration_version
        or result.configuration_sha256 != identity.configuration_sha256
        or result.tie_break_version != identity.tie_break_version
    ):
        raise RoutingReplayUnavailable("routing strategy replay identity mismatch")
    if result != observation.strategy_result:
        raise RoutingReplayUnavailable("routing strategy replay outcome mismatch")
    return result
