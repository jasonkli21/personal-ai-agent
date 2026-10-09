"""Paired deterministic evaluation of quota-scarcity routing policy."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_ai.routing.phase21 import (
    MAX_ROUTING_QUOTA_BUCKET_FACTS,
    EndpointRef,
    QuotaBucketDecisionFact,
    RankedCandidate,
    RoutingPreferences,
    StrategyCandidate,
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
        shared_reservation_basis = {}
        for endpoint in self.endpoints:
            for bucket_id in endpoint.quota_bucket_ids:
                fact = buckets[bucket_id]
                if fact.confidence != "unknown" and fact.reservation_units is not None:
                    prior = shared_reservation_basis.setdefault(
                        bucket_id, fact.reservation_units
                    )
                    if prior != fact.reservation_units:
                        raise ValueError("quota_scarcity_shared_reservation_basis_conflict")
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
    maximum_unavailable_increase: int = Field(default=0, ge=0, le=MAX_DEMANDS_PER_SCENARIO)
    maximum_latency_increase_per_demand_ms: int = Field(default=150, ge=0, le=600_000)
    minimum_protected_send_equivalents_saved: int = Field(default=1, ge=0, le=MAX_DEMANDS_PER_SCENARIO)
    maximum_uncertain_dispatches: int = Field(default=0, ge=0, le=MAX_DEMANDS_PER_SCENARIO)


class QuotaBucketOutcome(_FrozenModel):
    bucket_id: str
    unit: str
    initial_remaining_units: int | None = Field(default=None, ge=0)
    reserved_units: int = Field(ge=0)
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


class QuotaScarcityEvaluationReport(_FrozenModel):
    schema_version: Literal["quota-scarcity-evaluation-v1"]
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_strategy_id: str
    scarcity_strategy_id: str
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
        _evaluate_scenario(scenario, baseline_strategy, scarcity_strategy)
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
    }
    promoted = all(gate_results.values())
    return QuotaScarcityEvaluationReport(
        schema_version="quota-scarcity-evaluation-v1",
        suite_sha256=suite_sha256,
        baseline_strategy_id=baseline_strategy.ref.strategy_id,
        scarcity_strategy_id=scarcity_strategy.ref.strategy_id,
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


def _evaluate_scenario(scenario, baseline_strategy, scarcity_strategy):
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
    return PairedQuotaScenarioResult(
        scenario_id=scenario.scenario_id,
        baseline=baseline,
        scarcity=scarcity,
        quality_delta=round(scarcity.quality_per_demand - baseline.quality_per_demand, 6),
        unavailable_delta=scarcity.unavailable - baseline.unavailable,
        latency_delta_per_demand_ms=round(
            scarcity.latency_per_demand_ms - baseline.latency_per_demand_ms, 3
        ),
        protected_send_equivalents_saved=protected_saved,
    )


def _simulate(scenario: QuotaDemandScenario, strategy):
    buckets = {fact.bucket_id: fact for fact in scenario.quota_buckets}
    initial_remaining = {bucket_id: fact.remaining_units for bucket_id, fact in buckets.items()}
    reserved_units = {bucket_id: 0 for bucket_id in buckets}
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

    for _ in range(scenario.demand_count):
        available = []
        for endpoint in scenario.endpoints:
            if (
                endpoint.execution_mode != "STRICT_FREE"
                or not endpoint.hard_eligible
                or endpoint.quality_score + _QUALITY_TOLERANCE < scenario.quality_floor
                or (
                    endpoint.health_status == "cooldown"
                    and (endpoint.cooldown_until is None or endpoint.cooldown_until > scenario.observed_at)
                )
            ):
                continue
            endpoint_buckets = [buckets[bucket_id] for bucket_id in endpoint.quota_bucket_ids]
            if any(
                bucket.confidence != "unknown"
                and bucket.remaining_units is not None
                and bucket.reservation_units is not None
                and bucket.remaining_units < bucket.reservation_units
                for bucket in endpoint_buckets
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
            observed_at=scenario.observed_at,
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
        selected_facts = [buckets[bucket_id] for bucket_id in selected.quota_bucket_ids]
        if any(
            fact.confidence != "unknown"
            and fact.remaining_units is not None
            and (fact.reservation_units is None or fact.remaining_units < fact.reservation_units)
            for fact in selected_facts
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
            fact.confidence == "unknown" or fact.remaining_units is None
            for fact in selected_facts
        )
        uncertain_dispatches += int(uncertain)
        for fact in selected_facts:
            if fact.confidence == "unknown" or fact.remaining_units is None:
                continue
            amount = fact.reservation_units
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
            send_equivalents=send_equivalents[fact.bucket_id],
            remaining_units=buckets[fact.bucket_id].remaining_units,
            conserved=(
                initial_remaining[fact.bucket_id] is None
                or reserved_units[fact.bucket_id] <= initial_remaining[fact.bucket_id]
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


def main() -> None:
    report = run_quota_scarcity_evaluation()
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
