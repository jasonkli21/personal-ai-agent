"""Real-Postgres run persistence and actual P21/P19 synthetic dispatch test."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest

from personal_ai.auth.scope import ApplicationScope
from personal_ai.evaluation.provider_matrix import (
    load_provider_matrix_configuration,
    qualify_quality_profile,
)
from personal_ai.evaluation.provider_matrix_contracts import EvaluationRunStart
from personal_ai.evaluation.provider_matrix_runner import (
    ProviderMatrixRunner,
)
from personal_ai.llm.client import (
    GenerationMetadata,
    GenerationResult,
    ProviderCapabilities,
    ProviderIdentity,
    UsageMetadata,
)
from personal_ai.persistence.postgres import PostgresDatabase
from personal_ai.persistence.postgres_provider_matrix import PostgresProviderMatrixRepository
from personal_ai.persistence.postgres_routing import PostgresEndpointRegistryRepository
from personal_ai.persistence.postgres_routing_observations import PostgresRoutingDecisionRepository
from personal_ai.persistence.postgres_usage import PostgresProviderUsageAccounting
from personal_ai.routing import EndpointRegistry, RoutingDecisionService
from personal_ai.routing.contracts import EndpointCandidateRequirements
from personal_ai.routing.phase21 import (
    EvaluationQualityGate,
    RoutingRequestFacts,
    endpoint_configuration_sha256,
    task_configuration_sha256,
)
from personal_ai.routing.service import RoutingFinalizationError
from personal_ai.usage.profiles import EndpointProfileResolver
from tests.test_endpoint_registry import _bucket, _profile
from tests.test_provider_matrix import _valid_output
from tests.test_routing_phase21 import Authorization

pytestmark = pytest.mark.persistence_integration


class _PostgresSyntheticExecutor:
    evidence_source = "synthetic"

    def prepare(self, endpoint, _operation):
        return _PostgresSyntheticGenerator(endpoint)


class _PostgresMeasuredFixtureExecutor(_PostgresSyntheticExecutor):
    """Fixture-backed executor for exercising the live-quality persistence path only."""

    evidence_source = "live"


class _UnknownOutcomeExecutor:
    evidence_source = "synthetic"

    def prepare(self, endpoint, _operation):
        return _UnknownOutcomeGenerator(endpoint)


class _PostgresSyntheticGenerator:
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


class _UnknownOutcomeGenerator(_PostgresSyntheticGenerator):
    def complete(self, *_args, **_kwargs):
        raise TimeoutError("synthetic transport timeout")


@pytest.fixture
def database():
    dsn = os.environ.get("PERSISTENCE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set isolated PERSISTENCE_TEST_POSTGRES_DSN")
    db = PostgresDatabase(dsn, environment="test", min_size=1, max_size=8)
    db.migrate()
    try:
        yield db
    finally:
        db.close()


def test_synthetic_matrix_persists_through_postgres_and_p21_p19(database):
    scope = ApplicationScope(application_id="personal_ai")
    owner_id = "personal-ai-system"
    run_id = uuid4()
    endpoint = _profile(
        f"matrix:integration:{run_id.hex}",
        provider_id="synthetic-matrix-provider",
        model_id="synthetic-matrix-model",
        quota_buckets=(_bucket(f"matrix-bucket:{run_id.hex}"),),
    )
    catalog = PostgresEndpointRegistryRepository(database)
    registry = EndpointRegistry((endpoint,), repository=catalog)
    usage = PostgresProviderUsageAccounting(
        database,
        endpoint_profile_resolver=EndpointProfileResolver(registry, catalog),
    )
    evaluation_repository = PostgresProviderMatrixRepository(database)
    routing = RoutingDecisionService(
        registry,
        PostgresRoutingDecisionRepository(database),
        usage=usage,
        authorization=Authorization(),
        evaluation_quality_authority=evaluation_repository,
    )
    fixtures, task, _ = load_provider_matrix_configuration()
    runner = ProviderMatrixRunner(
        routing_service=routing,
        repository=evaluation_repository,
        executor=_PostgresSyntheticExecutor(),
    )
    summary, cases, quality_profiles = runner.run(
        evaluation_run_id=run_id,
        fixtures=fixtures,
        task=task,
        policy_version=fixtures[0].policy_version,
    )

    assert summary.status == "offline_baseline"
    assert summary.synthetic_cases == len(fixtures)
    assert summary.measured_cases == 0
    assert len(cases) == len(fixtures)
    assert not quality_profiles
    with database.connection() as connection:
        run = connection.execute(
            "SELECT status,completion_payload->>'status' FROM provider_matrix_runs "
            "WHERE evaluation_run_id=%s",
            (run_id,),
        ).fetchone()
        cases_stored = connection.execute(
            "SELECT count(*),count(*) FILTER(WHERE status='synthetic_baseline') "
            "FROM provider_matrix_cases WHERE evaluation_run_id=%s",
            (run_id,),
        ).fetchone()
        usage_stored = connection.execute(
            "SELECT count(*),count(*) FILTER(WHERE a.status='success') "
            "FROM provider_invocations i JOIN provider_attempts a USING(invocation_id) "
            "WHERE i.run_id=%s",
            (str(run_id),),
        ).fetchone()
    assert run == ("offline_baseline", "offline_baseline")
    assert cases_stored == (len(fixtures), len(fixtures))
    assert usage_stored == (len(fixtures), len(fixtures))

    # A completed synthetic run cannot authorize a later quality-waiver route.
    with database.connection() as connection:
        raw_gate = connection.execute(
            "SELECT gate_payload FROM provider_matrix_cases WHERE evaluation_run_id=%s LIMIT 1",
            (run_id,),
        ).fetchone()[0]
    gate = EvaluationQualityGate.model_validate(raw_gate)
    request = RoutingRequestFacts(
        request_id=gate.request_id,
        run_id=str(run_id),
        requirements=EndpointCandidateRequirements(
            execution_mode="STRICT_FREE",
            sensitivity="public",
            required_capabilities=task.required_capabilities,
            input_tokens=16,
            output_tokens=32,
            automatic=True,
        ),
        policy_version=fixtures[0].policy_version,
        prepared_context_tokens=16,
        count_source="synthetic-test:v1",
        count_confidence="estimated",
    )
    with pytest.raises(RoutingFinalizationError, match="routing_evaluation_quality_gate_denied"):
        routing.route(
            owner_id=owner_id,
            scope=scope,
            task=task,
            request=request,
            evaluation_quality_gate=gate,
        )


def test_postgres_floor_publication_is_consumed_by_p21(database):
    scope = ApplicationScope(application_id="personal_ai")
    owner_id = "personal-ai-system"
    run_id = uuid4()
    endpoint = _profile(
        f"matrix:quality-publication:{run_id.hex}",
        provider_id="synthetic-quality-provider",
        model_id="synthetic-quality-model",
        quota_buckets=(_bucket(f"matrix-quality-bucket:{run_id.hex}"),),
    )
    catalog = PostgresEndpointRegistryRepository(database)
    registry = EndpointRegistry((endpoint,), repository=catalog)
    usage = PostgresProviderUsageAccounting(
        database,
        endpoint_profile_resolver=EndpointProfileResolver(registry, catalog),
    )
    evaluation_repository = PostgresProviderMatrixRepository(database)
    routing = RoutingDecisionService(
        registry,
        PostgresRoutingDecisionRepository(database),
        usage=usage,
        authorization=Authorization(),
        evaluation_quality_authority=evaluation_repository,
    )
    fixtures, task, _ = load_provider_matrix_configuration()
    runner = ProviderMatrixRunner(
        routing_service=routing,
        repository=evaluation_repository,
        executor=_PostgresMeasuredFixtureExecutor(),
    )

    summary, cases, profiles = runner.run(
        evaluation_run_id=run_id,
        fixtures=fixtures,
        task=task,
        policy_version=fixtures[0].policy_version,
    )

    assert summary.status == "completed"
    assert len(cases) == len(fixtures)
    assert len(profiles) == 1
    unpromoted = profiles[0]
    assert unpromoted.status == "unpromoted"
    qualified = qualify_quality_profile(
        unpromoted,
        task=task,
        now=routing.current_time(owner_id=owner_id),
    )
    evaluation_repository.publish_quality_profile(qualified, expected_revision=1)
    evidence = evaluation_repository.quality_evidence(
        task_profile_id=task.profile_id,
        task_profile_version=task.profile_version,
        endpoint=endpoint.ref,
        quality_profile_id=task.quality.quality_profile_id,
        quality_profile_version=task.quality.quality_profile_version,
        policy_version=fixtures[0].policy_version,
        now=routing.current_time(owner_id=owner_id),
        owner_id=owner_id,
        scope=scope,
    )
    assert evidence is not None

    request = RoutingRequestFacts(
        request_id=f"quality-consumer:{uuid4().hex}",
        run_id="quality-consumer-run",
        requirements=EndpointCandidateRequirements(
            execution_mode="STRICT_FREE",
            sensitivity="public",
            required_capabilities=task.required_capabilities,
            input_tokens=64,
            output_tokens=256,
            automatic=True,
        ),
        policy_version=fixtures[0].policy_version,
        prepared_context_tokens=64,
        count_source="estimated-byte-upper-v1",
        count_confidence="estimated",
    )
    decision = routing.route(
        owner_id=owner_id,
        scope=scope,
        task=task,
        request=request,
        quality_evidence=(evidence,),
    )
    assert decision.selected == endpoint.ref
    candidate = next(row for row in decision.candidates if row.endpoint == endpoint.ref)
    assert candidate.quality_evidence_id == qualified.quality_evidence_id


def test_unresolved_unknown_attempt_blocks_same_case_under_new_run_id(database):
    endpoint = _profile(
        f"matrix:unknown:{uuid4().hex}",
        provider_id="synthetic-matrix-provider",
        model_id="synthetic-matrix-model",
        quota_buckets=(_bucket(f"matrix-unknown-bucket:{uuid4().hex}"),),
    )
    catalog = PostgresEndpointRegistryRepository(database)
    registry = EndpointRegistry((endpoint,), repository=catalog)
    usage = PostgresProviderUsageAccounting(
        database,
        endpoint_profile_resolver=EndpointProfileResolver(registry, catalog),
    )
    evaluation_repository = PostgresProviderMatrixRepository(database)
    routing = RoutingDecisionService(
        registry,
        PostgresRoutingDecisionRepository(database),
        usage=usage,
        authorization=Authorization(),
        evaluation_quality_authority=evaluation_repository,
    )
    fixtures, task, _ = load_provider_matrix_configuration()
    first_run_id, retry_run_id = uuid4(), uuid4()
    failed_runner = ProviderMatrixRunner(
        routing_service=routing,
        repository=evaluation_repository,
        executor=_UnknownOutcomeExecutor(),
    )
    first_summary, first_cases, _ = failed_runner.run(
        evaluation_run_id=first_run_id,
        fixtures=fixtures,
        task=task,
        policy_version=fixtures[0].policy_version,
    )
    assert first_summary.status == "failed"
    assert all(case.status == "failed" for case in first_cases)

    retry_executor = _PostgresSyntheticExecutor()
    retry_runner = ProviderMatrixRunner(
        routing_service=routing,
        repository=evaluation_repository,
        executor=retry_executor,
    )
    retry_summary, retry_cases, _ = retry_runner.run(
        evaluation_run_id=retry_run_id,
        fixtures=fixtures,
        task=task,
        policy_version=fixtures[0].policy_version,
    )
    assert retry_summary.status == "partial"
    assert all(case.status == "not_run" for case in retry_cases)
    assert not retry_executor.prepared
    with database.connection() as connection:
        attempts = connection.execute(
            "SELECT count(*),count(*) FILTER(WHERE status='unknown') FROM provider_attempts a "
            "JOIN provider_invocations i USING(invocation_id) WHERE i.run_id IN (%s,%s)",
            (str(first_run_id), str(retry_run_id)),
        ).fetchone()
    assert attempts == (len(fixtures), len(fixtures))


def test_concurrent_same_case_gate_authorization_has_one_oldest_run_winner(database):
    scope = ApplicationScope(application_id="personal_ai")
    owner_id = "personal-ai-system"
    endpoint = _profile(
        f"matrix:race:{uuid4().hex}",
        provider_id="synthetic-matrix-provider",
        model_id="synthetic-matrix-model",
        quota_buckets=(_bucket(f"matrix-race-bucket:{uuid4().hex}"),),
    )
    fixtures, task, _ = load_provider_matrix_configuration()
    fixture = fixtures[0]
    repository = PostgresProviderMatrixRepository(database)
    older_id, newer_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    case_identity = "d" * 64
    runs = []
    bindings = []
    requests = []
    for index, run_id in enumerate((older_id, newer_id)):
        gate = EvaluationQualityGate(
            evaluation_run_id=run_id,
            request_id=f"matrix-case:{run_id.hex}",
            fixture_id=fixture.fixture_id,
            prepared_input_sha256="e" * 64,
            endpoint=endpoint.ref,
            endpoint_configuration_sha256=endpoint_configuration_sha256(endpoint),
            task_configuration_sha256=task_configuration_sha256(task),
            evaluation_suite_id=fixture.evaluation_suite_id,
            evaluation_suite_version=fixture.evaluation_suite_version,
            scoring_policy_id=fixture.scoring_policy_id,
            scoring_policy_version=fixture.scoring_policy_version,
            output_tokens=256,
            task_profile_id=task.profile_id,
            task_profile_version=task.profile_version,
            quality_profile_id=task.quality.quality_profile_id,
            quality_profile_version=task.quality.quality_profile_version,
            policy_version=fixture.policy_version,
            case_identity_sha256=case_identity,
            mode="synthetic",
        )
        created_at = now - timedelta(seconds=2 - index)
        runs.append(
            EvaluationRunStart(
                evaluation_run_id=run_id,
                owner_id=owner_id,
                application_id=scope.application_id,
                workspace_id=scope.workspace_id,
                configuration_sha256="a" * 64,
                tested_revision="a1b2c3d",
                policy_version=fixture.policy_version,
                task_profile_id=task.profile_id,
                task_profile_version=task.profile_version,
                task_configuration_sha256=task_configuration_sha256(task),
                source="synthetic",
                expected_cases=1,
                created_at=created_at,
                gate_bindings=(gate,),
            )
        )
        bindings.append(gate)
        requests.append(
            RoutingRequestFacts(
                request_id=gate.request_id,
                run_id=str(run_id),
                requirements=EndpointCandidateRequirements(
                    execution_mode="STRICT_FREE",
                    sensitivity="public",
                    required_capabilities=task.required_capabilities,
                    input_tokens=64,
                    output_tokens=256,
                    automatic=True,
                ),
                policy_version=fixture.policy_version,
                prepared_context_tokens=64,
                count_source="synthetic-test:v1",
                count_confidence="estimated",
            )
        )
    for run in runs:
        repository.begin_run(run)

    barrier = Barrier(2)

    def authorize(index):
        barrier.wait()
        with repository.transaction(owner_id=owner_id) as connection:
            return repository.authorize(
                connection=connection,
                owner_id=owner_id,
                scope=scope,
                gate=bindings[index],
                task=task,
                request=requests[index],
                now=now,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(authorize, (0, 1)))
    assert results == (True, False)
