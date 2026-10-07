"""Durable per-owner request limits and conservative daily usage reservations."""

from __future__ import annotations

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
    """Test-only safeguard store; deployed environments use durable adapters."""

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
