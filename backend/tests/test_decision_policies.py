from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai.decisions.contracts import (
    CandidateProposal,
    ClaimProposal,
    Constraint,
    Preference,
    SuppliedEvidence,
)
from personal_ai.entities.research import (
    AvailabilityValue,
    CanonicalEntity,
    DateTimeValue,
    DateWindowValue,
    EntityAlias,
    EntityClaim,
    EvidenceReference,
    LocationValue,
    MoneyValue,
    NumberValue,
    QuantityValue,
    TextValue,
)
from personal_ai.ranking.policy import evaluate_candidates, resolve_candidate
from personal_ai.settings import Settings

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def evidence(*, owner="local", evidence_id=None, observed=NOW, expires=None):
    return EvidenceReference(
        evidence_id=evidence_id or uuid4(), source_observation_id=uuid4(), owner_id=owner,
        research_session_id=None, origin="supplied", url="https://example.org/source",
        title="Synthetic source", observed_at=observed,
        expires_at=expires or observed + timedelta(days=1), expiry_policy="supplied",
        content_fingerprint="a" * 64,
    )


def entity(name="Widget", *, entity_id=None, identifiers=None):
    return CanonicalEntity(
        id=entity_id or uuid4(), entity_type="object", canonical_name=name,
        owner_scope="owner:local", owner_id="local", identifiers=identifiers or {},
        created_at=NOW, updated_at=NOW,
    )


def claim(attribute, value, ref, *, entity_id=None, owner="local", scope=None, verified=True):
    return EntityClaim(
        id=uuid4(), entity_id=entity_id or uuid4(), owner_id=owner, attribute=attribute,
        typed_value=value, original_value="synthetic", unit=None, currency=None,
        evidence_refs=(ref,), evidence_ids=(ref.evidence_id,),
        observed_at=ref.observed_at, expires_at=ref.expires_at,
        claim_status="verified" if verified else "unverified", scope=scope,
    )


def test_resolution_requires_independent_identity_support_and_abstains_on_ambiguity():
    ref = evidence()
    stored = entity("Blue widget", identifiers={"catalog": "abc-1"})
    proposal = CandidateProposal(entity_type="object", canonical_name="Blue widget", identifiers={"catalog": "abc-1"})
    matched, selected = resolve_candidate(
        subject_id=uuid4(), owner_id="local", proposal=proposal, proposed_claims=(),
        evidence_refs=(ref,), entities=(stored,), aliases=(), claims_by_entity={},
        new_entity_id=uuid4(), now=NOW, threshold=0.9, match_id=uuid4(),
    )
    assert matched.outcome == "matched" and selected == stored.id

    near = CandidateProposal(entity_type="object", canonical_name="Blue widget pro")
    review, new_id = resolve_candidate(
        subject_id=uuid4(), owner_id="local", proposal=near, proposed_claims=(),
        evidence_refs=(ref,), entities=(stored,), aliases=(), claims_by_entity={},
        new_entity_id=uuid4(), now=NOW, threshold=0.9, match_id=uuid4(),
    )
    assert review.outcome == "review" and review.selected_entity_id is None and new_id != stored.id

    duplicate = entity("Different label", identifiers={"catalog": "abc-1"})
    ambiguous, _ = resolve_candidate(
        subject_id=uuid4(), owner_id="local", proposal=proposal, proposed_claims=(),
        evidence_refs=(ref,), entities=(stored, duplicate), aliases=(), claims_by_entity={},
        new_entity_id=uuid4(), now=NOW, threshold=0.9, match_id=uuid4(),
    )
    assert ambiguous.outcome == "review" and ambiguous.selected_entity_id is None


def test_alias_and_fresh_independent_claim_can_resolve_but_stale_claim_cannot():
    ref = evidence()
    stored = entity("Widget", identifiers={"catalog": "old"})
    old_claim = claim("color", TextValue(value="blue"), ref, entity_id=stored.id)
    proposal = CandidateProposal(
        entity_type="object", canonical_name="Widget",
        claims=(ClaimProposal(
            attribute="color", typed_value=TextValue(value="blue"), original_value="blue",
            evidence_ids=(ref.evidence_id,),
        ),),
    )
    new_claim = claim("color", TextValue(value="blue"), ref, entity_id=uuid4())
    alias = EntityAlias(
        id=uuid4(), entity_id=stored.id, owner_id="local", normalized_alias="widget",
        created_at=NOW,
    )
    matched, selected = resolve_candidate(
        subject_id=uuid4(), owner_id="local", proposal=proposal, proposed_claims=(new_claim,),
        evidence_refs=(ref,), entities=(stored,), aliases=(alias,),
        claims_by_entity={stored.id: (old_claim,)}, new_entity_id=uuid4(), now=NOW,
        threshold=0.9, match_id=uuid4(),
    )
    assert matched.outcome == "matched" and selected == stored.id

    stale_ref = evidence(observed=NOW - timedelta(days=4), expires=NOW - timedelta(days=1))
    stale_claim = claim("color", TextValue(value="blue"), stale_ref, entity_id=stored.id)
    abstained, selected = resolve_candidate(
        subject_id=uuid4(), owner_id="local", proposal=proposal, proposed_claims=(new_claim,),
        evidence_refs=(ref,), entities=(stored,), aliases=(alias,),
        claims_by_entity={stored.id: (stale_claim,)}, new_entity_id=uuid4(), now=NOW,
        threshold=0.9, match_id=uuid4(),
    )
    assert abstained.outcome == "review" and selected != stored.id


@pytest.mark.parametrize(
    ("attribute", "actual", "operator", "value", "upper", "allowed", "radius", "expected"),
    [
        ("price", MoneyValue(amount=Decimal(100), currency="USD"), "maximum", MoneyValue(amount=Decimal(100), currency="USD"), None, (), None, "pass"),
        ("size", QuantityValue(amount=Decimal(90), unit="cm"), "range", QuantityValue(amount=Decimal("0.8"), unit="m"), QuantityValue(amount=Decimal(1), unit="m"), (), None, "pass"),
        ("weight", QuantityValue(amount=Decimal(4), unit="kg"), "minimum", QuantityValue(amount=Decimal(8), unit="lb"), None, (), None, "pass"),
        ("currency", MoneyValue(amount=Decimal(90), currency="EUR"), "maximum", MoneyValue(amount=Decimal(100), currency="USD"), None, (), None, "unknown"),
        ("availability", AvailabilityValue(value="available"), "availability", AvailabilityValue(value="available"), None, (), None, "pass"),
        ("location", LocationValue(latitude=37.77, longitude=-122.42), "geospatial", LocationValue(latitude=37.78, longitude=-122.42), None, (), 2, "pass"),
        ("dates", DateWindowValue(start=date(2026, 10, 1), end=date(2026, 10, 8)), "date_window", DateWindowValue(start=date(2026, 10, 3), end=date(2026, 10, 6)), None, (), None, "pass"),
        ("color", TextValue(value="blue"), "set", None, None, (TextValue(value="red"), TextValue(value="blue")), None, "pass"),
        ("year", NumberValue(value=Decimal(2026)), "exact", NumberValue(value=Decimal(2026)), None, (), None, "pass"),
    ],
)
def test_typed_constraint_operators(attribute, actual, operator, value, upper, allowed, radius, expected):
    ref = evidence()
    candidate = entity(identifiers={"catalog": attribute})
    source_claim = claim(attribute, actual, ref, entity_id=candidate.id)
    fields = {
        "id": uuid4(), "attribute": attribute, "operator": operator, "value": value,
        "upper_value": upper, "allowed_values": allowed, "radius_km": radius,
    }
    constraint = Constraint(**{key: val for key, val in fields.items() if val is not None})
    results, state, _ = evaluate_candidates(
        decision_id=uuid4(), entities=(candidate,), claims_by_entity={candidate.id: (source_claim,)},
        constraints=(constraint,), preferences=(), now=NOW, preference_weight=1,
    )
    outcome = results[0].constraint_outcomes[0].outcome
    assert outcome == expected
    assert (state == "recommended") == (expected == "pass")


def test_attribute_freshness_conflict_and_missing_fail_closed():
    candidate = entity()
    fresh_a, fresh_b = evidence(), evidence()
    price_a = claim("price", MoneyValue(amount=Decimal(10), currency="USD"), fresh_a, entity_id=candidate.id)
    price_b = claim("price", MoneyValue(amount=Decimal(12), currency="USD"), fresh_b, entity_id=candidate.id)
    required = Constraint(
        id=uuid4(), attribute="price", operator="maximum",
        value=MoneyValue(amount=Decimal(20), currency="USD"),
    )
    results, state, selected = evaluate_candidates(
        decision_id=uuid4(), entities=(candidate,), claims_by_entity={candidate.id: (price_a, price_b)},
        constraints=(required,), preferences=(), now=NOW, preference_weight=1,
    )
    assert results[0].attribute_statuses[0].status == "conflicting"
    assert results[0].eligibility is False and state == "research_needed" and selected is None

    stale = claim(
        "price", MoneyValue(amount=Decimal(10), currency="USD"),
        evidence(observed=NOW - timedelta(days=4), expires=NOW - timedelta(days=1)),
        entity_id=candidate.id,
    )
    results, state, _ = evaluate_candidates(
        decision_id=uuid4(), entities=(candidate,), claims_by_entity={candidate.id: (stale,)},
        constraints=(required,), preferences=(), now=NOW, preference_weight=1,
    )
    assert results[0].attribute_statuses[0].status == "stale" and state == "research_needed"

    results, state, _ = evaluate_candidates(
        decision_id=uuid4(), entities=(candidate,), claims_by_entity={candidate.id: ()},
        constraints=(required,), preferences=(), now=NOW, preference_weight=1,
    )
    assert results[0].attribute_statuses[0].status == "missing" and state == "research_needed"


def test_preference_ranks_only_eligible_and_ties_are_stable():
    ref = evidence()
    first, second = entity("Beta", identifiers={"catalog": "b"}), entity("Alpha", identifiers={"catalog": "a"})
    first_claim = claim("color", TextValue(value="blue"), ref, entity_id=first.id)
    second_claim = claim("color", TextValue(value="red"), ref, entity_id=second.id)
    budget = Constraint(
        id=uuid4(), attribute="price", operator="maximum",
        value=MoneyValue(amount=Decimal(50), currency="USD"),
    )
    first_price = claim("price", MoneyValue(amount=Decimal(80), currency="USD"), ref, entity_id=first.id)
    second_price = claim("price", MoneyValue(amount=Decimal(40), currency="USD"), ref, entity_id=second.id)
    preference = Preference(attribute="color", target=TextValue(value="blue"))
    evaluations, state, selected = evaluate_candidates(
        decision_id=uuid4(), entities=(first, second),
        claims_by_entity={first.id: (first_claim, first_price), second.id: (second_claim, second_price)},
        constraints=(budget,), preferences=(preference,), now=NOW, preference_weight=1,
    )
    by_id = {result.entity_id: result for result in evaluations}
    assert by_id[first.id].eligibility is False and by_id[first.id].rank is None
    assert by_id[second.id].eligibility is True and by_id[second.id].rank == 1
    assert state == "recommended" and selected == second.id

    tied, _, top = evaluate_candidates(
        decision_id=uuid4(), entities=(first, second),
        claims_by_entity={first.id: (first_claim,), second.id: (second_claim,)},
        constraints=(), preferences=(), now=NOW, preference_weight=1,
    )
    assert top == second.id  # Stable name order breaks equal score.
    assert {item.score for item in tied} == {0.0}


def test_timestamps_must_be_aware_and_required_constraints_fail_closed():
    with pytest.raises(ValidationError):
        DateTimeValue(value="2026-10-02T00:00:00")
    with pytest.raises(ValidationError):
        Constraint(
            id=uuid4(), attribute="availability", operator="availability",
            value=AvailabilityValue(value="available"), missing_policy="allow_unknown",
        )


def test_policy_settings_are_versioned_bounded_and_disabled_by_default():
    base = {"_env_file": None, "ai_provider": "gemini", "ai_model": "synthetic"}
    settings = Settings(**base)
    assert not settings.decision_enabled and not settings.decision_inspection_enabled
    assert settings.entity_resolution_policy_version == "resolve-v1"
    with pytest.raises(ValidationError):
        Settings(**base, entity_resolution_policy_version="resolve-v2")
    with pytest.raises(ValidationError):
        Settings(**base, decision_max_candidates=13, decision_max_comparison_rows=12)


def test_direct_evidence_requires_a_matching_bounded_excerpt_fingerprint():
    passage = "A synthetic source says blue."
    values = {
        "evidence_id": uuid4(), "source_observation_id": uuid4(), "owner_id": "local",
        "url": "https://example.org/source", "observed_at": NOW,
        "expires_at": NOW + timedelta(hours=1), "content_fingerprint": sha256(passage.encode()).hexdigest(),
        "passage": passage,
    }
    direct = SuppliedEvidence(**values)
    assert direct.reference().origin == "supplied"
    with pytest.raises(ValidationError):
        SuppliedEvidence(**{**values, "content_fingerprint": "b" * 64})
