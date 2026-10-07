"""Backend-neutral account export and lifecycle contracts."""

from __future__ import annotations

import base64
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from personal_ai.auth.owner_data import OWNER_DATA_COLLECTIONS

EXPORT_COLLECTIONS = (*OWNER_DATA_COLLECTIONS, "account_lifecycle_requests")
MAX_EXPORT_SCAN_RECORDS = 100_000


class AccountDataUnavailable(RuntimeError):
    """Owner data could not be read or changed safely."""


class AccountRequestNotFound(LookupError):
    """The owner-scoped lifecycle request does not exist."""


class AccountRequestConflict(RuntimeError):
    """The idempotency key conflicts with a previous lifecycle action."""


class ExportTooLarge(RuntimeError):
    """The export exceeds its configured synchronous response limits."""


class AccountDataRepository(Protocol):
    """Backend-neutral export and account-lifecycle operations."""

    def close(self) -> None: ...
    def export_owner(self, owner_id: str, *, max_records: int, max_bytes: int) -> dict: ...
    def record_export(self, *, owner_id: str, idempotency_key: UUID, correlation_id: str) -> None: ...
    def create_deletion(self, *, owner_id: str, idempotency_key: UUID, correlation_id: str) -> dict: ...
    def get_deletion(self, *, owner_id: str, request_id: UUID) -> dict: ...
    def transition_deletion(
        self, *, owner_id: str, request_id: UUID, action: str, correlation_id: str
    ) -> dict: ...


def _portable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"$type": "base64", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _portable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_portable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"$type": "float", "value": repr(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        return {"$type": "geopoint", "latitude": value.latitude, "longitude": value.longitude}
    if value.__class__.__name__ == "Vector":
        return {"$type": "vector", "values": [_portable(item) for item in value]}
    raise TypeError("unsupported_export_value")
