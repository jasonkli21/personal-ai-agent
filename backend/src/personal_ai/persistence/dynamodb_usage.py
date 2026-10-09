"""Scoped, bounded DynamoDB operational events for provider attempts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from time import monotonic

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.dynamodb import (
    _delete,
    _namespace,
    _namespace_puts,
    _put,
)
from personal_ai.storage.errors import StorageUnavailableError

_EVENT_LIMIT_BYTES = 16 * 1024
PROVIDER_USAGE_EVENT_FIELDS = frozenset({
    "schema_version", "event_id", "invocation_id", "attempt_id", "parent_attempt_id",
    "send_number", "owner_id", "application_id", "workspace_id", "task_id", "operation",
    "request_id", "run_id", "endpoint_profile_id", "endpoint_profile_version", "provider_id",
    "model_id", "endpoint_id", "deployment_id", "credential_source", "credential_scope_id",
    "account_scope_id", "project_scope_id", "tier_id", "execution_mode", "cost_class",
    "billing_owner", "serializer_id", "runtime_id", "quota_membership", "routing_decision_id",
    "routing_strategy_id", "routing_strategy_version", "registry_version", "policy_version",
    "status", "error_code", "http_status", "started_at", "completed_at", "latency_ms",
    "input_tokens", "output_tokens", "total_tokens", "usage_source", "usage_confidence",
    "unit_usage", "unit_usage_source", "unit_usage_confidence", "rate_limits",
})


class DynamoDBProviderUsageEventRepository:
    """Append-only attempt facts; Postgres remains the admission authority."""

    def __init__(self, table, *, retention_days: int = 90) -> None:
        if not 7 <= retention_days <= 365:
            raise ValueError("provider_usage_retention_invalid")
        self.table = table
        self.retention_days = retention_days

    def publish(self, event: dict) -> None:
        if (
            not isinstance(event, dict)
            or set(event) != PROVIDER_USAGE_EVENT_FIELDS
            or event.get("schema_version") != "provider-usage-event-v1"
        ):
            raise ValueError("provider_usage_event_schema_invalid")
        owner_id = _bounded(event.get("owner_id"), 200)
        application_id = _bounded(event.get("application_id"), 42)
        workspace_id = event.get("workspace_id")
        if workspace_id is not None:
            workspace_id = _bounded(workspace_id, 100)
        scope = ApplicationScope(application_id=application_id, workspace_id=workspace_id)
        attempt_id = _bounded(event.get("attempt_id"), 36)
        invocation_id = _bounded(event.get("invocation_id"), 36)
        completed_at = datetime.fromisoformat(event["completed_at"])
        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("provider_usage_event_timestamp_invalid")
        completed_at = completed_at.astimezone(UTC)
        timestamp = completed_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        namespace = _namespace(scope, owner_id)
        partition = f"{namespace}#USAGE"
        sort_key = f"PUE#{timestamp}#{attempt_id}"
        expires_at = int((completed_at + timedelta(days=self.retention_days)).timestamp())
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        item = {
            "PK": partition,
            "SK": sort_key,
            "kind": "provider-usage-event",
            "event_id": attempt_id,
            "invocation_id": invocation_id,
            "attempt_id": attempt_id,
            "request_id": _bounded(event.get("request_id"), 200),
            "owner_id": owner_id,
            "application_id": application_id,
            "workspace_id_present": workspace_id is not None,
            "workspace_id": workspace_id or "",
            "recorded_at": timestamp,
            "expires_at": expires_at,
            "payload": payload,
        }
        encoded_size = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode())
        if encoded_size > _EVENT_LIMIT_BYTES:
            raise StorageUnavailableError("provider_usage_event_too_large")
        locator = {
            "PK": "MAINT#USAGE_EVENTS",
            "SK": f"EXP#{expires_at:020d}#{attempt_id}",
            "kind": "provider-usage-event-expiry",
            "event_id": attempt_id,
            "record_pk": partition,
            "record_sk": sort_key,
            "expires_at": expires_at,
            "owner_id": owner_id,
            "application_id": application_id,
            "workspace_id_present": workspace_id is not None,
            "workspace_id": workspace_id or "",
        }
        event_key = {"PK": partition, "SK": sort_key}
        existing = self.table.get(event_key)
        if existing is not None:
            if (
                existing.get("event_id") == attempt_id
                and existing.get("invocation_id") == invocation_id
                and existing.get("owner_id") == owner_id
                and existing.get("application_id") == application_id
            ):
                return
            raise ValueError("provider_usage_event_identity_conflict")
        operations = [
            *_namespace_puts(self.table, owner_id, scope),
            _put(item, condition="attribute_not_exists(PK)"),
            _put(locator, condition="attribute_not_exists(PK)"),
        ]
        try:
            self.table.transact(operations)
        except Exception:  # noqa: BLE001 - retry immutable transaction after idempotency check
            # A concurrent write may have created the namespace or event. Retry
            # the two immutable records after rechecking the idempotency key.
            existing = self.table.get(event_key)
            if existing is not None and existing.get("invocation_id") == invocation_id:
                return
            self.table.transact([
                _put(item, condition="attribute_not_exists(PK)"),
                _put(locator, condition="attribute_not_exists(PK)"),
            ])

    def purge_expired(self, *, now: datetime, limit: int) -> int:
        if not 1 <= limit <= 100:
            raise ValueError("provider_usage_event_cleanup_limit_invalid")
        now = now.astimezone(UTC)
        deadline = monotonic() + 15
        locators = self.table.query(
            partition="MAINT#USAGE_EVENTS",
            sort_prefix="EXP#",
            consistent=True,
            deadline=deadline,
            limit=limit,
        )
        expired = [item for item in locators if int(item.get("expires_at", 0)) <= now.timestamp()]
        removed = 0
        for item in expired:
            self.table.transact([
                _delete({"PK": item["record_pk"], "SK": item["record_sk"]}),
                _delete({"PK": item["PK"], "SK": item["SK"]}),
            ])
            removed += 1
        return removed


def _bounded(value, limit):
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError("provider_usage_event_identity_invalid")
    return value
