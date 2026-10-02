import asyncio
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from personal_ai.decisions.contracts import (
    Candidate,
    ClaimProposal,
    DecisionCreateRequest,
    Preference,
)
from personal_ai.decisions.repositories import InMemoryDecisionRepository
from personal_ai.domains.contracts import (
    DomainComparisonCreateRequest,
    DomainContractError,
    DomainLookupRequest,
    DomainRegistration,
    ProviderObservationExtension,
)
from personal_ai.domains.fixtures import FIXTURE_NOW, fixture_registry
from personal_ai.domains.providers import (
    DomainProviderError,
    FakeShoppingProductAdapter,
    FakeTravelPlaceAdapter,
    NominatimPlaceAdapter,
    OpenFoodFactsAdapter,
    ShoppingProductRecord,
    TravelPlaceRecord,
)
from personal_ai.domains.repositories import InMemoryDomainRepository
from personal_ai.domains.service import DomainService
from personal_ai.domains.shopping.models import (
    ProductVariantIdentity,
    ShoppingCostBreakdown,
    ShoppingReviewSignal,
    normalize_total_cost,
)
from personal_ai.domains.shopping.module import ShoppingModule
from personal_ai.domains.travel.models import (
    TravelConstraintInput,
    TravelDateWindow,
    TravelStayCost,
    compute_stay_total,
    local_time_to_utc,
)
from personal_ai.domains.travel.module import TravelModule
from personal_ai.entities.research import AvailabilityValue, LocationValue, MoneyValue
from personal_ai.evaluation.research import build_fixture
from personal_ai.settings import Settings
from personal_ai.storage.errors import ResourceNotFoundError


def _service(*, domains=(), adapters=None):
    return DomainService(
        Settings(
            _env_file=None,
            ai_provider="gemini",
            ai_model="synthetic",
            decision_enabled=True,
            travel_enabled="travel" in domains,
            shopping_enabled="shopping" in domains,
        ),
        InMemoryDecisionRepository(),
        InMemoryDomainRepository(),
        owner_id="local",
        clock=lambda: FIXTURE_NOW,
        adapters=adapters,
    )


def test_registrations_are_versioned_unique_and_disabled_by_default():
    assert not TravelModule().registration.enabled
    assert not ShoppingModule().registration.enabled
    with pytest.raises(ValueError, match="unique"):
        DomainRegistration(
            domain_id="demo",
            supported_entity_types=("object",),
            supported_constraints=(),
            supported_features=(),
            source_policy_version="source-v1",
            field_schema_version="fields-v1",
            feature_policy_version="features-v1",
            fields=(
                {"key": "name", "label": "Name", "value_kinds": ("text",)},
                {"key": "name", "label": "Other name", "value_kinds": ("text",)},
            ),
            source_adapters=("fake",),
            privacy_policy="Do not send private data.",
            retention_policy="Keep sourced facts expiring.",
        )


def test_travel_time_zone_window_and_dst_boundaries():
    window = TravelDateWindow(
        start=date(2026, 11, 1), end=date(2026, 11, 3), time_zone="America/Los_Angeles"
    )
    assert window.nights == 2
    assert window.as_value().end == date(2026, 11, 3)
    with pytest.raises(ValueError, match="ambiguous"):
        local_time_to_utc(date(2026, 11, 1), time(1, 30), "America/Los_Angeles")
    assert local_time_to_utc(
        date(2026, 11, 1), time(1, 30), "America/Los_Angeles", fold=1
    ) == datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
    with pytest.raises(ValueError, match="does not exist"):
        local_time_to_utc(date(2026, 3, 8), time(2, 30), "America/Los_Angeles")


def test_travel_stay_total_is_unknown_if_any_applicable_fee_is_unknown():
    nightly = MoneyValue(amount=Decimal(100), currency="USD")
    incomplete = compute_stay_total(TravelStayCost(
        nightly_rate=nightly,
        nights=2,
        taxes=None,
        fees_complete=False,
    ))
    complete = compute_stay_total(TravelStayCost(
        nightly_rate=nightly,
        nights=2,
        taxes=MoneyValue(amount=Decimal(20), currency="USD"),
        fees_complete=True,
    ))
    assert incomplete.amount is None and not incomplete.complete
    assert complete.amount.amount == Decimal(220) and complete.complete


def test_shopping_total_cost_requires_shipping_and_tax_disclosure():
    price = MoneyValue(amount=Decimal(40), currency="USD")
    unknown = normalize_total_cost(ShoppingCostBreakdown(
        item_price=price,
        shipping=None,
        tax_included=None,
        currency_as_of=date(2026, 10, 2),
    ))
    included = normalize_total_cost(ShoppingCostBreakdown(
        item_price=price,
        shipping=MoneyValue(amount=Decimal(5), currency="USD"),
        tax_included=True,
        currency_as_of=date(2026, 10, 2),
    ))
    assert not unknown.complete and unknown.amount is None
    assert included.complete and included.amount.amount == Decimal(45)


def test_variant_identity_is_order_independent_and_variant_specific():
    first = ProductVariantIdentity(
        model_number=" HT1 ", variant_attributes={"color": "Black", "compatibility": "USB-C"}
    )
    same = ProductVariantIdentity(
        model_number="ht1", variant_attributes={"compatibility": "usb-c", "color": "black"}
    )
    other = ProductVariantIdentity(
        model_number="HT1", variant_attributes={"color": "black", "compatibility": "Lightning"}
    )
    assert first.variant_key == same.variant_key
    assert first.variant_key != other.variant_key


def test_shopping_review_is_sourced_and_expires():
    review = ShoppingReviewSignal(
        rating=Decimal("4.2"),
        sample_count=54,
        source_name="Synthetic review source",
        source_url="https://example.org/reviews",
        observed_at=FIXTURE_NOW,
        expires_at=FIXTURE_NOW + timedelta(days=1),
    )
    assert review.sample_count == 54
    with pytest.raises(ValueError, match="freshness"):
        ShoppingReviewSignal(
            rating=Decimal("4.2"),
            sample_count=54,
            source_name="Synthetic review source",
            source_url="https://example.org/reviews",
            observed_at=FIXTURE_NOW,
            expires_at=FIXTURE_NOW,
        )


def test_provider_adapter_fakes_keep_lookup_bounded_and_exact():
    place = TravelPlaceRecord(
        name="Synthetic Place",
        provider_object_id="node/1",
        osm_type="node",
        latitude=37.7,
        longitude=-122.4,
        place_type="amenity/cafe",
        display_name="Synthetic Place, Example City",
        url="https://example.org/place",
    )
    travel = FakeTravelPlaceAdapter((place,))
    product = ShoppingProductRecord(
        barcode="000000000001",
        name="Synthetic Product",
        url="https://example.org/product",
    )
    shopping = FakeShoppingProductAdapter(product)
    assert len(asyncio.run(travel.lookup("Example City", 1))) == 1
    assert asyncio.run(shopping.lookup_barcode("000000000001")) == product
    assert asyncio.run(shopping.lookup_barcode("000000000002")) is None


def test_provider_failure_does_not_fabricate_a_candidate():
    adapter = FakeTravelPlaceAdapter(error=DomainProviderError("travel_provider_unavailable"))
    with pytest.raises(DomainProviderError, match="travel_provider_unavailable"):
        asyncio.run(adapter.lookup("Example City", 1))


def test_empty_place_lookup_returns_a_research_needed_comparison():
    service = _service(
        domains=("travel",),
        adapters={"travel": FakeTravelPlaceAdapter(())},
    )
    result = asyncio.run(service.lookup(
        "travel",
        DomainLookupRequest(idempotency_key=uuid4(), query="Unknown Place"),
    ))
    assert result.comparison.state == "no_verified_match"
    assert result.comparison.rows == ()


class _NoWait:
    def __init__(self):
        self.intervals = []

    async def wait(self, interval):
        self.intervals.append(interval)


def test_nominatim_adapter_uses_bounded_identified_queries_and_maps_attribution():
    observed = []

    def respond(request):
        observed.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json=[{
            "osm_type": "node", "osm_id": 123, "name": "Synthetic Park",
            "display_name": "Synthetic Park, Example City", "lat": "37.7", "lon": "-122.4",
            "category": "leisure", "type": "park",
        }])

    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        decision_enabled=True,
        travel_enabled=True,
        travel_places_adapter="osm_nominatim",
        travel_provider_policy_approved=True,
        travel_osm_contact_email="operator@example.org",
        travel_osm_user_agent="PersonalAISystem/0.1 contact operator@example.org",
    )
    limiter = _NoWait()
    adapter = NominatimPlaceAdapter(settings, transport=httpx.MockTransport(respond), rate_limiter=limiter)
    records = asyncio.run(adapter.lookup("Synthetic Park", 2))
    assert len(records) == 1 and records[0].provider_object_id == "node/123"
    assert observed[0].headers["user-agent"] == settings.travel_osm_user_agent
    assert "email=operator%40example.org" in str(observed[0].url)
    assert limiter.intervals == [1]
    module = TravelModule()
    _, evidence, sources = module.map_place_records(
        records,
        owner_id="local",
        provider="osm_nominatim",
        now=FIXTURE_NOW,
        ttl_seconds=3600,
    )
    assert "OpenStreetMap" in sources[0].attribution
    assert sources[0].policy_url == "https://operations.osmfoundation.org/policies/nominatim/"
    assert evidence[0].url == "https://www.openstreetmap.org/node/123"


def test_open_food_facts_adapter_requests_only_product_fields_and_uses_staging_auth():
    observed = []

    def respond(request):
        observed.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, json={
            "status": 1,
            "product": {
                "code": "000000000001", "product_name": "Synthetic oat drink",
                "brands": "Example Pantry", "quantity": "1 L", "categories_tags": ["en:drinks"],
            },
        })

    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        decision_enabled=True,
        shopping_enabled=True,
        shopping_products_adapter="open_food_facts",
        shopping_provider_policy_approved=True,
        shopping_off_user_agent="PersonalAISystem/0.1",
    )
    limiter = _NoWait()
    adapter = OpenFoodFactsAdapter(settings, transport=httpx.MockTransport(respond), rate_limiter=limiter)
    product = asyncio.run(adapter.lookup_barcode("000000000001"))
    assert product and product.name == "Synthetic oat drink"
    assert observed[0].url.params["fields"] == "code,product_name,brands,quantity,categories_tags"
    assert observed[0].headers["authorization"].startswith("Basic ")
    assert limiter.intervals == [4]
    _, evidence, sources = ShoppingModule().map_product_records(
        (product,), owner_id="local", provider="open_food_facts", now=FIXTURE_NOW, ttl_seconds=86400
    )
    assert "Open Food Facts" in sources[0].attribution
    assert evidence[0].title == "Synthetic oat drink"


def test_external_provider_adapter_fails_closed_without_policy_approval():
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
    )
    called = False

    def respond(_request):
        nonlocal called
        called = True
        return httpx.Response(200, json=[])

    adapter = NominatimPlaceAdapter(settings, transport=httpx.MockTransport(respond), rate_limiter=_NoWait())
    with pytest.raises(DomainProviderError, match="travel_provider_policy_required"):
        asyncio.run(adapter.lookup("Example City", 1))
    assert not called


def test_domain_comparisons_share_constraints_and_preserve_source_rows():
    fixture = next(item for item in fixture_registry() if item.fixture_id == "shopping-wrong-variant-excluded")
    result = _service(domains=("shopping",)).create("shopping", fixture.request)
    assert result.comparison.state == "recommended"
    assert len(result.comparison.constraints) == 4
    selected = next(row for row in result.comparison.rows if row.selected)
    excluded = next(row for row in result.comparison.rows if not row.eligible)
    assert selected.name == "Aster Trail Headlamp — Synthetic A"
    assert excluded.rank is None and excluded.score is None and not excluded.features
    compatibility = next(cell for cell in excluded.cells if cell.field == "compatibility")
    assert compatibility.value == "Lightning"
    assert compatibility.sources[0].url.startswith("https://example.org/domain-fixtures/")


def test_conflicting_travel_facts_are_visible_with_provenance():
    fixture = next(item for item in fixture_registry() if item.fixture_id == "travel-opening-hours-conflict")
    result = _service(domains=("travel",)).create("travel", fixture.request)
    row = result.comparison.rows[0]
    cell = next(item for item in row.cells if item.field == "opening_hours")
    assert cell.status == "conflicting"
    assert len(cell.sources) == 1
    assert cell.value and "09:00" in cell.value and "10:00" in cell.value


def test_domain_gate_and_unregistered_preferences_fail_closed():
    fixture = next(item for item in fixture_registry() if item.fixture_id == "travel-research-needed")
    with pytest.raises(ResourceNotFoundError):
        _service().create("travel", fixture.request)
    request = fixture.request.decision.model_copy(update={
        "preferences": (Preference(
            attribute="unregistered_preference",
            target=LocationValue(latitude=0, longitude=0),
        ),),
    })
    with pytest.raises(DomainContractError, match="travel_constraint_unregistered"):
        TravelModule().prepare_decision(request)


def test_phase_five_research_citations_carry_through_the_domain_comparison():
    fixture = {
        "name": "domain-source-handoff",
        "question": "Example Hotel total price?",
        "sources": [{
            "url": "https://example.org/hotel",
            "text": (
                "Example Hotel total price is 100.00 USD. "
                "Example Hotel availability is available."
            ),
        }],
    }
    research_service, research_request = build_fixture(fixture)

    async def finish_research():
        created = await research_service.create(research_request)
        claimed = await research_service.prepare_run(created.id)
        _ = [event async for event in research_service.stream(claimed)]
        return await research_service.detail(created.id)

    session = asyncio.run(finish_research())
    evidence_id = session.selection.evidence_ids[0]
    request = DomainComparisonCreateRequest(
        decision=DecisionCreateRequest(
            idempotency_key=research_request.idempotency_key,
            research_session_id=session.id,
            candidates=(Candidate(
                entity_type="object",
                canonical_name="Example Hotel",
                claims=(
                    ClaimProposal(
                        attribute="total_price",
                        typed_value=MoneyValue(amount=Decimal(100), currency="USD"),
                        original_value="100.00 USD",
                        evidence_ids=(evidence_id,),
                    ),
                    ClaimProposal(
                        attribute="availability",
                        typed_value=AvailabilityValue(value="available"),
                        original_value="available",
                        evidence_ids=(evidence_id,),
                    ),
                ),
            ),),
            constraints=TravelConstraintInput(
                total_budget=MoneyValue(amount=Decimal(150), currency="USD"),
            ).to_constraints(research_request.idempotency_key),
        ),
    )
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        decision_enabled=True,
        travel_enabled=True,
        research_enabled=True,
        research_storage="memory",
    )
    service = DomainService(
        settings,
        InMemoryDecisionRepository(),
        InMemoryDomainRepository(),
        research_repository=research_service.repository,
        owner_id="local",
        clock=lambda: datetime.now(UTC),
    )

    result = service.create("travel", request)
    total_price = next(cell for cell in result.comparison.rows[0].cells if cell.field == "total_price")
    assert result.comparison.state == "recommended"
    assert result.provider_observations[0].provider == "fake"
    assert total_price.sources[0].url == "https://example.org/hotel"
    assert total_price.sources[0].attribution.startswith("Source observed through Phase 5")


def test_brave_domain_sources_require_explicit_storage_rights_gate():
    source = ProviderObservationExtension(
        source_observation_id=uuid4(),
        evidence_id=uuid4(),
        owner_id="local",
        provider="brave",
        entity_kind="web_source",
        adapter_version="phase5-brave-snippet-v1",
        attribution="Synthetic source observation.",
        policy_url="https://api-dashboard.search.brave.com/documentation/resources/terms-of-service",
        url="https://example.org/source",
        title="Synthetic source",
        observed_at=FIXTURE_NOW,
        expires_at=FIXTURE_NOW + timedelta(hours=1),
    )
    service = _service(domains=("travel",))
    with pytest.raises(DomainContractError, match="domain_provider_policy_required"):
        service._validate_provider_observations(TravelModule(), (source,))

    service.settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        decision_enabled=True,
        travel_enabled=True,
        research_enabled=True,
        research_provider_storage_approved=True,
    )
    service._validate_provider_observations(TravelModule(), (source,))
