"""Paired direct/cascade baseline with physical and end-to-end resource totals.

The caller supplies the same isolated routing/ledger runtime for each arm. This
runner does not invent provider measurements or activate a cascade policy.
"""

from dataclasses import asdict, dataclass
from statistics import fmean

from personal_ai.evaluation.provider_matrix import (
    fixture_manifest_sha256,
    load_provider_matrix_configuration,
    score_output,
)


@dataclass(frozen=True)
class CascadeMeasurement:
    """Totals include preparation/count/summary calls, failures and rejects."""

    output: str | None
    physical_attempts: int
    auxiliary_calls: int
    input_tokens: int
    output_tokens: int
    quota_units: tuple[tuple[str, int], ...]
    latency_ms: int
    rejected: int

    def __post_init__(self):
        values = (self.physical_attempts, self.auxiliary_calls, self.input_tokens,
                  self.output_tokens, self.latency_ms, self.rejected)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("cascade_measurement_invalid")
        if any(type(units) is not int or units < 0 for _, units in self.quota_units):
            raise ValueError("cascade_measurement_quota_invalid")
        if len({key for key, _ in self.quota_units}) != len(self.quota_units):
            raise ValueError("cascade_measurement_quota_duplicate")


def run_paired_cascade_baseline(execute, *, configuration_sha256, tested_revision,
                              evidence_source="synthetic", minimum_benefit=0.02):
    """`execute(fixture, arm)` must use independent identical starting quota state.

    Compare accepted quality and conservative total token use; quota dimensions
    may not worsen. Per-case quality regressions veto adoption. Synthetic evidence
    can recommend further evaluation, but never authorizes live promotion.
    """
    if evidence_source not in {"synthetic", "live"} or not 0 < minimum_benefit <= 1:
        raise ValueError("cascade_baseline_configuration_invalid")
    if len(configuration_sha256) != 64 or any(c not in "0123456789abcdef" for c in configuration_sha256):
        raise ValueError("cascade_baseline_configuration_invalid")
    fixtures, task, scoring = load_provider_matrix_configuration()
    rows = []
    for fixture in fixtures:
        arms = {}
        for arm in ("direct", "cascade"):
            measured = execute(fixture, arm)
            if not isinstance(measured, CascadeMeasurement):
                raise TypeError("cascade_baseline_measurement_required")
            metrics = score_output(fixture, measured.output or "")
            arms[arm] = {
                **asdict(measured), "output": None,  # never retain raw output in compact report
                "accepted": measured.output is not None and metrics.hard_boundaries_passed,
                "quality": metrics.overall_score if measured.output is not None else 0,
            }
        rows.append({"fixture_id": fixture.fixture_id, **arms})

    totals = {}
    for arm in ("direct", "cascade"):
        quota = {}
        for row in rows:
            for key, units in row[arm]["quota_units"]:
                quota[key] = quota.get(key, 0) + units
        totals[arm] = {
            name: sum(row[arm][name] for row in rows)
            for name in ("physical_attempts", "auxiliary_calls", "input_tokens", "output_tokens",
                         "latency_ms", "rejected")
        }
        totals[arm].update(
            quality=fmean(row[arm]["quality"] for row in rows), quota_units=quota,
            accepted=sum(row[arm]["accepted"] for row in rows),
        )
    direct, cascade = totals["direct"], totals["cascade"]
    quality_safe = all(row["cascade"]["quality"] >= row["direct"]["quality"]
                       and row["cascade"]["accepted"] >= row["direct"]["accepted"] for row in rows)
    direct_tokens = direct["input_tokens"] + direct["output_tokens"]
    cascade_tokens = cascade["input_tokens"] + cascade["output_tokens"]
    token_benefit = (direct_tokens - cascade_tokens) / direct_tokens if direct_tokens else 0
    quota_safe = all(cascade["quota_units"].get(key, 0) <= direct["quota_units"].get(key, 0)
                     for key in set(direct["quota_units"]) | set(cascade["quota_units"]))
    benefit = cascade["quality"] - direct["quality"] >= minimum_benefit or (
        token_benefit >= minimum_benefit and quota_safe
    )
    qualifies = quality_safe and benefit and cascade["rejected"] <= direct["rejected"]
    return {
        "schema_version": "cascade-baseline-v1", "evidence_source": evidence_source,
        "tested_revision": tested_revision, "configuration_sha256": configuration_sha256,
        "fixture_manifest_sha256": fixture_manifest_sha256(fixtures),
        "strategy": "quota-scarcity", "scoring_policy": scoring,
        "minimum_benefit": minimum_benefit, "cases": rows, "totals": totals,
        "token_benefit": token_benefit, "quality_safe": quality_safe,
        "qualifies_for_further_evaluation": qualifies,
        "live_promotion_eligible": qualifies and evidence_source == "live",
        "runtime_default": "direct",
        "task_profile_id": task.profile_id, "task_profile_version": task.profile_version,
    }
