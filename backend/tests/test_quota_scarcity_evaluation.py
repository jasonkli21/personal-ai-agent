"""Deterministic paired Phase 23 routing evaluation fixtures."""

from personal_ai.evaluation.quota_scarcity import (
    QuotaEvaluationThresholds,
    load_quota_scarcity_suite,
    run_quota_scarcity_evaluation,
)


def test_quota_scarcity_paired_scenarios_conserve_capacity_without_weakening_gates():
    first = run_quota_scarcity_evaluation()
    second = run_quota_scarcity_evaluation()

    assert first == second
    assert first.promoted is True
    assert first.selected_strategy_id == "quota-scarcity"
    assert first.protected_send_equivalents_saved == 1
    assert first.uncertain_dispatches == 0
    assert all(first.gate_results.values())
    assert [scenario.scenario_id for scenario in first.scenarios] == [
        "scarcity-before-reset",
        "scarcity-near-reset",
        "unknown-capacity",
        "free-exhaustion-no-overflow",
    ]
    assert all(
        bucket.conserved
        for scenario in first.scenarios
        for bucket in scenario.scarcity.buckets
    )
    before_reset = first.scenarios[0]
    assert before_reset.protected_send_equivalents_saved == 1
    assert before_reset.scarcity.quality_floor_violations == 0
    assert before_reset.scarcity.unavailable == before_reset.baseline.unavailable
    unknown = first.scenarios[2]
    assert unknown.scarcity.uncertain_dispatches == 0
    assert unknown.scarcity.endpoint_dispatch_counts == {"known-route": 2}
    exhausted = first.scenarios[3]
    assert exhausted.scarcity.dispatched == 0
    assert exhausted.scarcity.unavailable == 2
    assert exhausted.scarcity.endpoint_dispatch_counts == {}


def test_failed_evaluation_threshold_rolls_back_to_fixed_routing_baseline():
    suite, _digest = load_quota_scarcity_suite()
    report = run_quota_scarcity_evaluation(
        suite,
        thresholds=QuotaEvaluationThresholds(
            minimum_quality_delta=0.0,
            maximum_unavailable_increase=0,
            maximum_latency_increase_per_demand_ms=150,
            minimum_protected_send_equivalents_saved=1,
            maximum_uncertain_dispatches=0,
        ),
    )

    assert report.promoted is False
    assert report.gate_results["quality_threshold"] is False
    assert report.selected_strategy_id == report.rollback_strategy_id == "deterministic-scoring"
