"""Deterministic freshness, hard-constraint, and explainable ranking policies."""

import re
import unicodedata
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt
from uuid import UUID, uuid5

from pydantic import ValidationError

from personal_ai.decisions.contracts import (
    AttributeStatus,
    CandidateEvaluation,
    CandidateProposal,
    Constraint,
    ConstraintOutcome,
    FeatureScore,
    Preference,
)
from personal_ai.entities.research import (
    AvailabilityValue,
    BooleanValue,
    CanonicalEntity,
    DateTimeValue,
    DateValue,
    DateWindowValue,
    EntityAlias,
    EntityClaim,
    EntityMatch,
    EvidenceReference,
    LocationValue,
    MoneyValue,
    NumberValue,
    QuantityValue,
    TextValue,
    TypedValue,
)

RESOLUTION_POLICY_VERSION = "resolve-v2"
CONSTRAINT_POLICY_VERSION = "constraint-v1"
RANKING_POLICY_VERSION = "rank-v1"
CLAIM_VERIFICATION_POLICY_VERSION = "claim-verification-v2"
IDENTITY_ATTRIBUTES = frozenset({
    "model", "sku", "catalog_id", "product_id", "upc", "ean", "isbn", "mpn",
})

_UNITS: dict[str, tuple[str, Decimal]] = {
    "m": ("length", Decimal(1)),
    "meter": ("length", Decimal(1)),
    "meters": ("length", Decimal(1)),
    "cm": ("length", Decimal("0.01")),
    "mm": ("length", Decimal("0.001")),
    "km": ("length", Decimal(1000)),
    "in": ("length", Decimal("0.0254")),
    "inch": ("length", Decimal("0.0254")),
    "inches": ("length", Decimal("0.0254")),
    "ft": ("length", Decimal("0.3048")),
    "foot": ("length", Decimal("0.3048")),
    "feet": ("length", Decimal("0.3048")),
    "kg": ("mass", Decimal(1)),
    "g": ("mass", Decimal("0.001")),
    "lb": ("mass", Decimal("0.45359237")),
    "lbs": ("mass", Decimal("0.45359237")),
}


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(
        "".join(char if char.isalnum() else " " for char in normalized).split()
    )


def _identifier(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _value_key(value: TypedValue) -> tuple | None:
    if isinstance(value, QuantityValue):
        unit = _UNITS.get(value.unit.casefold())
        if unit is None:
            return None
        dimension, factor = unit
        return ("quantity", dimension, value.amount * factor)
    if isinstance(value, MoneyValue):
        return ("money", value.currency, value.amount)
    if isinstance(value, NumberValue):
        return ("number", value.value)
    if isinstance(value, TextValue):
        return ("text", _identifier(value.value))
    if isinstance(value, DateValue):
        return ("date", value.value.isoformat())
    if isinstance(value, DateTimeValue):
        return ("datetime", value.value.isoformat())
    if isinstance(value, DateWindowValue):
        return ("date_window", value.start.isoformat(), value.end.isoformat())
    if isinstance(value, LocationValue):
        return ("location", round(value.latitude, 7), round(value.longitude, 7))
    if isinstance(value, AvailabilityValue):
        return ("availability", value.value)
    return ("boolean", value.value)


def values_equal(left: TypedValue, right: TypedValue) -> bool | None:
    left_key, right_key = _value_key(left), _value_key(right)
    if left_key is None or right_key is None:
        return None
    if left_key[0] != right_key[0]:
        return False
    # Different currencies and incompatible physical dimensions are unknown,
    # not a false comparison that could masquerade as a hard failure.
    if left_key[0] in {"money", "quantity"} and left_key[1] != right_key[1]:
        return None
    return left_key == right_key


def literal_supported(original_value: str, passage: str) -> bool:
    """Conservatively accept only values literally present in attributed text."""
    normalize = lambda text: " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    needle = normalize(original_value)
    haystack = normalize(passage)
    if not needle:
        return False
    start = 0
    while (position := haystack.find(needle, start)) >= 0:
        end = position + len(needle)
        left_ok = not needle[0].isalnum() or position == 0 or not haystack[position - 1].isalnum()
        right_ok = not needle[-1].isalnum() or end == len(haystack) or not haystack[end].isalnum()
        if left_ok and right_ok:
            return True
        start = position + 1
    return False


def claim_assertion_supported(
    subject: str, attribute: str, original_value: str, typed_value: TypedValue, passage: str
) -> bool:
    """Require a literal value in a simple, subject-bound, affirmative assertion.

    This intentionally handles only explicit single-sentence forms (plus a narrow
    adjacent ``Its color is ...`` form). It is not a semantic entailment check.
    """
    if not normalize_name(subject) or not literal_matches_typed_value(original_value, typed_value):
        return False
    value_pattern = re.escape(unicodedata.normalize("NFKC", original_value).strip())
    subject_pattern = r"\s+".join(re.escape(part) for part in unicodedata.normalize("NFKC", subject).split())
    subject_prefix = rf"^\s*(?:the\s+)?{subject_pattern}(?:\s+catalog\s+\S+)?\s+"
    # A complete assertion cannot borrow a value or omit a trailing qualifier.
    boundary = r"\s*[.!?;]?\s*$"
    if attribute.casefold() == "price":
        predicates = r"(?:costs?|price\s+is|is\s+priced\s+at|is\s+listed\s+for)"
        assertion_pattern = subject_prefix + predicates + rf"\s+{value_pattern}{boundary}"
    else:
        attribute_pattern = re.escape(attribute.replace("_", " "))
        assertion_pattern = (
            subject_prefix
            + rf"(?:{attribute_pattern}\s+(?:is|are|:|=)|is\s+{attribute_pattern})"
            + rf"\s+{value_pattern}{boundary}"
        )
        if attribute == "availability" and isinstance(typed_value, AvailabilityValue):
            assertion_pattern = (
                rf"(?:{assertion_pattern}|{subject_prefix}is\s+{value_pattern}{boundary})"
            )

    sentences = re.split(r"(?<=[.!?;])\s+", passage)
    for index, sentence in enumerate(sentences):
        sentence = unicodedata.normalize("NFKC", sentence)
        if re.search(r"\b(if|unless|whether|might|may|could|would)\b", sentence, re.IGNORECASE):
            continue
        if re.search(assertion_pattern, sentence, re.IGNORECASE):
            return True
        if index == 0 or attribute.casefold() == "price":
            continue
        current = unicodedata.normalize("NFKC", sentence)
        if not re.match(r"\s*(?:its|the item['’]s)\b", current, re.IGNORECASE):
            continue
        previous = unicodedata.normalize("NFKC", sentences[index - 1])
        # Anaphora is accepted only after one simple, explicit subject assertion.
        prior_assertion = re.fullmatch(
            subject_prefix + rf"(?:costs?|price\s+is|is\s+priced\s+at)\s+"
            rf"(?:[$€£]\s*)?{_NUMBER_PATTERN}\s+[A-Z]{{3}}{boundary}",
            previous,
            re.IGNORECASE,
        )
        if prior_assertion is None or re.search(
            r"\b(and|or|but|while|whereas|versus|if|unless)\b", previous, re.IGNORECASE
        ):
            continue
        pronoun_pattern = (
            rf"^\s*(?:its|the item['’]s)\s+{re.escape(attribute.replace('_', ' '))}"
            rf"\s+(?:is|are|:|=)\s+{value_pattern}{boundary}"
        )
        if re.search(pronoun_pattern, current, re.IGNORECASE):
            return True
    return False


_NUMBER_PATTERN = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"


def literal_matches_typed_value(original_value: str, value: TypedValue) -> bool:
    """Validate a proposed typed value against a conservatively parsed source literal."""
    literal = unicodedata.normalize("NFKC", original_value).strip()
    normalized = " ".join(literal.casefold().split())
    semantic_literal = literal.rstrip(" .,:;")
    normalized_semantic = " ".join(semantic_literal.casefold().split())

    if isinstance(value, TextValue):
        target = " ".join(unicodedata.normalize("NFKC", value.value).casefold().split())
        return normalized == target
    if isinstance(value, AvailabilityValue):
        return normalized_semantic == value.value
    if isinstance(value, BooleanValue):
        return normalized_semantic in ({"true", "yes"} if value.value else {"false", "no"})

    numbers = re.findall(rf"(?<![\w.]){_NUMBER_PATTERN}(?![\w.])", literal)
    if isinstance(value, NumberValue):
        if len(numbers) != 1:
            return False
        try:
            return Decimal(numbers[0].replace(",", "")) == value.value
        except InvalidOperation:
            return False

    if isinstance(value, MoneyValue):
        if len(numbers) != 1:
            return False
        codes = re.findall(r"(?<![A-Z])([A-Z]{3})(?![A-Z])", literal.upper())
        # Currency symbols are accepted only when they uniquely identify the
        # currency; dollar and yen symbols deliberately remain ambiguous.
        symbol_currency = {"€": "EUR", "£": "GBP"}.get(literal[:1])
        if value.currency not in codes and symbol_currency != value.currency:
            return False
        try:
            return Decimal(numbers[0].replace(",", "")) == value.amount
        except InvalidOperation:
            return False

    if isinstance(value, QuantityValue):
        if len(numbers) != 1:
            return False
        unit_match = re.search(r"([A-Za-z]+)\s*$", semantic_literal)
        if unit_match is None:
            return False
        try:
            parsed = QuantityValue(
                amount=Decimal(numbers[0].replace(",", "")),
                unit=unit_match.group(1),
            )
        except (InvalidOperation, ValidationError):
            return False
        return values_equal(parsed, value) is True

    if isinstance(value, DateValue):
        try:
            return date.fromisoformat(semantic_literal) == value.value
        except ValueError:
            return False

    if isinstance(value, DateTimeValue):
        try:
            parsed = datetime.fromisoformat(semantic_literal)
        except ValueError:
            return False
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return False
        return parsed.astimezone(UTC) == value.value

    if isinstance(value, DateWindowValue):
        match = re.fullmatch(
            r"\s*(\d{4}-\d{2}-\d{2})\s*(?:to|through|–|—)\s*(\d{4}-\d{2}-\d{2})\s*",
            semantic_literal,
            flags=re.IGNORECASE,
        )
        if match is None:
            return False
        try:
            return (
                date.fromisoformat(match.group(1)) == value.start
                and date.fromisoformat(match.group(2)) == value.end
            )
        except ValueError:
            return False

    if isinstance(value, LocationValue):
        match = re.fullmatch(
            r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*",
            semantic_literal,
        )
        if match is None:
            return False
        return (
            round(float(match.group(1)), 7) == round(value.latitude, 7)
            and round(float(match.group(2)), 7) == round(value.longitude, 7)
        )

    return False


def _claim_value_match(left: EntityClaim, right: EntityClaim) -> bool:
    result = values_equal(left.typed_value, right.typed_value)
    return result is True and left.scope == right.scope


def rank_with_domain_features(
    evaluations: tuple[CandidateEvaluation, ...],
    entities: tuple[CanonicalEntity, ...],
    features_by_entity: dict[UUID, tuple[FeatureScore, ...]],
    fallback_state: str,
) -> tuple[tuple[CandidateEvaluation, ...], str, UUID | None]:
    """Apply registered domain features after the shared eligibility filter.

    Phase 6 eligibility and exclusion outcomes are preserved. The shared stage
    combines its preference score with a domain feature score at equal weight,
    then applies the same stable name/entity tie breakers as rank-v1.
    """
    names = {entity.id: normalize_name(entity.canonical_name) for entity in entities}
    combined: dict[UUID, CandidateEvaluation] = {}
    for evaluation in evaluations:
        extra = features_by_entity.get(evaluation.entity_id, ()) if evaluation.eligibility else ()
        features = (*evaluation.feature_values, *extra)
        base_score = evaluation.score
        domain_values = [item for item in extra if item.value is not None and item.weight > 0]
        domain_weight = sum(item.weight for item in domain_values)
        domain_score = (
            sum(item.value * item.weight for item in domain_values) / domain_weight
            if domain_weight > 0
            else None
        )
        if base_score is None:
            score = domain_score
        elif domain_score is None:
            score = base_score
        else:
            score = 0.5 * base_score + 0.5 * domain_score
        combined[evaluation.entity_id] = evaluation.model_copy(
            update={"feature_values": features, "score": score, "rank": None}
        )

    eligible = [item for item in combined.values() if item.eligibility]
    eligible.sort(
        key=lambda item: (
            item.score is None,
            -(item.score if item.score is not None else 0),
            names.get(item.entity_id, ""),
            str(item.entity_id),
        )
    )
    ranked_ids = [item.entity_id for item in eligible if item.score is not None]
    ranked = {
        entity_id: combined[entity_id].model_copy(update={"rank": index + 1})
        for index, entity_id in enumerate(ranked_ids)
    }
    combined.update(ranked)
    selected = ranked_ids[0] if ranked_ids else None
    if selected is not None:
        state = "recommended"
    elif eligible:
        state = "eligible_unranked"
    else:
        # Keep the core distinction between research-needed and no-match.
        state = fallback_state
    return tuple(combined[item.entity_id] for item in evaluations), state, selected


def resolve_candidate(
    *,
    decision_id: UUID,
    subject_id: UUID,
    owner_id: str,
    proposal: CandidateProposal,
    proposed_claims: tuple[EntityClaim, ...],
    evidence_refs: tuple[EvidenceReference, ...],
    entities: tuple[CanonicalEntity, ...],
    aliases: tuple[EntityAlias, ...],
    claims_by_entity: dict[UUID, tuple[EntityClaim, ...]],
    new_entity_id: UUID,
    now: datetime,
    threshold: float,
    match_id: UUID,
) -> tuple[EntityMatch, UUID]:
    """Resolve strong identifiers exactly; otherwise abstain or create separately."""
    available = tuple(
        entity
        for entity in entities
        if entity.entity_type == proposal.entity_type
        and entity.status == "active"
        and entity.owner_scope in {f"owner:{owner_id}", "shared"}
    )
    proposed_ids = {key.casefold(): _identifier(value) for key, value in proposal.identifiers.items()}
    conflicting_identifier_entities = {
        entity.id
        for entity in available
        if any(
            key in {stored_key.casefold() for stored_key in entity.identifiers}
            and value != _identifier(next(
                stored_value for stored_key, stored_value in entity.identifiers.items()
                if stored_key.casefold() == key
            ))
            for key, value in proposed_ids.items()
        )
    }
    exact: list[tuple[CanonicalEntity, str]] = []
    for entity in available:
        if entity.id in conflicting_identifier_entities:
            continue
        same = [
            key for key, value in proposed_ids.items()
            if key in {k.casefold() for k in entity.identifiers}
            and value == _identifier(next(v for k, v in entity.identifiers.items() if k.casefold() == key))
        ]
        if same:
            exact.append((entity, "identifier_exact"))
    if len(exact) == 1:
        entity, feature = exact[0]
        match = EntityMatch(
            id=match_id, decision_id=decision_id, subject_id=subject_id, owner_id=owner_id,
            candidate_entity_id=entity.id,
            candidate_entity_ids=(entity.id,), selected_entity_id=entity.id,
            outcome="matched", confidence=1.0, feature_values={feature: 1.0},
            evidence_ids=tuple(ref.evidence_id for ref in evidence_refs), created_at=now,
        )
        return match, entity.id
    if len(exact) > 1:
        ids = tuple(sorted((entity.id for entity, _ in exact), key=str))
        return EntityMatch(
            id=match_id, decision_id=decision_id, subject_id=subject_id, owner_id=owner_id,
            candidate_entity_id=new_entity_id,
            candidate_entity_ids=ids, outcome="review", confidence=1.0,
            feature_values={"identifier_collision": 1.0},
            evidence_ids=tuple(ref.evidence_id for ref in evidence_refs), created_at=now,
        ), new_entity_id

    alias_by_entity = {
        alias.entity_id: alias.normalized_alias
        for alias in aliases
        if alias.owner_id in {owner_id, "*"}
    }
    proposed_name = normalize_name(proposal.canonical_name)
    eligible_proposed = tuple(
        claim for claim in proposed_claims
        if claim.attribute.casefold() in IDENTITY_ATTRIBUTES
        and claim.claim_status == "verified"
        and claim.verification_policy_version == CLAIM_VERIFICATION_POLICY_VERSION
        and claim.expires_at > now
    )
    scored: list[tuple[float, CanonicalEntity, dict[str, float]]] = []
    for entity in available:
        if entity.id in conflicting_identifier_entities:
            continue
        name_candidates = [normalize_name(entity.canonical_name)]
        if entity.id in alias_by_entity:
            name_candidates.append(normalize_name(alias_by_entity[entity.id]))
        similarity = max(
            (SequenceMatcher(None, proposed_name, name).ratio() for name in name_candidates),
            default=0.0,
        )
        stored_claims = tuple(
            claim for claim in claims_by_entity.get(entity.id, ())
            if claim.owner_id == owner_id
            and claim.attribute.casefold() in IDENTITY_ATTRIBUTES
            and claim.claim_status == "verified"
            and claim.verification_policy_version == CLAIM_VERIFICATION_POLICY_VERSION
            and claim.expires_at > now
        )
        shared_attributes = sorted({
            left.attribute
            for left in eligible_proposed
            for right in stored_claims
            if left.attribute == right.attribute and _claim_value_match(left, right)
        })
        independent = bool(shared_attributes)
        score = min(1.0, similarity * 0.65 + (0.35 if independent else 0.0))
        features = {"name_similarity": round(similarity, 6)}
        if shared_attributes:
            features["independent_attribute_match"] = 1.0
        if score >= 0.5:
            scored.append((score, entity, features))

    scored.sort(key=lambda item: (-item[0], str(item[1].id)))
    if scored and scored[0][0] >= threshold and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        score, entity, features = scored[0]
        if features.get("independent_attribute_match"):
            match = EntityMatch(
                id=match_id, decision_id=decision_id, subject_id=subject_id, owner_id=owner_id,
                candidate_entity_id=entity.id,
                candidate_entity_ids=(entity.id,), selected_entity_id=entity.id,
                outcome="matched", confidence=score, feature_values=features,
                evidence_ids=tuple(ref.evidence_id for ref in evidence_refs), created_at=now,
            )
            return match, entity.id

    if scored:
        top = scored[: min(20, len(scored))]
        best = top[0][0]
        ambiguous = len(top) > 1 and top[1][0] == best
        candidate_ids = tuple(item[1].id for item in top)
        return EntityMatch(
            id=match_id, decision_id=decision_id, subject_id=subject_id, owner_id=owner_id,
            candidate_entity_id=new_entity_id,
            candidate_entity_ids=candidate_ids, outcome="review",
            confidence=best,
            feature_values={
                f"candidate_{index}_{key}": value
                for index, (_, _, features) in enumerate(top)
                for key, value in features.items()
            } | ({"ambiguous_tie": 1.0} if ambiguous else {})
              | ({"conflicting_identifier": 1.0} if conflicting_identifier_entities else {}),
            evidence_ids=tuple(ref.evidence_id for ref in evidence_refs), created_at=now,
        ), new_entity_id

    return EntityMatch(
        id=match_id, decision_id=decision_id, subject_id=subject_id, owner_id=owner_id,
        candidate_entity_id=new_entity_id,
        candidate_entity_ids=(), outcome="no_match", confidence=0.0,
        feature_values=(
            {"conflicting_identifier": 1.0}
            if conflicting_identifier_entities else {}
        ), evidence_ids=tuple(ref.evidence_id for ref in evidence_refs), created_at=now,
    ), new_entity_id


def _status(
    attribute: str,
    scope: str | None,
    claims: tuple[EntityClaim, ...],
    now: datetime,
) -> AttributeStatus:
    relevant = tuple(
        claim for claim in claims
        if claim.attribute == attribute and (scope is None or claim.scope == scope)
    )
    active = tuple(claim for claim in relevant if claim.expires_at > now and claim.claim_status != "retracted")
    verified = tuple(
        claim for claim in active
        if claim.claim_status == "verified"
        and claim.verification_policy_version == CLAIM_VERIFICATION_POLICY_VERSION
    )
    unverified = tuple(
        claim for claim in active
        if claim.claim_status == "unverified"
        or claim.verification_policy_version != CLAIM_VERIFICATION_POLICY_VERSION
    )
    shown_claims = active or relevant
    claim_ids = tuple(sorted((claim.id for claim in shown_claims), key=str))
    evidence_ids = tuple(sorted({ref.evidence_id for claim in shown_claims for ref in claim.evidence_refs}, key=str))
    if verified:
        keys = {_value_key(claim.typed_value) for claim in verified}
        if None in keys or len(keys) > 1:
            status, reason = "conflicting", "fresh_claim_conflict"
        elif unverified and any(
            values_equal(unverified_claim.typed_value, verified[0].typed_value) is not True
            for unverified_claim in unverified
        ):
            status, reason = "conflicting", "verified_unverified_disagreement"
        else:
            status, reason = "verified", "fresh_attributed_claim"
    elif unverified:
        status, reason = "unverified", "source_value_not_validated"
    elif relevant:
        status, reason = "stale", "all_claims_expired_or_retracted"
    else:
        status, reason = "missing", "no_claim"
    return AttributeStatus(
        attribute=attribute, scope=scope, status=status, claim_ids=claim_ids,
        evidence_ids=evidence_ids, reason=reason,
    )


def attribute_status_for_claims(
    attribute: str,
    scope: str | None,
    claims: tuple[EntityClaim, ...],
    now: datetime,
) -> AttributeStatus:
    """Return the shared freshness/conflict status used by constraints and features."""
    return _status(attribute, scope, claims, now)


def verified_claims_for_feature(
    claims: tuple[EntityClaim, ...],
    attribute: str,
    now: datetime,
    *,
    evaluation=None,
    scope: str | None = None,
) -> tuple[AttributeStatus, tuple[EntityClaim, ...]]:
    """Select only claims admitted by the shared status policy for one feature.

    An omitted scope is inferred only when the candidate has one scope for the
    attribute. Multiple scopes are incomparable for a domain feature and are
    therefore omitted even if their values happen to match.
    """
    matching = tuple(item for item in claims if item.attribute == attribute)
    scopes = {item.scope for item in matching}
    if scope is None:
        if len(scopes) > 1:
            return attribute_status_for_claims(attribute, None, matching, now), ()
        scope = next(iter(scopes)) if scopes else None

    statuses = getattr(evaluation, "attribute_statuses", ()) if evaluation is not None else ()
    status = next(
        (
            item for item in statuses
            if item.attribute == attribute and item.scope == scope
        ),
        None,
    )
    if status is None:
        status = attribute_status_for_claims(attribute, scope, matching, now)
    if status.status != "verified":
        return status, ()

    selected = tuple(sorted(
        (
            item for item in matching
            if item.scope == scope
            and item.id in status.claim_ids
            and item.claim_status == "verified"
            and item.verification_policy_version == CLAIM_VERIFICATION_POLICY_VERSION
            and item.expires_at > now
        ),
        key=lambda item: str(item.id),
    ))
    return status, selected


def _numeric(value: TypedValue) -> tuple[Decimal, str] | None:
    if isinstance(value, NumberValue):
        return value.value, "number"
    if isinstance(value, MoneyValue):
        return value.amount, f"currency:{value.currency}"
    if isinstance(value, QuantityValue):
        unit = _UNITS.get(value.unit.casefold())
        if unit is None:
            return None
        dimension, factor = unit
        return value.amount * factor, f"unit:{dimension}"
    return None


def _distance_km(left: LocationValue, right: LocationValue) -> float:
    lat1, lat2 = radians(left.latitude), radians(right.latitude)
    d_lat = lat2 - lat1
    d_lon = radians(right.longitude - left.longitude)
    value = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    return 6371.0088 * 2 * asin(sqrt(value))


def _matches(actual: TypedValue, constraint: Constraint) -> tuple[bool | None, str]:
    op = constraint.operator
    expected = constraint.value
    if op in {"maximum", "minimum", "range"}:
        if isinstance(actual, DateValue) and isinstance(expected, DateValue):
            if op == "maximum":
                passed = actual.value <= expected.value
                return passed, "within_maximum" if passed else "over_maximum"
            if op == "minimum":
                passed = actual.value >= expected.value
                return passed, "within_minimum" if passed else "under_minimum"
            upper = constraint.upper_value
            if not isinstance(upper, DateValue):
                return None, "incompatible_range_units"
            passed = expected.value <= actual.value <= upper.value
            return passed, "inside_range" if passed else "outside_range"
        actual_numeric = _numeric(actual)
        expected_numeric = _numeric(expected) if expected is not None else None
        if actual_numeric is None or expected_numeric is None:
            return None, "unsupported_unit_or_currency"
        if actual_numeric[1] != expected_numeric[1]:
            return None, "incompatible_unit_or_currency"
        actual_number = actual_numeric[0]
        if op == "maximum":
            return actual_number <= expected_numeric[0], "within_maximum" if actual_number <= expected_numeric[0] else "over_maximum"
        if op == "minimum":
            return actual_number >= expected_numeric[0], "within_minimum" if actual_number >= expected_numeric[0] else "under_minimum"
        upper = _numeric(constraint.upper_value) if constraint.upper_value else None
        if upper is None or upper[1] != expected_numeric[1]:
            return None, "incompatible_range_units"
        passed = expected_numeric[0] <= actual_number <= upper[0]
        return passed, "inside_range" if passed else "outside_range"
    if op == "exact":
        same = values_equal(actual, expected)
        return same, "exact_match" if same is True else "value_mismatch" if same is False else "incompatible_value"
    if op == "set":
        results = [values_equal(actual, allowed) for allowed in constraint.allowed_values]
        if any(result is True for result in results):
            return True, "set_match"
        if all(result is False for result in results):
            return False, "not_in_set"
        return None, "incompatible_set_value"
    if op == "geospatial":
        if not isinstance(actual, LocationValue) or not isinstance(expected, LocationValue):
            return None, "location_unknown"
        distance = _distance_km(actual, expected)
        passed = distance <= (constraint.radius_km or 0)
        return passed, "inside_radius" if passed else "outside_radius"
    if op == "date_window":
        if not isinstance(actual, DateWindowValue) or not isinstance(expected, DateWindowValue):
            return None, "date_window_unknown"
        passed = actual.start <= expected.start and actual.end >= expected.end
        return passed, "covers_date_window" if passed else "does_not_cover_date_window"
    if op == "availability":
        if not isinstance(actual, AvailabilityValue) or not isinstance(expected, AvailabilityValue):
            return None, "availability_unknown"
        passed = actual.value == expected.value and actual.value != "unknown"
        return passed, "availability_matches" if passed else "availability_mismatch"
    return None, "unsupported_constraint"


def evaluate_candidates(
    *,
    decision_id: UUID,
    entities: tuple[CanonicalEntity, ...],
    claims_by_entity: dict[UUID, tuple[EntityClaim, ...]],
    constraints: tuple[Constraint, ...],
    preferences: tuple[Preference, ...],
    now: datetime,
    preference_weight: float,
    score_enabled: bool = True,
    identity_matches=(),
):
    """Filter first, then score only eligible candidates with a stable tie-break."""
    from personal_ai.decisions.contracts import CandidateEvaluation

    draft = []
    unknown_required = False
    identity_by_entity: dict[UUID, list[EntityMatch]] = {}
    for match in identity_matches:
        identity_by_entity.setdefault(match.candidate_entity_id, []).append(match)
    for entity in entities:
        claims = claims_by_entity.get(entity.id, ())
        relevant = {(item.attribute, item.scope) for item in constraints} | {
            (item.attribute, item.scope) for item in preferences
        }
        statuses = tuple(
            _status(attribute, scope, claims, now)
            for attribute, scope in sorted(relevant, key=lambda item: (item[0], item[1] or ""))
        )
        status_lookup = {(item.attribute, item.scope): item for item in statuses}
        outcomes: list[ConstraintOutcome] = []
        exclusions: list[str] = []
        candidate_matches = identity_by_entity.get(entity.id, [])
        identity_outcome = (
            "review" if any(match.outcome == "review" for match in candidate_matches)
            else "matched" if any(match.outcome == "matched" for match in candidate_matches)
            else "no_match"
        )
        identity_confidence = max((match.confidence for match in candidate_matches), default=0.0)
        identity_candidate_ids = tuple(sorted({
            candidate_id for match in candidate_matches for candidate_id in match.candidate_entity_ids
        }, key=str))
        if identity_outcome == "review":
            exclusions.append("identity_ambiguous")
            unknown_required = True
        elif any(
            match.feature_values.get("identity_evidence_missing")
            for match in candidate_matches
        ):
            exclusions.append("identity_evidence_missing")
            unknown_required = True
        verified_claims = tuple(
            claim for claim in claims
            if claim.claim_status == "verified"
            and claim.verification_policy_version == CLAIM_VERIFICATION_POLICY_VERSION
            and claim.expires_at > now
        )
        if not verified_claims:
            exclusions.append("candidate_no_current_evidence")
            unknown_required = True
        for constraint in constraints:
            status = status_lookup[(constraint.attribute, constraint.scope)]
            if status.status != "verified":
                outcome = "unknown"
                reason = status.status
                if constraint.required or constraint.missing_policy == "fail_closed":
                    exclusions.append(f"required_{constraint.attribute}_{status.status}")
                    unknown_required = True
            else:
                claim = next(
                    candidate_claim for candidate_claim in claims
                    if candidate_claim.id in status.claim_ids
                    and candidate_claim.claim_status == "verified"
                    and candidate_claim.verification_policy_version == CLAIM_VERIFICATION_POLICY_VERSION
                    and candidate_claim.expires_at > now
                )
                passed, reason = _matches(claim.typed_value, constraint)
                if passed is None:
                    outcome = "unknown"
                    if constraint.required:
                        exclusions.append(f"required_{constraint.attribute}_{reason}")
                        unknown_required = True
                elif passed:
                    outcome = "pass"
                else:
                    outcome = "fail"
                    if constraint.required:
                        exclusions.append(f"constraint_{constraint.attribute}_{reason}")
            outcomes.append(ConstraintOutcome(
                constraint_id=constraint.id, attribute=constraint.attribute,
                outcome=outcome, reason=reason, claim_ids=status.claim_ids,
                evidence_ids=status.evidence_ids,
            ))
        draft.append({
            "entity": entity,
            "identity_outcome": identity_outcome,
            "identity_confidence": identity_confidence,
            "identity_candidate_ids": identity_candidate_ids,
            "claims": claims,
            "statuses": statuses,
            "outcomes": tuple(outcomes),
            "exclusions": tuple(sorted(set(exclusions))),
            "eligible": not exclusions,
        })

    eligible = [item for item in draft if item["eligible"]]
    if score_enabled:
        for item in eligible:
            feature_values = []
            weighted_total = 0.0
            weight_total = 0.0
            status_lookup = {(status.attribute, status.scope): status for status in item["statuses"]}
            for preference in preferences:
                status = status_lookup.get((preference.attribute, preference.scope))
                if status is None or status.status != "verified":
                    value = None
                    evidence_ids = status.evidence_ids if status else ()
                    treatment = "omit"
                else:
                    claim = next(
                        candidate_claim for candidate_claim in item["claims"]
                        if candidate_claim.id in status.claim_ids
                        and candidate_claim.claim_status == "verified"
                        and candidate_claim.verification_policy_version == CLAIM_VERIFICATION_POLICY_VERSION
                        and candidate_claim.expires_at > now
                    )
                    match = values_equal(claim.typed_value, preference.target)
                    value = float(match) if match is not None else None
                    evidence_ids = status.evidence_ids
                    treatment = "omit" if match is None else "zero"
                feature_weight = preference.weight * preference_weight
                feature_values.append(FeatureScore(
                    name=f"preference:{preference.attribute}", value=value,
                    weight=feature_weight, evidence_ids=evidence_ids,
                    missing_treatment=treatment,
                ))
                if value is not None and feature_weight > 0:
                    weighted_total += value * feature_weight
                    weight_total += feature_weight
            item["features"] = tuple(feature_values)
            item["score"] = (weighted_total / weight_total) if weight_total else 0.0
    else:
        for item in eligible:
            item["features"] = ()
            item["score"] = None

    if score_enabled:
        eligible.sort(key=lambda item: (
            -(item["score"] or 0), normalize_name(item["entity"].canonical_name), str(item["entity"].id)
        ))
    else:
        eligible.sort(key=lambda item: (normalize_name(item["entity"].canonical_name), str(item["entity"].id)))

    ranks = (
        {item["entity"].id: index + 1 for index, item in enumerate(eligible)}
        if score_enabled
        else {}
    )
    results = tuple(
        CandidateEvaluation(
            id=uuid5(decision_id, f"candidate-evaluation:{item['entity'].id}"),
            decision_id=decision_id,
            entity_id=item["entity"].id,
            identity_outcome=item["identity_outcome"],
            identity_confidence=item["identity_confidence"],
            identity_candidate_entity_ids=item["identity_candidate_ids"],
            claim_ids=tuple(sorted((claim.id for claim in item["claims"]), key=str)),
            eligibility=item["eligible"],
            attribute_statuses=item["statuses"],
            constraint_outcomes=item["outcomes"],
            feature_values=item.get("features", ()),
            score=item.get("score"),
            rank=ranks.get(item["entity"].id),
            exclusion_reasons=item["exclusions"],
        )
        for item in draft
    )
    has_unknown = any(
        not item["eligible"] and any(outcome.outcome == "unknown" for outcome in item["outcomes"])
        for item in draft
    )
    if eligible:
        state = "recommended" if score_enabled else "eligible_unranked"
        selected = eligible[0]["entity"].id if score_enabled else None
    elif has_unknown or unknown_required:
        state, selected = "research_needed", None
    else:
        state, selected = "no_verified_match", None
    return results, state, selected
