"""Paired deterministic evaluation of quota-scarcity routing policy."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_ai.routing.phase21 import (
    MAX_ROUTING_QUOTA_BUCKET_FACTS,
    EndpointRef,
    QuotaBucketDecisionFact,
    QuotaReservationRequirement,
    RankedCandidate,
    RoutingPreferences,
    StrategyCandidate,
    StrategyRef,
    StrategyView,
)
from personal_ai.routing.strategy import (
    DeterministicScoringStrategy,
    QuotaAwareDeterministicStrategy,
)

FIXTURE_PATH = Path(__file__).with_name("quota-scarcity-fixtures.json")
MAX_SCENARIOS = 16
MAX_DEMANDS_PER_SCENARIO = 10_000
_QUALITY_TOLERANCE = 1e-12


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QuotaScenarioEndpoint(_FrozenModel):
    endpoint: EndpointRef
    execution_mode: Literal["STRICT_FREE", "EXPLICIT_BYOK", "CHATGPT_PLAN", "UNKNOWN"]
    hard_eligible: bool
    rejection_reason: str | None = Field(default=None, max_length=100)
    configured_priority: int = Field(ge=-100_000, le=100_000)
    quality_score: float = Field(ge=0, le=1)
    latency_ms: int = Field(ge=0, le=600_000)
    reliability: float | None = Field(default=None, ge=0, le=1)
    health_status: Literal["unobserved", "healthy", "degraded", "cooldown", "unknown"] = (
        "unobserved"
    )
    cooldown_until: datetime | None = None
    quota_bucket_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    quota_requirements: tuple[QuotaReservationRequirement, ...] = Field(
        min_length=1, max_length=32
    )

    @field_validator("rejection_reason")
    @classmethod
    def safe_rejection_reason(cls, value: str | None) -> str | None:
        if value is not None and not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("quota_scarcity_rejection_reason_invalid")
        return value

    @field_validator("cooldown_until")
    @classmethod
    def aware_cooldown(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("quota_scarcity_timestamp_must_be_aware")
        return value.astimezone(UTC) if value is not None else None


class QuotaDemandScenario(_FrozenModel):
    scenario_id: str = Field(min_length=1, max_length=100)
    demand_count: int = Field(ge=1, le=MAX_DEMANDS_PER_SCENARIO)
    advance_seconds_per_demand: int = Field(default=0, ge=0, le=86_400)
    quality_floor: float = Field(ge=0, le=1)
    preferences: RoutingPreferences
    observed_at: datetime
    endpoints: tuple[QuotaScenarioEndpoint, ...] = Field(min_length=1, max_length=32)
    quota_buckets: tuple[QuotaBucketDecisionFact, ...] = Field(
        min_length=1, max_length=MAX_ROUTING_QUOTA_BUCKET_FACTS
    )
    protected_bucket_ids: tuple[str, ...] = Field(default=(), max_length=128)

    @field_validator("scenario_id")
    @classmethod
    def safe_scenario_id(cls, value: str) -> str:
        if not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("quota_scarcity_scenario_id_invalid")
        return value

    @field_validator("observed_at")
    @classmethod
    def aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("quota_scarcity_timestamp_must_be_aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self) -> QuotaDemandScenario:
        if len({endpoint.endpoint for endpoint in self.endpoints}) != len(self.endpoints):
            raise ValueError("quota_scarcity_endpoint_duplicate")
        buckets = {bucket.bucket_id: bucket for bucket in self.quota_buckets}
        if len(buckets) != len(self.quota_buckets):
            raise ValueError("quota_scarcity_bucket_duplicate")
        if any(
            bucket_id not in buckets
            for endpoint in self.endpoints
            for bucket_id in endpoint.quota_bucket_ids
        ):
            raise ValueError("quota_scarcity_bucket_reference_missing")
        if any(bucket_id not in buckets for bucket_id in self.protected_bucket_ids):
            raise ValueError("quota_scarcity_protected_bucket_missing")
        if len(set(self.protected_bucket_ids)) != len(self.protected_bucket_ids):
            raise ValueError("quota_scarcity_protected_bucket_duplicate")
        for endpoint in self.endpoints:
            requirement_ids = tuple(row.bucket_id for row in endpoint.quota_requirements)
            if set(requirement_ids) != set(endpoint.quota_bucket_ids) or len(requirement_ids) != len(
                endpoint.quota_bucket_ids
            ):
                raise ValueError("quota_scarcity_reservation_requirements_incomplete")
        return self


class QuotaScenarioSuite(_FrozenModel):
    schema_version: Literal["quota-scarcity-suite-v1"]
    scenarios: tuple[QuotaDemandScenario, ...] = Field(min_length=1, max_length=MAX_SCENARIOS)

    @model_validator(mode="after")
    def unique_scenarios(self) -> QuotaScenarioSuite:
        if len({scenario.scenario_id for scenario in self.scenarios}) != len(self.scenarios):
            raise ValueError("quota_scarcity_scenario_duplicate")
        return self


class QuotaEvaluationThresholds(_FrozenModel):
    minimum_quality_delta: float = Field(default=-0.05, ge=-1, le=1)
    minimum_scenario_quality_delta: float = Field(default=-0.05, ge=-1, le=1)
    maximum_unavailable_increase: int = Field(default=0, ge=0, le=MAX_DEMANDS_PER_SCENARIO)
    maximum_latency_increase_per_demand_ms: int = Field(default=150, ge=0, le=600_000)
    minimum_protected_send_equivalents_saved: int = Field(default=1, ge=0, le=MAX_DEMANDS_PER_SCENARIO)
    maximum_uncertain_dispatches: int = Field(default=0, ge=0, le=MAX_DEMANDS_PER_SCENARIO)


class QuotaBucketOutcome(_FrozenModel):
    bucket_id: str
    unit: str
    initial_remaining_units: int | None = Field(default=None, ge=0)
    reserved_units: int = Field(ge=0)
    reset_capacity_added_units: int = Field(default=0, ge=0)
    send_equivalents: int = Field(ge=0)
    remaining_units: int | None = Field(default=None, ge=0)
    conserved: bool


class QuotaPolicyOutcome(_FrozenModel):
    dispatched: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    quality_floor_violations: int = Field(ge=0)
    quality_per_demand: float = Field(ge=0, le=1)
    mean_quality_when_dispatched: float | None = Field(default=None, ge=0, le=1)
    latency_per_demand_ms: float = Field(ge=0)
    uncertain_dispatches: int = Field(ge=0)
    hard_filter_violations: int = Field(ge=0)
    endpoint_dispatch_counts: dict[str, int]
    buckets: tuple[QuotaBucketOutcome, ...]


class PairedQuotaScenarioResult(_FrozenModel):
    scenario_id: str
    baseline: QuotaPolicyOutcome
    scarcity: QuotaPolicyOutcome
    quality_delta: float
    unavailable_delta: int
    latency_delta_per_demand_ms: float
    protected_send_equivalents_saved: int
    policy_configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_results: dict[str, bool]


class QuotaScarcityEvaluationReport(_FrozenModel):
    schema_version: Literal["quota-scarcity-evaluation-v1"]
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_strategy_id: str
    scarcity_strategy_id: str
    baseline_strategy: StrategyRef
    scarcity_strategy: StrategyRef
    baseline_implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scarcity_implementation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_tie_break_version: str
    scarcity_tie_break_version: str
    thresholds: QuotaEvaluationThresholds
    scenarios: tuple[PairedQuotaScenarioResult, ...]
    aggregate_quality_delta: float
    aggregate_unavailable_delta: int
    aggregate_latency_delta_per_demand_ms: float
    protected_send_equivalents_saved: int
    uncertain_dispatches: int
    promoted: bool
    selected_strategy_id: str
    rollback_strategy_id: str
    gate_results: dict[str, bool]


DEFAULT_THRESHOLDS = QuotaEvaluationThresholds()


def load_quota_scarcity_suite(path: Path = FIXTURE_PATH) -> tuple[QuotaScenarioSuite, str]:
    raw = path.read_bytes()
    suite = QuotaScenarioSuite.model_validate_json(raw)
    return suite, hashlib.sha256(raw).hexdigest()


def run_quota_scarcity_evaluation(
    suite: QuotaScenarioSuite | None = None,
    *,
    thresholds: QuotaEvaluationThresholds = DEFAULT_THRESHOLDS,
) -> QuotaScarcityEvaluationReport:
    if suite is None:
        suite, suite_sha256 = load_quota_scarcity_suite()
    else:
        suite = QuotaScenarioSuite.model_validate(suite.model_dump())
        canonical = json.dumps(
            suite.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        suite_sha256 = hashlib.sha256(canonical).hexdigest()

    baseline_strategy = DeterministicScoringStrategy()
    scarcity_strategy = QuotaAwareDeterministicStrategy()
    paired = tuple(
        _evaluate_scenario(scenario, baseline_strategy, scarcity_strategy, thresholds)
        for scenario in suite.scenarios
    )
    total_demands = sum(scenario.demand_count for scenario in suite.scenarios)
    aggregate_quality_delta = sum(
        result.quality_delta * scenario.demand_count
        for result, scenario in zip(paired, suite.scenarios, strict=True)
    ) / total_demands
    aggregate_unavailable_delta = sum(result.unavailable_delta for result in paired)
    aggregate_latency_delta = sum(
        result.latency_delta_per_demand_ms * scenario.demand_count
        for result, scenario in zip(paired, suite.scenarios, strict=True)
    ) / total_demands
    saved = sum(result.protected_send_equivalents_saved for result in paired)
    uncertain = sum(result.scarcity.uncertain_dispatches for result in paired)
    floor_violations = sum(result.scarcity.quality_floor_violations for result in paired)
    hard_filter_violations = sum(result.scarcity.hard_filter_violations for result in paired)
    conservation_violations = sum(
        1
        for result in paired
        for bucket in result.scarcity.buckets
        if not bucket.conserved
    )
    gate_results = {
        "task_quality_floor": floor_violations == 0,
        "quality_threshold": aggregate_quality_delta >= thresholds.minimum_quality_delta,
        "quota_conservation": (
            saved >= thresholds.minimum_protected_send_equivalents_saved
            and conservation_violations == 0
        ),
        "availability": aggregate_unavailable_delta <= thresholds.maximum_unavailable_increase,
        "latency": (
            aggregate_latency_delta <= thresholds.maximum_latency_increase_per_demand_ms
        ),
        "uncertainty": uncertain <= thresholds.maximum_uncertain_dispatches,
        "hard_eligibility": hard_filter_violations == 0,
        "scenario_protection": all(_scenario_passes_gates(result) for result in paired),
    }
    promoted = all(gate_results.values())
    return QuotaScarcityEvaluationReport(
        schema_version="quota-scarcity-evaluation-v1",
        suite_sha256=suite_sha256,
        baseline_strategy_id=baseline_strategy.ref.strategy_id,
        scarcity_strategy_id=scarcity_strategy.ref.strategy_id,
        baseline_strategy=baseline_strategy.ref,
        scarcity_strategy=scarcity_strategy.ref,
        baseline_implementation_sha256=baseline_strategy.implementation_sha256,
        scarcity_implementation_sha256=scarcity_strategy.implementation_sha256,
        baseline_tie_break_version=baseline_strategy.tie_break_version,
        scarcity_tie_break_version=scarcity_strategy.tie_break_version,
        thresholds=thresholds,
        scenarios=paired,
        aggregate_quality_delta=round(aggregate_quality_delta, 6),
        aggregate_unavailable_delta=aggregate_unavailable_delta,
        aggregate_latency_delta_per_demand_ms=round(aggregate_latency_delta, 3),
        protected_send_equivalents_saved=saved,
        uncertain_dispatches=uncertain,
        promoted=promoted,
        selected_strategy_id=(
            scarcity_strategy.ref.strategy_id
            if promoted
            else baseline_strategy.ref.strategy_id
        ),
        rollback_strategy_id=baseline_strategy.ref.strategy_id,
        gate_results=gate_results,
    )


def _evaluate_scenario(scenario, baseline_strategy, scarcity_strategy, thresholds):
    baseline = _simulate(scenario, baseline_strategy)
    scarcity = _simulate(scenario, scarcity_strategy)
    baseline_buckets = {item.bucket_id: item for item in baseline.buckets}
    scarcity_buckets = {item.bucket_id: item for item in scarcity.buckets}
    protected_saved = sum(
        max(
            0,
            baseline_buckets[bucket_id].send_equivalents
            - scarcity_buckets[bucket_id].send_equivalents,
        )
        for bucket_id in scenario.protected_bucket_ids
    )
    quality_delta = round(scarcity.quality_per_demand - baseline.quality_per_demand, 6)
    unavailable_delta = scarcity.unavailable - baseline.unavailable
    latency_delta = round(
        scarcity.latency_per_demand_ms - baseline.latency_per_demand_ms, 3
    )
    return PairedQuotaScenarioResult(
        scenario_id=scenario.scenario_id,
        baseline=baseline,
        scarcity=scarcity,
        quality_delta=quality_delta,
        unavailable_delta=unavailable_delta,
        latency_delta_per_demand_ms=latency_delta,
        protected_send_equivalents_saved=protected_saved,
        policy_configuration_sha256=_policy_configuration_sha256(scenario, scarcity_strategy),
        gate_results=_scenario_gate_results(
            scarcity,
            quality_delta=quality_delta,
            unavailable_delta=unavailable_delta,
            latency_delta=latency_delta,
            thresholds=thresholds,
        ),
    )


def _scenario_gate_results(
    scarcity, *, quality_delta, unavailable_delta, latency_delta, thresholds
) -> dict[str, bool]:
    return {
        "availability": unavailable_delta <= thresholds.maximum_unavailable_increase,
        "quality": quality_delta >= thresholds.minimum_scenario_quality_delta,
        "latency": latency_delta <= thresholds.maximum_latency_increase_per_demand_ms,
        "quality_floor": (
            scarcity.quality_floor_violations == 0 and scarcity.hard_filter_violations == 0
        ),
        "hard_eligibility": scarcity.hard_filter_violations == 0,
        "quota_conservation": all(bucket.conserved for bucket in scarcity.buckets),
    }


def _scenario_passes_gates(result: PairedQuotaScenarioResult) -> bool:
    return all(result.gate_results.values())


def _simulate(scenario: QuotaDemandScenario, strategy):
    buckets = {fact.bucket_id: fact for fact in scenario.quota_buckets}
    initial_remaining = {bucket_id: fact.remaining_units for bucket_id, fact in buckets.items()}
    reserved_units = {bucket_id: 0 for bucket_id in buckets}
    reset_capacity_added = {bucket_id: 0 for bucket_id in buckets}
    send_equivalents = {bucket_id: 0 for bucket_id in buckets}
    endpoint_counts: dict[str, int] = {}
    quality_total = 0.0
    quality_samples = []
    total_latency_ms = 0
    unavailable = 0
    uncertain_dispatches = 0
    floor_violations = 0
    hard_filter_violations = 0
    endpoint_by_ref = {row.endpoint: row for row in scenario.endpoints}

    for demand_index in range(scenario.demand_count):
        now = scenario.observed_at + timedelta(
            seconds=demand_index * scenario.advance_seconds_per_demand
        )
        advanced = {}
        for bucket_id, fact in buckets.items():
            if (
                fact.confidence != "unknown"
                and (fact.fresh_until is None or fact.fresh_until > now)
                and fact.reset_at is not None
                and fact.reset_at <= now
                and fact.window_seconds is not None
                and fact.limit_units is not None
            ):
                periods = int((now - fact.reset_at).total_seconds() // fact.window_seconds) + 1
                reset_capacity_added[bucket_id] += periods * fact.limit_units
            advanced[bucket_id] = _advance_bucket(fact, now)
        buckets = advanced
        available = []
        for endpoint in scenario.endpoints:
            if (
                endpoint.execution_mode != "STRICT_FREE"
                or not endpoint.hard_eligible
                or endpoint.quality_score + _QUALITY_TOLERANCE < scenario.quality_floor
                or (
                    endpoint.health_status == "cooldown"
                    and (endpoint.cooldown_until is None or endpoint.cooldown_until > now)
                )
            ):
                continue
            edge_requirements = {
                row.bucket_id: row.reservation_units for row in endpoint.quota_requirements
            }
            endpoint_buckets = [
                (buckets[bucket_id], edge_requirements[bucket_id])
                for bucket_id in endpoint.quota_bucket_ids
            ]
            if any(
                bucket.confidence != "unknown"
                and bucket.remaining_units is not None
                and reservation_units is not None
                and bucket.remaining_units < reservation_units
                for bucket, reservation_units in endpoint_buckets
            ):
                continue
            available.append(endpoint)
        strategy_candidates = tuple(
            StrategyCandidate(
                endpoint=endpoint.endpoint,
                configured_priority=endpoint.configured_priority,
                quality_score=endpoint.quality_score,
                latency_ms=endpoint.latency_ms,
                reliability=endpoint.reliability,
                quota_bucket_ids=endpoint.quota_bucket_ids,
                quota_requirements=endpoint.quota_requirements,
                health_status=endpoint.health_status,
                cooldown_until=endpoint.cooldown_until,
            )
            for endpoint in available
        )
        relevant_ids = {
            bucket_id for candidate in strategy_candidates for bucket_id in candidate.quota_bucket_ids
        }
        view = StrategyView(
            preferences=scenario.preferences,
            candidates=strategy_candidates,
            quota_buckets=tuple(buckets[bucket_id] for bucket_id in sorted(relevant_ids)),
            observed_at=now,
        )
        ranking: tuple[RankedCandidate, ...] = strategy.select(view) if available else ()
        if not ranking:
            unavailable += 1
            continue
        selected = endpoint_by_ref[ranking[0].endpoint]
        # These conditions mirror routing's pre-strategy hard filters. Keep an
        # explicit counter so a fixture or extension cannot mask a bypass.
        if (
            selected.execution_mode != "STRICT_FREE"
            or not selected.hard_eligible
            or selected.quality_score + _QUALITY_TOLERANCE < scenario.quality_floor
        ):
            hard_filter_violations += 1
            unavailable += 1
            continue
        edge_requirements = {
            row.bucket_id: row.reservation_units for row in selected.quota_requirements
        }
        selected_facts = [
            (buckets[bucket_id], edge_requirements[bucket_id])
            for bucket_id in selected.quota_bucket_ids
        ]
        if any(
            fact.confidence != "unknown"
            and fact.remaining_units is not None
            and (reservation_units is None or fact.remaining_units < reservation_units)
            for fact, reservation_units in selected_facts
        ):
            # The P19 reservation is all-or-nothing across every applicable bucket.
            unavailable += 1
            continue
        if selected.quality_score + _QUALITY_TOLERANCE < scenario.quality_floor:
            floor_violations += 1
        quality_total += selected.quality_score
        quality_samples.append(selected.quality_score)
        total_latency_ms += selected.latency_ms
        endpoint_counts[selected.endpoint.endpoint_profile_id] = (
            endpoint_counts.get(selected.endpoint.endpoint_profile_id, 0) + 1
        )
        uncertain = any(
            reservation_units != 0
            and (fact.confidence == "unknown" or fact.remaining_units is None)
            for fact, reservation_units in selected_facts
        )
        uncertain_dispatches += int(uncertain)
        for fact, amount in selected_facts:
            if amount == 0:
                continue
            if fact.confidence == "unknown" or fact.remaining_units is None:
                continue
            if amount is None or fact.remaining_units < amount:
                raise ValueError("quota_scarcity_atomic_capacity_check_failed")
            reserved_units[fact.bucket_id] += amount
            send_equivalents[fact.bucket_id] += 1
            buckets[fact.bucket_id] = fact.model_copy(
                update={
                    "remaining_units": fact.remaining_units - amount,
                    "consumed_units": fact.consumed_units + amount,
                }
            )

    bucket_outcomes = tuple(
        QuotaBucketOutcome(
            bucket_id=fact.bucket_id,
            unit=fact.unit,
            initial_remaining_units=initial_remaining[fact.bucket_id],
            reserved_units=reserved_units[fact.bucket_id],
            reset_capacity_added_units=reset_capacity_added[fact.bucket_id],
            send_equivalents=send_equivalents[fact.bucket_id],
            remaining_units=buckets[fact.bucket_id].remaining_units,
            conserved=(
                initial_remaining[fact.bucket_id] is None
                or reserved_units[fact.bucket_id]
                <= initial_remaining[fact.bucket_id] + reset_capacity_added[fact.bucket_id]
            ),
        )
        for fact in scenario.quota_buckets
    )
    total_demands = scenario.demand_count
    return QuotaPolicyOutcome(
        dispatched=len(quality_samples),
        unavailable=unavailable,
        quality_floor_violations=floor_violations,
        quality_per_demand=round(quality_total / total_demands, 6),
        mean_quality_when_dispatched=(
            round(sum(quality_samples) / len(quality_samples), 6) if quality_samples else None
        ),
        latency_per_demand_ms=round(total_latency_ms / total_demands, 3),
        uncertain_dispatches=uncertain_dispatches,
        hard_filter_violations=hard_filter_violations,
        endpoint_dispatch_counts=endpoint_counts,
        buckets=bucket_outcomes,
    )


def _advance_bucket(fact: QuotaBucketDecisionFact, now: datetime) -> QuotaBucketDecisionFact:
    """Advance only declared reset/freshness facts; never infer provider capacity."""
    if fact.confidence == "unknown":
        return fact.model_copy(
            update={"remaining_units": None, "time_to_reset_seconds": None}
        )
    if fact.fresh_until is not None and fact.fresh_until <= now:
        return fact.model_copy(
            update={
                "confidence": "unknown",
                "remaining_units": None,
                "time_to_reset_seconds": None,
            }
        )
    reset_at = fact.reset_at
    remaining = fact.remaining_units
    consumed = fact.consumed_units
    reserved = fact.reserved_units
    window_start = fact.window_start
    if reset_at is not None and reset_at <= now:
        if fact.window_seconds is None or fact.limit_units is None:
            return fact.model_copy(
                update={
                    "confidence": "unknown",
                    "remaining_units": None,
                    "time_to_reset_seconds": None,
                }
            )
        periods = int((now - reset_at).total_seconds() // fact.window_seconds) + 1
        window_start = reset_at + timedelta(seconds=(periods - 1) * fact.window_seconds)
        reset_at = reset_at + timedelta(seconds=periods * fact.window_seconds)
        remaining = fact.limit_units
        consumed = 0
        reserved = 0
    time_to_reset = (
        max(0, int((reset_at - now).total_seconds())) if reset_at is not None else None
    )
    return fact.model_copy(
        update={
            "window_start": window_start,
            "reset_at": reset_at,
            "time_to_reset_seconds": time_to_reset,
            "remaining_units": remaining,
            "consumed_units": consumed,
            "reserved_units": reserved,
        }
    )


def _policy_configuration_sha256(scenario, strategy) -> str:
    payload = json.dumps(
        {
            "dependencies": [row.model_dump(mode="json") for row in strategy.dependencies],
            "preferences": scenario.preferences.model_dump(mode="json"),
            "strategy": strategy.ref.model_dump(mode="json"),
            "tie_break_version": strategy.tie_break_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    report = run_quota_scarcity_evaluation()
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
