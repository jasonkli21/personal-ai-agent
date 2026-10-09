"""Transformation tests; do not substitute for engine migration acceptance."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from personal_ai.persistence.routing_migration import (
    historical_profile,
    migrate_routing_authorities,
)
from personal_ai.routing import EndpointRegistrySnapshot
from personal_ai.usage.quota import QuotaObservation
from tests.test_endpoint_registry import _profile


def old_snapshot():
    profile = _profile("legacy:profile").model_dump(mode="json")
    for bucket in profile["quota_buckets"]:
        bucket.update(remaining=0, reset_at=None, observed_at=None, fresh_until=None)
        bucket["operations"] = sorted(bucket["operations"])
    profile["capabilities"] = sorted(profile["capabilities"])
    digest = hashlib.sha256(
        json.dumps(
            {"revision": 1, "profiles": [profile]},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()
    return {
        "schema_version": "endpoint-registry-v1",
        "revision": 1,
        "registry_version": digest,
        "profiles": [profile],
    }


class MigrationConnection:
    def __init__(self, payload):
        self.payload = payload
        self.definitions = {}
        self.upgraded = None
        self.history_conflict = False

    def execute(self, sql, params=()):
        if sql.startswith("SELECT c->'profile'"):
            return SimpleNamespace(fetchall=list)
        if sql.startswith("SELECT scope_id,record_id,payload"):
            return SimpleNamespace(
                fetchall=lambda: [("scope", "endpoint-registry-v1", self.payload)]
            )
        if sql.startswith("SELECT clock_timestamp"):
            return SimpleNamespace(fetchone=lambda: (datetime.now(UTC),))
        if sql.startswith("INSERT INTO endpoint_profile_definitions"):
            self.definitions.setdefault((params[0], params[1]), json.loads(params[2]))
        elif sql.startswith("SELECT payload FROM endpoint_profile_definitions"):
            value = self.definitions.get(tuple(params))
            return SimpleNamespace(fetchone=lambda: (value,) if value else None)
        elif sql.startswith("UPDATE endpoint_registry_snapshots"):
            self.upgraded = json.loads(params[2])
        elif sql.startswith("INSERT INTO endpoint_profile_version_history"):
            return SimpleNamespace(fetchone=lambda: None if self.history_conflict else (params[2],))
        else:
            raise AssertionError(sql)
        return SimpleNamespace()


def test_migration_retains_old_definition_and_moves_runtime_observation(monkeypatch):
    from personal_ai.persistence import postgres_usage

    seen = []
    monkeypatch.setattr(
        postgres_usage, "_select_quota_window", lambda c, b, n: (n, None, "configured")
    )
    monkeypatch.setattr(postgres_usage, "_lock_or_seed_bucket", lambda c, b, *_: seen.append(b))
    original = old_snapshot()
    c = MigrationConnection(copy.deepcopy(original))
    migrate_routing_authorities(c)
    upgraded = EndpointRegistrySnapshot.model_validate(c.upgraded)
    assert upgraded.schema_version == "endpoint-registry-v2"
    assert upgraded.profiles[0].profile_version == 2
    assert "remaining" not in upgraded.model_dump_json()
    assert c.definitions[("legacy:profile", 1)]["quota_buckets"][0]["remaining"] == 0
    assert seen[0].remaining == 0
    assert historical_profile(c.definitions[("legacy:profile", 1)]).profile_version == 1
    c.payload = c.upgraded
    c.upgraded = None
    migrate_routing_authorities(c)
    assert c.upgraded is None


def test_corrupt_legacy_registry_is_not_reconstructed_from_current_configuration():
    payload = old_snapshot()
    payload["registry_version"] = "0" * 64
    with pytest.raises(RuntimeError, match="legacy_registry_corrupt"):
        migrate_routing_authorities(MigrationConnection(payload))


def test_conflicting_immutable_definitions_fail_migration():
    c = MigrationConnection(old_snapshot())
    c.definitions[("legacy:profile", 1)] = _profile(
        "legacy:profile", context_limit_tokens=123
    ).model_dump(mode="json")
    with pytest.raises(RuntimeError, match="definition_conflict"):
        migrate_routing_authorities(c)


def test_runtime_observations_validate_freshness_and_remaining():
    static = _profile().quota_buckets[0].model_dump()
    with pytest.raises(ValueError):
        QuotaObservation(**static, remaining=1000)
    with pytest.raises(ValueError):
        QuotaObservation(**static, fresh_until=datetime.now(UTC))


def test_migration_does_not_lower_a_conflicting_profile_high_water_mark(monkeypatch):
    from personal_ai.persistence import postgres_usage

    monkeypatch.setattr(
        postgres_usage, "_select_quota_window", lambda c, b, n: (n, None, "configured")
    )
    monkeypatch.setattr(postgres_usage, "_lock_or_seed_bucket", lambda *_: None)
    c = MigrationConnection(old_snapshot())
    c.history_conflict = True
    with pytest.raises(RuntimeError, match="legacy_endpoint_history_conflict"):
        migrate_routing_authorities(c)
