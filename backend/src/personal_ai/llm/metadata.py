"""Provider-neutral metadata shared by generation results and safe errors."""

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderRateLimitMetadata:
    """Bounded rate-limit values parsed from standard response headers."""

    requests_limit: int | None = None
    requests_remaining: int | None = None
    requests_reset_seconds: float | None = None
    tokens_limit: int | None = None
    tokens_remaining: int | None = None
    tokens_reset_seconds: float | None = None
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        for value in (self.requests_limit, self.requests_remaining,
                      self.tokens_limit, self.tokens_remaining):
            if value is not None and (isinstance(value, bool) or value < 0):
                raise ValueError("provider_rate_limit_metadata_invalid")
        for value in (self.requests_reset_seconds, self.tokens_reset_seconds,
                      self.retry_after_seconds):
            if value is not None and (
                isinstance(value, bool) or not math.isfinite(value) or value < 0
            ):
                raise ValueError("provider_rate_limit_metadata_invalid")
