"""Small async bridge for directly implemented HTTP provider adapters."""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

import anyio

from personal_ai.llm.metadata import ProviderRateLimitMetadata
from personal_ai.usage.accounting import new_invocation, unit_reservations
from personal_ai.usage.contracts import (
    AttemptMetadata,
    AttemptResult,
    ProviderEndpoint,
    ProviderUsageAccounting,
)

logger = logging.getLogger(__name__)
_RATE_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")


def rate_limit_metadata(headers) -> ProviderRateLimitMetadata | None:
    """Parse bounded standard rate-limit response fields without retaining headers."""
    values = {
        "requests_limit": _integer(headers.get("x-ratelimit-limit-requests")),
        "requests_remaining": _integer(headers.get("x-ratelimit-remaining-requests")),
        "requests_reset_seconds": _duration(headers.get("x-ratelimit-reset-requests")),
        "tokens_limit": _integer(headers.get("x-ratelimit-limit-tokens")),
        "tokens_remaining": _integer(headers.get("x-ratelimit-remaining-tokens")),
        "tokens_reset_seconds": _duration(headers.get("x-ratelimit-reset-tokens")),
        "retry_after_seconds": _duration(headers.get("retry-after")),
    }
    if not any(value is not None for value in values.values()):
        return None
    return ProviderRateLimitMetadata(**values)


def _integer(value) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _duration(value) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        text = str(value).strip().lower()
        parts = list(_RATE_DURATION_PART.finditer(text))
        if not parts or "".join(part.group(0) for part in parts) != text:
            return None
        scale = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
        parsed = sum(float(part.group(1)) * scale[part.group(2)] for part in parts)
    return parsed if parsed >= 0 and math.isfinite(parsed) else None


class AsyncProviderCall:
    """One logical provider call with explicit pre-send attempt and settlement."""

    def __init__(
        self,
        accounting: ProviderUsageAccounting,
        invocation,
        *,
        max_attempts: int,
        reservation_units: tuple[tuple[str, int], ...],
    ) -> None:
        self.accounting = accounting
        self.invocation = invocation
        self.max_attempts = max_attempts
        self.reservation_units = reservation_units
        self.attempt: AttemptMetadata | None = None
        self.started_monotonic: float | None = None
        self.finalized = False

    @classmethod
    async def begin(
        cls,
        accounting: ProviderUsageAccounting | None,
        endpoint: ProviderEndpoint,
        *,
        operation: str,
        quota_operation: str,
        max_attempts: int,
        input_tokens_estimate: int | None = None,
        additional_units: dict[str, int] | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> AsyncProviderCall | None:
        if accounting is None:
            return None
        invocation = new_invocation(
            endpoint,
            operation=operation,
            quota_operation=quota_operation,
            input_tokens_estimate=input_tokens_estimate,
            task_id=task_id,
            run_id=run_id,
        )
        await anyio.to_thread.run_sync(accounting.begin_invocation, invocation)
        return cls(
            accounting,
            invocation,
            max_attempts=max_attempts,
            reservation_units=unit_reservations(additional_units=additional_units),
        )

    async def reserve(self) -> None:
        if self.attempt is not None:
            raise RuntimeError("provider_attempt_already_reserved")
        attempt = AttemptMetadata(
            attempt_id=uuid4(),
            parent_attempt_id=None,
            send_number=1,
            started_at=datetime.now(UTC),
            reservation_units=self.reservation_units,
        )
        await anyio.to_thread.run_sync(
            lambda: self.accounting.reserve_attempt(
                self.invocation, attempt, max_attempts=self.max_attempts
            )
        )
        self.attempt = attempt
        self.started_monotonic = monotonic()

    async def finish(
        self,
        outcome: str,
        *,
        http_status: int | None = None,
        error_code: str | None = None,
        rate_limits: ProviderRateLimitMetadata | None = None,
    ) -> None:
        if self.finalized:
            return
        self.finalized = True
        completed_at = datetime.now(UTC)
        if self.attempt is not None:
            latency = int(max(0, monotonic() - (self.started_monotonic or monotonic())) * 1000)
            result = AttemptResult(
                outcome=outcome,  # type: ignore[arg-type]
                completed_at=completed_at,
                latency_ms=latency,
                http_status=http_status,
                error_code=error_code,
                usage_source="unknown",
                usage_confidence="unknown",
                rate_limits=rate_limits,
            )
            try:
                await anyio.to_thread.run_sync(
                    lambda: self.accounting.settle_attempt(
                        self.invocation, self.attempt, result
                    )
                )
            except Exception as error:  # noqa: BLE001 - unresolved reserve fences replay
                logger.info(
                    "provider_usage_settlement_pending attempt_id=%s error_class=%s",
                    self.attempt.attempt_id,
                    type(error).__name__,
                )
        try:
            await anyio.to_thread.run_sync(
                lambda: self.accounting.complete_invocation(
                    self.invocation, outcome=outcome, completed_at=completed_at
                )
            )
        except Exception as error:  # noqa: BLE001 - provider result remains unchanged
            logger.info(
                "provider_usage_invocation_completion_pending invocation_id=%s error_class=%s",
                self.invocation.invocation_id,
                type(error).__name__,
            )
