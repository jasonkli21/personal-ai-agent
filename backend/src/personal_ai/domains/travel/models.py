"""Typed travel inputs; proposal data is not an authoritative itinerary."""

from datetime import UTC, date, datetime, time
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, model_validator

from personal_ai.decisions.contracts import Constraint, DecisionRecord
from personal_ai.entities.research import (
    AvailabilityValue,
    BooleanValue,
    DateWindowValue,
    LocationValue,
    MoneyValue,
    NumberValue,
)

TRAVEL_AMENITIES = frozenset({"wifi", "kitchen", "parking", "accessible", "pool", "breakfast", "air_conditioning"})


class TravelDateWindow(DecisionRecord):
    start: date
    end: date
    time_zone: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_zone_and_range(self):
        if self.end <= self.start:
            raise ValueError("travel date window must include at least one night")
        try:
            ZoneInfo(self.time_zone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("unknown IANA time zone") from error
        return self

    def as_value(self) -> DateWindowValue:
        return DateWindowValue(start=self.start, end=self.end)

    @property
    def nights(self) -> int:
        return (self.end - self.start).days


class TravelConstraintInput(DecisionRecord):
    destination: LocationValue | None = None
    destination_radius_km: float | None = Field(default=None, gt=0, le=500)
    dates: TravelDateWindow | None = None
    party_size: int | None = Field(default=None, ge=1, le=50)
    total_budget: MoneyValue | None = None
    nightly_budget: MoneyValue | None = None
    required_amenities: tuple[str, ...] = Field(default=(), max_length=12)
    require_current_availability: bool = False

    @model_validator(mode="after")
    def radius_requires_location(self):
        if (self.destination is None) != (self.destination_radius_km is None):
            raise ValueError("destination and radius must be supplied together")
        if len({item.casefold() for item in self.required_amenities}) != len(self.required_amenities):
            raise ValueError("duplicate amenity")
        if {item.casefold().replace("-", "_") for item in self.required_amenities} - TRAVEL_AMENITIES:
            raise ValueError("unsupported travel amenity")
        return self

    def to_constraints(self, request_id: UUID) -> tuple[Constraint, ...]:
        constraints = []

        def add(attribute: str, operator: str, value, suffix: str, *, radius_km=None):
            constraints.append(Constraint(
                id=uuid5(NAMESPACE_URL, f"travel-input:{request_id}:{suffix}"),
                attribute=attribute,
                operator=operator,
                value=value,
                radius_km=radius_km,
                source="user",
            ))

        if self.destination is not None:
            add("location", "geospatial", self.destination, "destination", radius_km=self.destination_radius_km)
        if self.dates is not None:
            add("stay_dates", "date_window", self.dates.as_value(), "dates")
        if self.party_size is not None:
            add("party_size", "minimum", NumberValue(value=self.party_size), "party-size")
        if self.total_budget is not None:
            add("total_price", "maximum", self.total_budget, "total-budget")
        if self.nightly_budget is not None:
            add("nightly_price", "maximum", self.nightly_budget, "nightly-budget")
        for amenity in self.required_amenities:
            normalized = amenity.casefold().replace("-", "_")
            add(f"amenity_{normalized}", "exact", BooleanValue(value=True), f"amenity:{normalized}")
        if self.require_current_availability:
            add("availability", "availability", AvailabilityValue(value="available"), "availability")
        return tuple(constraints)


class TravelStayCost(DecisionRecord):
    nightly_rate: MoneyValue
    nights: int = Field(ge=1, le=365)
    cleaning_fee: MoneyValue | None = None
    taxes: MoneyValue | None = None
    fees_complete: bool = False

    @model_validator(mode="after")
    def same_currency(self):
        for amount in (self.cleaning_fee, self.taxes):
            if amount is not None and amount.currency != self.nightly_rate.currency:
                raise ValueError("stay cost currencies must match")
        return self


class TravelStayTotal(DecisionRecord):
    amount: MoneyValue | None
    complete: bool
    component_labels: tuple[str, ...] = ()
    reason: str | None = None


def compute_stay_total(cost: TravelStayCost) -> TravelStayTotal:
    """Calculate a display total only when all applicable fees are known."""
    if not cost.fees_complete or cost.taxes is None:
        return TravelStayTotal(
            amount=None,
            complete=False,
            component_labels=("nightly rate", "nights"),
            reason="taxes_or_fees_unknown",
        )
    total = cost.nightly_rate.amount * cost.nights + cost.taxes.amount
    labels = ["nightly rate", "nights", "taxes"]
    if cost.cleaning_fee is not None:
        total += cost.cleaning_fee.amount
        labels.append("cleaning fee")
    return TravelStayTotal(
        amount=MoneyValue(amount=total, currency=cost.nightly_rate.currency),
        complete=True,
        component_labels=tuple(labels),
    )


def local_time_to_utc(
    local_date: date,
    local_time: time,
    time_zone: str,
    *,
    fold: int | None = None,
) -> datetime:
    """Resolve a local wall time, rejecting DST gaps and unchosen ambiguities."""
    if fold not in {None, 0, 1}:
        raise ValueError("fold must be 0 or 1")
    zone = ZoneInfo(time_zone)
    naive = datetime.combine(local_date, local_time.replace(tzinfo=None))
    valid: dict[int, datetime] = {}
    for candidate_fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=candidate_fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone)
        if round_trip.replace(tzinfo=None) == naive:
            valid[candidate_fold] = candidate
    offsets = {item.utcoffset() for item in valid.values()}
    if not valid:
        raise ValueError("local time does not exist in this time zone")
    if len(offsets) > 1 and fold is None:
        raise ValueError("ambiguous local time requires an explicit fold")
    selected_fold = fold if fold is not None else next(iter(valid))
    if selected_fold not in valid:
        raise ValueError("invalid fold for local time")
    return valid[selected_fold].astimezone(UTC)
