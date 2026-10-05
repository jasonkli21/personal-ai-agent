"""Strict versioned contract for ephemeral booking-document extraction."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "booking-document-extraction-v1"
MAX_INPUT_CHARS = 200_000
MAX_CANDIDATES = 10
MAX_RESULT_RETENTION = timedelta(days=7)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


HexDigest = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]
Zone = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64)]


class BookingExtractionRequest(StrictModel):
    schema_version: Literal["booking-document-extraction-v1"] = SCHEMA_VERSION
    idempotency_key: UUID
    source_sha256: HexDigest
    media_type: Literal["text/plain", "application/pdf"]
    consent: Literal["submit_for_booking_extraction"]
    synthetic_fixture: bool = False
    document_text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)

    @field_validator("document_text")
    @classmethod
    def validate_document_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("document text must contain readable text")
        return value

    @model_validator(mode="after")
    def validate_source_hash(self) -> BookingExtractionRequest:
        encoded = self.document_text.encode("utf-8")
        if sha256(encoded).hexdigest() != self.source_sha256:
            raise ValueError("source hash does not match document text")
        return self

    def fingerprint(self) -> str:
        return sha256(
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "source_sha256": self.source_sha256,
                    "media_type": self.media_type,
                    "consent": self.consent,
                    "synthetic_fixture": self.synthetic_fixture,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


class ModelCandidate(StrictModel):
    reservation_type: Literal["flight", "lodging", "rail", "car", "activity", "other"] | None
    provider_name: str | None = Field(default=None, max_length=200)
    confirmation_code: str | None = Field(default=None, max_length=160)
    starts_at_text: str | None = Field(default=None, max_length=80)
    starts_at_date: date | None = None
    starts_at_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    starts_at_timezone: Zone | None = None
    ends_at_text: str | None = Field(default=None, max_length=80)
    ends_at_date: date | None = None
    ends_at_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    ends_at_timezone: Zone | None = None
    source_start: int = Field(ge=0, le=MAX_INPUT_CHARS)
    source_end: int = Field(gt=0, le=MAX_INPUT_CHARS)
    uncertain_fields: tuple[
        Literal[
            "reservation_type",
            "provider_name",
            "confirmation_code",
            "starts_at",
            "ends_at",
            "starts_at_timezone",
            "ends_at_timezone",
        ],
        ...,
    ] = Field(max_length=7)

    @model_validator(mode="after")
    def valid_span(self) -> ModelCandidate:
        if self.source_end <= self.source_start:
            raise ValueError("source span is empty")
        for endpoint in ("starts_at", "ends_at"):
            day = getattr(self, f"{endpoint}_date")
            local_time = getattr(self, f"{endpoint}_time")
            zone = getattr(self, f"{endpoint}_timezone")
            if (day is None) != (local_time is None):
                raise ValueError("schedule date and time must be paired")
            if day is None and zone is not None:
                raise ValueError("timezone requires a schedule value")
            if zone is not None:
                _validate_timezone(zone)
        return self


def _validate_timezone(value: str) -> None:
    offset = re.fullmatch(r"[+-](0\d|1[0-4]):([0-5]\d)", value)
    if offset:
        if offset.group(1) == "14" and offset.group(2) != "00":
            raise ValueError("unknown timezone")
        return
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError("unknown timezone") from error


class ModelExtraction(StrictModel):
    schema_version: Literal["booking-document-extraction-v1"]
    candidates: tuple[ModelCandidate, ...] = Field(max_length=MAX_CANDIDATES)


class BookingCandidate(StrictModel):
    candidate_id: str = Field(min_length=12, max_length=32, pattern=r"^c_[a-f0-9]{10,30}$")
    reservation_type: Literal["flight", "lodging", "rail", "car", "activity", "other"] | None
    provider_name: str | None = Field(default=None, max_length=200)
    confirmation_code: str | None = Field(default=None, max_length=160)
    starts_at_text: str | None = Field(default=None, max_length=80)
    starts_at_date: date | None = None
    starts_at_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    starts_at_timezone: Zone | None = None
    ends_at_text: str | None = Field(default=None, max_length=80)
    ends_at_date: date | None = None
    ends_at_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    ends_at_timezone: Zone | None = None
    source_start: int = Field(ge=0, le=MAX_INPUT_CHARS)
    source_end: int = Field(gt=0, le=MAX_INPUT_CHARS)
    source_excerpt: str = Field(max_length=240)
    uncertain_fields: tuple[
        Literal[
            "reservation_type",
            "provider_name",
            "confirmation_code",
            "starts_at",
            "ends_at",
            "starts_at_timezone",
            "ends_at_timezone",
        ],
        ...,
    ] = Field(max_length=7)


class BookingExtractionResult(StrictModel):
    schema_version: Literal["booking-document-extraction-v1"] = SCHEMA_VERSION
    extraction_id: UUID
    idempotency_key: UUID
    source_sha256: HexDigest
    state: Literal["running", "completed", "failed", "deleted", "expired"]
    candidates: tuple[BookingCandidate, ...] = Field(max_length=MAX_CANDIDATES)
    failure_code: (
        Literal[
            "provider_unavailable",
            "provider_timeout",
            "invalid_model_output",
            "generation_outcome_unknown",
            "context_too_large",
        ]
        | None
    ) = None
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def terminal_result(self) -> BookingExtractionResult:
        if (
            self.expires_at <= self.created_at
            or self.expires_at > self.created_at + MAX_RESULT_RETENTION
        ):
            raise ValueError("extraction expiry must be after creation and within retention")
        if self.state != "completed" and self.candidates:
            raise ValueError("non-completed results cannot expose candidates")
        if self.state == "failed" and self.failure_code is None:
            raise ValueError("failed results require a safe failure code")
        if self.state != "failed" and self.failure_code is not None:
            raise ValueError("only failed results may contain a failure code")
        identities = [candidate.candidate_id for candidate in self.candidates]
        spans = [(candidate.source_start, candidate.source_end) for candidate in self.candidates]
        if len(set(identities)) != len(identities) or len(set(spans)) != len(spans):
            raise ValueError("candidate identities and evidence spans must be unique")
        if any(
            candidate.source_end <= candidate.source_start or not candidate.source_excerpt.strip()
            for candidate in self.candidates
        ):
            raise ValueError("completed candidates require non-empty bounded evidence")
        return self


class BookingExtractionDeleteRequest(StrictModel):
    source_sha256: HexDigest
