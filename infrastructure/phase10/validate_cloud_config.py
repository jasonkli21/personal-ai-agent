"""Static P10.5 IAM/capacity guard for versioned cloud configuration."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def validate() -> list[str]:
    failures: list[str] = []
    runtime = json.loads((ROOT / "dynamodb-runtime-policy.json.tmpl").read_text())
    migration = json.loads((ROOT / "dynamodb-migration-policy.json.tmpl").read_text())
    bootstrap = json.loads((ROOT / "dynamodb-bootstrap-policy.json.tmpl").read_text())
    trust = json.loads((ROOT / "aws-google-oidc-trust-policy.json.tmpl").read_text())
    runtime_actions = set(runtime["Statement"][0]["Action"])
    migration_actions = set(migration["Statement"][0]["Action"])
    bootstrap_actions = set(bootstrap["Statement"][0]["Action"])
    if runtime_actions != {
        "dynamodb:GetItem", "dynamodb:Query", "dynamodb:TransactWriteItems", "dynamodb:UpdateItem"
    }:
        failures.append("runtime_dynamodb_actions_not_minimal")
    if not {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
            "dynamodb:Query", "dynamodb:TransactWriteItems"} <= migration_actions:
        failures.append("migration_dynamodb_actions_incomplete")
    if migration_actions & {"dynamodb:CreateTable", "dynamodb:UpdateTable", "dynamodb:Scan"}:
        failures.append("migration_role_has_bootstrap_or_unbounded_scan")
    if bootstrap_actions & migration_actions:
        failures.append("bootstrap_and_migration_rights_overlap")
    if bootstrap_actions != {
        "dynamodb:CreateTable", "dynamodb:DescribeTable", "dynamodb:UpdateTable", "dynamodb:TagResource"
    }:
        failures.append("bootstrap_dynamodb_actions_unexpected")
    for policy in (runtime, migration):
        for resource in policy["Statement"][0]["Resource"]:
            if "${TABLE_NAME}" not in resource or "*" in resource:
                failures.append("dynamodb_policy_resource_not_table_scoped")
    statement = trust["Statement"][0]
    conditions = statement["Condition"]["StringEquals"]
    if (
        statement["Principal"].get("Federated") != "accounts.google.com"
        or statement["Action"] != "sts:AssumeRoleWithWebIdentity"
        or set(conditions) != {
            "accounts.google.com:aud", "accounts.google.com:oaud", "accounts.google.com:sub"
        }
        or any(not str(value).startswith("${") for value in conditions.values())
    ):
        failures.append("google_oidc_trust_not_exact")

    template = (ROOT / "dynamodb-cloudformation.yaml").read_text()
    if "BillingMode: PROVISIONED" not in template or "TableClass: STANDARD" not in template:
        failures.append("dynamodb_fixed_standard_capacity_missing")
    for capacity in ("RuntimeReadCapacity", "RuntimeWriteCapacity", "JobIndexReadCapacity", "JobIndexWriteCapacity"):
        section = template.split(f"  {capacity}:\n", 1)[-1].split("  Resources:\n", 1)[0]
        if "Type: Number" not in section or "Default:" in section:
            failures.append(f"dynamodb_capacity_not_explicit:{capacity}")
    if "PAY_PER_REQUEST" in template or "AWS::ApplicationAutoScaling" in template:
        failures.append("dynamodb_paid_or_autoscaling_mode_present")
    if any(token in template for token in (
        "PointInTimeRecoverySpecification", "AWS::DynamoDB::GlobalTable", "BackupPolicy"
    )):
        failures.append("dynamodb_paid_extra_present")

    grants = (ROOT / "neon-role-grants.sql.tmpl").read_text()
    runtime_section = grants.split("TO p10_runtime;", 1)[0]
    if "storage_migration_" in runtime_section or "schema_migrations" in runtime_section:
        failures.append("neon_runtime_role_has_migration_access")
    if "legacy_memory_lifecycle_operations" in runtime_section:
        failures.append("neon_runtime_legacy_operation_grant_too_broad")
    migration_section = grants.split("TO p10_storage_migration;", 1)[-1]
    if "schema_migrations" not in migration_section:
        failures.append("neon_migration_schema_version_read_missing")
    if "storage_migration_epochs" not in grants or "p10_storage_migration" not in grants:
        failures.append("neon_migration_role_control_access_missing")
    if "GRANT CREATE" in grants or "GRANT ALL" in grants:
        failures.append("neon_runtime_or_migration_ddl_grant_present")
    return sorted(set(failures))


def main() -> int:
    failures = validate()
    if failures:
        print("P10.5 configuration check failed: " + ", ".join(failures))
        return 2
    print("P10.5 static IAM and capacity checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
