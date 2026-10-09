# ruff: noqa: TRY004
# Invalid persisted definition payloads use a consistent coded ValueError API.
"""Versioned, audit-only endpoint profile definition records.

The persisted representation is intentionally independent of the active
``EndpointProfile`` validator. Bump the definition schema and add a decoder
when that contract changes; never reinterpret an older schema as the newest.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from personal_ai.routing.contracts import EndpointProfile, EndpointRef

CURRENT_ENDPOINT_DEFINITION_SCHEMA_VERSION = 2
_SAFE_ID = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._:/@+-]{0,199}$")
_PROFILE_FIELDS = frozenset(
    {
        "endpoint_profile_id",
        "profile_version",
        "provider_id",
        "model_id",
        "endpoint_id",
        "deployment_id",
        "credential_source",
        "credential_reference",
        "credential_scope_id",
        "account_scope_id",
        "project_scope_id",
        "tier_id",
        "tier_verified",
        "execution_mode",
        "cost_class",
        "billing_owner",
        "enabled",
        "strict_free_enabled",
        "capabilities",
        "context_limit_tokens",
        "max_output_tokens",
        "embedding_dimensions",
        "max_search_query_chars",
        "max_search_results",
        "data_use_policy",
        "strict_free_attestation",
        "serializer_id",
        "runtime_id",
        "structured_schema_ids",
        "counter",
        "quota_membership",
        "quota_buckets",
    }
)
_BUCKET_FIELDS = frozenset(
    {
        "bucket_id",
        "authority_scope_id",
        "operations",
        "unit",
        "window_seconds",
        "source",
        "confidence",
        "reservation_units_per_request",
        "evidence_reference",
        "limit",
    }
)
_V1_DYNAMIC_FIELDS = frozenset({"remaining", "reset_at", "observed_at", "fresh_until"})


@dataclass(frozen=True, slots=True)
class EndpointProfileDefinition:
    """An immutable historical endpoint definition, kept as versioned JSON."""

    endpoint_profile_id: str
    profile_version: int
    definition_schema_version: int
    _payload_json: str

    @property
    def ref(self) -> EndpointRef:
        return EndpointRef(
            endpoint_profile_id=self.endpoint_profile_id,
            profile_version=self.profile_version,
        )

    @property
    def payload(self) -> dict[str, Any]:
        """Return a fresh decoded copy so callers cannot mutate retained state."""
        return json.loads(self._payload_json)

    @property
    def serialized_payload(self) -> str:
        """Canonical JSON text for persistence and immutable identity checks."""
        return self._payload_json


def encode_current_endpoint_profile(profile: EndpointProfile) -> EndpointProfileDefinition:
    """Encode the current model using the frozen V2 definition representation."""
    profile = EndpointProfile.model_validate(profile.model_dump())
    return decode_endpoint_profile_definition(
        CURRENT_ENDPOINT_DEFINITION_SCHEMA_VERSION,
        profile.model_dump(mode="json"),
        expected_endpoint_profile_id=profile.endpoint_profile_id,
        expected_profile_version=profile.profile_version,
    )


def decode_endpoint_profile_definition(
    definition_schema_version: int,
    payload: Any,
    *,
    expected_endpoint_profile_id: str | None = None,
    expected_profile_version: int | None = None,
) -> EndpointProfileDefinition:
    """Decode one known historical representation or fail explicitly."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("endpoint_definition_payload_invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("endpoint_definition_payload_invalid")

    if definition_schema_version == 1:
        normalized = _decode_v1(payload)
    elif definition_schema_version == 2:
        normalized = _decode_v2(payload)
    else:
        raise ValueError("endpoint_definition_schema_unsupported")

    endpoint_profile_id = normalized.get("endpoint_profile_id")
    profile_version = normalized.get("profile_version")
    if (
        endpoint_profile_id is None
        or profile_version is None
        or (expected_endpoint_profile_id is not None
            and endpoint_profile_id != expected_endpoint_profile_id)
        or (expected_profile_version is not None and profile_version != expected_profile_version)
    ):
        raise ValueError("endpoint_definition_identity_mismatch")
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(encoded.encode("ascii")) > 262_144:
        raise ValueError("endpoint_definition_payload_too_large")
    return EndpointProfileDefinition(
        endpoint_profile_id=endpoint_profile_id,
        profile_version=profile_version,
        definition_schema_version=definition_schema_version,
        _payload_json=encoded,
    )


def _decode_v1(payload: dict[str, Any]) -> dict[str, Any]:
    """Freeze the pre-V2 static profile shape without calling current models."""
    normalized = _validate_profile_shape(payload, dynamic_quota_fields=True)
    normalized["quota_buckets"] = [
        {key: value for key, value in bucket.items() if key not in _V1_DYNAMIC_FIELDS}
        for bucket in normalized["quota_buckets"]
    ]
    _canonicalize_unordered_fields(normalized)
    return normalized


def _decode_v2(payload: dict[str, Any]) -> dict[str, Any]:
    """Freeze the V2 static profile shape independently of future P18 models."""
    normalized = _validate_profile_shape(payload, dynamic_quota_fields=False)
    _canonicalize_unordered_fields(normalized)
    return normalized


def _canonicalize_unordered_fields(profile: dict[str, Any]) -> None:
    """Normalize the set-like fields shared by the frozen V1 and V2 shapes."""
    profile["capabilities"] = _sorted_string_values(profile["capabilities"])
    profile["structured_schema_ids"] = _sorted_string_values(
        profile["structured_schema_ids"]
    )
    buckets = profile["quota_buckets"]
    for bucket in buckets:
        bucket["operations"] = _sorted_string_values(bucket["operations"])
    buckets.sort(key=lambda bucket: bucket["bucket_id"])
    counter = profile.get("counter")
    if counter is not None:
        if not isinstance(counter, dict):
            raise ValueError("endpoint_definition_payload_invalid")
        counter["structured_schema_ids"] = _sorted_string_values(
            counter.get("structured_schema_ids")
        )


def _sorted_string_values(values: Any) -> list[str]:
    if (
        not isinstance(values, list)
        or any(not isinstance(value, str) for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("endpoint_definition_payload_invalid")
    return sorted(values)


def _validate_profile_shape(
    payload: dict[str, Any], *, dynamic_quota_fields: bool
) -> dict[str, Any]:
    if set(payload) != _PROFILE_FIELDS:
        raise ValueError("endpoint_definition_payload_invalid")
    profile_id = payload.get("endpoint_profile_id")
    version = payload.get("profile_version")
    if (
        not isinstance(profile_id, str)
        or not _SAFE_ID.fullmatch(profile_id)
        or not isinstance(version, int)
        or isinstance(version, bool)
        or version < 1
        or version > 2_147_483_647
    ):
        raise ValueError("endpoint_definition_identity_invalid")
    for field in (
        "provider_id",
        "model_id",
        "endpoint_id",
        "deployment_id",
        "credential_source",
        "credential_reference",
        "tier_id",
        "execution_mode",
        "cost_class",
        "billing_owner",
        "serializer_id",
        "runtime_id",
        "quota_membership",
    ):
        if not isinstance(payload.get(field), str):
            raise ValueError("endpoint_definition_payload_invalid")
    if not isinstance(payload.get("capabilities"), list) or not isinstance(
        payload.get("structured_schema_ids"), list
    ):
        raise ValueError("endpoint_definition_payload_invalid")
    buckets = payload.get("quota_buckets")
    if not isinstance(buckets, list) or len(buckets) > 32:
        raise ValueError("endpoint_definition_payload_invalid")
    allowed_bucket_fields = _BUCKET_FIELDS | (
        _V1_DYNAMIC_FIELDS if dynamic_quota_fields else frozenset()
    )
    for bucket in buckets:
        if (
            not isinstance(bucket, dict)
            or not _BUCKET_FIELDS.issubset(bucket)
            or not set(bucket).issubset(allowed_bucket_fields)
            or not isinstance(bucket.get("bucket_id"), str)
            or not _SAFE_ID.fullmatch(bucket["bucket_id"])
            or not isinstance(bucket.get("authority_scope_id"), str)
            or not isinstance(bucket.get("unit"), str)
            or not isinstance(bucket.get("operations"), list)
            or any(not isinstance(operation, str) for operation in bucket["operations"])
        ):
            raise ValueError("endpoint_definition_payload_invalid")
    return json.loads(json.dumps(payload, separators=(",", ":")))
