"""Typed shopping product, variant, offer, and sourced-review inputs."""

import json
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from personal_ai.decisions.contracts import Constraint, DecisionRecord
from personal_ai.entities.research import (
    AvailabilityValue,
    DateValue,
    LocationValue,
    MoneyValue,
    TextValue,
)

VARIANT_ATTRIBUTES = frozenset({
    "model", "size", "color", "condition", "material", "capacity",
    "compatibility", "dimensions", "style", "product_variant",
})


class ShoppingConstraintInput(DecisionRecord):
    max_total_price: MoneyValue | None = None
    max_item_price: MoneyValue | None = None
    specifications: dict[str, str] = Field(default_factory=dict, max_length=10)
    seller_location: LocationValue | None = None
    seller_radius_km: float | None = Field(default=None, gt=0, le=20_000)
    delivery_by: date | None = None
    return_policy: str | None = Field(default=None, max_length=300)
    require_availability: bool = True

    @model_validator(mode="after")
    def validate_location_and_specs(self):
        if (self.seller_location is None) != (self.seller_radius_km is None):
            raise ValueError("seller location and radius must be supplied together")
        if set(self.specifications) - VARIANT_ATTRIBUTES:
            raise ValueError("unregistered shopping specification")
        return self

    def to_constraints(self, request_id: UUID) -> tuple[Constraint, ...]:
        constraints = []

        def add(attribute: str, operator: str, value, suffix: str, *, radius_km=None):
            constraints.append(Constraint(
                id=uuid5(NAMESPACE_URL, f"shopping-input:{request_id}:{suffix}"),
                attribute=attribute,
                operator=operator,
                value=value,
                radius_km=radius_km,
                source="user",
            ))

        if self.max_total_price is not None:
            add("total_price", "maximum", self.max_total_price, "total-budget")
        if self.max_item_price is not None:
            add("price", "maximum", self.max_item_price, "item-budget")
        for attribute, value in sorted(self.specifications.items()):
            add(attribute, "exact", TextValue(value=value), f"specification:{attribute}")
        if self.seller_location is not None:
            add("seller_location", "geospatial", self.seller_location, "seller-location", radius_km=self.seller_radius_km)
        if self.delivery_by is not None:
            add("delivery_date", "maximum", DateValue(value=self.delivery_by), "delivery-deadline")
        if self.return_policy is not None:
            add("return_policy", "exact", TextValue(value=self.return_policy), "return-policy")
        if self.require_availability:
            add("availability", "availability", AvailabilityValue(value="available"), "availability")
        return tuple(constraints)


class ProductVariantIdentity(DecisionRecord):
    barcode: str | None = Field(default=None, pattern=r"^\d{8,14}$")
    model_number: str | None = Field(default=None, max_length=100)
    variant_attributes: dict[str, str] = Field(default_factory=dict, max_length=10)

    @model_validator(mode="after")
    def variant_keys_are_registered(self):
        if set(self.variant_attributes) - VARIANT_ATTRIBUTES:
            raise ValueError("unregistered product variant attribute")
        if any(not value.strip() for value in self.variant_attributes.values()):
            raise ValueError("empty product variant value")
        if not self.barcode and not self.model_number and not self.variant_attributes:
            raise ValueError("product variant requires an identity field")
        return self

    @property
    def variant_key(self) -> str:
        identity = {
            "barcode": self.barcode,
            "model_number": " ".join((self.model_number or "").casefold().split()) or None,
            "variant_attributes": {
                key: " ".join(value.casefold().split())
                for key, value in sorted(self.variant_attributes.items())
            },
        }
        payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode()).hexdigest()


class ShoppingCostBreakdown(DecisionRecord):
    item_price: MoneyValue
    shipping: MoneyValue | None = None
    tax_included: bool | None = None
    tax_amount: MoneyValue | None = None
    currency_as_of: date | None = None
    source_ids: tuple[str, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def known_components_use_same_currency(self):
        for component in (self.shipping, self.tax_amount):
            if component is not None and component.currency != self.item_price.currency:
                raise ValueError("shopping cost currencies must match")
        return self


class ShoppingTotalCost(DecisionRecord):
    amount: MoneyValue | None
    complete: bool
    component_labels: tuple[str, ...] = ()
    currency_as_of: date | None = None
    source_ids: tuple[str, ...] = ()
    reason: str | None = None


def normalize_total_cost(breakdown: ShoppingCostBreakdown) -> ShoppingTotalCost:
    """Return a total only when shipping, tax, currency, and date are explicit."""
    if breakdown.currency_as_of is None:
        return ShoppingTotalCost(
            amount=None,
            complete=False,
            source_ids=breakdown.source_ids,
            reason="currency_date_unknown",
        )
    if breakdown.shipping is None or breakdown.tax_included is None:
        return ShoppingTotalCost(
            amount=None,
            complete=False,
            currency_as_of=breakdown.currency_as_of,
            source_ids=breakdown.source_ids,
            reason="shipping_or_tax_unknown",
        )
    if not breakdown.tax_included and breakdown.tax_amount is None:
        return ShoppingTotalCost(
            amount=None,
            complete=False,
            currency_as_of=breakdown.currency_as_of,
            source_ids=breakdown.source_ids,
            reason="tax_amount_unknown",
        )
    amount = breakdown.item_price.amount + breakdown.shipping.amount
    labels = ["item price", "shipping"]
    if not breakdown.tax_included:
        amount += breakdown.tax_amount.amount
        labels.append("tax")
    else:
        labels.append("tax included")
    return ShoppingTotalCost(
        amount=MoneyValue(amount=amount, currency=breakdown.item_price.currency),
        complete=True,
        component_labels=tuple(labels),
        currency_as_of=breakdown.currency_as_of,
        source_ids=breakdown.source_ids,
    )


class ShoppingReviewSignal(DecisionRecord):
    """A dated provider-supplied opinion aggregate, not a product fact."""

    rating: Decimal = Field(ge=0, le=5)
    sample_count: int = Field(ge=1, le=10_000_000)
    source_name: str = Field(min_length=1, max_length=100)
    source_url: str = Field(min_length=1, max_length=2048)
    observed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def review_has_freshness(self):
        if self.expires_at <= self.observed_at:
            raise ValueError("invalid review signal freshness")
        return self


class ShoppingOfferInput(DecisionRecord):
    offer_id: str = Field(min_length=1, max_length=200)
    product_name: str = Field(min_length=1, max_length=300)
    variant: ProductVariantIdentity
    merchant: str = Field(min_length=1, max_length=200)
    price: MoneyValue
    shipping: MoneyValue | None = None
    tax_included: bool | None = None
    tax_amount: MoneyValue | None = None
    quoted_total: MoneyValue | None = None
    availability: str = Field(pattern=r"^(available|unavailable|unknown)$")
    delivery_date: date | None = None
    return_policy: str | None = Field(default=None, max_length=500)
    condition: str | None = Field(default=None, max_length=100)
    source_url: str = Field(min_length=1, max_length=2048)
    observed_at: datetime
    expires_at: datetime
    review_signal: ShoppingReviewSignal | None = None

    @model_validator(mode="after")
    def offer_is_consistent(self):
        if self.expires_at <= self.observed_at:
            raise ValueError("invalid offer freshness")
        for component in (self.shipping, self.tax_amount, self.quoted_total):
            if component is not None and component.currency != self.price.currency:
                raise ValueError("offer currencies must match")
        if self.review_signal and (
            self.review_signal.observed_at > self.observed_at
            or self.review_signal.expires_at < self.review_signal.observed_at
        ):
            raise ValueError("review observation is inconsistent")
        return self
