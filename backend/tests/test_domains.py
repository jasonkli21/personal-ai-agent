import asyncio
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from threading import Event, get_ident
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from personal_ai.decisions.contracts import (
    Candidate,
    ClaimProposal,
    Constraint,
    DecisionCreateRequest,
    Preference,
)
from personal_ai.decisions.repositories import InMemoryDecisionRepository
from personal_ai.domains.contracts import (
    DomainComparisonCreateRequest,
    DomainContractError,
    DomainLookupRequest,
    DomainLookupReservation,
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
    _ProcessRateLimiter,
)
from personal_ai.domains.repositories import DomainRepositoryError, InMemoryDomainRepository
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
from personal_ai.entities.research import (
    AvailabilityValue,
    BooleanValue,
    EntityClaim,
    EvidenceReference,
    LocationValue,
    MoneyValue,
    NumberValue,
    TextValue,
)
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


@pytest.mark.parametrize("domain,module", [("travel", TravelModule()), ("shopping", ShoppingModule())])
def test_availability_policy_marker_cannot_remove_a_user_requirement(domain, module):
    fixture = next(item for item in fixture_registry() if item.domain_id == domain)
    original = fixture.request.decision.constraints[0]
    user_constraint = original.model_copy(update={"source_record_id": f"{domain}-policy-v2"})
    request = fixture.request.decision.model_copy(update={"constraints": (user_constraint,)})
    prepared = module.prepare_decision(request)
    assert user_constraint in prepared.constraints
    assert module.prepare_decision(prepared) == prepared


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


def test_lookup_replay_returns_saved_comparison_without_repeating_provider_work():
    record = TravelPlaceRecord(
        name="Synthetic Museum",
        provider_object_id="node/9001",
        osm_type="node",
        latitude=37.7,
        longitude=-122.4,
        place_type="tourism=museum",
        display_name="Synthetic Museum, Example City",
        url="https://example.org/museum",
    )
    adapter = FakeTravelPlaceAdapter((record,))
    ticks = iter(FIXTURE_NOW + timedelta(seconds=offset) for offset in range(20))
    service = _service(domains=("travel",), adapters={"travel": adapter})
    service.clock = lambda: next(ticks)
    key = uuid4()
    request = DomainLookupRequest(idempotency_key=key, query="Synthetic Museum")

    first = asyncio.run(service.lookup("travel", request))
    class RejectAdapterResolution(dict):
        def get(self, key, default=None):
            raise AssertionError(f"completed replay resolved adapter for {key}")

    service.adapters = RejectAdapterResolution()
    replay = asyncio.run(service.lookup("travel", request))
    assert replay == first
    assert len(adapter.calls) == 1

    with pytest.raises(DomainContractError, match="idempotency_conflict"):
        asyncio.run(service.lookup("travel", request.model_copy(update={"query": "Different place"})))
    assert len(adapter.calls) == 1


def test_lookup_fences_concurrent_dispatch_and_does_not_repeat_uncertain_work():
    async def concurrent_case():
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingAdapter(FakeTravelPlaceAdapter):
            async def lookup(self, query, limit):
                self.calls.append((query, limit))
                started.set()
                await release.wait()
                return ()

        adapter = BlockingAdapter()
        service = _service(domains=("travel",), adapters={"travel": adapter})
        request = DomainLookupRequest(idempotency_key=uuid4(), query="Example City")
        first_task = asyncio.create_task(service.lookup("travel", request))
        await started.wait()
        with pytest.raises(DomainContractError, match="domain_lookup_in_progress"):
            await service.lookup("travel", request)
        release.set()
        await first_task
        assert len(adapter.calls) == 1

    asyncio.run(concurrent_case())

    uncertain_adapter = FakeTravelPlaceAdapter(error=RuntimeError("simulated lost provider outcome"))
    service = _service(domains=("travel",), adapters={"travel": uncertain_adapter})
    request = DomainLookupRequest(idempotency_key=uuid4(), query="Example City")
    with pytest.raises(DomainContractError, match="domain_lookup_outcome_unknown"):
        asyncio.run(service.lookup("travel", request))
    with pytest.raises(DomainContractError, match="domain_lookup_outcome_unknown"):
        asyncio.run(service.lookup("travel", request))
    assert len(uncertain_adapter.calls) == 1

    failed_adapter = FakeTravelPlaceAdapter(error=DomainProviderError("travel_provider_unavailable", 503))
    service = _service(domains=("travel",), adapters={"travel": failed_adapter})
    request = DomainLookupRequest(idempotency_key=uuid4(), query="Example City")
    for _ in range(2):
        with pytest.raises(DomainProviderError, match="travel_provider_unavailable"):
            asyncio.run(service.lookup("travel", request))
    assert len(failed_adapter.calls) == 1


def test_lookup_repository_fences_completion_and_records_completed_result():
    repository = InMemoryDomainRepository()
    now = FIXTURE_NOW
    reservation = DomainLookupReservation(
        id=uuid4(),
        owner_id="local",
        scope_version=2,
        domain_id="travel",
        idempotency_key=uuid4(),
        request_fingerprint="a" * 64,
        fence_token=uuid4(),
        created_at=now,
        updated_at=now,
    )
    assert repository.reserve_lookup(reservation) == reservation
    fixture = next(item for item in fixture_registry() if item.fixture_id == "travel-research-needed")
    result = _service(domains=("travel",)).create("travel", fixture.request)
    with pytest.raises(DomainRepositoryError, match="domain_lookup_fence_lost"):
        repository.complete_lookup(reservation.id, uuid4(), result)
    assert not repository.results
    completed = repository.complete_lookup(reservation.id, reservation.fence_token, result)
    assert completed == result
    assert repository.lookups[reservation.id].state == "completed"
    assert repository.lookups[reservation.id].comparison_id == result.comparison.id

    isolated = reservation.model_copy(update={"id": uuid4(), "owner_id": "another-owner"})
    repository.reserve_lookup(isolated)
    with pytest.raises(DomainRepositoryError, match="domain_lookup_result_conflict"):
        repository.complete_lookup(isolated.id, isolated.fence_token, result)


class _NoWait:
    def __init__(self):
        self.intervals = []

    async def wait(self, interval, *, deadline):
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
            "status": "success",
            "result": {"id": "product_found"},
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
    assert observed[0].url.path == "/api/v3.6/product/000000000001.json"
    assert observed[0].url.params["fields"] == "code,product_name,brands,quantity,categories_tags"
    assert observed[0].headers["authorization"].startswith("Basic ")
    assert limiter.intervals == [4]
    _, evidence, sources = ShoppingModule().map_product_records(
        (product,), owner_id="local", provider="open_food_facts", now=FIXTURE_NOW, ttl_seconds=86400
    )
    assert "Open Food Facts" in sources[0].attribution
    assert evidence[0].title == "Synthetic oat drink"


@pytest.mark.parametrize(
    ("status_code", "payload", "expected_error"),
    [
        (404, {"status": "failure", "result": {"id": "product_not_found"}}, None),
        (404, {"status": "failure", "result": {"id": "invalid_code"}}, "shopping_provider_invalid_response"),
        (200, {"status": 1, "product": {}}, "shopping_provider_invalid_response"),
        (200, {"status": "failure", "result": {"id": "product_not_found"}}, "shopping_provider_invalid_response"),
        (200, {"status": "success_with_errors", "result": {"id": "product_found"}, "product": {}}, "shopping_provider_invalid_response"),
    ],
)
def test_open_food_facts_v3_not_found_and_invalid_response_contract(status_code, payload, expected_error):
    settings = Settings(
        _env_file=None, ai_provider="gemini", ai_model="synthetic",
        shopping_provider_policy_approved=True,
        shopping_off_user_agent="PersonalAISystem/0.1",
    )
    adapter = OpenFoodFactsAdapter(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(status_code, json=payload)),
        rate_limiter=_NoWait(),
    )
    if expected_error is None:
        assert asyncio.run(adapter.lookup_barcode("000000000001")) is None
    else:
        with pytest.raises(DomainProviderError, match=expected_error):
            asyncio.run(adapter.lookup_barcode("000000000001"))


@pytest.mark.parametrize("product", [
    {"product_name": None, "code": "000000000001"},
    {"product_name": "Synthetic", "brands": {}, "code": "000000000001"},
    {"product_name": "Synthetic", "categories_tags": [None], "code": "000000000001"},
    {"product_name": "Synthetic"},
])
def test_open_food_facts_rejects_malformed_identity_without_stringifying_nulls(product):
    settings = Settings(
        _env_file=None, ai_provider="gemini", ai_model="synthetic",
        shopping_provider_policy_approved=True, shopping_off_user_agent="PersonalAISystem/0.1",
    )
    adapter = OpenFoodFactsAdapter(
        settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            "status": "success", "result": {"id": "product_found"}, "product": product,
        })),
        rate_limiter=_NoWait(),
    )
    with pytest.raises(DomainProviderError, match="shopping_provider_invalid_response"):
        asyncio.run(adapter.lookup_barcode("000000000001"))


def test_lookup_does_not_block_the_event_loop_with_synchronous_storage():
    async def scenario():
        service = _service(domains=("travel",), adapters={"travel": FakeTravelPlaceAdapter(())})
        main_thread = get_ident()
        threads = []
        original_reserve = service.repository.reserve_lookup
        original_create = service._create

        def reserve(reservation):
            threads.append(get_ident())
            return original_reserve(reservation)

        def create(*args, **kwargs):
            threads.append(get_ident())
            return original_create(*args, **kwargs)

        service.repository.reserve_lookup = reserve
        service._create = create
        result = await service.lookup("travel", DomainLookupRequest(idempotency_key=uuid4(), query="Park"))
        assert not result.comparison.rows
        assert len(threads) == 2 and all(thread != main_thread for thread in threads)

    asyncio.run(scenario())


def test_cancellation_waits_for_reservation_and_records_uncertain_without_provider_call():
    async def scenario():
        adapter = FakeTravelPlaceAdapter(())
        service = _service(domains=("travel",), adapters={"travel": adapter})
        entered, release = Event(), Event()
        reserve = service.repository.reserve_lookup

        def delayed_reserve(reservation):
            entered.set()
            assert release.wait(2)
            return reserve(reservation)

        service.repository.reserve_lookup = delayed_reserve
        task = asyncio.create_task(service.lookup(
            "travel", DomainLookupRequest(idempotency_key=uuid4(), query="Park"),
        ))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not adapter.calls
        assert next(iter(service.repository.lookups.values())).state == "uncertain"

    asyncio.run(scenario())


def test_rate_limiter_rejects_future_slots_without_extending_the_queue():
    limiter = _ProcessRateLimiter()
    limiter.next_request = monotonic() + 0.15
    reserved_slot = limiter.next_request
    with pytest.raises(TimeoutError, match="deadline"):
        asyncio.run(limiter.wait(1, deadline=monotonic() + 0.03))
    assert limiter.next_request == reserved_slot


def test_provider_deadline_covers_rate_wait_and_slow_response_body():
    base = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        travel_provider_policy_approved=True,
        travel_osm_contact_email="operator@example.org",
        travel_osm_user_agent="PersonalAISystem/0.1 contact operator@example.org",
        domain_provider_timeout_seconds=0.03,
    )
    transport_called = False

    def respond(_request):
        nonlocal transport_called
        transport_called = True
        return httpx.Response(200, headers={"content-type": "application/json"}, json=[])

    class SlowLimiter:
        async def wait(self, _interval, *, deadline):
            await asyncio.sleep(max(0, deadline - monotonic()) + 0.01)

    queued = NominatimPlaceAdapter(
        base,
        transport=httpx.MockTransport(respond),
        rate_limiter=SlowLimiter(),
    )
    with pytest.raises(DomainProviderError, match="travel_provider_timeout"):
        asyncio.run(queued.lookup("Example Park", 1))
    assert not transport_called

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"["
            await asyncio.sleep(0.1)
            yield b"]"

        async def aclose(self):
            return None

    def trickle(_request):
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=SlowBody(),
        )

    streaming = NominatimPlaceAdapter(
        base,
        transport=httpx.MockTransport(trickle),
        rate_limiter=_NoWait(),
    )
    with pytest.raises(DomainProviderError, match="travel_provider_timeout"):
        asyncio.run(streaming.lookup("Example Park", 1))


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
    assert len(result.comparison.constraints) == 5
    availability = next(
        constraint for constraint in result.comparison.constraints
        if constraint.attribute == "availability"
        and constraint.source_record_id == "shopping-policy-v2"
    )
    assert availability.required and availability.missing_policy == "fail_closed"
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
        clock=lambda: FIXTURE_NOW,
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


def test_domain_availability_policy_adds_a_separate_mandatory_constraint():
    for module in (TravelModule(), ShoppingModule()):
        key = uuid4()
        optional = Constraint(
            id=uuid4(),
            attribute="availability",
            operator="availability",
            value=AvailabilityValue(value="available"),
            required=False,
            missing_policy="allow_unknown",
        )
        prepared = module.prepare_decision(DecisionCreateRequest(
            idempotency_key=key,
            constraints=(optional,),
        ))
        requirements = [item for item in prepared.constraints if item.attribute == "availability"]
        assert optional in requirements
        mandatory = [item for item in requirements if item.source == "system"]
        assert len(mandatory) == 1
        assert mandatory[0].required and mandatory[0].missing_policy == "fail_closed"
        assert mandatory[0].value == AvailabilityValue(value="available")
        assert module.prepare_decision(prepared).constraints == prepared.constraints


def _feature_claim(
    entity_id,
    attribute,
    value,
    *,
    status="verified",
    scope=None,
    observed_at=FIXTURE_NOW,
    expires_at=None,
    evidence_id=None,
):
    expiry = expires_at or (observed_at + timedelta(days=2))
    evidence_id = evidence_id or uuid4()
    observation_id = uuid4()
    reference = EvidenceReference(
        evidence_id=evidence_id,
        source_observation_id=observation_id,
        owner_id="local",
        origin="supplied",
        url="https://example.org/feature-source",
        title="Synthetic feature evidence",
        observed_at=observed_at,
        expires_at=expiry,
        expiry_policy="supplied",
        content_fingerprint="f" * 64,
    )
    return EntityClaim(
        id=uuid4(),
        entity_id=entity_id,
        owner_id="local",
        attribute=attribute,
        typed_value=value,
        original_value=str(getattr(value, "value", getattr(value, "amount", value))),
        currency=value.currency if isinstance(value, MoneyValue) else None,
        evidence_refs=(reference,),
        evidence_ids=(evidence_id,),
        observed_at=observed_at,
        expires_at=expiry,
        claim_status=status,
        verification_policy_version="claim-verification-v2",
        scope=scope,
    )


def _feature_evaluation(entity_id):
    return SimpleNamespace(entity_id=entity_id, attribute_statuses=())


def _domain_feature(result, name):
    return next(item for item in result if item.name == name)


def test_domain_features_omit_conflicting_and_stale_claim_values():
    entity_id = uuid4()
    location = LocationValue(latitude=37.7, longitude=-122.4)
    claims = (
        _feature_claim(entity_id, "location", location),
        _feature_claim(
            entity_id,
            "location",
            LocationValue(latitude=40.7, longitude=-74.0),
            status="unverified",
        ),
        _feature_claim(
            entity_id,
            "amenity_wifi",
            BooleanValue(value=True),
            observed_at=FIXTURE_NOW - timedelta(days=3),
            expires_at=FIXTURE_NOW - timedelta(days=1),
        ),
    )
    preference = Preference(attribute="location", target=location)
    travel = TravelModule().calculate_features(
        entities=(),
        claims_by_entity={entity_id: claims},
        constraints=(),
        preferences=(preference,),
        evaluations=(_feature_evaluation(entity_id),),
        eligible_entity_ids=(entity_id,),
        now=FIXTURE_NOW,
        context={},
    )[entity_id]
    assert _domain_feature(travel, "travel.location_fit").value is None
    assert not _domain_feature(travel, "travel.location_fit").evidence_ids

    stale_and_retracted = {
        "stale": _feature_claim(
            uuid4(), "review_count", NumberValue(value=Decimal(20)),
            observed_at=FIXTURE_NOW - timedelta(days=3),
            expires_at=FIXTURE_NOW - timedelta(days=1),
        ),
        "retracted": _feature_claim(
            uuid4(), "review_count", NumberValue(value=Decimal(20)), status="retracted",
        ),
    }
    claims_by_entity = {
        name: (claim,)
        for name, claim in stale_and_retracted.items()
    }
    ids_by_entity = {name: claim.entity_id for name, claim in stale_and_retracted.items()}
    shopping = ShoppingModule().calculate_features(
        entities=(),
        claims_by_entity={ids_by_entity[name]: value for name, value in claims_by_entity.items()},
        constraints=(),
        preferences=(),
        evaluations=tuple(_feature_evaluation(entity_id) for entity_id in ids_by_entity.values()),
        eligible_entity_ids=tuple(ids_by_entity.values()),
        now=FIXTURE_NOW,
        context={},
    )
    assert all(
        _domain_feature(features, "shopping.review_evidence_quality").value is None
        for features in shopping.values()
    )


def test_travel_value_feature_uses_only_the_budget_price_basis_and_currency():
    entity_id = uuid4()
    claims = (
        _feature_claim(entity_id, "nightly_price", MoneyValue(amount=Decimal(5), currency="USD")),
        _feature_claim(entity_id, "total_price", MoneyValue(amount=Decimal(300), currency="USD")),
    )
    budget = Constraint(
        id=uuid4(),
        attribute="total_price",
        operator="maximum",
        value=MoneyValue(amount=Decimal(500), currency="USD"),
    )
    features = TravelModule().calculate_features(
        entities=(),
        claims_by_entity={entity_id: claims},
        constraints=(budget,),
        preferences=(),
        evaluations=(_feature_evaluation(entity_id),),
        eligible_entity_ids=(entity_id,),
        now=FIXTURE_NOW,
        context={},
    )[entity_id]
    value = _domain_feature(features, "travel.value_fit")
    assert value.value == pytest.approx(0.4)
    assert value.evidence_ids == claims[1].evidence_ids

    first, second = uuid4(), uuid4()
    incomparable = {
        first: (_feature_claim(first, "nightly_price", MoneyValue(amount=Decimal(100), currency="USD")),),
        second: (_feature_claim(second, "total_price", MoneyValue(amount=Decimal(150), currency="EUR")),),
    }
    unbudgeted = TravelModule().calculate_features(
        entities=(),
        claims_by_entity=incomparable,
        constraints=(),
        preferences=(),
        evaluations=tuple(_feature_evaluation(item) for item in incomparable),
        eligible_entity_ids=tuple(incomparable),
        now=FIXTURE_NOW,
        context={},
    )
    assert all(_domain_feature(items, "travel.value_fit").value is None for items in unbudgeted.values())


def test_shopping_feature_uses_preference_scope_and_omits_disagreement():
    entity_id = uuid4()
    requested = _feature_claim(
        entity_id, "compatibility", TextValue(value="USB-C"), scope="requested-port",
    )
    other_scope = _feature_claim(
        entity_id, "compatibility", TextValue(value="Lightning"), scope="other-port",
    )
    preference = Preference(
        attribute="compatibility", target=TextValue(value="USB-C"), scope="requested-port",
    )
    scoped = ShoppingModule().calculate_features(
        entities=(),
        claims_by_entity={entity_id: (requested, other_scope)},
        constraints=(),
        preferences=(preference,),
        evaluations=(_feature_evaluation(entity_id),),
        eligible_entity_ids=(entity_id,),
        now=FIXTURE_NOW,
        context={},
    )[entity_id]
    spec = _domain_feature(scoped, "shopping.specification_fit")
    assert spec.value == 1
    assert spec.evidence_ids == requested.evidence_ids

    disagreement = _feature_claim(
        entity_id, "compatibility", TextValue(value="Lightning"),
        status="unverified", scope="requested-port",
    )
    conflicted = ShoppingModule().calculate_features(
        entities=(),
        claims_by_entity={entity_id: (requested, disagreement)},
        constraints=(),
        preferences=(preference,),
        evaluations=(_feature_evaluation(entity_id),),
        eligible_entity_ids=(entity_id,),
        now=FIXTURE_NOW,
        context={},
    )[entity_id]
    assert _domain_feature(conflicted, "shopping.specification_fit").value is None
