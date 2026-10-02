"""Travel extension for shared evidence, constraints, entities, and ranking."""

from datetime import datetime, timedelta
from hashlib import sha256
from typing import ClassVar
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.decisions.contracts import (
    Candidate,
    ClaimProposal,
    Constraint,
    DecisionCreateRequest,
    FeatureScore,
    Preference,
    SuppliedEvidence,
)
from personal_ai.domains.contracts import (
    DomainContractError,
    DomainField,
    DomainRegistration,
    ProviderObservationExtension,
)
from personal_ai.domains.providers import (
    FakeTravelPlaceAdapter,
    NominatimPlaceAdapter,
    TravelPlaceRecord,
)
from personal_ai.entities.research import (
    AvailabilityValue,
    BooleanValue,
    CanonicalEntity,
    EntityClaim,
    LocationValue,
    MoneyValue,
    TextValue,
    TypedValue,
)

_FIELDS = (
    DomainField(key="place_type", label="Place type", value_kinds=("text",)),
    DomainField(key="location", label="Location", value_kinds=("location",)),
    DomainField(key="area", label="Neighborhood or area", value_kinds=("text",)),
    DomainField(key="stay_dates", label="Stay dates", value_kinds=("date_window",)),
    DomainField(key="party_size", label="Party size", value_kinds=("number",)),
    DomainField(key="nightly_price", label="Nightly price", value_kinds=("money",)),
    DomainField(key="total_price", label="Total price", value_kinds=("money",)),
    DomainField(key="availability", label="Availability", value_kinds=("availability",), required_for_recommendation=True),
    DomainField(key="amenity", label="Amenities", value_kinds=("text",)),
    *(DomainField(key=f"amenity_{key}", label=f"{key.replace('_', ' ').title()}", value_kinds=("boolean",))
      for key in ("wifi", "kitchen", "parking", "accessible", "pool", "breakfast", "air_conditioning")),
    DomainField(key="opening_hours", label="Opening hours", value_kinds=("text",)),
    DomainField(key="transit_time_minutes", label="Transit time", value_kinds=("number",)),
    DomainField(key="location_fit", label="Location fit", value_kinds=("number",), mutable=False),
    DomainField(key="value_fit", label="Value fit", value_kinds=("number",), mutable=False),
    DomainField(key="amenity_fit", label="Amenity fit", value_kinds=("number",), mutable=False),
)


class TravelModule:
    policy_version = "travel-features-v1"
    registration = DomainRegistration(
        domain_id="travel",
        supported_entity_types=("place", "object"),
        supported_constraints=(
            "location", "stay_dates", "flight_dates", "party_size", "total_price",
            "nightly_price", "availability", "amenity", "opening_hours",
            "transit_time_minutes", "distance_km", "area", "place_type",
            "amenity_wifi", "amenity_kitchen", "amenity_parking", "amenity_accessible",
            "amenity_pool", "amenity_breakfast", "amenity_air_conditioning",
        ),
        supported_features=("location_fit", "value_fit", "amenity_fit"),
        source_policy_version="travel-sources-v1",
        field_schema_version="travel-comparison-v1",
        feature_policy_version="travel-features-v1",
        fields=_FIELDS,
        source_adapters=("phase5-research", "fake", "brave", "osm_nominatim"),
        privacy_policy=(
            "Do not send private itinerary records or sensitive personal data to place providers. "
            "Only submitted place queries are sent when a provider is explicitly enabled."
        ),
        retention_policy=(
            "Place claims retain source IDs, attribution, observation time and expiry. "
            "No booking, itinerary history, or reservation is written."
        ),
    )
    feature_weights: ClassVar[dict[str, float]] = {
        "travel.location_fit": 0.40,
        "travel.value_fit": 0.35,
        "travel.amenity_fit": 0.25,
    }

    def registration_for(self, enabled: bool) -> DomainRegistration:
        return self.registration.model_copy(update={"enabled": enabled})

    def prepare_decision(self, request: DecisionCreateRequest) -> DecisionCreateRequest:
        booking_like = any(
            constraint.attribute in {
                "stay_dates", "flight_dates", "nightly_price", "total_price", "availability",
            }
            for constraint in request.constraints
        )
        constraints = request.constraints
        if booking_like and not any(item.attribute == "availability" for item in constraints):
            availability = Constraint(
                id=uuid5(request.idempotency_key, "travel-required-availability-v1"),
                attribute="availability",
                operator="availability",
                value=AvailabilityValue(value="available"),
                required=True,
                missing_policy="fail_closed",
                source="system",
                source_record_id="travel-policy-v1",
            )
            constraints = (*constraints, availability)
            request = request.model_copy(update={"constraints": constraints})
        self.validate_decision(request)
        return request

    def validate_decision(self, request: DecisionCreateRequest) -> None:
        registered_attrs = {field.key for field in self.registration.fields}
        registered_attrs.update(self.registration.supported_constraints)
        for candidate in request.candidates:
            if candidate.entity_type not in self.registration.supported_entity_types:
                raise DomainContractError("travel_entity_type_unsupported")
            for claim in candidate.claims:
                if claim.attribute not in registered_attrs:
                    raise DomainContractError("travel_claim_unregistered")
        for item in (*request.constraints, *request.preferences):
            if item.attribute not in self.registration.supported_constraints:
                raise DomainContractError("travel_constraint_unregistered")

    def get_adapter(self, settings, *, rate_limiter=None):
        if settings.travel_places_adapter == "osm_nominatim":
            return NominatimPlaceAdapter(settings, rate_limiter=rate_limiter)
        return FakeTravelPlaceAdapter(_synthetic_places())

    def map_place_records(
        self,
        records: tuple[TravelPlaceRecord, ...],
        *,
        owner_id: str,
        provider: str,
        now: datetime,
        ttl_seconds: int,
    ) -> tuple[tuple[Candidate, ...], tuple[SuppliedEvidence, ...], tuple[ProviderObservationExtension, ...]]:
        candidates, evidence, extensions = [], [], []
        for record in records:
            expires = now + timedelta(seconds=ttl_seconds)
            evidence_id = uuid5(NAMESPACE_URL, f"travel-evidence:{provider}:{record.provider_object_id}:{now.isoformat()}")
            observation_id = uuid5(NAMESPACE_URL, f"travel-observation:{provider}:{record.provider_object_id}:{now.isoformat()}")
            object_id = record.provider_object_id
            subject = record.name
            coordinates = f"{record.latitude:.7f}, {record.longitude:.7f}"
            place_type = record.place_type
            passage = (
                f"{subject} location is {coordinates}. "
                f"{subject} place type is {place_type}. "
                f"{subject} OpenStreetMap identifier is {object_id}. "
                f"{subject} address is {record.display_name}."
            )
            normalized = " ".join(passage.split())
            source = SuppliedEvidence(
                evidence_id=evidence_id,
                source_observation_id=observation_id,
                owner_id=owner_id,
                url=record.url,
                title=record.display_name[:300],
                observed_at=now,
                expires_at=expires,
                content_fingerprint=sha256(normalized.encode()).hexdigest(),
                passage=passage,
            )
            candidate = Candidate(
                entity_type="place",
                canonical_name=subject,
                identifiers={"osm": object_id},
                aliases=(),
                claims=(
                    ClaimProposal(
                        attribute="location",
                        typed_value=LocationValue(latitude=record.latitude, longitude=record.longitude),
                        original_value=coordinates,
                        evidence_ids=(evidence_id,),
                    ),
                    ClaimProposal(
                        attribute="place_type",
                        typed_value=TextValue(value=place_type),
                        original_value=place_type,
                        evidence_ids=(evidence_id,),
                    ),
                ),
            )
            extensions.append(
                ProviderObservationExtension(
                    source_observation_id=observation_id,
                    evidence_id=evidence_id,
                    owner_id=owner_id,
                    provider=provider,
                    provider_object_id=object_id,
                    entity_kind=place_type,
                    adapter_version=("nominatim-jsonv2-v1" if provider == "osm_nominatim" else "fake-travel-v1"),
                    attribution=(
                        "© OpenStreetMap contributors, ODbL 1.0"
                        if provider == "osm_nominatim"
                        else "Synthetic travel fixture data"
                    ),
                    policy_url=(
                        "https://operations.osmfoundation.org/policies/nominatim/"
                        if provider == "osm_nominatim"
                        else None
                    ),
                    url=record.url,
                    title=record.display_name[:300],
                    observed_at=now,
                    expires_at=expires,
                )
            )
            candidates.append(candidate)
            evidence.append(source)
        return tuple(candidates), tuple(evidence), tuple(extensions)

    def calculate_features(
        self,
        *,
        entities: tuple[CanonicalEntity, ...],
        claims_by_entity: dict,
        constraints: tuple[Constraint, ...],
        preferences: tuple[Preference, ...],
        evaluations,
        eligible_entity_ids: tuple[UUID, ...],
        now: datetime,
        context: dict,
    ) -> dict[UUID, tuple[FeatureScore, ...]]:
        del context
        fresh = {
            entity_id: tuple(
                item for item in claims_by_entity.get(entity_id, ())
                if item.claim_status == "verified"
                and item.verification_policy_version == "claim-verification-v2"
                and item.expires_at > now
            )
            for entity_id in eligible_entity_ids
        }
        del entities, evaluations
        geo = next((item for item in constraints if item.operator == "geospatial" and item.attribute == "location"), None)
        if geo is not None and geo.value is not None:
            target = (geo.value.latitude, geo.value.longitude)
            radius = geo.radius_km
        else:
            preference = next(
                (item for item in preferences if item.attribute == "location" and isinstance(item.target, LocationValue)),
                None,
            )
            target = (preference.target.latitude, preference.target.longitude) if preference else None
            radius = None

        budget = next(
            (item.value for item in constraints if item.operator == "maximum" and item.attribute in {"nightly_price", "total_price"} and isinstance(item.value, MoneyValue)),
            None,
        )
        price_claims: dict[UUID, EntityClaim] = {}
        for entity_id, claims in fresh.items():
            price_claims[entity_id] = next(
                (claim for claim in claims if claim.attribute in {"nightly_price", "total_price"} and isinstance(claim.typed_value, MoneyValue)),
                None,
            )
        comparable = [
            claim.typed_value.amount for claim in price_claims.values()
            if claim is not None and (budget is None or claim.typed_value.currency == budget.currency)
        ]
        cheapest, priciest = (min(comparable), max(comparable)) if comparable else (None, None)
        amenity_preferences = [
            item for item in preferences
            if item.attribute.startswith("amenity_") and isinstance(item.target, BooleanValue)
        ]
        output = {}
        for entity_id in eligible_entity_ids:
            claims = fresh[entity_id]
            evidence = lambda selected: tuple(sorted({ref.evidence_id for claim in selected for ref in claim.evidence_refs}, key=str))
            location_claim = next((item for item in claims if item.attribute == "location" and isinstance(item.typed_value, LocationValue)), None)
            location_fit = None
            if target and location_claim:
                distance = _distance_km(
                    target,
                    (location_claim.typed_value.latitude, location_claim.typed_value.longitude),
                )
                location_fit = max(0.0, 1.0 - distance / radius) if radius else 1.0 / (1.0 + distance)
            price_claim = price_claims.get(entity_id)
            value_fit = None
            if price_claim is not None:
                amount = price_claim.typed_value.amount
                currency = budget.currency if budget else price_claim.typed_value.currency
                if price_claim.typed_value.currency == currency:
                    if budget is not None and budget.amount > 0:
                        value_fit = max(0.0, min(1.0, 1.0 - float(amount / budget.amount)))
                    elif cheapest is not None and priciest is not None:
                        value_fit = (
                            1.0 if priciest == cheapest
                            else max(0.0, min(1.0, float((priciest - amount) / (priciest - cheapest))))
                        )
            amenity_claims = {claim.attribute: claim for claim in claims if claim.attribute.startswith("amenity_") and isinstance(claim.typed_value, BooleanValue)}
            amenity_fit = (
                sum(
                    item.attribute in amenity_claims
                    and amenity_claims[item.attribute].typed_value.value == item.target.value
                    for item in amenity_preferences
                ) / len(amenity_preferences)
                if amenity_preferences else None
            )
            output[entity_id] = (
                FeatureScore(name="travel.location_fit", value=location_fit, weight=0.40, evidence_ids=evidence((location_claim,)) if location_claim and location_fit is not None else (), missing_treatment="omit"),
                FeatureScore(name="travel.value_fit", value=value_fit, weight=0.35, evidence_ids=evidence((price_claim,)) if price_claim and value_fit is not None else (), missing_treatment="omit"),
                FeatureScore(name="travel.amenity_fit", value=amenity_fit, weight=0.25, evidence_ids=evidence(tuple(amenity_claims.values())) if amenity_fit is not None else (), missing_treatment="omit"),
            )
        return output

    def format_claim(self, attribute: str, claim: EntityClaim) -> str:
        return format_value(claim.typed_value)


def _distance_km(left: tuple[float, float], right: tuple[float, float]) -> float:
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1 = map(radians, left)
    lat2, lon2 = map(radians, right)
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(value))


def format_value(value: TypedValue) -> str:
    if isinstance(value, TextValue):
        return value.value
    if isinstance(value, MoneyValue):
        return f"{value.amount:.2f} {value.currency}"
    if isinstance(value, LocationValue):
        return f"{value.latitude:.5f}, {value.longitude:.5f}"
    if hasattr(value, "amount") and hasattr(value, "unit"):
        return f"{value.amount} {value.unit}"
    if hasattr(value, "start") and hasattr(value, "end"):
        return f"{value.start.isoformat()} to {value.end.isoformat()}"
    if hasattr(value, "value"):
        return str(value.value)
    return str(value.model_dump(mode="json"))


def _synthetic_places() -> tuple[TravelPlaceRecord, ...]:
    return (
        TravelPlaceRecord(
            name="Juniper House (synthetic)",
            provider_object_id="node/100000001",
            osm_type="node",
            latitude=37.7618,
            longitude=-122.4212,
            place_type="tourism/guest_house",
            display_name="Juniper House, Example District, Example City",
            url="https://example.org/synthetic-travel/juniper-house",
        ),
        TravelPlaceRecord(
            name="Maple Corner (synthetic)",
            provider_object_id="node/100000002",
            osm_type="node",
            latitude=37.7690,
            longitude=-122.4140,
            place_type="amenity/restaurant",
            display_name="Maple Corner, Example District, Example City",
            url="https://example.org/synthetic-travel/maple-corner",
        ),
    )
