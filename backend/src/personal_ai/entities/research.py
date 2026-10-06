"""Canonical research identities and immutable, evidence-backed claims.

These records identify candidates for decision support. They are not
authoritative product, place, booking, or purchase records.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_ai.auth.scope import ApplicationScopedRecord

EntityType = Literal["object", "place", "organization", "other"]


class DecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("created_at", "updated_at", "observed_at", "expires_at", check_fields=False)
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value.astimezone(UTC)


class ScopedDecisionRecord(DecisionRecord, ApplicationScopedRecord):
    """Persisted decision/entity record; user request contracts remain unscoped."""


class TextValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["text"] = "text"
    value: str = Field(min_length=1, max_length=500)


class NumberValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["number"] = "number"
    value: Decimal

    @field_validator("value")
    @classmethod
    def finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("finite number required")
        return value


class MoneyValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["money"] = "money"
    amount: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("amount")
    @classmethod
    def finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("finite amount required")
        return value


class QuantityValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["quantity"] = "quantity"
    amount: Decimal = Field(ge=0)
    unit: str = Field(min_length=1, max_length=30)

    @field_validator("amount")
    @classmethod
    def finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("finite quantity required")
        return value


class DateValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["date"] = "date"
    value: date


class DateTimeValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["datetime"] = "datetime"
    value: datetime

    @field_validator("value")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone required")
        return value.astimezone(UTC)


class DateWindowValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["date_window"] = "date_window"
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("invalid date window")
        return self


class LocationValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["location"] = "location"
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class AvailabilityValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["availability"] = "availability"
    value: Literal["available", "unavailable", "unknown"]


class BooleanValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["boolean"] = "boolean"
    value: bool


TypedValue = Annotated[
    TextValue | NumberValue | MoneyValue | QuantityValue | DateValue | DateTimeValue | DateWindowValue | LocationValue | AvailabilityValue | BooleanValue,
    Field(discriminator="kind"),
]


class EvidenceReference(ScopedDecisionRecord):
    """Immutable source attribution copied into a decision evidence snapshot."""

    evidence_id: UUID
    source_observation_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    research_session_id: UUID | None = None
    origin: Literal["research_session", "supplied"]
    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    observed_at: datetime
    expires_at: datetime
    expiry_policy: Literal["general", "current", "supplied"]
    content_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def source_is_valid(self):
        from personal_ai.search.policy import canonical_url

        if self.expires_at <= self.observed_at:
            raise ValueError("invalid source freshness")
        if canonical_url(self.url) != self.url:
            raise ValueError("source URL must be canonical and public")
        if (self.origin == "research_session") != (self.research_session_id is not None):
            raise ValueError("source origin does not match session reference")
        return self


class CanonicalEntity(ScopedDecisionRecord):
    id: UUID
    entity_type: EntityType
    canonical_name: str = Field(min_length=1, max_length=300)
    owner_scope: str = Field(min_length=1, max_length=220)
    owner_id: str = Field(min_length=1, max_length=200)
    identity_version: Literal["identity-v1"] = "identity-v1"
    identifiers: dict[str, str] = Field(default_factory=dict, max_length=12)
    status: Literal["active", "merged"] = "active"
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def scope_and_identity(self):
        if self.owner_scope not in {"shared", f"owner:{self.owner_id}"}:
            raise ValueError("invalid owner scope")
        if self.owner_scope == "shared" and self.owner_id != "*":
            raise ValueError("shared entities must use the shared owner marker")
        if self.updated_at < self.created_at:
            raise ValueError("invalid entity timestamps")
        if any(not key.strip() or not value.strip() for key, value in self.identifiers.items()):
            raise ValueError("invalid entity identifier")
        return self


class EntityAlias(ScopedDecisionRecord):
    id: UUID
    entity_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    normalized_alias: str = Field(min_length=1, max_length=300)
    source_evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=12)
    created_at: datetime


class EntityClaim(ScopedDecisionRecord):
    """An immutable observation; mutable values never become entity truth."""

    id: UUID
    entity_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    attribute: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")
    typed_value: TypedValue
    original_value: str = Field(min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=30)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    # Each of up to 12 deduplicated evidence passages may retain up to 12
    # source observations from Phase 5; keep the complete attribution graph.
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=144)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=12)
    observed_at: datetime
    expires_at: datetime
    claim_status: Literal["verified", "unverified", "retracted"]
    verification_policy_version: Literal["claim-verification-v1", "claim-verification-v2"] = "claim-verification-v1"
    schema_version: Literal["entity-claim-v1"] = "entity-claim-v1"
    scope: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def provenance_and_time(self):
        if self.expires_at <= self.observed_at:
            raise ValueError("invalid claim freshness")
        if any(ref.owner_id != self.owner_id for ref in self.evidence_refs):
            raise ValueError("foreign owner evidence reference")
        if set(self.evidence_ids) != {ref.evidence_id for ref in self.evidence_refs}:
            raise ValueError("claim evidence index does not match provenance")
        if self.observed_at != max(ref.observed_at for ref in self.evidence_refs):
            raise ValueError("claim observation time must match its latest source")
        if self.expires_at != min(ref.expires_at for ref in self.evidence_refs):
            raise ValueError("claim expiry must be the earliest source expiry")
        if self.claim_status == "verified" and any(
            ref.expires_at <= ref.observed_at for ref in self.evidence_refs
        ):
            raise ValueError("verified claim requires valid sources")
        return self




class EntityMatch(ScopedDecisionRecord):
    id: UUID
    decision_id: UUID
    subject_id: UUID
    owner_id: str
    candidate_entity_id: UUID
    candidate_entity_ids: tuple[UUID, ...] = Field(max_length=100)
    selected_entity_id: UUID | None = None
    outcome: Literal["matched", "review", "no_match"]
    confidence: float = Field(ge=0, le=1)
    feature_values: dict[str, float]
    policy_version: Literal["resolve-v1", "resolve-v2"] = "resolve-v2"
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=12)
    created_at: datetime

    @model_validator(mode="after")
    def selected_matches_outcome(self):
        if self.outcome == "matched":
            if self.selected_entity_id is None or self.selected_entity_id not in self.candidate_entity_ids:
                raise ValueError("matched result requires a candidate selection")
        elif self.selected_entity_id is not None:
            raise ValueError("review and no-match outcomes must abstain")
        return self
