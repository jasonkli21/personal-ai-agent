from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "p10_strict_zero_gate", _ROOT / "infrastructure/phase10/strict_zero_release_gate.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_GATE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_GATE)
REQUIRED_RESOURCES = _GATE.REQUIRED_RESOURCES
validate_report = _GATE.validate_report


def _report():
    observed = datetime.now(UTC).isoformat()
    return {
        "reviewed_at": observed,
        "reviewed_by": "reviewer",
        "strict_zero_reviewed": True,
        "unknown_costs": [],
        "dynamodb": {
            "billing_mode": "PROVISIONED",
            "autoscaling": False,
            "point_in_time_recovery": False,
            "on_demand_backup": False,
            "global_tables": False,
        },
        "claims": [
            {
                "resource": resource,
                "observed_at": observed,
                "source": "operator-verified-console-or-current-plan-evidence",
                "configuration": "explicit account, region, plan, and resource inventory",
                "confidence": "high",
                "eligible": True,
                "hard_cap_enforced": True,
                "allowance_remaining": 10,
                "projected_usage": 10,
                "projected_charge_usd": 0,
            }
            for resource in REQUIRED_RESOURCES
        ],
    }


def test_complete_reviewed_report_passes():
    assert validate_report(_report(), maximum_age_days=1) == []


def test_unknown_or_unbounded_capacity_blocks_release():
    report = _report()
    report["unknown_costs"] = ["Neon overflow"]
    report["dynamodb"]["billing_mode"] = "PAY_PER_REQUEST"
    report["claims"][0]["hard_cap_enforced"] = False
    failures = validate_report(report, maximum_age_days=1)
    assert "unknown_costs_remain" in failures
    assert "dynamodb_must_be_fixed_provisioned" in failures
    assert any(item.startswith("hard_cap_not_proven:") for item in failures)


def test_nonfinite_capacity_and_malformed_configuration_block_release():
    report = _report()
    report["dynamodb"] = []
    report["claims"][0]["projected_usage"] = float("nan")
    failures = validate_report(report, maximum_age_days=1)
    assert "dynamodb_configuration_must_be_object" in failures
    assert any(item.startswith("capacity_unknown:") for item in failures)
