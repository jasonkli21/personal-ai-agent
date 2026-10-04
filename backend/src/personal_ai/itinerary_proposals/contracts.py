"""Strict upstream contract for bounded travel itinerary proposals."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

SCHEMA_VERSION = "itinerary-proposal-v1"
CONTEXT_SCHEMA_VERSION = "travel-itinerary-context-v1"
POLICY_VERSION = "itinerary-proposal-policy-v2"

OpaqueHandle = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=10,
        max_length=66,
        pattern=r"^h_[A-Za-z0-9_-]{8,64}$",
    ),
]
EvidenceHandle = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=10,
        max_length=66,
        pattern=r"^e_[A-Za-z0-9_-]{8,64}$",
    ),
]
LocalTime = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"),
]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
ItemType = Literal["activity", "food", "lodging", "transport", "flight", "note"]
ItemStatus = Literal["tentative", "planned", "booked", "completed", "cancelled"]
SafeFailureCode = Literal[
    "generation_outcome_unknown",
    "provider_unavailable",
    "provider_timeout",
    "invalid_model_output",
    "context_too_large",
    "insufficient_evidence",
    "evidence_expired",
    "uncited_evidence",
    "unsupported_request",
    "no_safe_operations",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProposalItemContext(StrictModel):
    handle: OpaqueHandle
    label: str = Field(min_length=1, max_length=240)
    item_type: ItemType
    status: ItemStatus
    start_time: LocalTime | None
    end_time: LocalTime | None
    protected: StrictBool
    removable: StrictBool

    @model_validator(mode="after")
    def protect_anchors(self) -> ProposalItemContext:
        if self.status in {"booked", "completed"} and not self.protected:
            raise ValueError("booked and completed items must be protected")
        return self


class ProposalDayContext(StrictModel):
    handle: OpaqueHandle
    day_index: Annotated[int, Field(strict=True, ge=1, le=366)]
    date: date
    items: tuple[ProposalItemContext, ...] = Field(max_length=5000)


class ProposalCandidateContext(StrictModel):
    handle: OpaqueHandle
    label: str = Field(min_length=1, max_length=240)


class TravelItineraryContext(StrictModel):
    schema_version: Literal["travel-itinerary-context-v1"] = CONTEXT_SCHEMA_VERSION
    trip_handle: OpaqueHandle
    title: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date
    timezone: str = Field(min_length=1, max_length=64)
    days: tuple[ProposalDayContext, ...] = Field(min_length=1, max_length=366)
    candidates: tuple[ProposalCandidateContext, ...] = Field(max_length=500)
    removable_item_handles: tuple[OpaqueHandle, ...] = Field(max_length=25)

    @model_validator(mode="after")
    def validate_complete_projection(self) -> TravelItineraryContext:
        span = (self.end_date - self.start_date).days + 1
        if span < 1 or span > 366 or len(self.days) != span:
            raise ValueError("trip date range and day projection disagree")
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("unknown trip timezone") from error

        handles = [self.trip_handle]
        item_by_handle: dict[str, ProposalItemContext] = {}
        total_items = 0
        for index, day in enumerate(self.days, start=1):
            if day.day_index != index or day.date != date.fromordinal(
                self.start_date.toordinal() + index - 1
            ):
                raise ValueError("trip days must be contiguous and ordered")
            handles.append(day.handle)
            total_items += len(day.items)
            for item in day.items:
                handles.append(item.handle)
                item_by_handle[item.handle] = item
        if total_items > 5000:
            raise ValueError("too many itinerary items")
        handles.extend(candidate.handle for candidate in self.candidates)
        if len(handles) != len(set(handles)):
            raise ValueError("context handles must be unique across kinds")
        if len(self.removable_item_handles) != len(set(self.removable_item_handles)):
            raise ValueError("duplicate removable item handle")
        for handle in self.removable_item_handles:
            item = item_by_handle.get(handle)
            if item is None or item.protected or not item.removable:
                raise ValueError("removal allowlist does not match an eligible item")
        if any(
            item.removable != (item.handle in self.removable_item_handles)
            for item in item_by_handle.values()
        ):
            raise ValueError("removable flags and allowlist disagree")
        return self


class ItineraryProposalRequest(StrictModel):
    schema_version: Literal["itinerary-proposal-v1"] = SCHEMA_VERSION
    idempotency_key: UUID
    instruction: str = Field(min_length=1, max_length=2000)
    context: TravelItineraryContext
    research_session_ids: tuple[UUID, ...] = Field(default=(), max_length=3)

    @field_validator("instruction")
    @classmethod
    def normalize_instruction(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("invalid instruction")
        return value

    @field_validator("research_session_ids")
    @classmethod
    def unique_session_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate research session")
        return tuple(sorted(value, key=str))

    def fingerprint(self) -> str:
        normalized = self.model_dump(mode="json", exclude={"idempotency_key"})
        encoded = json.dumps(
            normalized,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


class ProposalAddItem(StrictModel):
    kind: Literal["add_item"]
    day_handle: OpaqueHandle
    candidate_handle: OpaqueHandle
    item_type: ItemType
    position: NonNegativeInt
    start_time: LocalTime | None = None
    end_time: LocalTime | None = None


class ProposalMoveItem(StrictModel):
    kind: Literal["move_item"]
    item_handle: OpaqueHandle
    day_handle: OpaqueHandle
    position: NonNegativeInt


class ProposalSetItemTimes(StrictModel):
    kind: Literal["set_item_times"]
    item_handle: OpaqueHandle
    start_time: LocalTime | None = None
    end_time: LocalTime | None = None

    @model_validator(mode="after")
    def requires_a_time_field(self) -> ProposalSetItemTimes:
        if not {"start_time", "end_time"}.intersection(self.model_fields_set):
            raise ValueError("set_item_times requires at least one time field")
        return self

    @model_serializer(mode="wrap")
    def preserve_partial_time_fields(self, handler: SerializerFunctionWrapHandler) -> dict:
        """Keep omitted endpoints omitted through HTTP and durable JSON."""
        serialized = handler(self)
        for field_name in ("start_time", "end_time"):
            if field_name not in self.model_fields_set:
                serialized.pop(field_name, None)
        return serialized


class ProposalRemoveItem(StrictModel):
    kind: Literal["remove_item"]
    item_handle: OpaqueHandle


ProposalOperation = Annotated[
    ProposalAddItem | ProposalMoveItem | ProposalSetItemTimes | ProposalRemoveItem,
    Field(discriminator="kind"),
]


class OperationEvidenceSupport(StrictModel):
    operation_index: Annotated[int, Field(strict=True, ge=0, le=24)]
    evidence_handles: tuple[EvidenceHandle, ...] = Field(max_length=24)


class ModelProposal(StrictModel):
    schema_version: Literal["itinerary-proposal-v1"]
    trip_handle: OpaqueHandle
    status: Literal["proposed", "insufficient", "uncited"]
    failure_code: (
        Literal[
            "insufficient_evidence",
            "evidence_expired",
            "uncited_evidence",
            "unsupported_request",
            "no_safe_operations",
        ]
        | None
    )
    operations: tuple[ProposalOperation, ...] = Field(max_length=25)
    operation_support: tuple[OperationEvidenceSupport, ...] = Field(max_length=25)

    @model_validator(mode="after")
    def status_matches_content(self) -> ModelProposal:
        if self.status == "proposed":
            if not self.operations or self.failure_code is not None:
                raise ValueError("proposed output needs operations and no failure")
        elif self.operations or self.operation_support or self.failure_code is None:
            raise ValueError("non-proposal output cannot contain operations")
        if len({item.operation_index for item in self.operation_support}) != len(
            self.operation_support
        ):
            raise ValueError("duplicate operation support")
        if any(item.operation_index >= len(self.operations) for item in self.operation_support):
            raise ValueError("operation support index is out of range")
        if any(
            len(item.evidence_handles) != len(set(item.evidence_handles))
            for item in self.operation_support
        ):
            raise ValueError("duplicate evidence handle")
        return self


class ProposalCitation(StrictModel):
    evidence_handle: EvidenceHandle
    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    observed_at: datetime
    expires_at: datetime

    @field_validator("url")
    @classmethod
    def canonical_public_url(cls, value: str) -> str:
        from personal_ai.search.policy import canonical_url

        if canonical_url(value) != value:
            raise ValueError("citation URL must be canonical")
        return value

    @field_validator("observed_at", "expires_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("citation timestamps require a timezone")
        return value.astimezone(UTC)


class ItineraryProposalResult(StrictModel):
    schema_version: Literal["itinerary-proposal-v1"] = SCHEMA_VERSION
    proposal_id: UUID
    state: Literal["running", "proposed", "insufficient", "uncited", "expired", "failed"]
    policy_version: Literal["itinerary-proposal-policy-v2"] = POLICY_VERSION
    support_mode: Literal["context_only", "research_evidence"]
    trip_handle: OpaqueHandle
    operations: tuple[ProposalOperation, ...] = Field(max_length=25)
    operation_support: tuple[OperationEvidenceSupport, ...] = Field(max_length=25)
    citations: tuple[ProposalCitation, ...] = Field(max_length=24)
    failure_code: SafeFailureCode | None = None
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("proposal timestamps require a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def state_matches_content(self) -> ItineraryProposalResult:
        if self.expires_at > self.created_at + timedelta(hours=24):
            raise ValueError("proposal lifetime exceeds 24 hours")
        if self.state == "proposed" and not self.operations:
            raise ValueError("proposed result requires operations")
        if self.state in {"proposed", "running"} and self.failure_code is not None:
            raise ValueError("successful and running results cannot include a failure")
        if self.state not in {"proposed", "running"} and self.failure_code is None:
            raise ValueError("terminal failure results require a safe failure code")
        if self.state != "proposed" and (
            self.operations or self.operation_support or self.citations
        ):
            raise ValueError("non-proposal result cannot expose operations or citations")
        if self.state == "proposed" and self.support_mode == "research_evidence" and not self.citations:
            raise ValueError("evidence-supported proposals require citations")
        if self.support_mode == "context_only" and (self.operation_support or self.citations):
            raise ValueError("context-only proposals cannot claim external evidence")
        citation_handles = {item.evidence_handle for item in self.citations}
        if len(citation_handles) != len(self.citations):
            raise ValueError("duplicate proposal citation")
        if len({support.operation_index for support in self.operation_support}) != len(
            self.operation_support
        ):
            raise ValueError("duplicate proposal operation support")
        if any(
            support.operation_index >= len(self.operations)
            or any(handle not in citation_handles for handle in support.evidence_handles)
            for support in self.operation_support
        ):
            raise ValueError("operation support is outside the proposal or lacks a citation")
        if self.citations:
            supported = {
                support.operation_index
                for support in self.operation_support
                if support.evidence_handles
            }
            if supported != set(range(len(self.operations))):
                raise ValueError("evidence-backed proposals must cite each operation")
        if any(self.expires_at > citation.expires_at for citation in self.citations):
            raise ValueError("proposal outlives its citation")
        if any(
            citation.observed_at > self.created_at or citation.expires_at <= citation.observed_at
            for citation in self.citations
        ):
            raise ValueError("invalid proposal citation timestamps")
        return self


class ProposalError(Exception):
    def __init__(self, code: str, status: int = 503):
        self.code, self.status = code, status
        super().__init__(code)
