"""Cross-endpoint evaluation stays on Phase 21 routing and Phase 19 dispatch."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_ai.artifacts.observations import validate_observation
from personal_ai.auth.scope import ApplicationScope
from personal_ai.evaluation.provider_matrix import (
    build_quality_profile,
    evaluation_suite_identity,
    fixture_manifest_sha256,
    git_revision,
    load_provider_matrix_configuration,
    promote_quality_profile,
    qualify_quality_profile,
    score_output,
)
from personal_ai.evaluation.provider_matrix_contracts import (
    EvaluationCaseSummary,
    EvaluationMetrics,
    EvaluationRunStart,
    HardConstraint,
)
from personal_ai.evaluation.provider_matrix_runner import (
    SYSTEM_EVALUATION_OWNER,
    SYSTEM_EVALUATION_SCOPE,
    EvaluationRunConflict,
    InMemoryEvaluationRunRepository,
    ProviderMatrixRunner,
    SyntheticEvaluationOutputRetention,
    _usage_confidence,
)
from personal_ai.llm.client import (
    GenerationMetadata,
    GenerationResult,
    ProviderCapabilities,
    ProviderIdentity,
    UsageMetadata,
)
from personal_ai.routing import (
    DeterministicScoringStrategy,
    EndpointRegistry,
    RoutingDecisionService,
)
from personal_ai.routing.contracts import EndpointCandidateRequirements
from personal_ai.routing.phase21 import (
    EvaluationQualityGate,
    PreparationIdentity,
    RoutingRequestFacts,
    endpoint_configuration_sha256,
    task_configuration_sha256,
)
from personal_ai.routing.service import RoutingFinalizationError
from tests.test_endpoint_registry import _bucket, _profile
from tests.test_routing_phase21 import Authorization, MemoryRepository, Usage


def _valid_output(messages=None):
    fixtures, _, _ = load_provider_matrix_configuration()
    fixture = next(
        (row for row in fixtures if messages and row.messages[-1].content == messages[-1].content),
        fixtures[0],
    )
    return json.dumps(fixture.reference_output)


class _Generator:
    def __init__(self, endpoint):
        self.identity = ProviderIdentity(
            provider_id=endpoint.provider_id,
            model_id=endpoint.model_id,
            serializer_id=endpoint.serializer_id,
        )
        self.capabilities = ProviderCapabilities(frozenset({"bounded_generation"}))

    def complete(self, messages, *_args, **_kwargs):
        return GenerationResult(
            text=_valid_output(messages),
            metadata=GenerationMetadata(
                status="success",
                identity=self.identity,
                usage=UsageMetadata(input_tokens=68, output_tokens=35, total_tokens=103),
            ),
        )


class _SyntheticExecutor:
    evidence_source = "synthetic"

    def __init__(self):
        self.prepared = []

    def prepare(self, endpoint, _operation):
        self.prepared.append(endpoint.endpoint_profile_id)
        return _Generator(endpoint)


class _FailOnceRepository(InMemoryEvaluationRunRepository):
    def __init__(self):
        super().__init__()
        self.failed_first_case = False

    def save_case(self, case):
        if not self.failed_first_case and case.status == "synthetic_baseline":
            self.failed_first_case = True
            raise RuntimeError("simulated process interruption")
        super().save_case(case)


class _FakeArtifactService:
    def __init__(self, outcomes):
        self.store = SimpleNamespace(store_id="memory:test")
        self.outcomes = list(outcomes)
        self.write_calls = 0

    def write(self, *_args, **_kwargs):
        self.write_calls += 1
        outcome = self.outcomes.pop(0)
        if outcome is None:
            return None
        return SimpleNamespace(artifact_id=outcome)


def _matrix(*, include_blocked=True):
    profiles = [
        _profile(
            "gemini:generation", provider_id="gemini", model_id="synthesis-a",
            quota_buckets=(_bucket("bucket-gemini"),),
        ),
        _profile(
            "groq:generation", provider_id="groq", model_id="synthesis-b",
            quota_buckets=(_bucket("bucket-groq"),),
        ),
        _profile(
            "cloudflare:generation", provider_id="cloudflare", model_id="synthesis-c",
            quota_buckets=(_bucket("bucket-cloudflare"),),
        ),
        _profile(
            "extension:generic", provider_id="new-provider", model_id="synthesis-d",
            quota_buckets=(_bucket("bucket-extension"),),
            serializer_id="extension-chat-v2",
        ),
    ]
    if include_blocked:
        profiles.append(
            _profile(
                "extension:paid-blocked",
                provider_id="paid-provider",
                model_id="paid-model",
                strict_free_enabled=False,
                tier_verified=False,
                cost_class="UNKNOWN",
                billing_owner="unknown",
                quota_buckets=(_bucket("bucket-paid"),),
            )
        )
    fixtures, task, _ = load_provider_matrix_configuration()
    # Test-only task/suite registration models an explicit trusted suite extension.
    task_profile_id = "task-profile:extension-synthesis"
    task = task.model_copy(
        update={
            "task_id": "evaluation:extension-task",
            "profile_id": task_profile_id,
        }
    )
    fixtures = tuple(
        fixture.model_copy(
            update={
                "task_profile_id": task.profile_id,
                "evaluation_suite_id": "evaluation-suite:matrix-test",
            }
        )
        for fixture in fixtures
    )
    suite_id, suite_version, _, _, suite_digest = evaluation_suite_identity(fixtures)
    run_repository = InMemoryEvaluationRunRepository()
    observations = MemoryRepository()
    registry = EndpointRegistry(tuple(profiles))
    usage = Usage(observations)
    authorization = Authorization()
    routing = RoutingDecisionService(
        registry,
        observations,
        DeterministicScoringStrategy(),
        usage=usage,
        authorization=authorization,
        evaluation_quality_authority=run_repository,
    )
    executor = _SyntheticExecutor()
    runner = ProviderMatrixRunner(
        routing_service=routing,
        repository=run_repository,
        executor=executor,
        approved_evaluation_suites={(suite_id, suite_version): suite_digest},
    )
    return runner, run_repository, observations, executor, tuple(profiles), fixtures, task


def test_fixture_scoring_is_deterministic_and_hard_boundaries_fail_closed():
    fixtures, task, _ = load_provider_matrix_configuration()
    first = score_output(fixtures[0], _valid_output())
    second = score_output(fixtures[0], _valid_output())
    assert first == second
    assert first.overall_score == 1
    assert first.hard_boundaries_passed
    for fixture in fixtures:
        reference = score_output(fixture, json.dumps(fixture.reference_output, sort_keys=True))
        assert reference.overall_score >= task.quality.minimum_score
        assert reference.hard_boundaries_passed

    unsafe = json.loads(_valid_output())
    unsafe["citations"][-1] = "source:unregistered"
    unsafe["museum_visit_allowed"] = True
    unsafe["answer"] += " PRIVATE_NOTE_exposed"
    failed = score_output(fixtures[0], json.dumps(unsafe))
    assert not failed.hard_boundaries_passed
    assert failed.citation_precision < 1
    assert failed.hard_constraint_satisfaction < 1
    assert failed.privacy == 0

    malformed_citations = json.loads(_valid_output())
    malformed_citations["citations"] = [fixtures[0].source_ids[0], 7, {"unexpected": "shape"}]
    malformed_score = score_output(fixtures[0], json.dumps(malformed_citations))
    assert malformed_score.citation_precision == pytest.approx(1 / 3)


def test_numeric_hard_constraints_reject_string_thresholds():
    with pytest.raises(ValidationError, match="evaluation_constraint_numeric_value_required"):
        HardConstraint(path="budget_usd", operator="lte", value="55")


def test_registered_generic_scorer_supports_a_different_task_output_shape():
    fixtures, _, _ = load_provider_matrix_configuration()
    numeric = type(fixtures[0]).model_validate(
        {
            **fixtures[0].model_dump(),
            "evaluation_suite_id": "evaluation-suite:numeric-output-test",
            "scoring_policy_id": "structured-output",
            "fixture_id": "fixture:numeric-output-test",
            "messages": (
                {"role": "system", "content": "Return JSON with an integer result."},
                {"role": "user", "content": "Return the result 42."},
            ),
            "source_ids": (),
            "expected_claims": (),
            "required_terms": (),
            "output_schema_id": "evaluation:integer-result-v1",
            "output_schema": {
                "required_fields": ["result"],
                "field_types": {"result": "integer"},
            },
            "hard_constraints": (HardConstraint(path="result", operator="equals", value=42),),
            "reference_output": {"result": 42},
        }
    )
    score = score_output(numeric, '{"result":42}')
    assert score.overall_score == 1
    assert score.hard_boundaries_passed
    assert not score_output(numeric, '{"result":"42"}').hard_boundaries_passed


def test_packaged_held_out_suite_can_qualify_from_its_actual_fixtures():
    fixtures, task, _ = load_provider_matrix_configuration()
    endpoint = _profile("suite:quality-endpoint", quota_buckets=(_bucket("suite-quality"),))
    run_id = uuid4()
    now = datetime.now(UTC)
    cases = []
    for fixture in fixtures:
        metrics = score_output(fixture, json.dumps(fixture.reference_output))
        cases.append(
            EvaluationCaseSummary(
                evaluation_run_id=run_id,
                fixture_id=fixture.fixture_id,
                task_profile_id=task.profile_id,
                task_profile_version=task.profile_version,
                evaluation_suite_id=fixture.evaluation_suite_id,
                evaluation_suite_version=fixture.evaluation_suite_version,
                scoring_policy_id=fixture.scoring_policy_id,
                scoring_policy_version=fixture.scoring_policy_version,
                evaluation_configuration_sha256="d" * 64,
                output_tokens=256,
                endpoint=endpoint.ref,
                provider_id=endpoint.provider_id,
                model_id=endpoint.model_id,
                serializer_id=endpoint.serializer_id,
                runtime_id=endpoint.runtime_id,
                counter_id=endpoint.counter.counter_id if endpoint.counter else None,
                counter_confidence=endpoint.counter.confidence if endpoint.counter else "unknown",
                preparation_counter_confidence="estimated",
                preparation_count_source="estimated-byte-upper-v1",
                preparation_input_tokens=128,
                prepared_input_sha256="e" * 64,
                endpoint_configuration_sha256=endpoint_configuration_sha256(endpoint),
                policy_version=fixture.policy_version,
                tested_revision="a1b2c3d",
                status="measured",
                routing_decision_id=uuid4(),
                invocation_id=uuid4(),
                attempt_id=uuid4(),
                metrics=metrics,
                measured_at=now,
            )
        )
    candidate = build_quality_profile(
        evaluation_run_id=run_id,
        task=task,
        endpoint=endpoint,
        policy_version=fixtures[0].policy_version,
        case_summaries=cases,
        tested_revision="a1b2c3d",
        fixture_manifest_sha256=fixture_manifest_sha256(fixtures),
        seed=None,
        measured_at=now,
        output_tokens=256,
    )
    assert candidate is not None
    assert candidate.sample_count == task.quality.minimum_samples
    assert candidate.confidence >= task.quality.minimum_confidence
    assert qualify_quality_profile(candidate, task=task, now=now).status == "qualified"


def test_usage_confidence_does_not_promote_estimates_to_provider_facts():
    assert _usage_confidence(None) == "unknown"
    assert _usage_confidence(UsageMetadata()) == "unknown"
    assert _usage_confidence(
        UsageMetadata(input_tokens=10, source="estimated", confidence="estimated")
    ) == "derived"
    assert _usage_confidence(UsageMetadata(input_tokens=10)) == "exact"


def test_matrix_uses_generic_profiles_task_contract_and_p21_p19_seams():
    runner, repository, observations, executor, profiles, fixtures, task = _matrix()
    summary, cases, quality_profiles = runner.run(
        evaluation_run_id=uuid4(),
        fixtures=fixtures,
        task=task,
        policy_version=fixtures[0].policy_version,
        single_provider_baseline=profiles[0].ref,
    )

    assert summary.status == "partial"
    assert summary.total_cases == len(fixtures) * len(profiles)
    assert summary.measured_cases == 0
    assert summary.synthetic_cases == len(fixtures) * (len(profiles) - 1)
    assert summary.skipped_cases == len(fixtures)
    assert len(cases) == summary.total_cases
    assert not quality_profiles
    assert all(case.status == "synthetic_baseline" for case in cases if case.metrics)
    assert all(case.metrics.overall_score == 1 for case in cases if case.metrics)
    assert "extension:generic" in executor.prepared
    # A paid/unknown-cost profile remains blocked even with an exact quality gate.
    assert "extension:paid-blocked" not in executor.prepared
    assert len(observations.attempts) == len(fixtures) * (len(profiles) - 1)
    assert repository.runs[summary.evaluation_run_id][1] == "partial"
    assert {
        record.decision.request.count_source for record in observations.records.values()
    } == {"estimated-byte-upper-v1"}
    assert all(
        record.decision.request.count_confidence == "estimated"
        for record in observations.records.values()
    )
    assert all(case.endpoint_configuration_sha256 == endpoint_configuration_sha256(
        next(p for p in profiles if p.ref == case.endpoint)
    ) for case in cases)
    prepared_events = [
        event
        for record in observations.records.values()
        for event in record.events
        if event.kind == "authorized" and event.preparation is not None
    ]
    assert prepared_events
    assert all(event.preparation.prepared_at >= observations.now for event in prepared_events)
    assert all(
        event.preparation.count_confidence == "estimated"
        and event.preparation.counter_id is None
        for event in prepared_events
    )
    first_fixture_digests = {
        case.endpoint: case.prepared_input_sha256
        for case in cases
        if case.fixture_id == fixtures[0].fixture_id and case.metrics is not None
    }
    assert first_fixture_digests[profiles[0].ref] != first_fixture_digests[profiles[3].ref]
    assert all(row.status == "not_approved" for row in summary.artifact_publications)


def test_matrix_excludes_non_generation_profiles_from_case_universe():
    runner, _repository, _observations, executor, profiles, fixtures, task = _matrix(
        include_blocked=False
    )
    embedding = _profile(
        "extension:embedding",
        provider_id="embedding-provider",
        model_id="embedding-model",
        capabilities=frozenset({"embeddings"}),
        embedding_dimensions=768,
        quota_buckets=(_bucket("embedding-bucket", operations=frozenset({"embeddings"})),),
    )
    search = _profile(
        "extension:search",
        provider_id="search-provider",
        model_id="search-model",
        capabilities=frozenset({"search"}),
        max_search_query_chars=500,
        max_search_results=10,
        quota_buckets=(_bucket("search-bucket", operations=frozenset({"search"})),),
    )
    runner.routing_service.registry = EndpointRegistry((*profiles, embedding, search))

    summary, cases, _ = runner.run(
        evaluation_run_id=uuid4(),
        fixtures=fixtures,
        task=task,
        policy_version=fixtures[0].policy_version,
    )

    assert summary.total_cases == len(fixtures) * len(profiles)
    assert all(case.endpoint not in {embedding.ref, search.ref} for case in cases)
    assert embedding.endpoint_profile_id not in executor.prepared
    assert search.endpoint_profile_id not in executor.prepared


def test_identical_run_resumes_without_repeating_a_settled_send():
    runner, _repository, observations, _executor, profiles, fixtures, task = _matrix(
        include_blocked=False
    )
    repository = _FailOnceRepository()
    runner.repository = repository
    runner.routing_service.evaluation_quality_authority = repository
    run_id = uuid4()

    with pytest.raises(RuntimeError, match="simulated process interruption"):
        runner.run(
            evaluation_run_id=run_id,
            fixtures=fixtures,
            task=task,
            policy_version=fixtures[0].policy_version,
        )
    sent_before_resume = len(observations.attempts)
    assert sent_before_resume == 1

    summary, cases, _ = runner.run(
        evaluation_run_id=run_id,
        fixtures=fixtures,
        task=task,
        policy_version=fixtures[0].policy_version,
    )

    assert summary.status == "partial"
    assert summary.failed_cases == 1
    assert len(cases) == summary.total_cases
    assert len(observations.attempts) == len(fixtures) * len(profiles)
    assert len(observations.attempts) == sent_before_resume + len(fixtures) * len(profiles) - 1
    assert repository.runs[run_id][1] == "partial"


def test_routing_exceptions_are_failed_cases_not_eligibility_skips():
    runner, repository, observations, _executor, _profiles, fixtures, task = _matrix(
        include_blocked=False
    )

    def fail_route(**_kwargs):
        raise RuntimeError("internal routing failure")

    runner.routing_service.route = fail_route
    summary, cases, _ = runner.run(
        evaluation_run_id=uuid4(),
        fixtures=fixtures,
        task=task,
        policy_version=fixtures[0].policy_version,
    )

    assert summary.status == "failed"
    assert summary.failed_cases == summary.total_cases
    assert summary.skipped_cases == 0
    assert all(case.status == "failed" for case in cases)
    assert not observations.attempts
    assert repository.runs[summary.evaluation_run_id][1] == "failed"


def test_artifact_publication_reports_partial_batch_failure():
    runner, _repository, _observations, _executor, profiles, fixtures, task = _matrix(
        include_blocked=False
    )
    runner.routing_service.registry = EndpointRegistry((profiles[0],))
    first_artifact_id = uuid4()
    artifact_service = _FakeArtifactService((None, first_artifact_id))
    runner.artifact_service = artifact_service
    runner.retention_authority = SyntheticEvaluationOutputRetention()

    summary, _cases, _ = runner.run(
        evaluation_run_id=uuid4(),
        fixtures=fixtures,
        task=task,
        policy_version=fixtures[0].policy_version,
    )

    publication = summary.artifact_publications[0]
    assert artifact_service.write_calls == 2
    assert publication.status == "publication_failed"
    assert publication.error_code == "artifact_write_not_ready"
    assert publication.artifact_ids == (first_artifact_id,)


def test_evaluation_gate_rejects_preparation_for_different_fixture_before_reservation():
    runner, repository, observations, _executor, profiles, fixtures, task = _matrix(
        include_blocked=False
    )
    run_id = uuid4()
    fixture = fixtures[0]
    endpoint = profiles[0]
    gate = EvaluationQualityGate(
        evaluation_run_id=run_id,
        request_id=f"evalcase:{run_id.hex}",
        fixture_id=fixture.fixture_id,
        prepared_input_sha256="e" * 64,
        endpoint=endpoint.ref,
        endpoint_configuration_sha256=endpoint_configuration_sha256(endpoint),
        task_configuration_sha256=task_configuration_sha256(task),
        task_profile_id=task.profile_id,
        task_profile_version=task.profile_version,
        quality_profile_id=task.quality.quality_profile_id,
        quality_profile_version=task.quality.quality_profile_version,
        policy_version=fixture.policy_version,
        case_identity_sha256="d" * 64,
        mode="synthetic",
    )
    repository.begin_run(
        EvaluationRunStart(
            evaluation_run_id=run_id,
            owner_id=SYSTEM_EVALUATION_OWNER,
            application_id=SYSTEM_EVALUATION_SCOPE.application_id,
            workspace_id=SYSTEM_EVALUATION_SCOPE.workspace_id,
            configuration_sha256="c" * 64,
            tested_revision="a1b2c3d",
            policy_version=fixture.policy_version,
            task_profile_id=task.profile_id,
            task_profile_version=task.profile_version,
            task_configuration_sha256=task_configuration_sha256(task),
            evaluation_suite_id=fixture.evaluation_suite_id,
            evaluation_suite_version=fixture.evaluation_suite_version,
            scoring_policy_id=fixture.scoring_policy_id,
            scoring_policy_version=fixture.scoring_policy_version,
            output_tokens=256,
            source="synthetic",
            expected_cases=1,
            created_at=observations.now,
            gate_bindings=(gate,),
        )
    )
    request = RoutingRequestFacts(
        request_id=gate.request_id,
        run_id=str(run_id),
        requirements=EndpointCandidateRequirements(
            execution_mode="STRICT_FREE",
            sensitivity="public",
            required_capabilities=task.required_capabilities,
            input_tokens=512,
            output_tokens=256,
            automatic=True,
        ),
        policy_version=fixture.policy_version,
        prepared_context_tokens=512,
        count_source="test-counter:v1",
        count_confidence="estimated",
    )
    decision = runner.routing_service.route(
        owner_id=SYSTEM_EVALUATION_OWNER,
        scope=SYSTEM_EVALUATION_SCOPE,
        task=task,
        request=request,
        evaluation_quality_gate=gate,
    )
    preparation = PreparationIdentity(
        endpoint=endpoint.ref,
        serializer_id=endpoint.serializer_id,
        input_tokens=128,
        count_source="test-counter:v1",
        count_confidence="estimated",
        prepared_input_sha256="f" * 64,
        prepared_at=decision.created_at,
    )
    with pytest.raises(
        RoutingFinalizationError,
        match="routing_evaluation_preparation_identity_mismatch",
    ):
        runner.routing_service.finalize(
            owner_id=SYSTEM_EVALUATION_OWNER,
            scope=SYSTEM_EVALUATION_SCOPE,
            decision_id=decision.routing_decision_id,
            preparation=preparation,
            operation="bounded_generation",
        )
    assert runner.routing_service.usage.reserve_calls == 0


def test_quality_waiver_keeps_phase21_quota_authority_in_force():
    runner, repository, observations, executor, profiles, fixtures, task = _matrix(
        include_blocked=False
    )
    runner.routing_service.usage.exhausted = True
    summary, cases, _ = runner.run(
        evaluation_run_id=uuid4(),
        fixtures=fixtures,
        task=task,
        policy_version=fixtures[0].policy_version,
    )
    assert summary.status == "partial"
    assert summary.total_cases == len(fixtures) * len(profiles)
    assert summary.measured_cases == 0
    assert all(case.status == "not_run" for case in cases)
    assert not executor.prepared
    assert not observations.attempts
    assert repository.runs[summary.evaluation_run_id][1] == "partial"


def test_quality_profile_requires_same_held_out_sample_and_explicit_benefit():
    now = datetime.now(UTC)
    _fixtures, task = load_provider_matrix_configuration()[:2]
    endpoints = (
        _profile(
            "candidate:profile", provider_id="new-provider", model_id="candidate-model",
            quota_buckets=(_bucket("bucket-candidate"),),
        ),
        _profile(
            "baseline:profile", provider_id="baseline-provider", model_id="baseline-model",
            quota_buckets=(_bucket("bucket-baseline"),),
        ),
    )
    manifest = "a" * 64
    test_cases = []
    candidate_run, baseline_run = uuid4(), uuid4()
    for endpoint, score in ((endpoints[0], 0.98), (endpoints[1], 0.85)):
        run_id = candidate_run if endpoint == endpoints[0] else baseline_run
        overall_score = (6 + 2 * score) / 8
        metrics = EvaluationMetrics(
            schema_validity=1,
            citation_precision=1,
            citation_coverage=1,
            provenance=1,
            answer_support=score,
            answer_relevance=score,
            hard_constraint_satisfaction=1,
            privacy=1,
            overall_score=overall_score,
            hard_boundaries_passed=True,
        )
        for index in range(20):
            test_cases.append(
                EvaluationCaseSummary(
                    evaluation_run_id=run_id,
                    fixture_id=f"fixture:{index}",
                    task_profile_id=task.profile_id,
                    task_profile_version=task.profile_version,
                    evaluation_suite_id=_fixtures[0].evaluation_suite_id,
                    evaluation_suite_version=_fixtures[0].evaluation_suite_version,
                    scoring_policy_id=_fixtures[0].scoring_policy_id,
                    scoring_policy_version=_fixtures[0].scoring_policy_version,
                    evaluation_configuration_sha256="b" * 64,
                    output_tokens=256,
                    endpoint=endpoint.ref,
                    provider_id=endpoint.provider_id,
                    model_id=endpoint.model_id,
                    account_scope_id=endpoint.account_scope_id,
                    credential_scope_id=endpoint.credential_scope_id,
                    serializer_id=endpoint.serializer_id,
                    runtime_id=endpoint.runtime_id,
                    preparation_counter_confidence="estimated",
                    preparation_count_source="estimated-byte-upper-v1",
                    preparation_input_tokens=64,
                    prepared_input_sha256="c" * 64,
                    endpoint_configuration_sha256=endpoint_configuration_sha256(endpoint),
                    policy_version="evaluation-policy:v1",
                    tested_revision="a1b2c3d",
                    status="measured",
                    routing_decision_id=uuid4(),
                    invocation_id=uuid4(),
                    attempt_id=uuid4(),
                    metrics=metrics,
                    measured_at=now,
                )
            )
    candidate_cases = [c for c in test_cases if c.provider_id == endpoints[0].provider_id]
    baseline_cases = [c for c in test_cases if c.provider_id == endpoints[1].provider_id]
    candidate = build_quality_profile(
        evaluation_run_id=candidate_run,
        task=task,
        endpoint=endpoints[0],
        policy_version="evaluation-policy:v1",
        case_summaries=candidate_cases,
        tested_revision="a1b2c3d",
        fixture_manifest_sha256=manifest,
        seed=None,
        measured_at=now,
        comparison_baseline=endpoints[1],
    )
    baseline = build_quality_profile(
        evaluation_run_id=baseline_run,
        task=task,
        endpoint=endpoints[1],
        policy_version="evaluation-policy:v1",
        case_summaries=baseline_cases,
        tested_revision="a1b2c3d",
        fixture_manifest_sha256=manifest,
        seed=None,
        measured_at=now,
    )
    assert candidate and baseline
    assert candidate.confidence > 0.8
    promoted = promote_quality_profile(candidate, baseline, task=task, now=now)
    assert promoted.status == "qualified"
    assert promoted.revision == candidate.revision + 1
    assert promoted.quality_evidence_version == candidate.quality_evidence_version + 1
    assert promoted.as_routing_evidence().quality_evidence_id == promoted.quality_evidence_id

    comparison_repository = InMemoryEvaluationRunRepository()
    comparison_repository.save_quality_profile(candidate)
    comparison_repository.save_quality_profile(baseline)
    comparison_repository.publish_quality_profile(promoted, expected_revision=1)
    assert comparison_repository.get_quality_profile(
        promoted.quality_evidence_id
    ).baseline_evidence_id == baseline.quality_evidence_id
    mismatched_baseline = promoted.model_copy(
        update={"comparison_baseline_configuration_sha256": "f" * 64}
    )
    mismatched_repository = InMemoryEvaluationRunRepository()
    mismatched_repository.save_quality_profile(candidate)
    mismatched_repository.save_quality_profile(baseline)
    with pytest.raises(EvaluationRunConflict, match="quality_profile_baseline_mismatch"):
        mismatched_repository.publish_quality_profile(
            mismatched_baseline, expected_revision=1
        )

    evidence_repository = InMemoryEvaluationRunRepository()
    evidence_repository.save_quality_profile(candidate)
    evidence_repository.save_quality_profile(baseline)
    floor_qualified = qualify_quality_profile(candidate, task=task, now=now)
    evidence_repository.publish_quality_profile(floor_qualified, expected_revision=1)
    routing_evidence = evidence_repository.quality_evidence(
        task_profile_id=task.profile_id,
        task_profile_version=task.profile_version,
        endpoint=endpoints[0].ref,
        quality_profile_id=task.quality.quality_profile_id,
        quality_profile_version=task.quality.quality_profile_version,
        policy_version="evaluation-policy:v1",
        now=now,
    )
    observations = MemoryRepository()
    routing_service = RoutingDecisionService(
        EndpointRegistry(endpoints),
        observations,
        DeterministicScoringStrategy(),
        usage=Usage(observations),
        authorization=Authorization(),
    )
    request = RoutingRequestFacts(
        request_id=f"quality-route:{uuid4().hex}",
        run_id="quality-run:promoted-profile",
        requirements=EndpointCandidateRequirements(
            execution_mode="STRICT_FREE",
            sensitivity="public",
            required_capabilities=task.required_capabilities,
            input_tokens=64,
            output_tokens=256,
            automatic=True,
        ),
        policy_version="evaluation-policy:v1",
        prepared_context_tokens=64,
        count_source="synthetic-test:v1",
        count_confidence="estimated",
    )
    decision = routing_service.route(
        owner_id="quality-owner",
        scope=ApplicationScope(application_id="personal_ai"),
        task=task,
        request=request,
        quality_evidence=(routing_evidence,),
    )
    assert decision.selected == endpoints[0].ref
    candidate_fact = next(row for row in decision.candidates if row.endpoint == endpoints[0].ref)
    assert candidate_fact.quality_evidence_id == floor_qualified.quality_evidence_id

    under_sampled = candidate.model_copy(update={"sample_count": 3})
    with pytest.raises(ValueError, match="quality_profile_promotion_threshold_not_met"):
        promote_quality_profile(under_sampled, baseline, task=task, now=now)

    wrong_baseline = build_quality_profile(
        evaluation_run_id=baseline_run,
        task=task,
        endpoint=endpoints[0],
        policy_version="evaluation-policy:v1",
        case_summaries=candidate_cases,
        tested_revision="a1b2c3d",
        fixture_manifest_sha256=manifest,
        seed=None,
        measured_at=now,
        comparison_baseline=endpoints[0],
    )
    with pytest.raises(ValueError, match="quality_profile_promotion_threshold_not_met"):
        promote_quality_profile(wrong_baseline, baseline, task=task, now=now)


def test_git_revision_binds_dirty_tracked_source_content(tmp_path: Path):
    def git(*arguments):
        subprocess.run(
            ["git", *arguments],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    git("config", "user.email", "review@example.invalid")
    git("config", "user.name", "Review Test")
    source = tmp_path / "backend" / "src" / "evaluation.py"
    source.parent.mkdir(parents=True)
    source.write_text("revision = 1\n", encoding="utf-8")
    git("add", "backend/src/evaluation.py")
    git("commit", "-q", "-m", "baseline")

    clean_revision = git_revision(tmp_path)
    source.write_text("revision = 2\n", encoding="utf-8")
    first_dirty_revision = git_revision(tmp_path)
    source.write_text("revision = 3\n", encoding="utf-8")
    second_dirty_revision = git_revision(tmp_path)

    assert clean_revision != first_dirty_revision
    assert first_dirty_revision != second_dirty_revision
    assert "-working-tree-" in first_dirty_revision


def test_evaluation_fixtures_require_explicit_synthetic_public_classification():
    fixtures, _task, _ = load_provider_matrix_configuration()
    with pytest.raises(ValidationError):
        type(fixtures[0]).model_validate(
            {**fixtures[0].model_dump(), "data_classification": "personal"}
        )


def test_raw_output_artifact_contract_does_not_accept_prompts():
    from personal_ai.artifacts.observations import RawEvaluationOutputBatch

    body = {
        "schema_version": "evaluation-raw-outputs-v1",
        "evaluation_run_id": uuid4(),
        "retention_policy_reference": "approval:fixture-only",
        "retention_expires_at": datetime.now(UTC),
        "outputs": [
            {
                "case_id": "fixture:one",
                "task_profile_id": "task:one",
                "endpoint_profile_id": "provider:one",
                "endpoint_profile_version": 1,
                "provider_id": "provider",
                "model_id": "model",
                "serializer_id": "serializer:v1",
                "runtime_id": "runtime:v1",
                "invocation_id": uuid4(),
                "attempt_id": uuid4(),
                "status": "success",
                "output_text": "synthetic result",
                "latency_ms": 1,
            }
        ],
    }
    assert RawEvaluationOutputBatch.model_validate(body).outputs[0].output_text == "synthetic result"
    body["outputs"][0]["prompt"] = "private input"
    with pytest.raises(ValidationError):
        validate_observation("evaluation", body, jsonl=False)


def test_provider_matrix_requires_persistent_gate_authority():
    runner, repository, observations, _executor, _profiles, _fixtures, _task = _matrix()
    assert runner.repository is repository
    assert observations is runner.routing_service.observations
