"""Shopping extension that keeps product identity and each offer distinct."""

import math
from datetime import datetime, timedelta
from decimal import Decimal
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
    FakeShoppingProductAdapter,
    OpenFoodFactsAdapter,
    ShoppingProductRecord,
)
from personal_ai.domains.shopping.models import (
    ShoppingCostBreakdown,
    ShoppingOfferInput,
    normalize_total_cost,
)
from personal_ai.entities.research import (
    AvailabilityValue,
    BooleanValue,
    CanonicalEntity,
    EntityClaim,
    LocationValue,
    MoneyValue,
    NumberValue,
    TextValue,
    TypedValue,
)
from personal_ai.ranking.policy import verified_claims_for_feature

_CLAIM_FIELDS = (
    ("product_variant", "Product variant", "text", False),
    ("brand", "Brand", "text", False),
    ("model", "Model", "text", False),
    ("package_quantity", "Package quantity", "text", False),
    ("category", "Category", "text", False),
    ("size", "Size", "text", False),
    ("color", "Color", "text", False),
    ("condition", "Condition", "text", False),
    ("material", "Material", "text", False),
    ("capacity", "Capacity", "text", False),
    ("compatibility", "Compatibility", "text", True),
    ("dimensions", "Dimensions", "text", False),
    ("style", "Style", "text", False),
    ("merchant", "Merchant", "text", False),
    ("price", "Item price", "money", False),
    ("shipping_price", "Shipping", "money", False),
    ("tax_included", "Tax included", "boolean", False),
    ("tax_amount", "Tax amount", "money", False),
    ("quoted_total", "Merchant quoted total", "money", False),
    ("total_price", "Complete total price", "money", False),
    ("availability", "Availability", "availability", True),
    ("delivery_date", "Delivery date", "date", False),
    ("return_policy", "Return policy", "text", False),
    ("review_rating", "Review rating", "number", False),
    ("review_count", "Review sample size", "number", False),
)
_FEATURE_FIELDS = (
    DomainField(key="offer_value", label="Quoted offer value", value_kinds=("number",), mutable=False),
    DomainField(key="specification_fit", label="Specification fit", value_kinds=("number",), mutable=False),
    DomainField(key="delivery_fit", label="Delivery fit", value_kinds=("number",), mutable=False),
    DomainField(key="review_evidence_quality", label="Review evidence quality", value_kinds=("number",), mutable=False),
)


class ShoppingModule:
    policy_version = "shopping-features-v2"
    registration = DomainRegistration(
        domain_id="shopping",
        supported_entity_types=("object",),
        supported_constraints=(
            "product_variant", "price", "total_price", "availability", "brand", "model",
            "size", "color", "condition", "material", "capacity", "compatibility",
            "dimensions", "style", "merchant", "seller_location", "delivery_date",
            "return_policy", "package_quantity", "category",
        ),
        supported_features=("offer_value", "specification_fit", "delivery_fit", "review_evidence_quality"),
        source_policy_version="shopping-sources-v1",
        field_schema_version="shopping-comparison-v1",
        feature_policy_version="shopping-features-v2",
        fields=tuple(
            [DomainField(key=key, label=label, value_kinds=(kind,), required_for_recommendation=required)
             for key, label, kind, required in _CLAIM_FIELDS]
            + list(_FEATURE_FIELDS)
        ),
        source_adapters=("phase5-research", "fake", "brave", "open_food_facts"),
        privacy_policy=(
            "Barcode lookup sends only the submitted barcode. Do not send private purchase history, "
            "receipts, or sensitive product queries to a public catalog."
        ),
        retention_policy=(
            "Product facts, offers, and review observations remain separately attributable and expiring. "
            "No purchase, checkout, or price history is written."
        ),
    )
    feature_weights: ClassVar[dict[str, float]] = {
        "shopping.offer_value": 0.45,
        "shopping.specification_fit": 0.25,
        "shopping.delivery_fit": 0.15,
        "shopping.review_evidence_quality": 0.15,
    }

    def registration_for(self, enabled: bool) -> DomainRegistration:
        return self.registration.model_copy(update={"enabled": enabled})

    def prepare_decision(self, request: DecisionCreateRequest) -> DecisionCreateRequest:
        constraints = request.constraints
        marker = "shopping-policy-v2"
        availability = Constraint(
            id=uuid5(request.idempotency_key, "shopping-required-availability-v2"),
            attribute="availability",
            operator="availability",
            value=AvailabilityValue(value="available"),
            required=True,
            missing_policy="fail_closed",
            source="system",
            source_record_id=marker,
        )
        constraints = tuple(item for item in constraints if item != availability)
        request = request.model_copy(update={"constraints": (*constraints, availability)})
        self.validate_decision(request)
        return request

    def validate_decision(self, request: DecisionCreateRequest) -> None:
        registered_attrs = {field.key for field in self.registration.fields}
        registered_attrs.update(self.registration.supported_constraints)
        for candidate in request.candidates:
            if candidate.entity_type not in self.registration.supported_entity_types:
                raise DomainContractError("shopping_entity_type_unsupported")
            for claim in candidate.claims:
                if claim.attribute not in registered_attrs:
                    raise DomainContractError("shopping_claim_unregistered")
        for item in (*request.constraints, *request.preferences):
            if item.attribute not in self.registration.supported_constraints:
                raise DomainContractError("shopping_constraint_unregistered")

    def get_adapter(self, settings, *, rate_limiter=None):
        if settings.shopping_products_adapter == "open_food_facts":
            return OpenFoodFactsAdapter(settings, rate_limiter=rate_limiter)
        product = ShoppingProductRecord(
            barcode="000000000001",
            name="Cedar Oat Drink (synthetic)",
            brand="Example Pantry",
            quantity="1 L",
            categories=("plant-based drinks",),
            url="https://example.org/synthetic-shopping/cedar-oat-drink",
        )
        return FakeShoppingProductAdapter(product)

    def map_product_records(
        self,
        records: tuple[ShoppingProductRecord, ...],
        *,
        owner_id: str,
        provider: str,
        now: datetime,
        ttl_seconds: int,
    ) -> tuple[tuple[Candidate, ...], tuple[SuppliedEvidence, ...], tuple[ProviderObservationExtension, ...]]:
        candidates, evidence, extensions = [], [], []
        for record in records:
            evidence_id = uuid5(NAMESPACE_URL, f"shopping-product-evidence:{provider}:{record.barcode}:{now.isoformat()}")
            observation_id = uuid5(NAMESPACE_URL, f"shopping-product-observation:{provider}:{record.barcode}:{now.isoformat()}")
            subject = record.name
            clauses = [f"{subject} product variant is {record.barcode}."]
            claims = [
                ClaimProposal(
                    attribute="product_variant",
                    typed_value=TextValue(value=record.barcode),
                    original_value=record.barcode,
                    evidence_ids=(evidence_id,),
                )
            ]
            if record.brand:
                clauses.append(f"{subject} brand is {record.brand}.")
                claims.append(ClaimProposal(
                    attribute="brand", typed_value=TextValue(value=record.brand),
                    original_value=record.brand, evidence_ids=(evidence_id,),
                ))
            if record.quantity:
                clauses.append(f"{subject} package quantity is {record.quantity}.")
                claims.append(ClaimProposal(
                    attribute="package_quantity", typed_value=TextValue(value=record.quantity),
                    original_value=record.quantity, evidence_ids=(evidence_id,),
                ))
            if record.categories:
                category = ", ".join(record.categories)
                clauses.append(f"{subject} category is {category}.")
                claims.append(ClaimProposal(
                    attribute="category", typed_value=TextValue(value=category),
                    original_value=category, evidence_ids=(evidence_id,),
                ))
            passage = " ".join(clauses)
            normalized = " ".join(passage.split())
            expires = now + timedelta(seconds=ttl_seconds)
            source = SuppliedEvidence(
                evidence_id=evidence_id,
                source_observation_id=observation_id,
                owner_id=owner_id,
                url=record.url,
                title=record.name,
                observed_at=now,
                expires_at=expires,
                content_fingerprint=sha256(normalized.encode()).hexdigest(),
                passage=passage,
            )
            candidates.append(Candidate(
                entity_type="object",
                canonical_name=subject,
                identifiers={"upc": record.barcode},
                claims=tuple(claims),
            ))
            evidence.append(source)
            extensions.append(ProviderObservationExtension(
                source_observation_id=observation_id,
                evidence_id=evidence_id,
                owner_id=owner_id,
                provider=provider,
                provider_object_id=record.barcode,
                entity_kind="product_variant",
                adapter_version=("open-food-facts-v3.6-read-v1" if provider == "open_food_facts" else "fake-product-v1"),
                attribution=(
                    "Product data: Open Food Facts, ODbL 1.0; individual contents: Database Contents License"
                    if provider == "open_food_facts"
                    else "Synthetic shopping fixture data"
                ),
                policy_url=(
                    "https://openfoodfacts.github.io/openfoodfacts-server/api/tutorials/license-be-on-the-legal-side/"
                    if provider == "open_food_facts"
                    else None
                ),
                url=record.url,
                title=record.name,
                observed_at=now,
                expires_at=expires,
            ))
        return tuple(candidates), tuple(evidence), tuple(extensions)

    def map_offer(
        self,
        offer: ShoppingOfferInput,
        *,
        owner_id: str,
        provider: str,
        adapter_version: str,
    ) -> tuple[Candidate, tuple[SuppliedEvidence, ...], tuple[ProviderObservationExtension, ...]]:
        """Map one source offer; distinct merchant offers stay distinct entities."""
        base_id = f"{provider}:{offer.offer_id}:{offer.variant.variant_key}"
        stable_offer_id = f"{offer.offer_id}:{offer.variant.variant_key}"
        subject = f"{offer.product_name} — {offer.merchant}"
        claim_specs = []
        sentences = [f"{subject} offer identifier is {stable_offer_id}."]

        def add_claim(attribute, typed_value, literal, sentence):
            sentences.append(sentence)
            claim_specs.append((sentence, attribute, typed_value, literal))

        add_claim(
            "product_variant",
            TextValue(value=offer.variant.variant_key),
            offer.variant.variant_key,
            f"{subject} product variant is {offer.variant.variant_key}.",
        )
        add_claim("merchant", TextValue(value=offer.merchant), offer.merchant, f"{subject} merchant is {offer.merchant}.")
        add_claim(
            "price", offer.price, f"{offer.price.amount:.2f} {offer.price.currency}",
            f"{subject} costs {offer.price.amount:.2f} {offer.price.currency}.",
        )
        add_claim(
            "availability", AvailabilityValue(value=offer.availability), offer.availability,
            f"{subject} availability is {offer.availability}.",
        )
        for attribute, value in offer.variant.variant_attributes.items():
            add_claim(attribute, TextValue(value=value), value, f"{subject} {attribute.replace('_', ' ')} is {value}.")
        if offer.variant.model_number:
            add_claim("model", TextValue(value=offer.variant.model_number), offer.variant.model_number, f"{subject} model is {offer.variant.model_number}.")
        if offer.variant.barcode:
            sentences.append(f"{subject} barcode is {offer.variant.barcode}.")
            # `upc` is an identity identifier; its source literal is in the passage.
        if offer.shipping is not None:
            add_claim(
                "shipping_price", offer.shipping, f"{offer.shipping.amount:.2f} {offer.shipping.currency}",
                f"{subject} shipping price is {offer.shipping.amount:.2f} {offer.shipping.currency}.",
            )
        if offer.tax_included is not None:
            literal = "true" if offer.tax_included else "false"
            add_claim("tax_included", BooleanValue(value=offer.tax_included), literal, f"{subject} tax included is {literal}.")
        if offer.tax_amount is not None:
            add_claim(
                "tax_amount", offer.tax_amount, f"{offer.tax_amount.amount:.2f} {offer.tax_amount.currency}",
                f"{subject} tax amount is {offer.tax_amount.amount:.2f} {offer.tax_amount.currency}.",
            )
        complete_cost = normalize_total_cost(ShoppingCostBreakdown(
            item_price=offer.price,
            shipping=offer.shipping,
            tax_included=offer.tax_included,
            tax_amount=offer.tax_amount,
            currency_as_of=offer.observed_at.date(),
            source_ids=(offer.offer_id,),
        ))
        if offer.quoted_total is not None:
            literal = f"{offer.quoted_total.amount:.2f} {offer.quoted_total.currency}"
            add_claim("quoted_total", offer.quoted_total, literal, f"{subject} quoted total is {literal}.")
            if complete_cost.complete and complete_cost.amount == offer.quoted_total:
                add_claim("total_price", offer.quoted_total, literal, f"{subject} total price is {literal}.")
        if offer.delivery_date is not None:
            add_claim("delivery_date", _date_value(offer.delivery_date), offer.delivery_date.isoformat(), f"{subject} delivery date is {offer.delivery_date.isoformat()}.")
        if offer.return_policy:
            add_claim("return_policy", TextValue(value=offer.return_policy), offer.return_policy, f"{subject} return policy is {offer.return_policy}.")
        if offer.condition:
            add_claim("condition", TextValue(value=offer.condition), offer.condition, f"{subject} condition is {offer.condition}.")

        chunks = []
        pending = []
        for sentence in sentences:
            if pending and len(" ".join((*pending, sentence))) > 1_100:
                chunks.append(tuple(pending))
                pending = []
            pending.append(sentence)
        if pending:
            chunks.append(tuple(pending))

        sources = []
        extensions = []
        claims = []
        claim_specs_by_sentence = {item[0]: item[1:] for item in claim_specs}
        title = f"{offer.product_name} offer at {offer.merchant}"
        for chunk_index, chunk in enumerate(chunks):
            evidence_id = uuid5(NAMESPACE_URL, f"shopping-offer-evidence:{base_id}:{offer.observed_at.isoformat()}:{chunk_index}")
            observation_id = uuid5(NAMESPACE_URL, f"shopping-offer-observation:{base_id}:{offer.observed_at.isoformat()}:{chunk_index}")
            passage = " ".join(chunk)
            if len(passage) > 1_200:
                raise DomainContractError("shopping_source_passage_too_large")
            sources.append(_evidence(
                evidence_id=evidence_id,
                observation_id=observation_id,
                owner_id=owner_id,
                url=offer.source_url,
                title=title,
                observed_at=offer.observed_at,
                expires_at=offer.expires_at,
                passage=passage,
            ))
            extensions.append(_provider_observation(
                evidence_id=evidence_id,
                observation_id=observation_id,
                owner_id=owner_id,
                provider=provider,
                provider_object_id=offer.offer_id,
                entity_kind="merchant_offer",
                adapter_version=adapter_version,
                attribution=f"Offer information supplied by {provider}; current offer is not guaranteed.",
                url=offer.source_url,
                title=title,
                observed_at=offer.observed_at,
                expires_at=offer.expires_at,
            ))
            for sentence in chunk:
                spec = claim_specs_by_sentence.get(sentence)
                if spec:
                    attribute, typed_value, literal = spec
                    claims.append(_claim(attribute, typed_value, literal, evidence_id))
        if offer.review_signal:
            review_evidence_id = uuid5(NAMESPACE_URL, f"shopping-review-evidence:{base_id}:{offer.review_signal.observed_at.isoformat()}")
            review_observation_id = uuid5(NAMESPACE_URL, f"shopping-review-observation:{base_id}:{offer.review_signal.observed_at.isoformat()}")
            rating = str(offer.review_signal.rating)
            sample_count = str(offer.review_signal.sample_count)
            review_passage = f"{subject} review rating is {rating}. {subject} review count is {sample_count}."
            claims.extend((
                _claim("review_rating", NumberValue(value=offer.review_signal.rating), rating, review_evidence_id),
                _claim("review_count", NumberValue(value=Decimal(sample_count)), sample_count, review_evidence_id),
            ))
            sources.append(_evidence(
                evidence_id=review_evidence_id,
                observation_id=review_observation_id,
                owner_id=owner_id,
                url=offer.review_signal.source_url,
                title=f"Review summary from {offer.review_signal.source_name}",
                observed_at=offer.review_signal.observed_at,
                expires_at=offer.review_signal.expires_at,
                passage=review_passage,
            ))
            extensions.append(_provider_observation(
                evidence_id=review_evidence_id,
                observation_id=review_observation_id,
                owner_id=owner_id,
                provider=_provider_slug(f"{provider}_reviews"),
                provider_object_id=offer.offer_id,
                entity_kind="review_signal",
                adapter_version="review-signal-v1",
                attribution=(
                    f"Sourced opinion aggregate from {offer.review_signal.source_name}; "
                    f"rating {rating}/5, sample size {sample_count}; not a product fact"
                ),
                url=offer.review_signal.source_url,
                title=f"Review summary from {offer.review_signal.source_name}",
                observed_at=offer.review_signal.observed_at,
                expires_at=offer.review_signal.expires_at,
            ))
        return Candidate(
            entity_type="object",
            canonical_name=subject,
            identifiers={"offer_id": stable_offer_id},
            claims=tuple(claims),
        ), tuple(sources), tuple(extensions)

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
        del entities, context
        claims = {entity_id: tuple(claims_by_entity.get(entity_id, ())) for entity_id in eligible_entity_ids}
        evaluations_by_id = {item.entity_id: item for item in evaluations}
        price_by_entity = {}
        for entity_id, entity_claims in claims.items():
            _, selected = verified_claims_for_feature(
                entity_claims, "total_price", now,
                evaluation=evaluations_by_id.get(entity_id),
            )
            price_by_entity[entity_id] = tuple(
                item for item in selected if isinstance(item.typed_value, MoneyValue)
            )
        price_choice = {
            entity_id: selected[0]
            for entity_id, selected in price_by_entity.items()
            if selected
        }
        price_groups: dict[tuple[str, str | None], list[tuple[UUID, Decimal]]] = {}
        for entity_id, item in price_choice.items():
            price_groups.setdefault((item.typed_value.currency, item.scope), []).append(
                (entity_id, item.typed_value.amount)
            )
        preference_fields = tuple(
            item for item in preferences
            if item.attribute in {"model", "size", "color", "condition", "material", "capacity", "compatibility", "dimensions", "style"}
        )
        delivery_constraints = tuple(
            item for item in constraints
            if item.attribute == "delivery_date" and item.operator in {"maximum", "date_window"}
        )
        delivery_constraint = delivery_constraints[0] if len(delivery_constraints) == 1 else None
        delivery_deadline = delivery_constraint.value if delivery_constraint is not None else None
        output = {}
        for entity_id in eligible_entity_ids:
            items = claims[entity_id]
            ids = lambda selected: tuple(sorted({ref.evidence_id for claim in selected for ref in claim.evidence_refs}, key=str))
            evaluation = evaluations_by_id.get(entity_id)
            selected_price_claims = price_by_entity.get(entity_id, ())
            price_claim = price_choice.get(entity_id)
            offer_value = None
            if price_claim is not None:
                comparable = price_groups.get((price_claim.typed_value.currency, price_claim.scope), [])
                if len({candidate_id for candidate_id, _ in comparable}) >= 2:
                    amounts = [amount for _, amount in comparable]
                    lowest, highest = min(amounts), max(amounts)
                    offer_value = 1.0 if lowest == highest else max(
                        0.0, min(1.0, float((highest - price_claim.typed_value.amount) / (highest - lowest)))
                    )
            spec_matches = 0
            resolved_specifications = 0
            spec_evidence = []
            for preference in preference_fields:
                _, actual_claims = verified_claims_for_feature(
                    items, preference.attribute, now,
                    evaluation=evaluation, scope=preference.scope,
                )
                actual_claims = tuple(
                    item for item in actual_claims if isinstance(item.typed_value, type(preference.target))
                )
                if not actual_claims:
                    continue
                resolved_specifications += 1
                if _same_value(actual_claims[0].typed_value, preference.target):
                    spec_matches += 1
                spec_evidence.extend(actual_claims)
            specification_fit = (
                spec_matches / resolved_specifications if resolved_specifications else None
            )
            _, delivery_claims = verified_claims_for_feature(
                items, "delivery_date", now,
                evaluation=evaluation,
                scope=delivery_constraint.scope if delivery_constraint is not None else None,
            ) if delivery_constraint is not None else (None, ())
            delivery_claim = next((item for item in delivery_claims if hasattr(item.typed_value, "value")), None)
            delivery_fit = None
            if delivery_claim is not None and hasattr(delivery_claim.typed_value, "value") and delivery_deadline is not None:
                delivery_date = delivery_claim.typed_value.value
                if hasattr(delivery_deadline, "value"):
                    deadline = delivery_deadline.value
                elif hasattr(delivery_deadline, "end"):
                    deadline = delivery_deadline.end
                else:
                    deadline = None
                if deadline is not None:
                    days = (delivery_date - now.date()).days
                    allowed_days = max(1, (deadline - now.date()).days)
                    delivery_fit = max(0.0, min(1.0, 1.0 - days / allowed_days))
            _, review_count_claims = verified_claims_for_feature(
                items, "review_count", now, evaluation=evaluation,
            )
            review_count = next((item for item in review_count_claims if isinstance(item.typed_value, NumberValue)), None)
            review_quality = None
            if review_count is not None:
                count = float(review_count.typed_value.value)
                age_days = max(0.0, (now - review_count.observed_at).total_seconds() / 86400)
                recency = max(0.0, 1.0 - age_days / 180.0)
                review_quality = min(1.0, math.log1p(count) / math.log1p(500)) * recency
            output[entity_id] = (
                FeatureScore(name="shopping.offer_value", value=offer_value, weight=0.45, evidence_ids=ids(selected_price_claims) if selected_price_claims and offer_value is not None else (), missing_treatment="omit"),
                FeatureScore(name="shopping.specification_fit", value=specification_fit, weight=0.25, evidence_ids=ids(tuple(spec_evidence)) if specification_fit is not None else (), missing_treatment="omit"),
                FeatureScore(name="shopping.delivery_fit", value=delivery_fit, weight=0.15, evidence_ids=ids((delivery_claim,)) if delivery_claim and delivery_fit is not None else (), missing_treatment="omit"),
                FeatureScore(name="shopping.review_evidence_quality", value=review_quality, weight=0.15, evidence_ids=ids((review_count,)) if review_count and review_quality is not None else (), missing_treatment="omit"),
            )
        return output

    def format_claim(self, attribute: str, claim: EntityClaim) -> str:
        if attribute == "review_rating" and isinstance(claim.typed_value, NumberValue):
            return f"{claim.typed_value.value}/5 (sourced opinion)"
        if attribute == "review_count" and isinstance(claim.typed_value, NumberValue):
            return f"sample size {claim.typed_value.value}"
        return format_value(claim.typed_value)


def _claim(attribute: str, typed_value: TypedValue, original: str, evidence_id) -> ClaimProposal:
    return ClaimProposal(attribute=attribute, typed_value=typed_value, original_value=original, evidence_ids=(evidence_id,))


def _evidence(*, evidence_id, observation_id, owner_id, url, title, observed_at, expires_at, passage):
    normalized = " ".join(passage.split())
    return SuppliedEvidence(
        evidence_id=evidence_id,
        source_observation_id=observation_id,
        owner_id=owner_id,
        url=url,
        title=title,
        observed_at=observed_at,
        expires_at=expires_at,
        content_fingerprint=sha256(normalized.encode()).hexdigest(),
        passage=passage,
    )


def _provider_observation(*, evidence_id, observation_id, owner_id, provider, provider_object_id, entity_kind, adapter_version, attribution, url, title, observed_at, expires_at):
    return ProviderObservationExtension(
        source_observation_id=observation_id,
        evidence_id=evidence_id,
        owner_id=owner_id,
        provider=_provider_slug(provider),
        provider_object_id=provider_object_id,
        entity_kind=entity_kind,
        adapter_version=adapter_version,
        attribution=attribution,
        url=url,
        title=title,
        observed_at=observed_at,
        expires_at=expires_at,
    )


def _provider_slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")
    return (slug or "source")[:80]


def _same_value(actual: TypedValue, wanted: TypedValue) -> bool:
    if isinstance(actual, TextValue) and isinstance(wanted, TextValue):
        return actual.value.casefold().strip() == wanted.value.casefold().strip()
    return actual == wanted


def _date_value(value):
    from personal_ai.entities.research import DateValue

    return DateValue(value=value)


def format_value(value: TypedValue) -> str:
    if isinstance(value, TextValue):
        return value.value
    if isinstance(value, MoneyValue):
        return f"{value.amount:.2f} {value.currency}"
    if isinstance(value, AvailabilityValue):
        return value.value
    if isinstance(value, NumberValue):
        return str(value.value)
    if isinstance(value, LocationValue):
        return f"{value.latitude:.5f}, {value.longitude:.5f}"
    if hasattr(value, "value"):
        return str(value.value)
    return str(value.model_dump(mode="json"))
