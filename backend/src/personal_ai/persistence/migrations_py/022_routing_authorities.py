# ruff: noqa: N999, TRY004
# N999: the numbered module name is the immutable partner for migration 022.
# TRY004: malformed persisted rows raise RuntimeError with stable migration codes.
"""Frozen Python conversion paired with SQL migration 022.

This module is part of migration 022's checksum and must not be edited after
that migration is released. Later corrections belong in a new numbered
migration. Keep this file self-contained: it must not import live Phase 18/19
models, repositories, or quota helpers.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_DYNAMIC_QUOTA_FIELDS = {"remaining", "reset_at", "observed_at", "fresh_until"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._:/@+-]{0,199}$")
_MAX_PROFILE_VERSION = 2_147_483_647
_PROFILE_FIELDS = {
    "endpoint_profile_id", "profile_version", "provider_id", "model_id", "endpoint_id",
    "deployment_id", "credential_source", "credential_reference", "credential_scope_id",
    "account_scope_id", "project_scope_id", "tier_id", "tier_verified", "execution_mode",
    "cost_class", "billing_owner", "enabled", "strict_free_enabled", "capabilities",
    "context_limit_tokens", "max_output_tokens", "embedding_dimensions",
    "max_search_query_chars", "max_search_results", "data_use_policy",
    "strict_free_attestation", "serializer_id", "runtime_id", "structured_schema_ids",
    "counter", "quota_membership", "quota_buckets",
}
_BUCKET_FIELDS = {
    "bucket_id", "authority_scope_id", "operations", "unit", "window_seconds", "source",
    "confidence", "reservation_units_per_request", "evidence_reference", "limit",
}


@dataclass(frozen=True, slots=True)
class _QuotaBucketV1:
    bucket_id: str
    authority_scope_id: str
    unit: str
    window_seconds: int | None
    reset_at: datetime | None
    source: str
    confidence: str
    evidence_reference: str | None
    limit: int | None
    remaining: int | None
    observed_at: datetime | None
    fresh_until: datetime | None


def migrate_routing_authorities(connection: Any) -> None:
    """Convert V1 registry state using only the code frozen in this file."""
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
        if not isinstance(payload, dict):
            raise RuntimeError("endpoint_registry_record_invalid")
        schema_version = payload.get("schema_version")
        if schema_version == "endpoint-registry-v2":
            _validate_registry_v2(payload)
            continue
        if schema_version != "endpoint-registry-v1":
            raise RuntimeError("endpoint_registry_schema_unsupported")

        revision = _positive_integer(payload.get("revision"), "legacy_registry_corrupt")
        documents = payload.get("profiles")
        if not isinstance(documents, list) or len(documents) > 32:
            raise RuntimeError("legacy_registry_corrupt")
        canonical_old = [_canonical_profile(profile, dynamic_quota_fields=True) for profile in documents]
        canonical_old.sort(key=lambda profile: profile["endpoint_profile_id"])
        old_digest = _registry_digest(canonical_old, revision)
        if payload.get("registry_version") != old_digest:
            raise RuntimeError("legacy_registry_corrupt")

        profiles: list[dict[str, Any]] = []
        now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        for original in canonical_old:
            old_definition = json.loads(json.dumps(original, separators=(",", ":")))
            old_definition["quota_buckets"] = [
                {key: value for key, value in bucket.items() if key not in _DYNAMIC_QUOTA_FIELDS}
                for bucket in original["quota_buckets"]
            ]
            _insert_definition(connection, old_definition, schema_version=1)
            for raw_bucket in original["quota_buckets"]:
                bucket = _quota_bucket(raw_bucket)
                window_start, reset_at, confidence = _select_quota_window(connection, bucket, now)
                _lock_or_seed_bucket(connection, bucket, window_start, reset_at, confidence, now)

            profile = _canonical_profile(original, dynamic_quota_fields=True)
            profile["quota_buckets"] = [
                {key: value for key, value in bucket.items() if key not in _DYNAMIC_QUOTA_FIELDS}
                for bucket in profile["quota_buckets"]
            ]
            profile["profile_version"] += 1
            if profile["profile_version"] > _MAX_PROFILE_VERSION:
                raise RuntimeError("legacy_endpoint_history_conflict")
            profile = _canonical_profile(profile, dynamic_quota_fields=False)
            _insert_definition(connection, profile, schema_version=2)
            profiles.append(profile)

            history = connection.execute(
                "INSERT INTO endpoint_profile_version_history(scope_id,endpoint_profile_id,last_profile_version,updated_at) "
                "VALUES (%s,%s,%s,now()) ON CONFLICT(scope_id,endpoint_profile_id) DO UPDATE "
                "SET last_profile_version=EXCLUDED.last_profile_version,updated_at=now() "
                "WHERE endpoint_profile_version_history.last_profile_version=%s RETURNING last_profile_version",
                (scope_id, profile["endpoint_profile_id"], profile["profile_version"],
                 profile["profile_version"] - 1),
            ).fetchone()
            if history is None:
                raise RuntimeError("legacy_endpoint_history_conflict")

        next_revision = revision + 1
        snapshot = {
            "schema_version": "endpoint-registry-v2",
            "revision": next_revision,
            "registry_version": _registry_digest(profiles, next_revision),
            "profiles": profiles,
        }
        _validate_registry_v2(snapshot)
        connection.execute(
            "UPDATE endpoint_registry_snapshots SET revision=%s,registry_version=%s,payload=%s::jsonb,updated_at=now() "
            "WHERE scope_id=%s AND record_id=%s",
            (next_revision, snapshot["registry_version"], json.dumps(snapshot), scope_id, record_id),
        )


def retain_definition(connection: Any, payload: Any) -> None:
    """Retain a V1 endpoint definition without consulting current models."""
    profile = _canonical_profile(payload, dynamic_quota_fields=True)
    profile["quota_buckets"] = [
        {key: value for key, value in bucket.items() if key not in _DYNAMIC_QUOTA_FIELDS}
        for bucket in profile["quota_buckets"]
    ]
    _insert_definition(connection, profile, schema_version=1)


def _insert_definition(connection: Any, profile: dict[str, Any], *, schema_version: int) -> None:
    connection.execute(
        "INSERT INTO endpoint_profile_definitions(endpoint_profile_id,profile_version,"
        "definition_schema_version,payload) VALUES (%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",
        (profile["endpoint_profile_id"], profile["profile_version"], schema_version,
         json.dumps(profile, sort_keys=True, separators=(",", ":"))),
    )
    stored = connection.execute(
        "SELECT definition_schema_version,payload FROM endpoint_profile_definitions "
        "WHERE endpoint_profile_id=%s AND profile_version=%s",
        (profile["endpoint_profile_id"], profile["profile_version"]),
    ).fetchone()
    if (
        stored is None
        or stored[0] != schema_version
        or not isinstance(stored[1], dict)
        or stored[1] != profile
    ):
        raise RuntimeError("legacy_endpoint_definition_conflict")


def _canonical_profile(payload: Any, *, dynamic_quota_fields: bool) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _PROFILE_FIELDS:
        raise RuntimeError("legacy_registry_corrupt")
    profile_id = payload.get("endpoint_profile_id")
    version = payload.get("profile_version")
    if (
        not isinstance(profile_id, str)
        or not _SAFE_ID.fullmatch(profile_id)
        or not isinstance(version, int)
        or isinstance(version, bool)
        or not 1 <= version <= _MAX_PROFILE_VERSION
    ):
        raise RuntimeError("legacy_registry_corrupt")
    result = json.loads(json.dumps(payload, separators=(",", ":")))
    if not isinstance(result.get("capabilities"), list):
        raise RuntimeError("legacy_registry_corrupt")
    result["capabilities"] = sorted(result["capabilities"])
    if not isinstance(result.get("structured_schema_ids"), list):
        raise RuntimeError("legacy_registry_corrupt")
    result["structured_schema_ids"] = sorted(result["structured_schema_ids"])
    buckets = result.get("quota_buckets")
    if not isinstance(buckets, list) or len(buckets) > 32:
        raise RuntimeError("legacy_registry_corrupt")
    for bucket in buckets:
        if not isinstance(bucket, dict):
            raise RuntimeError("legacy_registry_corrupt")
        allowed = _BUCKET_FIELDS | (_DYNAMIC_QUOTA_FIELDS if dynamic_quota_fields else set())
        if not _BUCKET_FIELDS.issubset(bucket) or not set(bucket).issubset(allowed):
            raise RuntimeError("legacy_registry_corrupt")
        if not isinstance(bucket.get("operations"), list):
            raise RuntimeError("legacy_registry_corrupt")
        bucket["operations"] = sorted(bucket["operations"])
        if dynamic_quota_fields:
            for name in ("reset_at", "observed_at", "fresh_until"):
                _parse_timestamp(bucket.get(name))
    buckets.sort(key=lambda bucket: bucket["bucket_id"])
    counter = result.get("counter")
    if counter is not None:
        if not isinstance(counter, dict) or not isinstance(counter.get("structured_schema_ids"), list):
            raise RuntimeError("legacy_registry_corrupt")
        counter["structured_schema_ids"] = sorted(counter["structured_schema_ids"])
    return result


def _validate_registry_v2(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "endpoint-registry-v2":
        raise RuntimeError("endpoint_registry_schema_unsupported")
    revision = _positive_integer(payload.get("revision"), "endpoint_registry_record_invalid")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or len(profiles) > 32:
        raise RuntimeError("endpoint_registry_record_invalid")
    canonical = [_canonical_profile(profile, dynamic_quota_fields=False) for profile in profiles]
    if len({profile["endpoint_profile_id"] for profile in canonical}) != len(canonical):
        raise RuntimeError("endpoint_registry_record_invalid")
    if _registry_digest(canonical, revision) != payload.get("registry_version"):
        raise RuntimeError("endpoint_registry_record_invalid")


def _registry_digest(profiles: list[dict[str, Any]], revision: int) -> str:
    canonical = [_canonical_profile(profile, dynamic_quota_fields=(
        any(field in bucket for bucket in profile.get("quota_buckets", [])
            for field in _DYNAMIC_QUOTA_FIELDS)
    )) for profile in profiles]
    canonical.sort(key=lambda profile: profile["endpoint_profile_id"])
    encoded = json.dumps(
        {"revision": revision, "profiles": canonical},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _positive_integer(value: Any, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(code)
    return value


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise RuntimeError("legacy_registry_corrupt") from error
    else:
        raise RuntimeError("legacy_registry_corrupt")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("legacy_registry_corrupt")
    return parsed.astimezone(UTC)


def _quota_bucket(raw: dict[str, Any]) -> _QuotaBucketV1:
    for key in ("bucket_id", "authority_scope_id", "unit", "source", "confidence"):
        if not isinstance(raw.get(key), str):
            raise RuntimeError("legacy_registry_corrupt")
    return _QuotaBucketV1(
        bucket_id=raw["bucket_id"],
        authority_scope_id=raw["authority_scope_id"],
        unit=raw["unit"],
        window_seconds=raw.get("window_seconds"),
        reset_at=_parse_timestamp(raw.get("reset_at")),
        source=raw["source"],
        confidence=raw["confidence"],
        evidence_reference=raw.get("evidence_reference"),
        limit=raw.get("limit"),
        remaining=raw.get("remaining"),
        observed_at=_parse_timestamp(raw.get("observed_at")),
        fresh_until=_parse_timestamp(raw.get("fresh_until")),
    )


def _select_quota_window(connection: Any, bucket: _QuotaBucketV1, now: datetime):
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"provider-quota:{bucket.bucket_id}",),
    )
    latest = connection.execute(
        "SELECT window_start,reset_at,authority_scope_id,unit,confidence,source,fresh_until "
        "FROM provider_quota_bucket_windows WHERE bucket_id=%s "
        "ORDER BY window_start DESC LIMIT 1 FOR UPDATE",
        (bucket.bucket_id,),
    ).fetchone()
    if latest is None:
        return _quota_window(bucket, now)
    window_start, reset_at, authority, unit, existing_confidence, existing_source, fresh_until = latest
    if authority != bucket.authority_scope_id or unit != bucket.unit:
        raise ValueError("provider_quota_bucket_identity_conflict")
    if _unknown_daily_bucket(bucket):
        if (
            existing_source == "provider_headers"
            and existing_confidence != "unknown"
            and (fresh_until is None or fresh_until > now)
            and (reset_at is None or reset_at > now)
        ):
            return window_start.astimezone(UTC), reset_at, existing_confidence
        return _utc_day_start(now), None, "unknown"
    if (
        bucket.observed_at is not None
        and reset_at is not None
        and bucket.reset_at is not None
        and bucket.observed_at > window_start
        and bucket.reset_at > now
    ):
        return (
            bucket.reset_at - timedelta(seconds=bucket.window_seconds or 0),
            bucket.reset_at,
            _bucket_confidence(bucket),
        )
    if reset_at is None or reset_at > now:
        confidence = (
            "unknown"
            if bucket.fresh_until is not None and bucket.fresh_until <= now
            else existing_confidence
        )
        return window_start.astimezone(UTC), reset_at, confidence
    if bucket.window_seconds is not None:
        periods = int((now - reset_at).total_seconds() // bucket.window_seconds) + 1
        next_reset = reset_at + timedelta(seconds=periods * bucket.window_seconds)
        return (
            next_reset - timedelta(seconds=bucket.window_seconds),
            next_reset,
            "derived" if existing_confidence != "unknown" else "unknown",
        )
    return window_start.astimezone(UTC), reset_at, "unknown"


def _bucket_confidence(bucket: _QuotaBucketV1) -> str:
    if bucket.confidence == "unknown":
        return "unknown"
    return "exact" if bucket.source == "provider_headers" else "configured"


def _unknown_daily_bucket(bucket: _QuotaBucketV1) -> bool:
    return (
        bucket.confidence == "unknown"
        and bucket.limit is None
        and bucket.remaining is None
        and bucket.window_seconds is None
        and bucket.reset_at is None
        and bucket.observed_at is None
    )


def _utc_day_start(value: datetime) -> datetime:
    value = value.astimezone(UTC)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _quota_window(bucket: _QuotaBucketV1, now: datetime):
    confidence = _bucket_confidence(bucket)
    reset_at = bucket.reset_at
    window = bucket.window_seconds
    if _unknown_daily_bucket(bucket):
        return _utc_day_start(now), None, "unknown"
    if reset_at is not None and window is not None and reset_at <= now:
        periods = int((now - reset_at).total_seconds() // window) + 1
        reset_at = reset_at + timedelta(seconds=periods * window)
        window_start = reset_at - timedelta(seconds=window)
        if confidence != "unknown":
            confidence = "derived"
    elif reset_at is not None and window is not None:
        window_start = reset_at - timedelta(seconds=window)
    else:
        window_start = bucket.observed_at or now
        if reset_at is None and window is not None:
            reset_at = window_start + timedelta(seconds=window)
            if confidence != "unknown":
                confidence = "derived"
    if bucket.fresh_until is not None and bucket.fresh_until <= now:
        confidence = "unknown"
    if reset_at is not None and reset_at <= now and bucket.reset_at is None:
        confidence = "unknown"
    return window_start.astimezone(UTC), reset_at, confidence


def _lock_or_seed_bucket(
    connection: Any,
    bucket: _QuotaBucketV1,
    window_start: datetime,
    reset_at: datetime | None,
    confidence: str,
    now: datetime,
) -> None:
    source = bucket.source
    observed_at = bucket.observed_at
    fresh_until = bucket.fresh_until
    connection.execute(
        "INSERT INTO provider_quota_bucket_windows(bucket_id,authority_scope_id,unit,window_start,"
        "window_seconds,reset_at,source,confidence,evidence_reference,limit_units,reported_remaining,"
        "observed_at,fresh_until,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(bucket_id,window_start) DO NOTHING",
        (
            bucket.bucket_id, bucket.authority_scope_id, bucket.unit, window_start,
            bucket.window_seconds, reset_at, source, confidence, bucket.evidence_reference,
            bucket.limit, bucket.remaining, observed_at, fresh_until, now,
        ),
    )
    existing = connection.execute(
        "SELECT authority_scope_id,unit,window_seconds,reset_at,observed_at,source,confidence,"
        "limit_units,reported_remaining,consumed_units,reserved_units "
        "FROM provider_quota_bucket_windows WHERE bucket_id=%s AND window_start=%s FOR UPDATE",
        (bucket.bucket_id, window_start),
    ).fetchone()
    if existing is None:
        raise RuntimeError("provider_quota_bucket_state_missing")
    if existing[0] != bucket.authority_scope_id or existing[1] != bucket.unit:
        raise ValueError("provider_quota_bucket_identity_conflict")
    if (
        bucket.window_seconds is not None and existing[2] is not None
        and bucket.window_seconds != existing[2]
    ) or (bucket.reset_at is not None and existing[3] != bucket.reset_at):
        raise ValueError("provider_quota_window_identity_conflict")
    if observed_at is not None and (existing[4] is None or observed_at > existing[4]):
        connection.execute(
            "UPDATE provider_quota_bucket_windows SET source=%s,confidence=%s,evidence_reference=%s,"
            "limit_units=%s,reported_remaining=%s,observed_at=%s,fresh_until=%s,"
            "reset_at=COALESCE(%s,reset_at),updated_at=%s WHERE bucket_id=%s AND window_start=%s",
            (
                source, confidence, bucket.evidence_reference, bucket.limit, bucket.remaining,
                observed_at, fresh_until, reset_at, now, bucket.bucket_id, window_start,
            ),
        )
        return
    if existing[5] == "provider_headers":
        if bucket.limit is not None:
            connection.execute(
                "UPDATE provider_quota_bucket_windows SET limit_units=CASE WHEN limit_units IS NULL "
                "THEN %s ELSE LEAST(limit_units,%s) END,updated_at=%s "
                "WHERE bucket_id=%s AND window_start=%s",
                (bucket.limit, bucket.limit, now, bucket.bucket_id, window_start),
            )
        return
    if (
        source in {"operator_attestation", "provider_contract"}
        and confidence != "unknown"
        and (bucket.limit is not None or bucket.remaining is not None)
    ):
        existing_limit, existing_remaining = existing[7], existing[8]
        used = int(existing[9]) + int(existing[10])
        conservative_total = existing_limit
        if existing_remaining is not None:
            remaining_total = used + int(existing_remaining)
            conservative_total = (
                remaining_total if conservative_total is None
                else min(int(conservative_total), remaining_total)
            )
        if bucket.limit is not None:
            conservative_total = (
                int(bucket.limit) if conservative_total is None
                else min(int(conservative_total), int(bucket.limit))
            )
        if bucket.remaining is not None:
            remaining_total = used + int(bucket.remaining)
            conservative_total = (
                remaining_total if conservative_total is None
                else min(int(conservative_total), remaining_total)
            )
        connection.execute(
            "UPDATE provider_quota_bucket_windows SET source=%s,confidence=%s,evidence_reference=%s,"
            "limit_units=%s,reported_remaining=NULL,observed_at=NULL,fresh_until=NULL,"
            "window_seconds=COALESCE(%s,window_seconds),reset_at=COALESCE(%s,reset_at),updated_at=%s "
            "WHERE bucket_id=%s AND window_start=%s",
            (
                source, confidence, bucket.evidence_reference, conservative_total,
                bucket.window_seconds, reset_at, now, bucket.bucket_id, window_start,
            ),
        )
