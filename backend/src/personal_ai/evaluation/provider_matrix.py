"""Deterministic quality scoring and held-out profile promotion rules."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean
from uuid import UUID, uuid5

from personal_ai.evaluation.provider_matrix_contracts import (
    EvaluationFixture,
    EvaluationMetrics,
    QualityProfile,
)
from personal_ai.routing.contracts import EndpointProfile
from personal_ai.routing.phase21 import (
    RoutingTaskProfile,
    endpoint_configuration_sha256,
    quality_identity_sha256,
    task_configuration_sha256,
)

FIXTURE_PATH = Path(__file__).with_name("provider-matrix-fixtures.json")
SCORING_POLICY_ID = "deterministic-task-matrix"
SCORING_POLICY_VERSION = 1
MAX_FIXTURES = 512
_SCORERS = {}


@dataclass(frozen=True)
class SemanticScore:
    citation_precision: float = 1.0
    citation_coverage: float = 1.0
    provenance: float = 1.0
    answer_support: float = 1.0
    answer_relevance: float = 1.0


def register_evaluation_scorer(policy_id: str, version: int, scorer) -> None:
    """Register a deterministic task validator for a versioned evaluation suite."""
    key = (policy_id, version)
    if key in _SCORERS:
        raise ValueError("evaluation_scorer_already_registered")
    _SCORERS[key] = scorer


def _score_synthesis(fixture: EvaluationFixture, output: dict | None) -> SemanticScore:
    actual_claims = output.get("claims", []) if output is not None else []
    actual_claims = actual_claims if isinstance(actual_claims, list) else []
    expected_claims = {claim.claim_id: claim for claim in fixture.expected_claims}
    valid_claim_ids = set()
    valid_claim_count = 0
    seen_claim_ids = set()
    for claim in actual_claims:
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("claim_id")
        expected = expected_claims.get(claim_id) if isinstance(claim_id, str) else None
        source_ids = claim.get("source_ids")
        sources_valid = (
            isinstance(source_ids, list)
            and bool(source_ids)
            and all(isinstance(item, str) and item in fixture.source_ids for item in source_ids)
            and len(source_ids) == len(set(source_ids))
        )
        if (
            expected is not None
            and claim_id not in seen_claim_ids
            and str(claim.get("value")) == expected.value
            and sources_valid
            and set(expected.source_ids).issubset(source_ids)
        ):
            valid_claim_ids.add(claim_id)
            valid_claim_count += 1
        if isinstance(claim_id, str):
            seen_claim_ids.add(claim_id)

    answer_support = len(valid_claim_ids) / len(expected_claims) if expected_claims else 1.0
    provenance = valid_claim_count / len(actual_claims) if actual_claims else 0.0
    answer = output.get("answer", "") if output is not None else ""
    answer = answer if isinstance(answer, str) else ""
    answer_folded = answer.casefold()
    answer_relevance = (
        sum(term.casefold() in answer_folded for term in fixture.required_terms)
        / len(fixture.required_terms)
        if fixture.required_terms else 1.0
    )
    raw_citations = output.get("citations", []) if output is not None else []
    citations = raw_citations if isinstance(raw_citations, list) else []
    citation_ids = [
        item if isinstance(item, str) else item.get("source_id") if isinstance(item, dict) else None
        for item in citations
    ]
    valid_citations = [
        item for item in citation_ids if isinstance(item, str) and item in fixture.source_ids
    ]
    citation_precision = len(valid_citations) / len(citations) if citations else 0.0
    expected_sources = {source for claim in fixture.expected_claims for source in claim.source_ids}
    citation_coverage = (
        len(expected_sources.intersection(valid_citations)) / len(expected_sources)
        if expected_sources else 1.0
    )
    return SemanticScore(
        citation_precision=citation_precision,
        citation_coverage=citation_coverage,
        provenance=provenance,
        answer_support=answer_support,
        answer_relevance=answer_relevance,
    )


def _score_structured_output(_fixture: EvaluationFixture, _output: dict | None) -> SemanticScore:
    return SemanticScore()


register_evaluation_scorer(SCORING_POLICY_ID, SCORING_POLICY_VERSION, _score_synthesis)
register_evaluation_scorer("structured-output", 1, _score_structured_output)


def load_provider_matrix_configuration():
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixtures = tuple(EvaluationFixture.model_validate(row) for row in raw["fixtures"])
    if not 1 <= len(fixtures) <= MAX_FIXTURES:
        raise ValueError("evaluation_fixture_count_invalid")
    if len({fixture.fixture_id for fixture in fixtures}) != len(fixtures):
        raise ValueError("evaluation_fixture_id_duplicate")
    if len({(fixture.evaluation_suite_id, fixture.evaluation_suite_version) for fixture in fixtures}) != 1:
        raise ValueError("evaluation_fixture_suite_identity_mismatch")
    if len({(fixture.scoring_policy_id, fixture.scoring_policy_version) for fixture in fixtures}) != 1:
        raise ValueError("evaluation_fixture_scoring_policy_mismatch")
    declared_suite = raw.get("evaluation_suite", {})
    suite_id, suite_version, _scoring_id, _scoring_version, _suite_sha = evaluation_suite_identity(fixtures)
    if (declared_suite.get("id"), declared_suite.get("version")) != (suite_id, suite_version):
        raise ValueError("evaluation_suite_declaration_mismatch")
    task = RoutingTaskProfile.model_validate(raw["task_profile"])
    if any(
        fixture.task_profile_id != task.profile_id
        or fixture.task_profile_version != task.profile_version
        for fixture in fixtures
    ):
        raise ValueError("evaluation_fixture_task_profile_mismatch")
    if any(fixture.policy_version != fixtures[0].policy_version for fixture in fixtures):
        raise ValueError("evaluation_fixture_policy_version_mismatch")
    if raw.get("synthetic") is not True or any(
        fixture.data_classification != "synthetic_public" for fixture in fixtures
    ):
        raise ValueError("evaluation_fixture_source_not_synthetic_public")
    declared_scoring = raw["scoring_policy"]
    fixture_scoring = (fixtures[0].scoring_policy_id, fixtures[0].scoring_policy_version)
    if (declared_scoring.get("id"), declared_scoring.get("version")) != fixture_scoring:
        raise ValueError("evaluation_scoring_policy_declaration_mismatch")
    if fixture_scoring not in _SCORERS:
        raise ValueError("evaluation_scoring_policy_unregistered")
    if len(fixtures) < task.quality.minimum_samples:
        raise ValueError("evaluation_suite_below_quality_sample_floor")
    for fixture in fixtures:
        reference_metrics = score_output(fixture, json.dumps(fixture.reference_output))
        if (
            reference_metrics.overall_score < task.quality.minimum_score
            or not reference_metrics.hard_boundaries_passed
        ):
            raise ValueError("evaluation_fixture_reference_output_invalid")
    return fixtures, task, declared_scoring


def evaluation_suite_identity(fixtures: Iterable[EvaluationFixture]):
    fixtures = tuple(fixtures)
    if not fixtures:
        raise ValueError("evaluation_fixture_count_invalid")
    suite_keys = {
        (fixture.evaluation_suite_id, fixture.evaluation_suite_version,
         fixture.scoring_policy_id, fixture.scoring_policy_version)
        for fixture in fixtures
    }
    if len(suite_keys) != 1:
        raise ValueError("evaluation_fixture_suite_identity_mismatch")
    suite_id, suite_version, scoring_id, scoring_version = next(iter(suite_keys))
    payload = {
        "evaluation_suite_id": suite_id,
        "evaluation_suite_version": suite_version,
        "fixture_manifest_sha256": fixture_manifest_sha256(fixtures),
        "scoring_policy_id": scoring_id,
        "scoring_policy_version": scoring_version,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return suite_id, suite_version, scoring_id, scoring_version, digest


def _json_object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _type_matches(value, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return False


def _path(value, path: str):
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _constraint_passes(output, constraint) -> bool:
    actual = _path(output, constraint.path)
    expected = constraint.value
    if actual is None:
        return False
    if constraint.operator == "lte":
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
            and actual <= expected
        )
    if constraint.operator == "gte":
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
            and actual >= expected
        )
    if constraint.operator == "equals":
        return actual == expected
    if constraint.operator == "not_equals":
        return actual != expected
    if constraint.operator == "not_contains":
        return isinstance(actual, str) and str(expected).casefold() not in actual.casefold()
    return False


def score_output(
    fixture: EvaluationFixture,
    output_text: str,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    usage_confidence: str = "unknown",
    latency_ms: int | None = None,
    quota_units: tuple[tuple[str, int], ...] = (),
    quota_confidence: str = "unknown",
) -> EvaluationMetrics:
    """Apply shared structural checks and the suite's registered task validator."""
    output = _json_object(output_text)
    schema_validity = 0.0
    if output is not None:
        schema_validity = float(
            set(fixture.output_schema.required_fields).issubset(output)
            and all(
                _type_matches(output.get(key), expected_type)
                for key, expected_type in fixture.output_schema.field_types.items()
                if key in output
            )
        )

    scorer = _SCORERS.get((fixture.scoring_policy_id, fixture.scoring_policy_version))
    if scorer is None:
        raise ValueError("evaluation_scoring_policy_unregistered")
    semantic = scorer(fixture, output)

    constraints = [_constraint_passes(output or {}, row) for row in fixture.hard_constraints]
    hard_constraint_satisfaction = sum(constraints) / len(constraints) if constraints else 1.0
    privacy = float(
        not any(marker.casefold() in output_text.casefold() for marker in fixture.forbidden_literals)
    )
    dimensions = (
        schema_validity,
        semantic.citation_precision,
        semantic.citation_coverage,
        semantic.provenance,
        semantic.answer_support,
        semantic.answer_relevance,
        hard_constraint_satisfaction,
        privacy,
    )
    overall_score = fmean(dimensions)
    hard_boundaries_passed = all(
        (
            schema_validity == 1,
            semantic.citation_precision == 1,
            semantic.citation_coverage == 1,
            semantic.provenance == 1,
            semantic.answer_support == 1,
            hard_constraint_satisfaction == 1,
            privacy == 1,
        )
    )
    return EvaluationMetrics(
        schema_validity=schema_validity,
        citation_precision=semantic.citation_precision,
        citation_coverage=semantic.citation_coverage,
        provenance=semantic.provenance,
        answer_support=semantic.answer_support,
        answer_relevance=semantic.answer_relevance,
        hard_constraint_satisfaction=hard_constraint_satisfaction,
        privacy=privacy,
        overall_score=overall_score,
        hard_boundaries_passed=hard_boundaries_passed,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usage_confidence=usage_confidence,
        latency_ms=latency_ms,
        quota_units=tuple(sorted(quota_units)),
        quota_confidence=quota_confidence,
    )


def wilson_lower_bound(successes: int, samples: int, *, z: float = 1.96) -> float:
    if samples < 1 or successes < 0 or successes > samples:
        return 0.0
    proportion = successes / samples
    denominator = 1 + z * z / samples
    center = proportion + z * z / (2 * samples)
    margin = z * math.sqrt(proportion * (1 - proportion) / samples + z * z / (4 * samples**2))
    return max(0.0, min(1.0, (center - margin) / denominator))


def build_quality_profile(
    *,
    evaluation_run_id: UUID,
    task: RoutingTaskProfile,
    endpoint: EndpointProfile,
    policy_version: str,
    case_summaries: Iterable,
    tested_revision: str,
    fixture_manifest_sha256: str,
    seed: int | None,
    measured_at: datetime,
    evaluation_configuration_sha256: str | None = None,
    output_tokens: int = 256,
    evaluation_suite_id: str | None = None,
    evaluation_suite_version: int | None = None,
    comparison_baseline: EndpointProfile | None = None,
    retention_seconds: int | None = None,
) -> QualityProfile | None:
    if seed is not None:
        raise ValueError("evaluation_seed_unsupported")
    cases = tuple(case_summaries)
    measured = tuple(
        case for case in cases if case.status == "measured" and case.metrics is not None
    )
    if not measured or task.quality.mode != "measured_floor":
        return None
    policy = task.quality
    metrics = [case.metrics for case in measured]
    mean_score = fmean(metric.overall_score for metric in metrics)
    passed_count = sum(
        metric.hard_boundaries_passed and metric.overall_score >= policy.minimum_score
        for metric in metrics
    )
    confidence = wilson_lower_bound(passed_count, len(cases))
    coverage = len(measured) / len(cases) if cases else 0.0
    hard_passed = len(measured) == len(cases) and all(
        metric.hard_boundaries_passed for metric in metrics
    )
    endpoint_digest = endpoint_configuration_sha256(endpoint)
    task_digest = task_configuration_sha256(task)
    quality_id = policy.quality_profile_id or "quality-profile-missing"
    quality_version = policy.quality_profile_version or 1
    if not cases:
        return None
    first_case = cases[0]
    suite_id = evaluation_suite_id or first_case.evaluation_suite_id
    suite_version = evaluation_suite_version or first_case.evaluation_suite_version
    execution_digest = evaluation_configuration_sha256 or first_case.evaluation_configuration_sha256
    scoring_id = first_case.scoring_policy_id
    scoring_version = first_case.scoring_policy_version
    if any(
        case.evaluation_suite_id != suite_id
        or case.evaluation_suite_version != suite_version
        or case.scoring_policy_id != scoring_id
        or case.scoring_policy_version != scoring_version
        or case.evaluation_configuration_sha256 != execution_digest
        or case.output_tokens != output_tokens
        for case in cases
    ):
        raise ValueError("evaluation_case_profile_identity_mismatch")
    preparation_identities = {
        (case.preparation_counter_id, case.preparation_counter_confidence,
         case.preparation_count_source or "unknown")
        for case in measured
    }
    if len(preparation_identities) != 1:
        raise ValueError("evaluation_preparation_counter_identity_mismatch")
    prep_counter_id, prep_confidence, prep_count_source = next(iter(preparation_identities))
    identity_digest = quality_identity_sha256(
        endpoint_digest=endpoint_digest,
        task_digest=task_digest,
        policy_version=policy_version,
        quality_profile_id=quality_id,
        quality_profile_version=quality_version,
        scoring_policy_id=scoring_id,
        scoring_policy_version=scoring_version,
        tested_revision=tested_revision,
        evaluation_suite_id=suite_id,
        evaluation_suite_version=suite_version,
        fixture_manifest_sha256=fixture_manifest_sha256,
        evaluation_configuration_sha256=execution_digest,
        output_tokens=output_tokens,
        preparation_counter_id=prep_counter_id,
        preparation_counter_confidence=prep_confidence,
        preparation_count_source=prep_count_source,
    )
    profile_id = uuid5(
        evaluation_run_id,
        f"quality-profile-v1:{task.profile_id}:{task.profile_version}:"
        f"{endpoint.endpoint_profile_id}:{endpoint.profile_version}",
    )
    max_age = min(policy.max_age_seconds, retention_seconds or policy.max_age_seconds)
    return QualityProfile(
        quality_evidence_id=profile_id,
        quality_evidence_version=1,
        evaluation_run_id=evaluation_run_id,
        quality_profile_id=quality_id,
        quality_profile_version=quality_version,
        task_profile_id=task.profile_id,
        task_profile_version=task.profile_version,
        evaluation_suite_id=suite_id,
        evaluation_suite_version=suite_version,
        evaluation_configuration_sha256=execution_digest,
        output_tokens=output_tokens,
        comparison_baseline_endpoint=(comparison_baseline.ref if comparison_baseline else None),
        comparison_baseline_configuration_sha256=(
            endpoint_configuration_sha256(comparison_baseline)
            if comparison_baseline else None
        ),
        endpoint=endpoint.ref,
        provider_id=endpoint.provider_id,
        model_id=endpoint.model_id,
        account_scope_id=endpoint.account_scope_id,
        credential_scope_id=endpoint.credential_scope_id,
        endpoint_id=endpoint.endpoint_id,
        deployment_id=endpoint.deployment_id,
        serializer_id=endpoint.serializer_id,
        runtime_id=endpoint.runtime_id,
        counter_id=endpoint.counter.counter_id if endpoint.counter else None,
        counter_confidence=endpoint.counter.confidence if endpoint.counter else "unknown",
        preparation_counter_id=prep_counter_id,
        preparation_counter_confidence=prep_confidence,
        preparation_count_source=prep_count_source,
        policy_version=policy_version,
        endpoint_configuration_sha256=endpoint_digest,
        task_configuration_sha256=task_digest,
        quality_identity_sha256=identity_digest,
        scoring_policy_id=scoring_id,
        scoring_policy_version=scoring_version,
        minimum_score=policy.minimum_score,
        minimum_coverage=policy.minimum_coverage,
        minimum_confidence=policy.minimum_confidence,
        minimum_samples=policy.minimum_samples,
        minimum_benefit=policy.minimum_benefit,
        max_age_seconds=policy.max_age_seconds,
        tested_revision=tested_revision,
        fixture_manifest_sha256=fixture_manifest_sha256,
        seed=seed,
        sample_count=len(measured),
        coverage=coverage,
        score=mean_score,
        confidence=confidence,
        hard_boundaries_passed=hard_passed,
        mean_metrics={
            name: fmean(getattr(metric, name) for metric in metrics)
            for name in (
                "schema_validity", "citation_precision", "citation_coverage", "provenance",
                "answer_support", "answer_relevance", "hard_constraint_satisfaction", "privacy",
            )
        },
        measured_at=measured_at,
        fresh_until=measured_at + timedelta(seconds=max_age),
        status="unpromoted",
    )


def promote_quality_profile(
    candidate: QualityProfile,
    baseline: QualityProfile,
    *,
    task: RoutingTaskProfile,
    now: datetime,
) -> QualityProfile:
    """Return qualified evidence only after matching, held-out threshold checks."""
    policy = task.quality
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("quality_profile_promotion_timestamp_must_be_aware")
    if (
        candidate.status != "unpromoted"
        or baseline.status not in {"unpromoted", "qualified"}
        or candidate.task_profile_id != task.profile_id
        or candidate.task_profile_version != task.profile_version
        or baseline.task_profile_id != task.profile_id
        or baseline.task_profile_version != task.profile_version
        or candidate.quality_profile_id != policy.quality_profile_id
        or candidate.quality_profile_version != policy.quality_profile_version
        or candidate.minimum_score != policy.minimum_score
        or candidate.minimum_coverage != policy.minimum_coverage
        or candidate.minimum_confidence != policy.minimum_confidence
        or candidate.minimum_samples != policy.minimum_samples
        or candidate.minimum_benefit != policy.minimum_benefit
        or candidate.max_age_seconds != policy.max_age_seconds
        or baseline.quality_profile_id != candidate.quality_profile_id
        or baseline.quality_profile_version != candidate.quality_profile_version
        or candidate.policy_version != baseline.policy_version
        or candidate.tested_revision != baseline.tested_revision
        or candidate.seed != baseline.seed
        or candidate.fixture_manifest_sha256 != baseline.fixture_manifest_sha256
        or candidate.evaluation_suite_id != baseline.evaluation_suite_id
        or candidate.evaluation_suite_version != baseline.evaluation_suite_version
        or candidate.evaluation_configuration_sha256 != baseline.evaluation_configuration_sha256
        or candidate.output_tokens != baseline.output_tokens
        or candidate.preparation_counter_id != baseline.preparation_counter_id
        or candidate.preparation_counter_confidence != baseline.preparation_counter_confidence
        or candidate.preparation_count_source != baseline.preparation_count_source
        or candidate.task_configuration_sha256 != baseline.task_configuration_sha256
        or candidate.scoring_policy_id != baseline.scoring_policy_id
        or candidate.scoring_policy_version != baseline.scoring_policy_version
        or candidate.comparison_baseline_endpoint != baseline.endpoint
        or candidate.comparison_baseline_configuration_sha256
        != baseline.endpoint_configuration_sha256
        or candidate.endpoint == baseline.endpoint
        or candidate.sample_count < policy.minimum_samples
        or baseline.sample_count < policy.minimum_samples
        or candidate.sample_count != baseline.sample_count
        or candidate.coverage < policy.minimum_coverage
        or baseline.coverage < policy.minimum_coverage
        or candidate.coverage != baseline.coverage
        or candidate.score < policy.minimum_score
        or candidate.confidence < policy.minimum_confidence
        or baseline.confidence < policy.minimum_confidence
        or baseline.score < policy.minimum_score
        or not candidate.hard_boundaries_passed
        or not baseline.hard_boundaries_passed
        or candidate.fresh_until <= now
        or baseline.fresh_until <= now
        or candidate.score - baseline.score < policy.minimum_benefit
    ):
        raise ValueError("quality_profile_promotion_threshold_not_met")
    return candidate.model_copy(
        update={
            "status": "qualified",
            "quality_evidence_version": candidate.quality_evidence_version + 1,
            "revision": candidate.revision + 1,
            "baseline_evidence_id": baseline.quality_evidence_id,
            "promotion_minimum_benefit": policy.minimum_benefit,
        }
    )


def qualify_quality_profile(
    candidate: QualityProfile,
    *,
    task: RoutingTaskProfile,
    now: datetime,
) -> QualityProfile:
    """Qualify an endpoint against the absolute task floor, without a baseline."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("quality_profile_qualification_timestamp_must_be_aware")
    policy = task.quality
    if (
        candidate.status != "unpromoted"
        or candidate.task_profile_id != task.profile_id
        or candidate.task_profile_version != task.profile_version
        or candidate.task_configuration_sha256 != task_configuration_sha256(task)
        or candidate.quality_profile_id != policy.quality_profile_id
        or candidate.quality_profile_version != policy.quality_profile_version
        or candidate.sample_count < policy.minimum_samples
        or candidate.coverage < policy.minimum_coverage
        or candidate.score < policy.minimum_score
        or candidate.confidence < policy.minimum_confidence
        or not candidate.hard_boundaries_passed
        or candidate.measured_at > now
        or candidate.fresh_until <= now
    ):
        raise ValueError("quality_profile_floor_not_met")
    return candidate.model_copy(
        update={
            "status": "qualified",
            "quality_evidence_version": candidate.quality_evidence_version + 1,
            "revision": candidate.revision + 1,
        }
    )


def git_revision(root: Path | None = None) -> str:
    root = root or Path(__file__).resolve().parents[4]
    revision = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--", "backend/src"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--", "backend/src"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    if not dirty:
        return revision
    diff_digest = hashlib.sha256(diff).hexdigest()[:12]
    return f"{revision}-working-tree-{diff_digest}"


def fixture_manifest_sha256(fixtures: Iterable[EvaluationFixture]) -> str:
    normalized = sorted(
        (fixture.fixture_id, fixture.case_identity_sha256) for fixture in fixtures
    )
    return hashlib.sha256(
        json.dumps(normalized, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
