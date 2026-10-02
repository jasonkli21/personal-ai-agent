"""Deterministic synthetic travel and shopping request fixtures."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.decisions.contracts import (
    Candidate,
    ClaimProposal,
    DecisionCreateRequest,
    Preference,
    SuppliedEvidence,
)
from personal_ai.domains.contracts import (
    DomainComparisonCreateRequest,
    ProviderObservationExtension,
)
from personal_ai.domains.shopping.models import (
    ProductVariantIdentity,
    ShoppingConstraintInput,
    ShoppingCostBreakdown,
    ShoppingOfferInput,
    ShoppingReviewSignal,
    normalize_total_cost,
)
from personal_ai.domains.shopping.module import ShoppingModule
from personal_ai.domains.travel.models import TravelConstraintInput, TravelDateWindow
from personal_ai.entities.research import (
    AvailabilityValue,
    BooleanValue,
    DateWindowValue,
    LocationValue,
    MoneyValue,
    NumberValue,
    TextValue,
    TypedValue,
)

FIXTURE_NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


@dataclass(frozen=True)
class DomainFixtureCase:
    fixture_id: str
    domain_id: str
    title: str
    description: str
    request: DomainComparisonCreateRequest
    expected_state: str
    expected_selected_name: str | None = None
    expected_eligible_count: int | None = None
    expected_cell: tuple[str, str] | None = None
    expected_note: str | None = None


def _id(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"phase7-fixture:{value}")


def _literal(value: TypedValue) -> str:
    if isinstance(value, MoneyValue):
        return f"{value.amount:.2f} {value.currency}"
    if isinstance(value, LocationValue):
        return f"{value.latitude:.7f}, {value.longitude:.7f}"
    if isinstance(value, DateWindowValue):
        return f"{value.start.isoformat()} to {value.end.isoformat()}"
    if isinstance(value, BooleanValue):
        return "true" if value.value else "false"
    if isinstance(value, NumberValue):
        return str(value.value)
    if isinstance(value, AvailabilityValue):
        return value.value
    return value.value


def _assertion(subject: str, attribute: str, original: str) -> str:
    if attribute == "price":
        return f"{subject} costs {original}."
    if attribute == "availability":
        return f"{subject} availability is {original}."
    return f"{subject} {attribute.replace('_', ' ')} is {original}."


def _candidate(
    *,
    domain_id: str,
    fixture_id: str,
    name: str,
    entity_type: str,
    provider_id: str,
    facts: tuple[tuple[str, TypedValue, str | None], ...],
    provider: str | None = None,
    observed_at: datetime = FIXTURE_NOW,
    expires_at: datetime | None = None,
) -> tuple[Candidate, SuppliedEvidence, ProviderObservationExtension]:
    provider = provider or f"fake_{domain_id}_fixtures"
    expiry = expires_at or observed_at + timedelta(days=1)
    evidence_id = _id(f"{domain_id}:{fixture_id}:{provider_id}:evidence")
    observation_id = _id(f"{domain_id}:{fixture_id}:{provider_id}:observation")
    clauses = [_assertion(name, "provider_id", provider_id)]
    claims = []
    for attribute, value, supplied_literal in facts:
        original = supplied_literal or _literal(value)
        clauses.append(_assertion(name, attribute, original))
        claims.append(ClaimProposal(
            attribute=attribute,
            typed_value=value,
            original_value=original,
            unit=value.unit if hasattr(value, "unit") else None,
            currency=value.currency if isinstance(value, MoneyValue) else None,
            evidence_ids=(evidence_id,),
        ))
    passage = " ".join(clauses)
    url = f"https://example.org/domain-fixtures/{domain_id}/{quote(fixture_id)}/{quote(provider_id)}"
    normalized = " ".join(passage.split())
    source = SuppliedEvidence(
        evidence_id=evidence_id,
        source_observation_id=observation_id,
        owner_id="local",
        url=url,
        title=f"Synthetic {domain_id} evidence: {name}",
        observed_at=observed_at,
        expires_at=expiry,
        content_fingerprint=sha256(normalized.encode()).hexdigest(),
        passage=passage,
    )
    provider_observation = ProviderObservationExtension(
        source_observation_id=observation_id,
        evidence_id=evidence_id,
        owner_id="local",
        provider=provider,
        provider_object_id=provider_id,
        entity_kind=entity_type,
        adapter_version="synthetic-domain-fixture-v1",
        attribution="Synthetic fixture data; not a live place, product, offer, or review.",
        url=url,
        title=f"Synthetic {domain_id} evidence: {name}",
        observed_at=observed_at,
        expires_at=expiry,
    )
    return Candidate(
        entity_type=entity_type,
        canonical_name=name,
        identifiers={"provider_id": provider_id},
        claims=tuple(claims),
    ), source, provider_observation


def _comparison_request(fixture_id, candidates, sources, observations, constraints, preferences=()):
    decision = DecisionCreateRequest(
        idempotency_key=_id(f"{fixture_id}:decision"),
        candidates=tuple(item[0] for item in candidates),
        constraints=tuple(constraints),
        preferences=tuple(preferences),
        supplied_evidence=tuple(item[1] for item in candidates),
    )
    return DomainComparisonCreateRequest(
        decision=decision,
        provider_observations=tuple(item[2] for item in candidates),
    )


def _travel_fixture(fixture_id: str) -> DomainFixtureCase:
    module = "travel"
    dates = TravelDateWindow(
        start=date(2026, 10, 12),
        end=date(2026, 10, 14),
        time_zone="America/Los_Angeles",
    )
    constraints = TravelConstraintInput(
        destination=LocationValue(latitude=37.7620, longitude=-122.4210),
        destination_radius_km=1,
        dates=dates,
        party_size=2,
        total_budget=MoneyValue(amount=Decimal(500), currency="USD"),
        required_amenities=("wifi",),
        require_current_availability=True,
    ).to_constraints(_id(f"{fixture_id}:constraints"))

    if fixture_id == "travel-date-budget-comparison":
        candidate_facts = (
            ("place_type", TextValue(value="guest house"), None),
            ("location", LocationValue(latitude=37.7618, longitude=-122.4212), None),
            ("stay_dates", dates.as_value(), None),
            ("party_size", NumberValue(value=2), None),
            ("nightly_price", MoneyValue(amount=Decimal(210), currency="USD"), None),
            ("total_price", MoneyValue(amount=Decimal(420), currency="USD"), None),
            ("availability", AvailabilityValue(value="available"), None),
            ("amenity_wifi", BooleanValue(value=True), None),
        )
        alternatives = [
            ("Juniper House (synthetic)", "hotel-juniper", candidate_facts),
            ("Maple House (synthetic)", "hotel-maple", (
                *candidate_facts[:5],
                ("total_price", MoneyValue(amount=Decimal(620), currency="USD"), None),
                *candidate_facts[6:],
            )),
            ("Cedar House (synthetic)", "hotel-cedar", (
                *candidate_facts[:6],
                ("availability", AvailabilityValue(value="unavailable"), None),
                *candidate_facts[7:],
            )),
            ("Willow House (synthetic)", "hotel-willow", (
                *candidate_facts[:1],
                ("location", LocationValue(latitude=37.8010, longitude=-122.4010), None),
                *candidate_facts[2:],
            )),
        ]
        candidates = tuple(
            _candidate(
                domain_id=module, fixture_id=fixture_id, name=name, entity_type="object",
                provider_id=provider_id, facts=facts,
            )
            for name, provider_id, facts in alternatives
        )
        request = _comparison_request(
            fixture_id, candidates, (), (), constraints,
        )
        return DomainFixtureCase(
            fixture_id, module, "Date, party, and budget filtering",
            "Filters current availability, destination distance, party size, and total stay cost before ranking.",
            request, "recommended", "Juniper House (synthetic)", 1,
        )

    if fixture_id == "travel-research-needed":
        candidate = _candidate(
            domain_id=module, fixture_id=fixture_id, name="Unverified Harbor Stay",
            entity_type="object", provider_id="hotel-harbor",
            facts=(("place_type", TextValue(value="hotel"), None),),
        )
        request = _comparison_request(
            fixture_id, (candidate,), (), (), constraints,
        )
        return DomainFixtureCase(
            fixture_id, module, "Missing current stay evidence",
            "The candidate has no current availability, dates, capacity, location, or price claims.",
            request, "research_needed", None, 0,
        )

    if fixture_id == "travel-no-verified-match":
        facts = (
            ("place_type", TextValue(value="guest house"), None),
            ("location", LocationValue(latitude=37.8010, longitude=-122.4010), None),
            ("stay_dates", dates.as_value(), None),
            ("party_size", NumberValue(value=2), None),
            ("total_price", MoneyValue(amount=Decimal(400), currency="USD"), None),
            ("availability", AvailabilityValue(value="available"), None),
            ("amenity_wifi", BooleanValue(value=True), None),
        )
        candidate = _candidate(
            domain_id=module, fixture_id=fixture_id, name="Far Shore Guest House",
            entity_type="object", provider_id="hotel-far-shore", facts=facts,
        )
        request = _comparison_request(fixture_id, (candidate,), (), (), constraints)
        return DomainFixtureCase(
            fixture_id, module, "No place meets the destination radius",
            "All other required facts are fresh, but the only candidate is outside the requested area.",
            request, "no_verified_match", None, 0,
        )

    if fixture_id == "travel-opening-hours-conflict":
        candidate, source, observation = _candidate(
            domain_id=module, fixture_id=fixture_id, name="Example Cafe",
            entity_type="place", provider_id="place-cafe",
            facts=(
                ("availability", AvailabilityValue(value="available"), None),
                ("location", LocationValue(latitude=37.7620, longitude=-122.4210), None),
                ("opening_hours", TextValue(value="Mon 09:00-17:00"), None),
                ("opening_hours", TextValue(value="Mon 10:00-18:00"), None),
            ),
        )
        request = _comparison_request(
            fixture_id,
            ((candidate, source, observation),),
            (),
            (),
            constraints=(),
            preferences=(Preference(
                attribute="location",
                target=LocationValue(latitude=37.7620, longitude=-122.4210),
                weight=1.0,
            ),),
        )
        return DomainFixtureCase(
            fixture_id, module, "Conflicting opening-hours observations",
            "Two attributed statements remain visible as a conflict instead of being silently chosen.",
            request, "recommended", "Example Cafe", 1,
            expected_cell=("opening_hours", "conflicting"),
        )
    raise KeyError(fixture_id)


def _shopping_offer(
    *,
    fixture_id: str,
    offer_id: str,
    merchant: str,
    amount: str,
    shipping: str | None,
    tax_included: bool | None,
    tax_amount: str | None,
    quoted_total: str | None,
    compatibility: str,
    delivery: date | None,
    review_rating: str | None = None,
    review_count: int | None = None,
    observed_at: datetime = FIXTURE_NOW,
    expires_at: datetime | None = None,
) -> ShoppingOfferInput:
    expires_at = expires_at or observed_at + timedelta(hours=6)
    review = None
    if review_rating is not None and review_count is not None:
        review = ShoppingReviewSignal(
            rating=Decimal(review_rating),
            sample_count=review_count,
            source_name="Synthetic Review Board",
            source_url=f"https://example.org/domain-fixtures/shopping/{quote(fixture_id)}/{quote(offer_id)}/reviews",
            observed_at=observed_at,
            expires_at=expires_at,
        )
    return ShoppingOfferInput(
        offer_id=offer_id,
        product_name="Aster Trail Headlamp",
        variant=ProductVariantIdentity(
            model_number="Aster-HT1",
            variant_attributes={"compatibility": compatibility, "color": "black", "size": "standard"},
        ),
        merchant=merchant,
        price=MoneyValue(amount=Decimal(amount), currency="USD"),
        shipping=MoneyValue(amount=Decimal(shipping), currency="USD") if shipping is not None else None,
        tax_included=tax_included,
        tax_amount=MoneyValue(amount=Decimal(tax_amount), currency="USD") if tax_amount is not None else None,
        quoted_total=MoneyValue(amount=Decimal(quoted_total), currency="USD") if quoted_total is not None else None,
        availability="available",
        delivery_date=delivery,
        return_policy="30 days",
        condition="new",
        source_url=f"https://example.org/domain-fixtures/shopping/{quote(fixture_id)}/{quote(offer_id)}",
        observed_at=observed_at,
        expires_at=expires_at,
        review_signal=review,
    )


def _mapped_offers(fixture_id, offers):
    module = ShoppingModule()
    candidates, evidence, observations = [], [], []
    for offer in offers:
        candidate, sources, extensions = module.map_offer(
            offer,
            owner_id="local",
            provider="fake_shopping_fixtures",
            adapter_version="synthetic-offer-v1",
        )
        candidates.append(candidate)
        evidence.extend(sources)
        observations.extend(extensions)
    return tuple(candidates), tuple(evidence), tuple(observations)


def _shopping_fixture(fixture_id: str) -> DomainFixtureCase:
    module = "shopping"
    constraints = ShoppingConstraintInput(
        max_total_price=MoneyValue(amount=Decimal(100), currency="USD"),
        specifications={"compatibility": "USB-C"},
        delivery_by=date(2026, 10, 10),
        require_availability=True,
    ).to_constraints(_id(f"{fixture_id}:constraints"))

    if fixture_id == "shopping-offer-comparison":
        offers = (
            _shopping_offer(
                fixture_id=fixture_id, offer_id="listing-a", merchant="Synthetic Outfitters",
                amount="80", shipping="10", tax_included=False, tax_amount="6", quoted_total="96",
                compatibility="USB-C", delivery=date(2026, 10, 5), review_rating="4.5", review_count=250,
            ),
            _shopping_offer(
                fixture_id=fixture_id, offer_id="listing-b", merchant="Synthetic Trail Store",
                amount="91", shipping="0", tax_included=True, tax_amount=None, quoted_total="91",
                compatibility="USB-C", delivery=date(2026, 10, 8), review_rating="4.0", review_count=12,
            ),
        )
        candidates, evidence, observations = _mapped_offers(fixture_id, offers)
        request = DomainComparisonCreateRequest(
            decision=DecisionCreateRequest(
                idempotency_key=_id(f"{fixture_id}:decision"),
                candidates=candidates,
                constraints=constraints,
                supplied_evidence=evidence,
            ),
            provider_observations=observations,
        )
        return DomainFixtureCase(
            fixture_id, module, "Variant-safe offer comparison",
            "Two merchant offers for one USB-C variant retain separate offer identity, totals, review sources, and delivery evidence.",
            request, "recommended", "Aster Trail Headlamp — Synthetic Trail Store", 2,
            expected_cell=("review_rating", "verified"),
        )

    if fixture_id == "shopping-wrong-variant-excluded":
        offers = (
            _shopping_offer(
                fixture_id=fixture_id, offer_id="usb-c-listing", merchant="Synthetic A",
                amount="70", shipping="0", tax_included=True, tax_amount=None, quoted_total="70",
                compatibility="USB-C", delivery=date(2026, 10, 5),
            ),
            _shopping_offer(
                fixture_id=fixture_id, offer_id="lightning-listing", merchant="Synthetic B",
                amount="20", shipping="0", tax_included=True, tax_amount=None, quoted_total="20",
                compatibility="Lightning", delivery=date(2026, 10, 5),
            ),
        )
        candidates, evidence, observations = _mapped_offers(fixture_id, offers)
        request = DomainComparisonCreateRequest(
            decision=DecisionCreateRequest(
                idempotency_key=_id(f"{fixture_id}:decision"),
                candidates=candidates,
                constraints=constraints,
                supplied_evidence=evidence,
            ),
            provider_observations=observations,
        )
        return DomainFixtureCase(
            fixture_id, module, "Wrong compatibility is excluded",
            "A cheaper Lightning variant cannot pass a USB-C compatibility requirement.",
            request, "recommended", "Aster Trail Headlamp — Synthetic A", 1,
        )

    if fixture_id == "shopping-stale-offer":
        offers = (_shopping_offer(
            fixture_id=fixture_id, offer_id="expired-listing", merchant="Synthetic Merchant",
            amount="50", shipping="0", tax_included=True, tax_amount=None, quoted_total="50",
            compatibility="USB-C", delivery=date(2026, 10, 5),
            observed_at=FIXTURE_NOW - timedelta(days=2),
            expires_at=FIXTURE_NOW - timedelta(days=1),
        ),)
        candidates, evidence, observations = _mapped_offers(fixture_id, offers)
        request = DomainComparisonCreateRequest(
            decision=DecisionCreateRequest(
                idempotency_key=_id(f"{fixture_id}:decision"),
                candidates=candidates,
                constraints=constraints,
                supplied_evidence=evidence,
            ),
            provider_observations=observations,
        )
        return DomainFixtureCase(
            fixture_id, module, "Expired offer requires new research",
            "An expired price and availability observation cannot satisfy current shopping constraints.",
            request, "research_needed", None, 0,
            expected_cell=("total_price", "stale"),
        )

    if fixture_id == "shopping-product-without-offer":
        from personal_ai.domains.providers import ShoppingProductRecord

        products = (ShoppingProductRecord(
            barcode="000000000001",
            name="Cedar Oat Drink (synthetic)",
            brand="Example Pantry",
            quantity="1 L",
            categories=("plant-based drinks",),
            url="https://example.org/domain-fixtures/shopping/cedar-oat-drink",
        ),)
        product_candidates, product_evidence, product_observations = ShoppingModule().map_product_records(
            products, owner_id="local", provider="fake_shopping_catalog", now=FIXTURE_NOW, ttl_seconds=86400,
        )
        request = DomainComparisonCreateRequest(
            decision=DecisionCreateRequest(
                idempotency_key=_id(f"{fixture_id}:decision"),
                candidates=product_candidates,
                constraints=constraints,
                supplied_evidence=product_evidence,
            ),
            provider_observations=product_observations,
        )
        return DomainFixtureCase(
            fixture_id, module, "Catalog match without a current offer",
            "Structured product identity has no merchant, price, delivery, or current availability evidence.",
            request, "research_needed", None, 0,
            expected_cell=("availability", "missing"),
        )

    if fixture_id == "shopping-incomplete-total-cost":
        offers = (_shopping_offer(
            fixture_id=fixture_id, offer_id="incomplete-cost-listing", merchant="Synthetic Merchant",
            amount="49", shipping=None, tax_included=None, tax_amount=None, quoted_total=None,
            compatibility="USB-C", delivery=date(2026, 10, 5),
        ),)
        candidates, evidence, observations = _mapped_offers(fixture_id, offers)
        request = DomainComparisonCreateRequest(
            decision=DecisionCreateRequest(
                idempotency_key=_id(f"{fixture_id}:decision"),
                candidates=candidates,
                constraints=constraints,
                supplied_evidence=evidence,
            ),
            provider_observations=observations,
        )
        cost = normalize_total_cost(ShoppingCostBreakdown(
            item_price=MoneyValue(amount=Decimal(49), currency="USD"),
            shipping=None,
            tax_included=None,
            currency_as_of=FIXTURE_NOW.date(),
            source_ids=("synthetic-item-price",),
        ))
        return DomainFixtureCase(
            fixture_id, module, "Incomplete total cost stays unknown",
            "The item price is fresh, but shipping and tax treatment are unknown, so a total budget cannot pass.",
            request, "research_needed", None, 0,
            expected_cell=("total_price", "missing"),
            expected_note=cost.reason,
        )
    if fixture_id == "shopping-inconsistent-total-cost":
        offers = (_shopping_offer(
            fixture_id=fixture_id,
            offer_id="inconsistent-cost-listing",
            merchant="Synthetic Merchant",
            amount="49",
            shipping="5",
            tax_included=True,
            tax_amount=None,
            quoted_total="49",
            compatibility="USB-C",
            delivery=date(2026, 10, 5),
        ),)
        candidates, evidence, observations = _mapped_offers(fixture_id, offers)
        request = DomainComparisonCreateRequest(
            decision=DecisionCreateRequest(
                idempotency_key=_id(f"{fixture_id}:decision"),
                candidates=candidates,
                constraints=constraints,
                supplied_evidence=evidence,
            ),
            provider_observations=observations,
        )
        return DomainFixtureCase(
            fixture_id,
            module,
            "Inconsistent quoted total stays unverified",
            "The source quotes 49 USD, but disclosed item and shipping components total 54 USD, so the budget cannot use that quote as a complete total.",
            request,
            "research_needed",
            None,
            0,
            expected_cell=("total_price", "missing"),
        )
    raise KeyError(fixture_id)


def fixture_registry() -> tuple[DomainFixtureCase, ...]:
    return (
        _travel_fixture("travel-date-budget-comparison"),
        _travel_fixture("travel-research-needed"),
        _travel_fixture("travel-no-verified-match"),
        _travel_fixture("travel-opening-hours-conflict"),
        _shopping_fixture("shopping-offer-comparison"),
        _shopping_fixture("shopping-wrong-variant-excluded"),
        _shopping_fixture("shopping-stale-offer"),
        _shopping_fixture("shopping-product-without-offer"),
        _shopping_fixture("shopping-incomplete-total-cost"),
        _shopping_fixture("shopping-inconsistent-total-cost"),
    )


def get_fixture(domain_id: str, fixture_id: str) -> DomainFixtureCase:
    for fixture in fixture_registry():
        if fixture.domain_id == domain_id and fixture.fixture_id == fixture_id:
            return fixture
    raise KeyError(fixture_id)


def list_fixtures(domain_id: str) -> tuple[DomainFixtureCase, ...]:
    return tuple(item for item in fixture_registry() if item.domain_id == domain_id)
