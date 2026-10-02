"""Deterministic offline evaluation for evidence-backed decision support."""

import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.decisions.contracts import (
    Candidate,
    ClaimProposal,
    Constraint,
    DecisionCreateRequest,
    Preference,
    SuppliedEvidence,
)
from personal_ai.decisions.repositories import InMemoryDecisionRepository
from personal_ai.decisions.service import DecisionService
from personal_ai.entities.research import (
    AvailabilityValue,
    CanonicalEntity,
    DateWindowValue,
    LocationValue,
    MoneyValue,
    QuantityValue,
    TextValue,
)
from personal_ai.ranking.policy import evaluate_candidates
from personal_ai.settings import Settings

FIXTURE_PATH = Path(__file__).with_name("decision-fixtures.json")
NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def load_fixtures() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())["fixtures"]


def _id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"decision-evaluation-v1:{key}")


def _source(
    key: str,
    passage: str,
    *,
    observed_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> SuppliedEvidence:
    normalized = " ".join(passage.split())
    return SuppliedEvidence(
        evidence_id=_id(f"evidence:{key}"),
        source_observation_id=_id(f"observation:{key}"),
        owner_id="local",
        url=f"https://example.org/decision-eval/{key}",
        title=f"Synthetic evidence for {key}",
        observed_at=observed_at,
        expires_at=expires_at or observed_at + timedelta(days=1),
        content_fingerprint=sha256(normalized.encode()).hexdigest(),
        passage=passage,
    )


def _claim(attribute: str, value, literal: str, *sources: SuppliedEvidence) -> ClaimProposal:
    return ClaimProposal(
        attribute=attribute,
        typed_value=value,
        original_value=literal,
        unit=value.unit if isinstance(value, QuantityValue) else None,
        currency=value.currency if isinstance(value, MoneyValue) else None,
        evidence_ids=tuple(item.evidence_id for item in sources),
    )


def _candidate(
    name: str,
    source: SuppliedEvidence,
    claims: tuple[ClaimProposal, ...],
    *,
    identifiers: dict[str, str] | None = None,
    entity_type: str = "object",
) -> Candidate:
    return Candidate(
        entity_type=entity_type,
        canonical_name=name,
        identifiers=identifiers or {},
        claims=claims,
    )


def _request(
    key: str,
    candidates: tuple[Candidate, ...],
    sources: tuple[SuppliedEvidence, ...],
    constraints: tuple[Constraint, ...] = (),
    preferences: tuple[Preference, ...] = (),
) -> DecisionCreateRequest:
    unique_sources = {item.evidence_id: item for item in sources}
    return DecisionCreateRequest(
        idempotency_key=_id(f"request:{key}"),
        candidates=candidates,
        constraints=constraints,
        preferences=preferences,
        supplied_evidence=tuple(unique_sources[key] for key in sorted(unique_sources, key=str)),
    )


def _run(
    repository: InMemoryDecisionRepository,
    request: DecisionCreateRequest,
    *,
    ranker=evaluate_candidates,
):
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        decision_enabled=True,
        decision_inspection_enabled=True,
    )
    return DecisionService(
        settings, repository, owner_id="local", clock=lambda: NOW, ranker=ranker
    ).create(request)


def _budget(maximum: str, *, attribute: str = "price") -> Constraint:
    return Constraint(
        id=_id(f"constraint:{attribute}:{maximum}"),
        attribute=attribute,
        operator="maximum",
        value=MoneyValue(amount=Decimal(maximum), currency="USD"),
    )


def _widget(
    key: str,
    name: str,
    *,
    amount: str = "40",
    color: str = "blue",
    identifier: str | None = None,
    observed_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> tuple[SuppliedEvidence, Candidate]:
    sku = identifier
    identity = f" catalog {sku}" if sku else ""
    source = _source(
        key,
        f"{name}{identity} costs ${amount} USD. {name} color is {color}.",
        observed_at=observed_at,
        expires_at=expires_at,
    )
    claims = (
        _claim("price", MoneyValue(amount=Decimal(amount), currency="USD"), f"${amount} USD", source),
        _claim("color", TextValue(value=color), color, source),
    )
    return source, _candidate(
        name, source, claims,
        identifiers={"catalog": sku} if sku else None,
    )


def _scenario(fixture: dict):
    name = fixture["name"]
    repository = InMemoryDecisionRepository()
    constraints: tuple[Constraint, ...] = ()
    preferences: tuple[Preference, ...] = ()
    sources: tuple[SuppliedEvidence, ...]
    candidates: tuple[Candidate, ...]
    ranker = evaluate_candidates

    if name == "exact-stable-identifier":
        old_source, old_candidate = _widget("exact-old", "Orion Widget", identifier="sku")
        _run(repository, _request("exact-seed", (old_candidate,), (old_source,), (_budget("50"),)))
        source, candidate = _widget("exact-new", "Orion Widget", identifier="sku")
        sources, candidates, constraints = (source,), (candidate,), (_budget("50"),)
    elif name == "alias-plus-fresh-attribute":
        old_source = _source("alias-old", "Aster Widget model is AW-1.")
        old_candidate = _candidate("Aster Widget", old_source, (
            _claim("model", TextValue(value="AW-1"), "AW-1", old_source),
        ))
        _run(repository, _request("alias-seed", (old_candidate,), (old_source,), (_budget("50"),)))
        source = _source("alias-new", "Aster Widgets model is AW-1. Aster Widgets costs $40 USD.")
        candidate = _candidate("Aster Widgets", source, (
            _claim("model", TextValue(value="AW-1"), "AW-1", source),
            _claim("price", MoneyValue(amount=Decimal(40), currency="USD"), "$40 USD", source),
        ))
        sources, candidates, constraints = (source,), (candidate,), (_budget("50"),)
    elif name == "near-name-alone-abstains":
        old_source = _source("near-old", "Acme Widget color is blue.")
        old_candidate = _candidate(
            "Acme Widget", old_source,
            (_claim("color", TextValue(value="blue"), "blue", old_source),),
        )
        _run(repository, _request("near-seed", (old_candidate,), (old_source,)))
        source = _source("near-new", "Acme Widgets color is red.")
        candidate = _candidate(
            "Acme Widgets", source,
            (_claim("color", TextValue(value="red"), "red", source),),
        )
        sources, candidates = (source,), (candidate,)
    elif name == "ambiguous-exact-identifiers":
        for index in range(2):
            entity = CanonicalEntity(
                id=_id(f"duplicate-identifier-entity:{index}"),
                entity_type="object",
                canonical_name=f"Collision Widget {index}",
                owner_scope="owner:local",
                owner_id="local",
                identifiers={"catalog": "SHARED-SKU"},
                created_at=NOW - timedelta(days=1),
                updated_at=NOW - timedelta(days=1),
            )
            repository.entities[entity.id] = entity
        source = _source("ambiguous", "Collision Widget catalog SHARED-SKU color is blue.")
        candidate = _candidate(
            "Collision Widget", source,
            (_claim("color", TextValue(value="blue"), "blue", source),),
            identifiers={"catalog": "SHARED-SKU"},
        )
        sources, candidates = (source,), (candidate,)
    elif name == "stale-identity-claim-excluded":
        stale_observed = NOW - timedelta(days=2)
        stale_expires = NOW - timedelta(days=1)
        old_source = _source(
            "stale-old", "Northstar Compact color is blue.",
            observed_at=stale_observed, expires_at=stale_expires,
        )
        old_candidate = _candidate(
            "Northstar Compact", old_source,
            (_claim("color", TextValue(value="blue"), "blue", old_source),),
        )
        _run(repository, _request("stale-seed", (old_candidate,), (old_source,)))
        source = _source(
            "stale-new", "Northstar Compacts color is blue.",
            observed_at=stale_observed, expires_at=stale_expires,
        )
        candidate = _candidate(
            "Northstar Compacts", source,
            (_claim("color", TextValue(value="blue"), "blue", source),),
        )
        constraints = (Constraint(
            id=_id("stale-color"), attribute="color", operator="exact", value=TextValue(value="blue")
        ),)
        sources, candidates = (source,), (candidate,)
    elif name == "conflicting-current-values":
        first = _source("conflict-a", "Cedar Widget costs $20 USD.")
        second = _source("conflict-b", "Cedar Widget costs $21 USD.")
        candidate = _candidate("Cedar Widget", first, (
            _claim("price", MoneyValue(amount=Decimal(20), currency="USD"), "$20 USD", first),
            _claim("price", MoneyValue(amount=Decimal(21), currency="USD"), "$21 USD", second),
        ))
        constraints = (_budget("30"),)
        sources, candidates = (first, second), (candidate,)
    elif name == "missing-required-attribute":
        source = _source("missing", "Moss Widget color is green.")
        candidate = _candidate(
            "Moss Widget", source,
            (_claim("color", TextValue(value="green"), "green", source),),
        )
        constraints = (_budget("50"),)
        sources, candidates = (source,), (candidate,)
    elif name == "maximum-budget-boundary":
        source, candidate = _widget("budget-boundary", "Boundary Widget", amount="50")
        constraints = (_budget("50"),)
        sources, candidates = (source,), (candidate,)
    elif name == "known-unit-conversion":
        source = _source("unit-conversion", "Pine Desk width is 25.4 mm.")
        candidate = _candidate(
            "Pine Desk", source,
            (_claim("width", QuantityValue(amount=Decimal("25.4"), unit="mm"), "25.4 mm", source),),
        )
        constraints = (Constraint(
            id=_id("width-max"), attribute="width", operator="maximum",
            value=QuantityValue(amount=Decimal(1), unit="in"),
        ),)
        sources, candidates = (source,), (candidate,)
    elif name == "unknown-currency-conversion":
        source = _source("currency", "Silver Lamp costs €20.")
        candidate = _candidate(
            "Silver Lamp", source,
            (_claim("price", MoneyValue(amount=Decimal(20), currency="EUR"), "€20", source),),
        )
        constraints = (_budget("50"),)
        sources, candidates = (source,), (candidate,)
    elif name == "date-location-availability":
        source = _source(
            "date-location-availability",
            "Cedar Lodge dates are 2026-09-10 to 2026-09-12; Cedar Lodge location is 37.7749, -122.4194; Cedar Lodge availability is available.",
        )
        candidate = _candidate("Cedar Lodge", source, (
            _claim("dates", DateWindowValue(start=date(2026, 9, 10), end=date(2026, 9, 12)),
                   "2026-09-10 to 2026-09-12", source),
            _claim("location", LocationValue(latitude=37.7749, longitude=-122.4194),
                   "37.7749, -122.4194", source),
            _claim("availability", AvailabilityValue(value="available"), "available", source),
        ), entity_type="place")
        constraints = (
            Constraint(id=_id("date-window"), attribute="dates", operator="date_window",
                       value=DateWindowValue(start=date(2026, 9, 11), end=date(2026, 9, 12))),
            Constraint(id=_id("location-radius"), attribute="location", operator="geospatial",
                       value=LocationValue(latitude=37.78, longitude=-122.42), radius_km=2),
            Constraint(id=_id("availability-required"), attribute="availability", operator="availability",
                       value=AvailabilityValue(value="available")),
        )
        sources, candidates = (source,), (candidate,)
    elif name == "equal-score-stable-tie":
        beta_source = _source("tie-beta", "Beta Widget color is blue.")
        alpha_source = _source("tie-alpha", "Alpha Widget color is red.")
        beta = _candidate("Beta Widget", beta_source,
                          (_claim("color", TextValue(value="blue"), "blue", beta_source),))
        alpha = _candidate("Alpha Widget", alpha_source,
                           (_claim("color", TextValue(value="red"), "red", alpha_source),))
        constraints = (Constraint(
            id=_id("tie-color-set"), attribute="color", operator="set",
            allowed_values=(TextValue(value="blue"), TextValue(value="red")),
        ),)
        sources, candidates = (beta_source, alpha_source), (beta, alpha)
    elif name == "preference-cannot-resurrect-excluded":
        blue_source = _source("preferred-blue", "Blue Widget costs $80 USD. Blue Widget color is blue.")
        red_source = _source("eligible-red", "Red Widget costs $40 USD. Red Widget color is red.")
        blue = _candidate("Blue Widget", blue_source, (
            _claim("price", MoneyValue(amount=Decimal(80), currency="USD"), "$80 USD", blue_source),
            _claim("color", TextValue(value="blue"), "blue", blue_source),
        ))
        red = _candidate("Red Widget", red_source, (
            _claim("price", MoneyValue(amount=Decimal(40), currency="USD"), "$40 USD", red_source),
            _claim("color", TextValue(value="red"), "red", red_source),
        ))
        constraints = (_budget("50"),)
        preferences = (Preference(attribute="color", target=TextValue(value="blue")),)
        sources, candidates = (blue_source, red_source), (blue, red)
    elif name == "empty-eligible-set":
        source, candidate = _widget("empty-set", "Expensive Widget", amount="99")
        constraints = (_budget("50"),)
        sources, candidates = (source,), (candidate,)
    elif name == "ranking-failure-keeps-eligible":
        source, candidate = _widget("ranking-failure", "Rankless Widget", amount="40")
        constraints = (_budget("50"),)

        def unavailable_ranker(**_):
            raise RuntimeError("synthetic ranking failure")

        ranker = unavailable_ranker
        sources, candidates = (source,), (candidate,)
    else:
        raise ValueError(f"unknown decision fixture: {name}")

    result = _run(
        repository,
        _request(name, candidates, sources, constraints, preferences),
        ranker=ranker,
    )
    return result, fixture


def _identity_matches(expected: str, actual: str) -> bool:
    if expected in {"exact_match", "matched"}:
        return actual == "matched"
    if expected in {"review_or_separate", "no_match_or_review"}:
        return actual in {"review", "no_match"}
    if expected == "review":
        return actual == "review"
    if expected == "separate":
        return actual == "no_match"
    return False


def _constraint_result(fixture: dict, result) -> bool:
    expected = fixture["constraint"]
    outcomes = [outcome for evaluation in result.evaluations for outcome in evaluation.constraint_outcomes]
    if expected == "unranked_identity":
        return not outcomes and any(match.outcome == "review" for match in result.matches)
    if expected == "not_applicable":
        return not outcomes
    if expected == "unknown":
        return bool(outcomes) and any(item.outcome == "unknown" for item in outcomes)
    if expected in {"pass", "pass_at_boundary", "pass_after_conversion", "all_operators"}:
        if not outcomes or any(item.outcome != "pass" for item in outcomes):
            return False
        if expected == "all_operators":
            return {item.attribute for item in outcomes} == {"dates", "location", "availability"}
        return True
    if expected == "fail":
        return any(item.outcome == "fail" for item in outcomes)
    if expected == "all_fail":
        return bool(outcomes) and all(item.outcome == "fail" for item in outcomes)
    return False


def _ranking_matches(fixture: dict, result) -> bool:
    expected = fixture["ranking"]
    state = result.decision.state
    if expected == "eligible":
        return state == "recommended" and result.decision.selected_entity_id is not None
    if expected == "no_auto_merge":
        return state == "research_needed" and result.matches[0].outcome in {"review", "no_match"}
    if expected == "research_needed":
        return state == "research_needed" and result.decision.selected_entity_id is None
    if expected == "stable_name_then_id":
        selected = next((item for item in result.entities if item.id == result.decision.selected_entity_id), None)
        return state == "recommended" and selected is not None and selected.canonical_name == "Alpha Widget"
    if expected == "excluded":
        selected = next((item for item in result.entities if item.id == result.decision.selected_entity_id), None)
        return (
            state == "recommended" and selected is not None and selected.canonical_name == "Red Widget"
            and any(not item.eligibility for item in result.evaluations)
        )
    if expected == "no_verified_match":
        return state == "no_verified_match" and result.decision.selected_entity_id is None
    if expected == "eligible_unranked":
        return (
            state == "eligible_unranked" and result.decision.selected_entity_id is None
            and any(item.eligibility and item.rank is None and item.score is None for item in result.evaluations)
        )
    return False


def evaluate() -> dict:
    rows = []
    for fixture in load_fixtures():
        result, fixture = _scenario(fixture)
        identity = result.matches[0].outcome if result.matches else "no_match"
        identity_passed = _identity_matches(fixture["identity"], identity)
        constraints_passed = _constraint_result(fixture, result)
        ranking_passed = _ranking_matches(fixture, result)
        rows.append({
            "fixture": fixture["name"],
            "decision_id": str(result.decision.id),
            "evidence_snapshot_id": str(result.evidence_snapshot.id),
            "entity_policy": result.decision.policy_versions.resolution,
            "claim_verification_policy": result.decision.policy_versions.claim_verification,
            "constraint_policy": result.decision.policy_versions.constraints,
            "ranking_policy": result.decision.policy_versions.ranking,
            "identity_outcome": identity,
            "identity_expectation": fixture["identity"],
            "constraint_outcomes": [
                {"attribute": item.attribute, "outcome": item.outcome, "reason": item.reason}
                for evaluation in result.evaluations for item in evaluation.constraint_outcomes
            ],
            "result": result.decision.state,
            "expected_result": fixture["ranking"],
            "selected_entity_id": str(result.decision.selected_entity_id) if result.decision.selected_entity_id else None,
            "passed": identity_passed and constraints_passed and ranking_passed,
        })
    revision = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=Path(__file__).resolve().parents[4],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=Path(__file__).resolve().parents[4],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip())
    first_policy = rows[0]
    return {
        "schema_version": "decision-eval-v1",
        "synthetic": True,
        "tested_at": datetime.now(UTC).isoformat(),
        "revision": f"{revision}-working-tree" if dirty else revision,
        "policy_versions": {
            "identity": "identity-v1",
            "resolution": first_policy["entity_policy"],
            "claim_verification": first_policy["claim_verification_policy"],
            "constraints": first_policy["constraint_policy"],
            "ranking": first_policy["ranking_policy"],
        },
        "passed": all(row["passed"] for row in rows),
        "results": rows,
    }


if __name__ == "__main__":
    report = evaluate()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
