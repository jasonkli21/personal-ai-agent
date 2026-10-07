from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "p10_cloud_config", ROOT / "infrastructure/phase10/validate_cloud_config.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_p10_iam_capacity_and_neon_role_templates_are_fail_closed():
    assert MODULE.validate() == []


def test_runtime_transaction_components_and_current_schema_grants_are_present():
    runtime_policy = (
        ROOT / "infrastructure/phase10/dynamodb-runtime-policy.json.tmpl"
    ).read_text()
    for action in (
        "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
        "dynamodb:ConditionCheckItem", "dynamodb:TransactWriteItems",
    ):
        assert action in runtime_policy

    grants = (ROOT / "infrastructure/phase10/neon-role-grants.sql.tmpl").read_text()
    assert "legacy_memory_lifecycle_operations" not in grants
    assert "storage_migration_epochs" not in grants
    assert "storage_migration_checkpoints" not in grants
    assert "storage_migration_records" not in grants
