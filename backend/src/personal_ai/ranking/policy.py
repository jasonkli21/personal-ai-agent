"""Deterministic freshness, hard-constraint, and explainable ranking policies."""

import unicodedata
from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt
from uuid import UUID, uuid5

from personal_ai.decisions.contracts import (
    AttributeStatus,
    CandidateProposal,
    Constraint,
    ConstraintOutcome,
    FeatureScore,
    Preference,
)
from personal_ai.entities.research import (
    AvailabilityValue,
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

RESOLUTION_POLICY_VERSION = "resolve-v1"
CONSTRAINT_POLICY_VERSION = "constraint-v1"
RANKING_POLICY_VERSION = "rank-v1"

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
    return bool(needle) and needle in normalize(passage)


def _claim_value_match(left: EntityClaim, right: EntityClaim) -> bool:
    result = values_equal(left.typed_value, right.typed_value)
    return result is True and left.scope == right.scope


def resolve_candidate(
    *,
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
    exact: list[tuple[CanonicalEntity, str]] = []
    for entity in available:
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
            id=match_id, subject_id=subject_id, owner_id=owner_id,
            candidate_entity_ids=(entity.id,), selected_entity_id=entity.id,
            outcome="matched", confidence=1.0, feature_values={feature: 1.0},
            evidence_ids=tuple(ref.evidence_id for ref in evidence_refs), created_at=now,
        )
        return match, entity.id
    if len(exact) > 1:
        ids = tuple(sorted((entity.id for entity, _ in exact), key=str))
        return EntityMatch(
            id=match_id, subject_id=subject_id, owner_id=owner_id,
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
        if claim.claim_status == "verified" and claim.expires_at > now
    )
    scored: list[tuple[float, CanonicalEntity, dict[str, float]]] = []
    for entity in available:
        name_candidates = [normalize_name(entity.canonical_name)]
        if entity.id in alias_by_entity:
            name_candidates.append(normalize_name(alias_by_entity[entity.id]))
        similarity = max(
            (SequenceMatcher(None, proposed_name, name).ratio() for name in name_candidates),
            default=0.0,
        )
        stored_claims = tuple(
            claim for claim in claims_by_entity.get(entity.id, ())
            if claim.owner_id == owner_id and claim.claim_status == "verified" and claim.expires_at > now
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
        if score >= 0.4:
            scored.append((score, entity, features))

    scored.sort(key=lambda item: (-item[0], str(item[1].id)))
    if scored and scored[0][0] >= threshold and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        score, entity, features = scored[0]
        if features.get("independent_attribute_match"):
            match = EntityMatch(
                id=match_id, subject_id=subject_id, owner_id=owner_id,
                candidate_entity_ids=(entity.id,), selected_entity_id=entity.id,
                outcome="matched", confidence=score, feature_values=features,
                evidence_ids=tuple(ref.evidence_id for ref in evidence_refs), created_at=now,
            )
            return match, entity.id

    if scored:
        top = scored[: min(20, len(scored))]
        best = top[0][0]
        ambiguous = len(top) > 1 and top[1][0] == best
        return EntityMatch(
            id=match_id, subject_id=subject_id, owner_id=owner_id,
            candidate_entity_ids=tuple(item[1].id for item in top), outcome="review",
            confidence=best,
            feature_values={
                f"candidate_{index}_{key}": value
                for index, (_, _, features) in enumerate(top)
                for key, value in features.items()
            } | ({"ambiguous_tie": 1.0} if ambiguous else {}),
            evidence_ids=tuple(ref.evidence_id for ref in evidence_refs), created_at=now,
        ), new_entity_id

    return EntityMatch(
        id=match_id, subject_id=subject_id, owner_id=owner_id,
        candidate_entity_ids=(), outcome="no_match", confidence=0.0,
        feature_values={}, evidence_ids=tuple(ref.evidence_id for ref in evidence_refs), created_at=now,
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
    verified = tuple(claim for claim in active if claim.claim_status == "verified")
    unverified = tuple(claim for claim in active if claim.claim_status == "unverified")
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
        status, reason = "unverified", "literal_support_not_established"
    elif relevant:
        status, reason = "stale", "all_claims_expired_or_retracted"
    else:
        status, reason = "missing", "no_claim"
    return AttributeStatus(
        attribute=attribute, scope=scope, status=status, claim_ids=claim_ids,
        evidence_ids=evidence_ids, reason=reason,
    )


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
):
    """Filter first, then score only eligible candidates with a stable tie-break."""
    from personal_ai.decisions.contracts import CandidateEvaluation

    draft = []
    unknown_required = False
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
        verified_claims = tuple(
            claim for claim in claims
            if claim.claim_status == "verified" and claim.expires_at > now
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

    ranks = {item["entity"].id: index + 1 for index, item in enumerate(eligible)}
    results = tuple(
        CandidateEvaluation(
            id=uuid5(decision_id, f"candidate-evaluation:{item['entity'].id}"),
            decision_id=decision_id,
            entity_id=item["entity"].id,
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
