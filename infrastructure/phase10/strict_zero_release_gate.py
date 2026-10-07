"""Fail closed on stale, incomplete, or nonzero Phase 10 cost evidence."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REQUIRED_RESOURCES = frozenset({
    "neon_compute",
    "neon_storage",
    "neon_connections",
    "neon_transfer",
    "neon_vector_toast_and_index_storage",
    "dynamodb_table_read_capacity",
    "dynamodb_table_write_capacity",
    "dynamodb_table_storage",
    "dynamodb_job_gsi_read_capacity",
    "dynamodb_job_gsi_write_capacity",
    "gcp_cloud_run",
    "gcp_pubsub",
    "gcp_gcs",
    "gcp_artifact_registry",
    "gcp_build",
    "gcp_secret_manager",
    "gcp_scheduler",
    "gcp_external_egress",
    "aws_return_traffic",
    "runtime_recovery_amplification",
})


def _finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_report(report: dict, *, maximum_age_days: int, now: datetime | None = None) -> list[str]:
    if not isinstance(report, dict):
        return ["report_must_be_object"]
    now = now or datetime.now(UTC)
    failures: list[str] = []
    if maximum_age_days < 0:
        failures.append("maximum_age_days_invalid")
    reviewed = report.get("reviewed_at")
    try:
        reviewed_at = datetime.fromisoformat(str(reviewed).replace("Z", "+00:00"))
        if reviewed_at.tzinfo is None:
            raise ValueError
        reviewed_at = reviewed_at.astimezone(UTC)
        if reviewed_at > now or now - reviewed_at > timedelta(days=maximum_age_days):
            failures.append("review_date_stale_or_future")
    except (TypeError, ValueError):
        failures.append("review_date_missing_or_invalid")
    if report.get("strict_zero_reviewed") is not True:
        failures.append("strict_zero_review_missing")
    if not report.get("reviewed_by"):
        failures.append("reviewer_missing")
    if report.get("unknown_costs") != []:
        failures.append("unknown_costs_remain")
    dynamodb = report.get("dynamodb")
    if not isinstance(dynamodb, dict):
        failures.append("dynamodb_configuration_must_be_object")
        dynamodb = {}
    if dynamodb.get("billing_mode") != "PROVISIONED":
        failures.append("dynamodb_must_be_fixed_provisioned")
    for setting in ("autoscaling", "point_in_time_recovery", "on_demand_backup", "global_tables"):
        if dynamodb.get(setting) is not False:
            failures.append(f"dynamodb_{setting}_must_be_explicitly_disabled")
    claims = report.get("claims")
    if not isinstance(claims, list):
        claims = []
    by_name = {item.get("resource"): item for item in claims if isinstance(item, dict)}
    if len(by_name) != len([item for item in claims if isinstance(item, dict)]):
        failures.append("duplicate_resource_claim")
    for resource in sorted(REQUIRED_RESOURCES):
        claim = by_name.get(resource)
        if claim is None:
            failures.append(f"allowance_missing:{resource}")
            continue
        observed = claim.get("observed_at")
        try:
            observed_at = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
            if observed_at.tzinfo is None or observed_at > now or now - observed_at > timedelta(days=maximum_age_days):
                raise ValueError
        except (TypeError, ValueError):
            failures.append(f"observation_stale_or_invalid:{resource}")
        if not claim.get("source") or not claim.get("configuration") or claim.get("confidence") != "high":
            failures.append(f"source_or_confidence_unverified:{resource}")
        if claim.get("eligible") is not True:
            failures.append(f"eligibility_not_proven:{resource}")
        if claim.get("hard_cap_enforced") is not True:
            failures.append(f"hard_cap_not_proven:{resource}")
        allowance = claim.get("allowance_remaining")
        projected = claim.get("projected_usage")
        charge = claim.get("projected_charge_usd")
        if not _finite_number(allowance) or not _finite_number(projected):
            failures.append(f"capacity_unknown:{resource}")
        elif allowance < 0 or projected < 0 or projected > allowance:
            failures.append(f"capacity_exceeded:{resource}")
        if not _finite_number(charge) or charge != 0:
            failures.append(f"nonzero_or_unknown_charge:{resource}")
    return sorted(set(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--maximum-age-days", type=int, required=True)
    args = parser.parse_args(argv)
    if args.maximum_age_days < 0:
        parser.error("--maximum-age-days must be non-negative")
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("strict-$0 release gate: report unreadable", file=sys.stderr)
        return 2
    if not isinstance(report, dict):
        print("strict-$0 release gate: report root must be an object", file=sys.stderr)
        return 2
    failures = validate_report(report, maximum_age_days=args.maximum_age_days)
    if failures:
        print("strict-$0 release gate blocked: " + ", ".join(failures), file=sys.stderr)
        return 2
    print("strict-$0 release gate passed for the reviewed configuration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
