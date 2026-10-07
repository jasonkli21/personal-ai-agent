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
