"""Transformation tests; do not substitute for engine migration acceptance."""

import copy
import hashlib
import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from personal_ai.persistence.postgres import migration_checksum
from personal_ai.routing import CounterCompatibility, EndpointRegistrySnapshot
from personal_ai.routing.contracts import EndpointProfile
from personal_ai.routing.definitions import (
    decode_endpoint_profile_definition,
    encode_current_endpoint_profile,
)
from personal_ai.usage.quota import QuotaObservation
from tests.test_endpoint_registry import _bucket, _profile

_ROOT = Path(__file__).resolve().parents[1]
migrate_routing_authorities = importlib.import_module(
    "personal_ai.persistence.migrations_py.022_routing_authorities"
).migrate_routing_authorities


def _canonical_legacy_profile(profile):
    profile = copy.deepcopy(profile)
    profile["capabilities"] = sorted(profile["capabilities"])
    profile["structured_schema_ids"] = sorted(profile["structured_schema_ids"])
    for bucket in profile["quota_buckets"]:
        bucket["operations"] = sorted(bucket["operations"])
    profile["quota_buckets"].sort(key=lambda bucket: bucket["bucket_id"])
    if profile["counter"] is not None:
        profile["counter"]["structured_schema_ids"] = sorted(
            profile["counter"]["structured_schema_ids"]
        )
    return profile


def old_snapshot(profile=None, *, reorder=False):
    profile = (profile or _profile("legacy:profile")).model_dump(mode="json")
    for bucket in profile["quota_buckets"]:
        bucket.update(remaining=0, reset_at=None, observed_at=None, fresh_until=None)
    canonical = _canonical_legacy_profile(profile)
    digest = hashlib.sha256(
        json.dumps(
            {"revision": 1, "profiles": [canonical]},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()
    if reorder:
        profile["capabilities"].reverse()
        profile["structured_schema_ids"].reverse()
        profile["quota_buckets"].reverse()
        for bucket in profile["quota_buckets"]:
            bucket["operations"].reverse()
        if profile["counter"] is not None:
            profile["counter"]["structured_schema_ids"].reverse()
    return {
        "schema_version": "endpoint-registry-v1",
        "revision": 1,
        "registry_version": digest,
        "profiles": [profile],
    }


def _profile_with_unordered_fields(profile_id="canonical:profile"):
    operations = frozenset({"bounded_generation", "token_counting"})
    counter = CounterCompatibility(
        endpoint_profile_id=profile_id,
        endpoint_id="synthetic-endpoint-v1",
        deployment_id="synthetic-deployment-a",
        credential_scope_id="credential-a",
        account_scope_id="account-a",
        provider_id="synthetic",
        model_id="model-a",
        serializer_id="synthetic-chat-v1",
        counter_id="synthetic-counter-v1",
        structured_schema_ids=("schema:z", "schema:a"),
    )
    return _profile(
        profile_id,
        capabilities=frozenset({"bounded_generation", "token_counting"}),
        counter=counter,
        structured_schema_ids=("schema:z", "schema:a"),
        quota_buckets=(
            _bucket("bucket:z", operations=operations),
            _bucket("bucket:a", operations=operations),
        ),
    )


def _unordered_payload_variants(profile, *, schema_version):
    first = profile.model_dump(mode="json")
    first["capabilities"] = ["token_counting", "bounded_generation"]
    first["structured_schema_ids"] = ["schema:z", "schema:a"]
    first["quota_buckets"].sort(key=lambda bucket: bucket["bucket_id"], reverse=True)
    for bucket in first["quota_buckets"]:
        bucket["operations"] = ["token_counting", "bounded_generation"]
        if schema_version == 1:
            bucket.update(remaining=0, reset_at=None, observed_at=None, fresh_until=None)
    first["counter"]["structured_schema_ids"] = ["schema:z", "schema:a"]

    second = copy.deepcopy(first)
    second["capabilities"].reverse()
    second["structured_schema_ids"].reverse()
    second["quota_buckets"].reverse()
    for bucket in second["quota_buckets"]:
        bucket["operations"].reverse()
    second["counter"]["structured_schema_ids"].reverse()
    return first, second


class MigrationConnection:
    def __init__(self, payload):
        self.payload = payload
        self.definitions = {}
        self.quota_windows = {}
        self.upgraded = None
        self.history_conflict = False

    def execute(self, sql, params=()):
        if sql.startswith("SELECT c->'profile'"):
            return SimpleNamespace(fetchall=list)
        if sql.startswith("SELECT pg_advisory_xact_lock"):
            return SimpleNamespace()
        if sql.startswith("SELECT scope_id,record_id,payload"):
            return SimpleNamespace(
                fetchall=lambda: [("scope", "endpoint-registry-v1", self.payload)]
            )
        if sql.startswith("SELECT clock_timestamp"):
            return SimpleNamespace(fetchone=lambda: (datetime.now(UTC),))
        if sql.startswith("INSERT INTO endpoint_profile_definitions"):
            self.definitions.setdefault(
                (params[0], params[1]), (params[2], json.loads(params[3]))
            )
        elif sql.startswith("SELECT definition_schema_version,payload FROM endpoint_profile_definitions"):
            value = self.definitions.get(tuple(params))
            return SimpleNamespace(fetchone=lambda: value)
        elif sql.startswith("INSERT INTO endpoint_profile_version_history"):
            return SimpleNamespace(fetchone=lambda: None if self.history_conflict else (params[2],))
        elif sql.startswith("INSERT INTO provider_quota_bucket_windows"):
            self.quota_windows[(params[0], params[3])] = params
        elif sql.startswith("SELECT window_start,reset_at,authority_scope_id,unit,confidence,source,fresh_until"):
            return SimpleNamespace(fetchone=lambda: None)
        elif sql.startswith("SELECT authority_scope_id,unit,window_seconds,reset_at,observed_at,source,confidence,"):
            row = self.quota_windows[(params[0], params[1])]
            return SimpleNamespace(
                fetchone=lambda: (
                    row[1], row[2], row[4], row[5], row[11], row[6], row[7],
                    row[9], row[10], 0, 0,
                )
            )
        elif sql.startswith("UPDATE provider_quota_bucket_windows"):
            pass
        elif sql.startswith("UPDATE endpoint_registry_snapshots"):
            self.upgraded = json.loads(params[2])
        else:
            raise AssertionError(sql)
        return SimpleNamespace()


def test_migration_retains_v1_definition_moves_runtime_observation_and_upgrades_snapshot():
    c = MigrationConnection(copy.deepcopy(old_snapshot()))
    migrate_routing_authorities(c)

    upgraded = EndpointRegistrySnapshot.model_validate(c.upgraded)
    assert upgraded.schema_version == "endpoint-registry-v2"
    assert upgraded.profiles[0].profile_version == 2
    assert "remaining" not in upgraded.model_dump_json()
    assert c.definitions[("legacy:profile", 1)][0] == 1
    assert "remaining" not in c.definitions[("legacy:profile", 1)][1]["quota_buckets"][0]
    assert c.definitions[("legacy:profile", 2)][0] == 2
    assert c.quota_windows


def test_migration_semantics_ignore_mutable_phase18_and_phase19_runtime_helpers(monkeypatch):
    from personal_ai.persistence import postgres_usage

    original = old_snapshot()

    def changed_runtime_contract(*args, **kwargs):
        raise AssertionError("migration called mutable runtime behavior")

    monkeypatch.setattr(postgres_usage, "_select_quota_window", changed_runtime_contract)
    monkeypatch.setattr(postgres_usage, "_lock_or_seed_bucket", changed_runtime_contract)
    monkeypatch.setattr(EndpointProfile, "model_validate", classmethod(changed_runtime_contract))

    c = MigrationConnection(copy.deepcopy(original))
    migrate_routing_authorities(c)
    assert EndpointRegistrySnapshot.model_validate(c.upgraded).profiles[0].profile_version == 2


def test_corrupt_legacy_registry_is_not_reconstructed_from_current_configuration():
    payload = old_snapshot()
    payload["registry_version"] = "0" * 64
    with pytest.raises(RuntimeError, match="legacy_registry_corrupt"):
        migrate_routing_authorities(MigrationConnection(payload))


def test_conflicting_immutable_definitions_fail_migration():
    c = MigrationConnection(old_snapshot())
    c.definitions[("legacy:profile", 1)] = (
        1,
        _profile("legacy:profile", context_limit_tokens=123).model_dump(mode="json"),
    )
    with pytest.raises(RuntimeError, match="legacy_endpoint_definition_conflict"):
        migrate_routing_authorities(c)


def test_migration_does_not_lower_a_conflicting_profile_high_water_mark():
    c = MigrationConnection(old_snapshot())
    c.history_conflict = True
    with pytest.raises(RuntimeError, match="legacy_endpoint_history_conflict"):
        migrate_routing_authorities(c)


def test_migration_checksum_is_deterministic_and_covers_frozen_implementation():
    sql = (_ROOT / "src/personal_ai/persistence/migrations/022_routing_authorities.sql").read_text()
    migration_python = _ROOT / "src/personal_ai/persistence/migrations_py"
    initializer = (migration_python / "__init__.py").read_bytes()
    frozen = (migration_python / "022_routing_authorities.py").read_bytes()
    expected = hashlib.sha256(
        sql.encode("utf-8") + b"\0" + initializer + b"\0" + frozen
    ).hexdigest()
    assert migration_checksum(22, sql) == expected
    assert migration_checksum(22, sql) == migration_checksum(22, sql)
    assert migration_checksum(21, sql) == hashlib.sha256(sql.encode("utf-8")).hexdigest()


def test_endpoint_definition_decoders_are_versioned_and_independent_of_current_model(monkeypatch):
    profile = _profile("legacy:profile").model_dump(mode="json")
    profile["quota_buckets"][0].update(remaining=0, reset_at=None, observed_at=None, fresh_until=None)

    def changed_current_contract(*args, **kwargs):
        raise AssertionError("historical decoder called current EndpointProfile")

    monkeypatch.setattr(EndpointProfile, "model_validate", classmethod(changed_current_contract))
    v1 = decode_endpoint_profile_definition(1, profile)
    v2_profile = _profile("current:profile").model_dump(mode="json")
    v2 = decode_endpoint_profile_definition(2, v2_profile)

    assert v1.ref.endpoint_profile_id == "legacy:profile"
    assert v1.definition_schema_version == 1
    assert "remaining" not in v1.payload["quota_buckets"][0]
    assert v2.ref.endpoint_profile_id == "current:profile"
    assert v2.definition_schema_version == 2
    with pytest.raises(ValueError, match="endpoint_definition_schema_unsupported"):
        decode_endpoint_profile_definition(3, v2_profile)


@pytest.mark.parametrize("schema_version", [1, 2])
def test_endpoint_definition_decoders_canonicalize_unordered_collections(schema_version):
    profile = _profile_with_unordered_fields()
    first, second = _unordered_payload_variants(profile, schema_version=schema_version)

    decoded_first = decode_endpoint_profile_definition(schema_version, first)
    decoded_second = decode_endpoint_profile_definition(schema_version, second)

    assert decoded_first == decoded_second
    assert decoded_first.serialized_payload == decoded_second.serialized_payload
    canonical = decoded_first.payload
    assert canonical["capabilities"] == ["bounded_generation", "token_counting"]
    assert canonical["structured_schema_ids"] == ["schema:a", "schema:z"]
    assert [bucket["bucket_id"] for bucket in canonical["quota_buckets"]] == [
        "bucket:a",
        "bucket:z",
    ]
    assert all(
        bucket["operations"] == ["bounded_generation", "token_counting"]
        for bucket in canonical["quota_buckets"]
    )
    assert canonical["counter"]["structured_schema_ids"] == ["schema:a", "schema:z"]
    if schema_version == 1:
        assert all("remaining" not in bucket for bucket in canonical["quota_buckets"])


def test_migration_v1_and_v2_definitions_match_runtime_canonical_encoding():
    profile = _profile_with_unordered_fields("legacy:profile")
    legacy = old_snapshot(profile, reorder=True)
    connection = MigrationConnection(copy.deepcopy(legacy))

    migrate_routing_authorities(connection)

    v1_schema, v1_payload = connection.definitions[("legacy:profile", 1)]
    v2_schema, v2_payload = connection.definitions[("legacy:profile", 2)]
    assert v1_schema == 1
    assert decode_endpoint_profile_definition(1, v1_payload) == decode_endpoint_profile_definition(
        1, legacy["profiles"][0]
    )

    migrated_v2 = decode_endpoint_profile_definition(v2_schema, v2_payload)
    runtime_profile = EndpointProfile.model_validate(connection.upgraded["profiles"][0])
    assert v2_schema == 2
    assert migrated_v2 == encode_current_endpoint_profile(runtime_profile)


def test_runtime_quota_observations_validate_freshness_and_remaining():
    static = _profile().quota_buckets[0].model_dump()
    with pytest.raises(ValueError):
        QuotaObservation(**static, remaining=1000)
    with pytest.raises(ValueError):
        QuotaObservation(**static, fresh_until=datetime.now(UTC))
