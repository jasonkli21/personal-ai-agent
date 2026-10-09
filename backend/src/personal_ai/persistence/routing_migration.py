"""One-time, transactional conversion of registry V1 facts for migration 022."""

import hashlib
import json

from personal_ai.routing.contracts import (
    EndpointProfile,
    EndpointRegistrySnapshot,
    compute_registry_version,
)

_DYNAMIC = {"remaining", "reset_at", "observed_at", "fresh_until"}


def historical_profile(payload):
    """Resolve old definitions for audit only; no current eligibility implied."""
    data = dict(payload)
    data["quota_buckets"] = [
        {k: v for k, v in b.items() if k not in _DYNAMIC} for b in data["quota_buckets"]
    ]
    return EndpointProfile.model_validate(data)


def migrate_routing_authorities(connection):
    # Old decisions retain full definitions; validate identity conflicts before cutover.
    legacy = connection.execute(
        "SELECT c->'profile' FROM routing_decisions_legacy, "
        "jsonb_array_elements(decision_facts->'candidates') c WHERE c->'profile' IS NOT NULL"
    ).fetchall()
    for (profile,) in legacy:
        retain_definition(connection, profile)
    rows = connection.execute(
        "SELECT scope_id,record_id,payload FROM endpoint_registry_snapshots FOR UPDATE"
    ).fetchall()
    for scope_id, record_id, payload in rows:
        if payload.get("schema_version") == "endpoint-registry-v2":
            EndpointRegistrySnapshot.model_validate(payload)
            continue
        documents = sorted(payload["profiles"], key=lambda p: p["endpoint_profile_id"])
        for p in documents:
            p["capabilities"] = sorted(p["capabilities"])
            p["structured_schema_ids"] = sorted(p["structured_schema_ids"])
            p["quota_buckets"] = sorted(p["quota_buckets"], key=lambda b: b["bucket_id"])
            for b in p["quota_buckets"]:
                b["operations"] = sorted(b["operations"])
            if p["counter"]:
                p["counter"]["structured_schema_ids"] = sorted(
                    p["counter"]["structured_schema_ids"]
                )
        digest = hashlib.sha256(
            json.dumps(
                {"revision": payload["revision"], "profiles": documents},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).hexdigest()
        if digest != payload["registry_version"]:
            raise RuntimeError("legacy_registry_corrupt")
        profiles = []
        for old in documents:
            retain_definition(connection, old)
            # Import original runtime observations into P19, keeping existing ledger rows.
            from personal_ai.persistence.postgres_usage import (
                _lock_or_seed_bucket,
                _select_quota_window,
            )
            from personal_ai.usage.quota import QuotaObservation

            now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
            for raw in old["quota_buckets"]:
                bucket = QuotaObservation.model_validate(raw)
                start, reset, confidence = _select_quota_window(connection, bucket, now)
                _lock_or_seed_bucket(connection, bucket, start, reset, confidence, now)
            profile = historical_profile(old)
            # Schema change produces a new immutable definition, never reuse V1 identity.
            profile = profile.model_copy(update={"profile_version": old["profile_version"] + 1})
            profiles.append(profile)
            history = connection.execute(
                "INSERT INTO endpoint_profile_version_history(scope_id,endpoint_profile_id,last_profile_version,updated_at) "
                "VALUES (%s,%s,%s,now()) ON CONFLICT(scope_id,endpoint_profile_id) DO UPDATE "
                "SET last_profile_version=EXCLUDED.last_profile_version,updated_at=now() "
                "WHERE endpoint_profile_version_history.last_profile_version=%s RETURNING last_profile_version",
                (
                    scope_id,
                    profile.endpoint_profile_id,
                    profile.profile_version,
                    old["profile_version"],
                ),
            ).fetchone()
            if history is None:
                raise RuntimeError("legacy_endpoint_history_conflict")
            connection.execute(
                "INSERT INTO endpoint_profile_definitions(endpoint_profile_id,profile_version,payload) "
                "VALUES (%s,%s,%s::jsonb)",
                (profile.endpoint_profile_id, profile.profile_version, profile.model_dump_json()),
            )
        revision = payload["revision"] + 1
        snapshot = EndpointRegistrySnapshot(
            revision=revision,
            registry_version=compute_registry_version(profiles, revision=revision),
            profiles=tuple(profiles),
        )
        connection.execute(
            "UPDATE endpoint_registry_snapshots SET revision=%s,registry_version=%s,payload=%s::jsonb,updated_at=now() "
            "WHERE scope_id=%s AND record_id=%s",
            (revision, snapshot.registry_version, snapshot.model_dump_json(), scope_id, record_id),
        )


def retain_definition(connection, payload):
    profile = historical_profile(payload)
    connection.execute(
        "INSERT INTO endpoint_profile_definitions(endpoint_profile_id,profile_version,payload) "
        "VALUES (%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",
        (profile.endpoint_profile_id, profile.profile_version, json.dumps(payload)),
    )
    stored = connection.execute(
        "SELECT payload FROM endpoint_profile_definitions WHERE endpoint_profile_id=%s AND profile_version=%s",
        (profile.endpoint_profile_id, profile.profile_version),
    ).fetchone()
    if stored is None or historical_profile(stored[0]) != profile:
        raise RuntimeError("legacy_endpoint_definition_conflict")
