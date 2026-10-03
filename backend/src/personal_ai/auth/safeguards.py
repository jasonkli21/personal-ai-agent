"""Durable per-owner request limits and conservative daily usage reservations."""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import UTC, date, datetime, timedelta
from typing import Protocol


class SafeguardUnavailable(RuntimeError):
    """A safety counter could not be read or updated reliably."""


class SafeguardDenied(RuntimeError):
    """A configured request or daily usage ceiling has been reached."""

    def __init__(self, code: str, retry_after: int) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = max(1, retry_after)


class SafeguardStore(Protocol):
    def consume_request(self, owner_id: str, limit: int) -> int: ...
    def reserve_daily(
        self, owner_id: str, calls: int, tokens: int, call_limit: int, token_limit: int
    ) -> int: ...


class InMemorySafeguardStore:
    """Test/local store; deployed environments use Firestore transactions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, int], int] = {}
        self._daily: dict[tuple[str, date], tuple[int, int]] = {}

    def consume_request(self, owner_id: str, limit: int) -> int:
        now = time.time()
        window = int(now // 60)
        retry_after = 60 - int(now % 60)
        with self._lock:
            self._requests = {
                key: count for key, count in self._requests.items() if key[1] >= window - 1
            }
            key = (owner_id, window)
            count = self._requests.get(key, 0)
            if count >= limit:
                raise SafeguardDenied("rate_limit_exceeded", retry_after)
            self._requests[key] = count + 1
        return retry_after

    def reserve_daily(
        self, owner_id: str, calls: int, tokens: int, call_limit: int, token_limit: int
    ) -> int:
        now = datetime.now(UTC)
        period = now.date()
        retry_after = int(
            (
                datetime.combine(period + timedelta(days=1), datetime.min.time(), UTC) - now
            ).total_seconds()
        )
        with self._lock:
            key = (owner_id, period)
            current_calls, current_tokens = self._daily.get(key, (0, 0))
            if current_calls + calls > call_limit or current_tokens + tokens > token_limit:
                raise SafeguardDenied("daily_budget_exceeded", retry_after)
            self._daily[key] = (current_calls + calls, current_tokens + tokens)
        return retry_after


class FirestoreSafeguardStore:
    """Transactionally enforce fixed-window limits across Cloud Run instances."""

    def __init__(self, *, project_id: str | None, emulator_host: str | None) -> None:
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import firestore

        self._firestore = firestore
        if emulator_host is None:
            self._db = firestore.Client(project=project_id)
        else:
            host = emulator_host.strip()
            if not host or "://" in host or "/" in host:
                raise ValueError("firestore_emulator_host must be a host and optional port")
            self._db = firestore.Client(project=project_id, credentials=AnonymousCredentials())
            self._db._emulator_host = host

    @staticmethod
    def _opaque_id(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def consume_request(self, owner_id: str, limit: int) -> int:
        now = datetime.now(UTC)
        epoch = int(now.timestamp() // 60)
        retry_after = 60 - int(now.timestamp() % 60)
        ref = self._db.collection("rate_limit_windows").document(
            self._opaque_id(f"{owner_id}\0{epoch}")
        )
        transaction = self._db.transaction()

        @self._firestore.transactional
        def apply(tx):
            snapshot = ref.get(transaction=tx)
            values = snapshot.to_dict() if snapshot.exists else {}
            count = int((values or {}).get("request_count", 0))
            if count >= limit:
                raise SafeguardDenied("rate_limit_exceeded", retry_after)
            tx.set(
                ref,
                {
                    "request_count": count + 1,
                    "window_start": datetime.fromtimestamp(epoch * 60, UTC),
                    "expires_at": datetime.fromtimestamp((epoch + 2) * 60, UTC),
                    "policy_version": "request-rate-v1",
                },
            )

        try:
            apply(transaction)
        except SafeguardDenied:
            raise
        except Exception as error:
            raise SafeguardUnavailable from error
        return retry_after

    def reserve_daily(
        self, owner_id: str, calls: int, tokens: int, call_limit: int, token_limit: int
    ) -> int:
        now = datetime.now(UTC)
        period = now.date()
        period_start = datetime.combine(period, datetime.min.time(), UTC)
        period_end = period_start + timedelta(days=1)
        retry_after = max(1, int((period_end - now).total_seconds()))
        opaque_owner = self._opaque_id(owner_id)
        ref = self._db.collection("usage_budgets").document(
            self._opaque_id(f"{opaque_owner}\0{period.isoformat()}")
        )
        transaction = self._db.transaction()

        @self._firestore.transactional
        def apply(tx):
            snapshot = ref.get(transaction=tx)
            values = snapshot.to_dict() if snapshot.exists else {}
            reserved = (values or {}).get("reserved", {})
            current_calls = int(reserved.get("provider_calls", 0))
            current_tokens = int(reserved.get("input_tokens", 0))
            if current_calls + calls > call_limit or current_tokens + tokens > token_limit:
                raise SafeguardDenied("daily_budget_exceeded", retry_after)
            tx.set(
                ref,
                {
                    "scope": f"owner:{opaque_owner}",
                    "period_start": period_start,
                    "period_end": period_end,
                    "limit": {"provider_calls": call_limit, "input_tokens": token_limit},
                    "reserved": {
                        "provider_calls": current_calls + calls,
                        "input_tokens": current_tokens + tokens,
                    },
                    "settled": {"provider_calls": 0, "input_tokens": 0},
                    "state": "reserved",
                    "policy_version": "usage-budget-v1",
                    "expires_at": period_end + timedelta(days=90),
                },
            )

        try:
            apply(transaction)
        except SafeguardDenied:
            raise
        except Exception as error:
            raise SafeguardUnavailable from error
        return retry_after
