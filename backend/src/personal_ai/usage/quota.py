"""Phase 19 observations extend static topology; live state never enters P18."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from personal_ai.routing.contracts import QuotaBucket, _require_aware


@dataclass(frozen=True, slots=True)
class QuotaLedgerBucketSnapshot:
    """Decision-time projection of one canonical Phase 19 quota window."""

    bucket_id: str
    unit: str
    window_seconds: int | None
    window_start: datetime
    reset_at: datetime | None
    time_to_reset_seconds: int | None
    source: str
    confidence: str
    evidence_reference: str | None
    limit_units: int | None
    reported_remaining_units: int | None
    consumed_units: int
    reserved_units: int
    remaining_units: int | None
    reservation_units: int | None
    observed_at: datetime | None
    fresh_until: datetime | None


@dataclass(frozen=True, slots=True)
class EndpointRuntimeSnapshot:
    """Current ledger health and bucket facts read in the caller's transaction."""

    health_status: str
    cooldown_until: datetime | None
    failure_streak: int
    quota_buckets: tuple[QuotaLedgerBucketSnapshot, ...]
    rejection_reasons: tuple[str, ...]


class QuotaObservation(QuotaBucket):
    reset_at: datetime | None = None
    observed_at: datetime | None = None
    fresh_until: datetime | None = None
    remaining: int | None = Field(default=None, ge=0)

    @field_validator("reset_at", "observed_at", "fresh_until")
    @classmethod
    def aware(cls, value):
        return _require_aware(value)

    @model_validator(mode="after")
    def interval(self):
        if self.fresh_until is not None and (
            self.observed_at is None or self.fresh_until < self.observed_at
        ):
            raise ValueError("quota_freshness_interval_invalid")
        if self.remaining is not None and self.limit is not None and self.remaining > self.limit:
            raise ValueError("quota_remaining_exceeds_limit")
        return self
