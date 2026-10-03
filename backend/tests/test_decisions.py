import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from personal_ai.decisions.contracts import (
    Candidate,
    ClaimProposal,
    Constraint,
    DecisionCreateRequest,
    DecisionResult,
    Preference,
    SuppliedEvidence,
)
from personal_ai.decisions.repositories import DecisionError, InMemoryDecisionRepository
from personal_ai.decisions.service import DecisionService
from personal_ai.entities.research import CanonicalEntity, MoneyValue, TextValue
from personal_ai.main import app
from personal_ai.settings import Settings, get_settings
from personal_ai.storage.errors import ResourceNotFoundError

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def settings(**overrides):
    values = {
        "_env_file": None,
        "ai_provider": "gemini",
        "ai_model": "synthetic",
        "decision_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def evidence(passage: str, *, evidence_id=None, observed_at=NOW, expires_at=None):
    passage = re.sub(r"\$(\d[\d,]*(?:\.\d+)?)\b(?!\s+USD)", r"$\1 USD", passage)
    return SuppliedEvidence(
        evidence_id=evidence_id or uuid4(),
        source_observation_id=uuid4(),
        owner_id="local",
        url=f"https://example.org/source/{uuid4()}",
        title="Synthetic source",
        observed_at=observed_at,
        expires_at=expires_at or observed_at + timedelta(days=1),
        content_fingerprint=sha256(" ".join(passage.split()).encode()).hexdigest(),
        passage=passage,
    )


def candidate(name, sku, amount, color, evidence_item):
    return Candidate(
        entity_type="object",
        canonical_name=name,
        identifiers={"catalog": sku},
        claims=(
            ClaimProposal(
                attribute="price",
                typed_value=MoneyValue(amount=Decimal(amount), currency="USD"),
                original_value=f"${amount} USD",
                currency="USD",
                evidence_ids=(evidence_item.evidence_id,),
            ),
            ClaimProposal(
                attribute="color",
                typed_value=TextValue(value=color),
                original_value=color,
                evidence_ids=(evidence_item.evidence_id,),
            ),
        ),
    )


def budget(value="50"):
    return Constraint(
        id=uuid4(),
        attribute="price",
        operator="maximum",
        value=MoneyValue(amount=Decimal(value), currency="USD"),
        source="user",
    )


def make_service(repository=None, *, clock=lambda: NOW, ranker=None, **setting_overrides):
    return DecisionService(
        settings(**setting_overrides),
        repository or InMemoryDecisionRepository(),
        clock=clock,
        **({} if ranker is None else {"ranker": ranker}),
    )


def test_identifiers_from_another_subject_do_not_merge_canonical_entities():
    repository = InMemoryDecisionRepository()
    service = make_service(repository)
    first_source = evidence("Other Widget catalog OTHER-1 costs $40. Its color is blue.")
    first = service.create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("Other Widget", "OTHER-1", "40", "blue", first_source),),
        supplied_evidence=(first_source,),
    ))
    next_source = evidence("New Widget costs $40. Its color is blue. Other Widget catalog OTHER-1 costs $80.")
    result = service.create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("New Widget", "OTHER-1", "40", "blue", next_source),),
        supplied_evidence=(next_source,),
    ))
    assert result.entities[0].id != first.entities[0].id
    assert result.entities[0].identifiers == {}


def test_direct_evidence_decision_filters_before_preference_ranking_and_inspects():
    repository = InMemoryDecisionRepository()
    service = make_service(repository, decision_inspection_enabled=True)
    blue_source = evidence("Blue Widget catalog SKU-1 costs $80. Its color is blue.")
    red_source = evidence("Red Widget catalog SKU-2 costs $40. Its color is red.")
    request = DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(
            candidate("Blue Widget", "SKU-1", "80", "blue", blue_source),
            candidate("Red Widget", "SKU-2", "40", "red", red_source),
        ),
        constraints=(budget(),),
        preferences=(
            {"attribute": "color", "target": {"kind": "text", "value": "blue"}},
        ),
        supplied_evidence=(blue_source, red_source),
    )

    result = service.create(request)
    selected = next(entity for entity in result.entities if entity.id == result.decision.selected_entity_id)
    evaluations = {item.entity_id: item for item in result.evaluations}
    by_name = {entity.canonical_name: evaluations[entity.id] for entity in result.entities}
    assert result.decision.state == "recommended"
    assert selected.canonical_name == "Red Widget"
    assert by_name["Blue Widget"].eligibility is False
    assert "constraint_price_over_maximum" in by_name["Blue Widget"].exclusion_reasons
    assert by_name["Red Widget"].eligibility is True
    assert by_name["Red Widget"].feature_values[0].value == 0
    assert result.recommendation.evidence_ids == (red_source.evidence_id,)
    assert {ref.url for ref in result.evidence_snapshot.evidence_refs} == {
        blue_source.url, red_source.url,
    }
    assert "Blue Widget catalog SKU-1 costs $80" not in result.model_dump_json()

    inspection = service.inspect(result.decision.id)
    assert len(inspection.selected) == 1 and len(inspection.excluded) == 1
    assert inspection.policy_versions.constraints == "constraint-v1"
    assert len(inspection.evidence_refs) == 2
    service.owner_id = "other"
    with pytest.raises(ResourceNotFoundError):
        service.detail(result.decision.id)


def test_source_literal_must_agree_with_typed_value_before_hard_constraint_use():
    source = evidence("Actual Widget costs $40 USD.")
    candidate_with_value = Candidate(
        entity_type="object",
        canonical_name="Actual Widget",
        claims=(ClaimProposal(
            attribute="price",
            typed_value=MoneyValue(amount=Decimal(400), currency="USD"),
            original_value="$40 USD",
            currency="USD",
            evidence_ids=(source.evidence_id,),
        ),),
    )
    result = make_service().create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate_with_value,),
        constraints=(budget("50"),),
        supplied_evidence=(source,),
    ))

    assert result.claims[0].claim_status == "unverified"
    assert result.evaluations[0].attribute_statuses[0].status == "unverified"
    assert result.evaluations[0].constraint_outcomes[0].outcome == "unknown"

    matching_source = evidence("Actual Widget costs $40 USD.")
    matching = candidate_with_value.model_copy(update={
        "claims": (candidate_with_value.claims[0].model_copy(update={
            "typed_value": MoneyValue(amount=Decimal(40), currency="USD"),
            "evidence_ids": (matching_source.evidence_id,),
        }),),
    })
    verified = make_service().create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(matching,),
        constraints=(budget("50"),),
        supplied_evidence=(matching_source,),
    ))
    assert verified.claims[0].claim_status == "verified"
    assert verified.evaluations[0].constraint_outcomes[0].outcome == "pass"


@pytest.mark.parametrize(
    ("subject", "passage", "original", "amount"),
    [
        ("Expensive Widget", "Expensive Widget costs $900 USD. Cheap Widget costs $10 USD.", "$10 USD", "10"),
        ("Expensive Widget", "Expensive Widget costs $900 USD while Cheap Widget costs $10 USD.", "$10 USD", "10"),
        ("Widget", "Widget price is $900 USD; shipping is $10 USD.", "$10 USD", "10"),
        ("Widget", "Widget price is $900 USD, shipping is $10 USD.", "$10 USD", "10"),
        ("Widget", "Widget costs $10 USD, excluding a required $900 USD fee.", "$10 USD", "10"),
        ("Widget", "Widget costs $10 USD if a discount applies.", "$10 USD", "10"),
    ],
)
def test_claim_value_must_be_bound_to_the_candidate_and_attribute(subject, passage, original, amount):
    source = evidence(passage)
    claim = ClaimProposal(
        attribute="price", typed_value=MoneyValue(amount=Decimal(amount), currency="USD"),
        original_value=original, currency="USD", evidence_ids=(source.evidence_id,),
    )
    result = make_service().create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(Candidate(entity_type="object", canonical_name=subject, claims=(claim,)),),
        constraints=(budget("50"),), supplied_evidence=(source,),
    ))
    assert result.claims[0].claim_status == "unverified"
    assert result.evaluations[0].eligibility is False
    assert result.decision.state == "research_needed"


def test_negated_availability_is_not_verified_as_available():
    source = evidence("Widget is not available.")
    result = make_service().create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(Candidate(entity_type="object", canonical_name="Widget", claims=(
            ClaimProposal(
                attribute="availability", typed_value={"kind": "availability", "value": "available"},
                original_value="available", evidence_ids=(source.evidence_id,),
            ),
        )),),
        constraints=(Constraint(
            id=uuid4(), attribute="availability", operator="availability",
            value={"kind": "availability", "value": "available"},
        ),),
        supplied_evidence=(source,),
    ))
    assert result.claims[0].claim_status == "unverified"
    assert result.evaluations[0].eligibility is False


def test_unsupported_candidate_identity_is_excluded_from_recommendations():
    source = evidence("A different product costs $10 USD.")
    result = make_service().create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(Candidate(entity_type="object", canonical_name="Invented Widget", claims=(
            ClaimProposal(
                attribute="price", typed_value=MoneyValue(amount=Decimal(10), currency="USD"),
                original_value="$10 USD", currency="USD", evidence_ids=(source.evidence_id,),
            ),
        )),),
        constraints=(budget("50"),), supplied_evidence=(source,),
    ))
    assert result.matches[0].feature_values["identity_evidence_missing"] == 1
    assert result.evaluations[0].eligibility is False
    assert "identity_evidence_missing" in result.evaluations[0].exclusion_reasons
    assert result.decision.state == "research_needed"


def test_conflicting_stable_identifiers_prevent_fuzzy_entity_merge():
    repository = InMemoryDecisionRepository()
    service = make_service(repository)
    first_source = evidence("Model X catalog SKU-A costs $40 USD.")
    first = service.create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("Model X", "SKU-A", "40", "black", first_source),),
        supplied_evidence=(first_source,),
    ))
    second_source = evidence("Model Y catalog SKU-B costs $40 USD.")
    second = service.create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("Model Y", "SKU-B", "40", "black", second_source),),
        supplied_evidence=(second_source,),
    ))
    assert first.entities[0].id != second.entities[0].id
    assert second.matches[0].outcome == "no_match"
    assert second.matches[0].feature_values["conflicting_identifier"] == 1
    assert first.decision.state == second.decision.state == "recommended"


def test_replay_survives_lower_candidate_limits_and_new_repository_state():
    repository = InMemoryDecisionRepository()
    sources = (evidence("Alpha Widget costs $10 USD."), evidence("Beta Widget costs $20 USD."))
    request = DecisionCreateRequest(
        idempotency_key=uuid4(), supplied_evidence=sources,
        candidates=tuple(Candidate(
            entity_type="object", canonical_name=name,
            claims=(ClaimProposal(
                attribute="price", typed_value=MoneyValue(amount=amount, currency="USD"),
                original_value=f"${amount} USD", evidence_ids=(source.evidence_id,),
            ),),
        ) for name, amount, source in zip(("Alpha Widget", "Beta Widget"), (10, 20), sources, strict=True)),
    )
    result = make_service(repository).create(request)
    repository.list_entities = lambda *_args, **_kwargs: pytest.fail("replay must not scan entities")
    replay = make_service(repository, decision_max_candidates=1, decision_max_comparison_rows=1)
    assert replay.create(request) == result


def test_idempotency_conflict_and_source_update_keep_old_claims_and_show_conflict():
    repository = InMemoryDecisionRepository()
    service = make_service(repository)
    original = evidence("Blue Widget catalog SKU-1 costs $40.")
    key = uuid4()
    first_request = DecisionCreateRequest(
        idempotency_key=key,
        candidates=(candidate("Blue Widget", "SKU-1", "40", "blue", original),),
        supplied_evidence=(original,),
    )
    first = service.create(first_request)
    assert service.create(first_request) == first
    assert len(repository.claims) == 2
    with pytest.raises(DecisionError, match="idempotency_conflict"):
        service.create(first_request.model_copy(update={
            "preferences": (Preference(attribute="color", target=TextValue(value="blue")),),
        }))

    update_clock = NOW + timedelta(hours=1)
    updated_service = make_service(repository, clock=lambda: update_clock)
    update = evidence(
        "Blue Widget catalog SKU-1 costs $60.",
        observed_at=update_clock,
        expires_at=update_clock + timedelta(days=1),
    )
    changed = updated_service.create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("Blue Widget", "SKU-1", "60", "blue", update),),
        constraints=(budget(),),
        supplied_evidence=(update,),
    ))
    assert len(repository.entities) == 1
    assert len(repository.claims) == 4
    assert changed.decision.state == "research_needed"
    assert changed.evaluations[0].eligibility is False
    assert changed.evaluations[0].attribute_statuses[0].status == "conflicting"


def test_ambiguous_resolution_abstains_and_ranking_failure_keeps_candidates_unranked():
    repository = InMemoryDecisionRepository()
    service = make_service(repository)
    first = evidence("Blue Widget catalog SKU-1 costs $40.")
    seeded = service.create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("Blue Widget", "SKU-1", "40", "blue", first),),
        supplied_evidence=(first,),
    ))
    original_entity = seeded.entities[0]
    duplicate = original_entity.model_copy(update={"id": uuid4(), "canonical_name": "Different widget"})
    repository.entities[duplicate.id] = duplicate
    ambiguous_evidence = evidence("Blue Widget catalog SKU-1 costs $40.")
    ambiguous = service.create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("Blue Widget", "SKU-1", "40", "blue", ambiguous_evidence),),
        supplied_evidence=(ambiguous_evidence,),
    ))
    assert ambiguous.matches[0].outcome == "review"
    assert ambiguous.decision.state == "research_needed"
    assert ambiguous.evaluations[0].eligibility is False
    assert "identity_ambiguous" in ambiguous.evaluations[0].exclusion_reasons

    def failing_ranker(**_):
        raise RuntimeError("synthetic ranker failure")

    unranked_service = make_service(ranker=failing_ranker)
    fresh = evidence("Independent Widget costs $10.")
    unranked = unranked_service.create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(Candidate(
            entity_type="object", canonical_name="Independent Widget",
            claims=(ClaimProposal(
                attribute="price", typed_value=MoneyValue(amount=Decimal(10), currency="USD"),
                original_value="$10 USD", currency="USD", evidence_ids=(fresh.evidence_id,),
            ),),
        ),),
        supplied_evidence=(fresh,),
    ))
    assert unranked.decision.state == "eligible_unranked"
    assert unranked.decision.selected_entity_id is None
    assert unranked.evaluations[0].eligibility is True
    assert unranked.evaluations[0].score is None and unranked.evaluations[0].rank is None


def test_supplied_evidence_owner_and_claim_provenance_are_enforced():
    service = make_service()
    foreign = evidence("Widget catalog SKU-1 costs $40.").model_copy(update={"owner_id": "other"})
    request = DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("Widget", "SKU-1", "40", "blue", foreign),),
        supplied_evidence=(foreign,),
    )
    with pytest.raises(DecisionError, match="decision_evidence_owner_mismatch"):
        service.create(request)

    local = evidence("Widget catalog SKU-1 costs $40.")
    no_evidence = DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("Widget", "SKU-1", "40", "blue", local),),
        supplied_evidence=(local,),
    )
    unlinked = no_evidence.model_copy(update={
        "candidates": (candidate("Widget", "SKU-1", "40", "blue", local).model_copy(update={
            "claims": (ClaimProposal(
                attribute="price", typed_value=MoneyValue(amount=Decimal(40), currency="USD"),
                original_value="$40 USD", currency="USD", evidence_ids=(uuid4(),),
            ),),
        }),),
    })
    with pytest.raises(DecisionError, match="decision_evidence_not_found"):
        service.create(unlinked)


def test_future_observations_cannot_be_treated_as_current_evidence():
    future = evidence(
        "Widget catalog SKU-1 costs $40.",
        observed_at=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(days=1),
    )
    request = DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("Widget", "SKU-1", "40", "blue", future),),
        supplied_evidence=(future,),
    )

    with pytest.raises(DecisionError, match="decision_evidence_from_future"):
        make_service().create(request)


def test_decision_api_is_gated_and_serves_persisted_result():
    from personal_ai.api.decisions import decision_service

    previous = app.dependency_overrides.copy()
    decision = evidence("Small Widget costs $10.")
    service = make_service(decision_inspection_enabled=True)
    request = DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(Candidate(
            entity_type="object", canonical_name="Small Widget",
            claims=(ClaimProposal(
                attribute="price", typed_value=MoneyValue(amount=Decimal(10), currency="USD"),
                original_value="$10 USD", currency="USD", evidence_ids=(decision.evidence_id,),
            ),),
        ),),
        supplied_evidence=(decision,),
    )
    body = request.model_dump(mode="json")
    body["supplied_evidence"] = [
        {**item.model_dump(mode="json"), "passage": item.passage}
        for item in request.supplied_evidence
    ]
    app.dependency_overrides[decision_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: settings(
        decision_enabled=True, decision_inspection_enabled=True
    )
    try:
        client = TestClient(app)
        created = client.post("/v1/decisions", json=body)
        assert created.status_code == 201
        decision_id = created.json()["decision"]["id"]
        assert client.get(f"/v1/decisions/{decision_id}").json()["decision"]["id"] == decision_id
        assert client.get(f"/v1/decisions/{decision_id}/inspection").status_code == 200
        paths = client.get("/openapi.json").json()["paths"]
        assert "/v1/decisions" in paths
        assert "/v1/decisions/{decision_id}/inspection" in paths
    finally:
        app.dependency_overrides = previous

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[decision_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: settings(
        decision_enabled=True, decision_inspection_enabled=False
    )
    try:
        assert TestClient(app).get(f"/v1/decisions/{decision_id}/inspection").status_code == 404
    finally:
        app.dependency_overrides = previous

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: settings(decision_enabled=False)
    try:
        assert TestClient(app).post("/v1/decisions", json=body).status_code == 404
    finally:
        app.dependency_overrides = previous


@pytest.mark.anyio
async def test_phase5_session_supplies_owner_scoped_decision_evidence():
    from personal_ai.evaluation.research import build_fixture, load_fixtures

    fixture = {**load_fixtures()[0], "sources": [{
        "url": "https://example.org/star", "text": "The synthetic star color is blue.",
    }]}
    research, research_request = build_fixture(fixture)
    session = await research.create(research_request)
    claimed = await research.prepare_run(session.id)
    _ = [event async for event in research.stream(claimed)]
    completed = await research.detail(session.id)
    evidence_id = completed.selection.evidence_ids[0]

    service = DecisionService(
        settings(),
        InMemoryDecisionRepository(),
        research_repository=research.repository,
        clock=lambda: NOW,
    )
    request = DecisionCreateRequest(
        idempotency_key=uuid4(),
        research_session_id=completed.id,
        candidates=(Candidate(
            entity_type="other",
            canonical_name="Synthetic Star",
            claims=(ClaimProposal(
                attribute="color",
                typed_value=TextValue(value="blue"),
                original_value="blue",
                evidence_ids=(evidence_id,),
            ),),
        ),),
        constraints=(Constraint(
            id=uuid4(), attribute="color", operator="exact",
            value=TextValue(value="blue"), source="user",
        ),),
    )
    result = service.create(request)

    assert result.decision.research_session_id == completed.id
    assert result.decision.state == "recommended"
    assert result.claims[0].claim_status == "verified"
    assert result.recommendation.evidence_ids == (evidence_id,)
    reference = result.evidence_snapshot.evidence_refs[0]
    assert reference.research_session_id == completed.id
    assert reference.origin == "research_session"
    assert reference.owner_id == completed.owner_id

    class UnavailableResearchRepository:
        def get(self, *_):
            raise AssertionError("idempotent replay must not revisit research evidence")

    replay_service = DecisionService(
        settings(), service.repository,
        research_repository=UnavailableResearchRepository(),
        clock=lambda: NOW + timedelta(days=2),
    )
    assert replay_service.create(request) == result

    foreign_service = DecisionService(
        settings(),
        InMemoryDecisionRepository(),
        research_repository=research.repository,
        owner_id="another-owner",
        clock=lambda: NOW,
    )
    with pytest.raises(ResourceNotFoundError):
        foreign_service.create(DecisionCreateRequest(
            idempotency_key=uuid4(), research_session_id=completed.id,
        ))


def test_entity_scan_limit_abstains_instead_of_resolving_from_a_truncated_set():
    repository = InMemoryDecisionRepository()
    for index in range(101):
        entity_id = uuid4()
        repository.entities[entity_id] = CanonicalEntity(
            id=entity_id,
            entity_type="object",
            canonical_name=f"Existing Widget {index}",
            owner_scope="owner:local",
            owner_id="local",
            created_at=NOW,
            updated_at=NOW,
        )
    source = evidence("Widget catalog SKU-1 costs $40.")
    request = DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(candidate("Widget", "SKU-1", "40", "blue", source),),
        supplied_evidence=(source,),
    )

    with pytest.raises(DecisionError, match="decision_entity_resolution_limit"):
        make_service(repository).create(request)


def test_decision_snapshot_requires_exact_claim_source_references():
    source = evidence("Small Widget costs $10.")
    result = make_service().create(DecisionCreateRequest(
        idempotency_key=uuid4(),
        candidates=(Candidate(
            entity_type="object",
            canonical_name="Small Widget",
            claims=(ClaimProposal(
                attribute="price",
                typed_value=MoneyValue(amount=Decimal(10), currency="USD"),
                original_value="$10 USD",
                evidence_ids=(source.evidence_id,),
            ),),
        ),),
        supplied_evidence=(source,),
    ))
    data = result.model_dump(mode="json")
    data["evidence_snapshot"]["evidence_refs"][0]["source_observation_id"] = str(uuid4())

    with pytest.raises(ValidationError, match="claim provenance is not in the decision snapshot"):
        DecisionResult.model_validate(data)
