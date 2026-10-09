"""Bounded task-by-endpoint evaluation through routing and P19 dispatch authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from personal_ai.artifacts.service import ArtifactService
from personal_ai.auth.scope import ApplicationScope
from personal_ai.context.builder import SOURCE_CLASSES, ContextBuilder, ContextBuildPolicy
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.evaluation.provider_matrix import (
    build_quality_profile,
    evaluation_suite_identity,
    fixture_manifest_sha256,
    git_revision,
    load_provider_matrix_configuration,
    score_output,
)
from personal_ai.evaluation.provider_matrix_contracts import (
    EvaluationArtifactPublication,
    EvaluationCaseSummary,
    EvaluationFixture,
    EvaluationRunStart,
    EvaluationRunSummary,
    QualityProfile,
)
from personal_ai.llm.client import ChatMessage, GenerationClient, InferenceContext
from personal_ai.llm.providers import build_generation_adapter
from personal_ai.routing.contracts import EndpointOperation, EndpointProfile, EndpointRef
from personal_ai.routing.phase21 import (
    EvaluationQualityGate,
    PreparationIdentity,
    RoutingRequestFacts,
    RoutingTaskProfile,
    StrategyView,
    endpoint_configuration_sha256,
    task_configuration_sha256,
)
from personal_ai.routing.strategy import DeterministicScoringStrategy
from personal_ai.usage.contracts import AttemptResult

SYSTEM_EVALUATION_OWNER = "personal-ai-system"
SYSTEM_EVALUATION_SCOPE = ApplicationScope(application_id="personal_ai")
MAX_CASES_PER_RUN = 512
MAX_CASES_TOTAL = 10_000
MAX_EVALUATION_CONTEXT_TOKENS = 128_000
MAX_OUTPUT_TEXT_CHARS = 65_536
MAX_RETAINED_OUTPUT_CHARS = 16_384
MAX_RAW_OUTPUTS_PER_ARTIFACT = 16
MAX_RAW_OUTPUT_BUFFER_BYTES = 512 * 1024
ARTIFACT_RETENTION_DAYS = 7


class EvaluationRunConflict(RuntimeError):
    pass


class EvaluationRunRepository(Protocol):
    def begin_run(self, run: EvaluationRunStart) -> None: ...
    def get_run_state(self, evaluation_run_id: UUID): ...
    def save_case(self, case: EvaluationCaseSummary) -> None: ...
    def complete_run(self, summary: EvaluationRunSummary) -> None: ...
    def save_quality_profile(self, profile: QualityProfile) -> None: ...
    def get_quality_profile(self, evidence_id: UUID) -> QualityProfile: ...
    def publish_quality_profile(self, profile: QualityProfile, *, expected_revision: int) -> None: ...
    def quality_evidence(
        self,
        *,
        task_profile_id: str,
        task_profile_version: int,
        endpoint: EndpointRef,
        quality_profile_id: str,
        quality_profile_version: int,
        policy_version: str,
        now: datetime,
    ): ...

    def authorize(
        self,
        *,
        connection,
        owner_id,
        scope,
        gate,
        task,
        request,
        now,
    ) -> bool: ...


class EvaluationGenerationExecutor(Protocol):
    evidence_source: Literal["synthetic", "live"]

    def prepare(
        self, endpoint: EndpointProfile, operation: EndpointOperation
    ) -> GenerationClient: ...


class OutputRetentionApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_run_id: UUID
    endpoint: EndpointRef
    evidence_source: Literal["synthetic", "live"]
    account_scope_id: str | None = None
    reference: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][-A-Za-z0-9._:+/]{0,199}$")
    valid_until: datetime

    @field_validator("valid_until")
    @classmethod
    def expiry_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluation_retention_expiry_must_be_aware")
        return value.astimezone(UTC)


class EvaluationOutputRetentionAuthority(Protocol):
    def authorize(
        self,
        *,
        evaluation_run_id: UUID,
        endpoint: EndpointProfile,
        now: datetime,
    ) -> OutputRetentionApproval | None: ...


class NoEvaluationOutputRetention:
    """Default-deny retention. Live output retention needs explicit current approval."""

    def authorize(self, **_):
        return None


class SyntheticEvaluationOutputRetention:
    """Explicit test/offline authority for synthetic output artifacts only."""

    def authorize(self, *, evaluation_run_id, endpoint, now):
        return OutputRetentionApproval(
            evaluation_run_id=evaluation_run_id,
            endpoint=endpoint.ref,
            evidence_source="synthetic",
            account_scope_id=endpoint.account_scope_id,
            reference="synthetic-fixture-retention-v1",
            valid_until=now + timedelta(days=ARTIFACT_RETENTION_DAYS),
        )


class LiteLLMProfileExecutor:
    """Prepare the existing neutral generation adapter for the exact registry profile.

    The SDK remains behind the normal inference gateway. P19 accounting is disabled
    in the gateway instance because the Phase21 dispatch receipt owns this one send.
    """

    evidence_source: Literal["live"] = "live"

    def __init__(self, settings):
        self.settings = settings

    def prepare(self, endpoint: EndpointProfile, operation: EndpointOperation):
        from personal_ai.routing.configured import build_initial_endpoint_profiles

        configured = {
            item.endpoint_profile_id: item for item in build_initial_endpoint_profiles(self.settings)
        }.get(endpoint.endpoint_profile_id)
        if configured is None or configured.model_copy(update={"profile_version": endpoint.profile_version}) != endpoint:
            raise ValueError("evaluation_endpoint_configuration_mismatch")
        generator = build_generation_adapter(
            self.settings,
            provider=endpoint.provider_id,
            usage_accounting=None,
        )
        if (
            generator.identity.provider_id != endpoint.provider_id
            or generator.identity.model_id != endpoint.model_id
            or generator.identity.serializer_id != endpoint.serializer_id
            or not generator.capabilities.supports(operation)
        ):
            raise ValueError("evaluation_generation_adapter_mismatch")
        return generator


class InMemoryEvaluationRunRepository:
    """Concurrency-safe contract adapter used by deterministic harness checks."""

    def __init__(self):
        from threading import RLock

        self.lock = RLock()
        self.runs: dict[UUID, tuple[EvaluationRunStart, str, EvaluationRunSummary | None]] = {}
        self.cases: dict[tuple[UUID, str, str, int], EvaluationCaseSummary] = {}
        self.quality_profiles: dict[UUID, QualityProfile] = {}

    def begin_run(self, run):
        run = EvaluationRunStart.model_validate(run.model_dump())
        with self.lock:
            if run.evaluation_run_id in self.runs:
                previous = self.runs[run.evaluation_run_id][0]
                if _run_start_identity(previous) != _run_start_identity(run) or previous.gate_bindings != run.gate_bindings:
                    raise EvaluationRunConflict("evaluation_run_idempotency_conflict")
                return
            self.runs[run.evaluation_run_id] = (run, "running", None)

    def get_run_state(self, evaluation_run_id):
        with self.lock:
            stored = self.runs.get(evaluation_run_id)
            if stored is None:
                raise LookupError("evaluation_run_unavailable")
            cases = tuple(
                case for key, case in self.cases.items() if key[0] == evaluation_run_id
            )
            return stored[0], stored[2], cases

    def save_case(self, case):
        key = (
            case.evaluation_run_id,
            case.fixture_id,
            case.endpoint.endpoint_profile_id,
            case.endpoint.profile_version,
        )
        with self.lock:
            previous = self.cases.get(key)
            if previous is not None and previous != case:
                raise EvaluationRunConflict("evaluation_case_idempotency_conflict")
            self.cases[key] = case

    def complete_run(self, summary):
        with self.lock:
            previous = self.runs.get(summary.evaluation_run_id)
            if previous is None:
                raise EvaluationRunConflict("evaluation_run_missing")
            if previous[2] is not None and previous[2] != summary:
                raise EvaluationRunConflict("evaluation_run_completion_conflict")
            run_start = previous[0]
            cases = [key for key in self.cases if key[0] == summary.evaluation_run_id]
            if len(cases) != run_start.expected_cases or summary.total_cases != run_start.expected_cases:
                raise EvaluationRunConflict("evaluation_run_case_count_mismatch")
            self.runs[summary.evaluation_run_id] = (previous[0], summary.status, summary)

    def save_quality_profile(self, profile):
        with self.lock:
            if profile.status != "unpromoted" or profile.revision != 1:
                raise EvaluationRunConflict("quality_profile_must_start_unpromoted")
            previous = self.quality_profiles.get(profile.quality_evidence_id)
            if previous is not None and previous != profile:
                raise EvaluationRunConflict("quality_profile_identity_conflict")
            self.quality_profiles[profile.quality_evidence_id] = profile

    def get_quality_profile(self, evidence_id):
        try:
            return self.quality_profiles[evidence_id]
        except KeyError as error:
            raise LookupError("quality_profile_unavailable") from error

    def publish_quality_profile(self, profile, *, expected_revision):
        with self.lock:
            previous = self.get_quality_profile(profile.quality_evidence_id)
            if previous.revision != expected_revision or profile.revision != expected_revision + 1:
                raise EvaluationRunConflict("quality_profile_revision_conflict")
            if profile.status != "qualified" or previous.status != "unpromoted":
                raise EvaluationRunConflict("quality_profile_publication_invalid")
            if profile.baseline_evidence_id is not None:
                baseline = self.get_quality_profile(profile.baseline_evidence_id)
                if (
                    baseline.endpoint == profile.endpoint
                    or baseline.evaluation_suite_id != profile.evaluation_suite_id
                    or baseline.evaluation_suite_version != profile.evaluation_suite_version
                    or baseline.fixture_manifest_sha256 != profile.fixture_manifest_sha256
                    or baseline.evaluation_configuration_sha256 != profile.evaluation_configuration_sha256
                    or profile.comparison_baseline_endpoint != baseline.endpoint
                    or profile.comparison_baseline_configuration_sha256
                    != baseline.endpoint_configuration_sha256
                    or profile.score - baseline.score < profile.promotion_minimum_benefit
                ):
                    raise EvaluationRunConflict("quality_profile_baseline_mismatch")
            self.quality_profiles[profile.quality_evidence_id] = profile

    def quality_evidence(
        self,
        *,
        task_profile_id,
        task_profile_version,
        endpoint,
        quality_profile_id,
        quality_profile_version,
        policy_version,
        now,
    ):
        matches = [
            profile
            for profile in self.quality_profiles.values()
            if profile.status == "qualified"
            and profile.task_profile_id == task_profile_id
            and profile.task_profile_version == task_profile_version
            and profile.endpoint == endpoint
            and profile.quality_profile_id == quality_profile_id
            and profile.quality_profile_version == quality_profile_version
            and profile.policy_version == policy_version
            and profile.measured_at <= now < profile.fresh_until
        ]
        if not matches:
            return None
        return max(matches, key=lambda profile: (profile.measured_at, profile.quality_evidence_id.int)).as_routing_evidence()

    def authorize(self, *, connection, owner_id, scope, gate, task, request, now):
        del connection, now
        with self.lock:
            run = self.runs.get(gate.evaluation_run_id)
            if run is None or run[1] != "running":
                return False
            start = run[0]
            for prior_id, prior in self.runs.items():
                if prior_id == gate.evaluation_run_id or prior[1] != "running":
                    continue
                if (prior[0].created_at, prior_id.int) >= (
                    start.created_at,
                    gate.evaluation_run_id.int,
                ):
                    continue
                if any(
                    binding.case_identity_sha256 == gate.case_identity_sha256
                    and binding.endpoint == gate.endpoint
                    for binding in prior[0].gate_bindings
                ):
                    return False
            if (owner_id, scope.application_id, scope.workspace_id) != (
                start.owner_id,
                start.application_id,
                start.workspace_id,
            ):
                return False
            if gate not in start.gate_bindings:
                return False
            return (
                request.request_id == gate.request_id
                and request.run_id == str(gate.evaluation_run_id)
                and task.profile_id == gate.task_profile_id
                and task.profile_version == gate.task_profile_version
                and task_configuration_sha256(task) == gate.task_configuration_sha256
                and request.policy_version == gate.policy_version
            )


class ProviderMatrixRunner:
    """Iterate fixture/profile pairs through Phase21 and settle every send via Phase19."""

    def __init__(
        self,
        *,
        routing_service,
        repository: EvaluationRunRepository,
        executor: EvaluationGenerationExecutor,
        artifact_service: ArtifactService | None = None,
        retention_authority: EvaluationOutputRetentionAuthority | None = None,
        deterministic_baseline_strategy=None,
        approved_evaluation_suites: Mapping[tuple[str, int], str] | None = None,
        owner_id: str = SYSTEM_EVALUATION_OWNER,
        scope: ApplicationScope = SYSTEM_EVALUATION_SCOPE,
        clock=None,
    ):
        self.routing_service = routing_service
        self.repository = repository
        self.executor = executor
        self.artifact_service = artifact_service
        self.retention_authority = retention_authority or NoEvaluationOutputRetention()
        self.deterministic_baseline_strategy = (
            deterministic_baseline_strategy or DeterministicScoringStrategy()
        )
        if approved_evaluation_suites is None:
            canonical_fixtures, _, _ = load_provider_matrix_configuration()
            suite_id, suite_version, _, _, suite_digest = evaluation_suite_identity(canonical_fixtures)
            approved_evaluation_suites = {(suite_id, suite_version): suite_digest}
        self.approved_evaluation_suites = dict(approved_evaluation_suites)
        self.owner_id = owner_id
        self.scope = scope
        self.clock = clock or (lambda: datetime.now(UTC))
        if (owner_id, scope) != (SYSTEM_EVALUATION_OWNER, SYSTEM_EVALUATION_SCOPE):
            raise ValueError("provider_matrix_system_scope_required")
        if getattr(routing_service, "evaluation_quality_authority", None) is not repository:
            raise ValueError("evaluation_run_repository_must_authorize_routing")

    def run(
        self,
        *,
        evaluation_run_id: UUID,
        fixtures: Sequence[EvaluationFixture],
        task: RoutingTaskProfile,
        policy_version: str,
        single_provider_baseline: EndpointRef | None = None,
        output_tokens: int = 256,
    ) -> tuple[EvaluationRunSummary, tuple[EvaluationCaseSummary, ...], tuple[QualityProfile, ...]]:
        tested_revision = git_revision()
        seed = None
        fixtures = tuple(EvaluationFixture.model_validate(item.model_dump()) for item in fixtures)
        task = RoutingTaskProfile.model_validate(task.model_dump())
        if not 1 <= len(fixtures) <= MAX_CASES_PER_RUN:
            raise ValueError("evaluation_fixture_count_invalid")
        if not 1 <= output_tokens <= 4096:
            raise ValueError("evaluation_output_bound_invalid")
        if any(
            not fixture.held_out
            or fixture.data_classification != "synthetic_public"
            or fixture.task_profile_id != task.profile_id
            or fixture.task_profile_version != task.profile_version
            or fixture.policy_version != policy_version
            for fixture in fixtures
        ):
            raise ValueError("evaluation_fixture_policy_mismatch")
        suite_id, suite_version, scoring_id, scoring_version, suite_digest = evaluation_suite_identity(fixtures)
        if self.approved_evaluation_suites.get((suite_id, suite_version)) != suite_digest:
            raise ValueError("evaluation_suite_not_approved")
        if (
            task.quality.mode != "measured_floor"
            or task.max_physical_attempts != 1
            or task.max_reselections != 0
            or task.max_auxiliary_calls != 0
        ):
            raise ValueError("evaluation_task_bounds_invalid")
        operation = _task_operation(task)
        context_policy = ContextBuildPolicy(
            global_input_tokens=MAX_EVALUATION_CONTEXT_TOKENS,
            source_max_tokens={
                source_class: MAX_EVALUATION_CONTEXT_TOKENS
                for source_class in SOURCE_CLASSES
            },
        )
        context_builder = ContextBuilder(EstimatedTokenCounter(), clock=self.clock)
        prepared_contexts = {
            fixture.fixture_id: context_builder.build(
                _messages(fixture),
                (),
                context_policy,
                base_sensitivity="public",
            )
            for fixture in fixtures
        }
        prepared_identities = {
            fixture_id: {
                "fixture_input_sha256": _prepared_input_digest(context.messages),
                "context_manifest_sha256": _context_manifest_digest(context.manifest),
                "input_tokens": context.token_count,
                "count_source": context.manifest.counter_version,
                "count_confidence": context.manifest.counter_kind,
            }
            for fixture_id, context in prepared_contexts.items()
        }
        requirements_by_fixture = {
            fixture.fixture_id: _requirements(
                task=task,
                fixture=fixture,
                input_tokens=prepared_contexts[fixture.fixture_id].token_count,
                output_tokens=output_tokens,
            )
            for fixture in fixtures
        }
        profiles = tuple(
            profile for profile in self.routing_service.registry.profiles
            if operation in profile.capabilities
        )
        if not profiles:
            raise ValueError("evaluation_endpoint_profiles_unavailable")
        baseline_profile = None
        if single_provider_baseline is not None:
            baseline_profile = next(
                (profile for profile in profiles if profile.ref == single_provider_baseline), None
            )
            if baseline_profile is None:
                raise ValueError("evaluation_baseline_endpoint_unavailable")
        if len(fixtures) * len(profiles) > MAX_CASES_TOTAL:
            raise ValueError("evaluation_matrix_case_limit")
        source = getattr(self.executor, "evidence_source", None)
        if source not in {"synthetic", "live"}:
            raise ValueError("evaluation_executor_evidence_source_required")
        manifest_sha = fixture_manifest_sha256(fixtures)
        configuration_digest = _configuration_digest(
            fixtures,
            task,
            profiles,
            policy_version=policy_version,
            tested_revision=tested_revision,
            source=source,
            seed=seed,
            prepared_identities=prepared_identities,
            evaluation_suite_sha256=suite_digest,
            scoring_policy_id=scoring_id,
            scoring_policy_version=scoring_version,
            output_tokens=output_tokens,
            single_provider_baseline=baseline_profile,
        )
        endpoint_prepared_identities = {
            (fixture.fixture_id, endpoint.ref): {
                **prepared_identities[fixture.fixture_id],
                "prepared_input_sha256": _prepared_input_digest(
                    prepared_contexts[fixture.fixture_id].messages,
                    endpoint.serializer_id,
                ),
            }
            for fixture in fixtures
            for endpoint in profiles
        }
        created_at = self.routing_service.current_time(owner_id=self.owner_id)
        gate_bindings = tuple(
            EvaluationQualityGate(
                evaluation_run_id=evaluation_run_id,
                request_id=_case_request_id(evaluation_run_id, fixture, endpoint),
                fixture_id=fixture.fixture_id,
                prepared_input_sha256=endpoint_prepared_identities[
                    (fixture.fixture_id, endpoint.ref)
                ]["prepared_input_sha256"],
                endpoint=endpoint.ref,
                endpoint_configuration_sha256=endpoint_configuration_sha256(endpoint),
                task_configuration_sha256=task_configuration_sha256(task),
                task_profile_id=task.profile_id,
                task_profile_version=task.profile_version,
                quality_profile_id=task.quality.quality_profile_id,
                quality_profile_version=task.quality.quality_profile_version,
                policy_version=policy_version,
                case_identity_sha256=_case_identity(
                    fixture,
                    endpoint,
                    task,
                    prepared_input_sha256=endpoint_prepared_identities[
                        (fixture.fixture_id, endpoint.ref)
                    ][
                        "prepared_input_sha256"
                    ],
                    context_manifest_sha256=prepared_identities[fixture.fixture_id][
                        "context_manifest_sha256"
                    ],
                    evaluation_suite_sha256=suite_digest,
                    output_tokens=output_tokens,
                ),
                mode=source,
            )
            for fixture in fixtures
            for endpoint in profiles
        )
        start = EvaluationRunStart(
            evaluation_run_id=evaluation_run_id,
            owner_id=self.owner_id,
            application_id=self.scope.application_id,
            workspace_id=self.scope.workspace_id,
            configuration_sha256=configuration_digest,
            tested_revision=tested_revision,
            policy_version=policy_version,
            task_profile_id=task.profile_id,
            task_profile_version=task.profile_version,
            task_configuration_sha256=task_configuration_sha256(task),
            evaluation_suite_id=suite_id,
            evaluation_suite_version=suite_version,
            scoring_policy_id=scoring_id,
            scoring_policy_version=scoring_version,
            output_tokens=output_tokens,
            source=source,
            seed=seed,
            expected_cases=len(fixtures) * len(profiles),
            created_at=created_at,
            gate_bindings=gate_bindings,
        )
        self.repository.begin_run(start)
        stored_start, stored_completion, stored_cases = self.repository.get_run_state(
            evaluation_run_id
        )
        created_at = stored_start.created_at

        def case_for(evaluation_run_id, fixture, endpoint, policy_version, tested_revision, **values):
            return self._case(
                evaluation_run_id,
                fixture,
                endpoint,
                policy_version,
                tested_revision,
                evaluation_configuration_sha256=configuration_digest,
                output_tokens=output_tokens,
                **values,
            )

        summaries: list[EvaluationCaseSummary] = list(stored_cases)
        existing_cases_by_identity = {
            (case.fixture_id, case.endpoint): case for case in stored_cases
        }
        decision_baselines: list[str] = []
        raw_output_buffers: dict[tuple[str, str, datetime], list[dict]] = {}
        raw_output_bytes: dict[tuple[str, str, datetime], int] = {}
        raw_output_sequences: dict[tuple[str, str, datetime], int] = {}
        artifact_publications = {
            endpoint.ref: {
                "approved": False,
                "failed": False,
                "artifact_ids": [],
            }
            for endpoint in profiles
        }
        retention_approvals = {}
        for fixture in (() if stored_completion is not None else fixtures):
            if all(
                (fixture.fixture_id, endpoint.ref) in existing_cases_by_identity
                for endpoint in profiles
            ):
                continue
            decisions = []
            endpoint_cases = []
            prepared_context = prepared_contexts[fixture.fixture_id]
            prepared_identity = prepared_identities[fixture.fixture_id]
            request_requirements = requirements_by_fixture[fixture.fixture_id]
            source_digests = tuple(
                sorted(hashlib.sha256(item.encode("utf-8")).hexdigest() for item in fixture.source_ids)
            )
            for endpoint in profiles:
                if (fixture.fixture_id, endpoint.ref) in existing_cases_by_identity:
                    continue
                endpoint_prepared_identity = endpoint_prepared_identities[
                    (fixture.fixture_id, endpoint.ref)
                ]
                gate = next(
                    binding
                    for binding in gate_bindings
                    if binding.fixture_id == fixture.fixture_id
                    and binding.endpoint == endpoint.ref
                )
                excluded = tuple(
                    sorted(
                        profile.endpoint_profile_id
                        for profile in profiles
                        if profile.endpoint_profile_id != endpoint.endpoint_profile_id
                    )
                )
                request_id = gate.request_id
                request = RoutingRequestFacts(
                    request_id=request_id,
                    run_id=str(evaluation_run_id),
                    requirements=request_requirements,
                    policy_version=policy_version,
                    source_reference_sha256s=source_digests,
                    prepared_context_tokens=prepared_context.token_count,
                    count_source=prepared_identity["count_source"],
                    count_confidence=prepared_identity["count_confidence"],
                    excluded_endpoint_profile_ids=excluded,
                )
                try:
                    decision = self.routing_service.route(
                        owner_id=self.owner_id,
                        scope=self.scope,
                        task=task,
                        request=request,
                        evaluation_quality_gate=gate,
                    )
                except Exception as error:  # noqa: BLE001 - no provider IO on route failure
                    code = _safe_code(error, "evaluation_routing_unavailable")
                    endpoint_cases.append(
                        case_for(
                            evaluation_run_id,
                            fixture,
                            endpoint,
                            policy_version,
                            tested_revision,
                            status="failed",
                            reason=code,
                            single_provider_baseline=endpoint.ref == single_provider_baseline,
                        )
                    )
                    continue
                decisions.append((decision, endpoint))
                candidate = next(
                    (item for item in decision.candidates if item.endpoint == endpoint.ref), None
                )
                if decision.selected != endpoint.ref or candidate is None or not candidate.eligible:
                    reason = (
                        decision.no_route_reason
                        or (candidate.rejection_reasons[0] if candidate and candidate.rejection_reasons else "endpoint_not_eligible")
                    )
                    endpoint_cases.append(
                        case_for(
                            evaluation_run_id,
                            fixture,
                            endpoint,
                            policy_version,
                            tested_revision,
                            status="not_run",
                            reason=reason,
                            routing_decision_id=decision.routing_decision_id,
                            single_provider_baseline=endpoint.ref == single_provider_baseline,
                        )
                    )

            strategy_ranking = self._strategy_baseline(task, decisions)
            if strategy_ranking:
                decision_baselines.append(strategy_ranking[0].endpoint.endpoint_profile_id)
            strategy_positions = {
                row.endpoint: (index, row.score)
                for index, row in enumerate(strategy_ranking, start=1)
            }
            for index, case in enumerate(endpoint_cases):
                position = strategy_positions.get(case.endpoint)
                if position is not None:
                    endpoint_cases[index] = case.model_copy(
                        update={
                            "deterministic_strategy_rank": position[0],
                            "deterministic_strategy_score": position[1],
                            "deterministic_strategy_baseline": position[0] == 1,
                        }
                    )

            decisions_by_endpoint = {
                endpoint.ref: decision for decision, endpoint in decisions
            }
            cases_by_endpoint = {case.endpoint: case for case in endpoint_cases}
            for endpoint in profiles:
                endpoint_prepared_identity = endpoint_prepared_identities[
                    (fixture.fixture_id, endpoint.ref)
                ]
                case = cases_by_endpoint.get(endpoint.ref)
                if case is None:
                    decision = decisions_by_endpoint.get(endpoint.ref)
                    if decision is None:
                        continue
                    position = strategy_positions.get(endpoint.ref)
                    try:
                        generator = self.executor.prepare(endpoint, operation)
                        _validate_generator(generator, endpoint, operation)
                    except Exception as error:  # noqa: BLE001 - fail before finalize/provider IO
                        self.routing_service.finish(
                            owner_id=self.owner_id,
                            scope=self.scope,
                            decision_id=decision.routing_decision_id,
                            reason="evaluation-executor-unavailable",
                        )
                        case = case_for(
                            evaluation_run_id,
                            fixture,
                            endpoint,
                            policy_version,
                            tested_revision,
                            status="failed",
                            reason=_safe_code(error, "evaluation_executor_unavailable"),
                            routing_decision_id=decision.routing_decision_id,
                            single_provider_baseline=endpoint.ref == single_provider_baseline,
                            deterministic_strategy_rank=position[0] if position else None,
                            deterministic_strategy_score=position[1] if position else None,
                            deterministic_strategy_baseline=bool(position and position[0] == 1),
                        )
                        self.repository.save_case(case)
                        summaries.append(case)
                        continue
                    prepared_input = prepared_context.messages
                    preparation_counter = EstimatedTokenCounter()
                    prepared_count = preparation_counter.count(prepared_input)
                    prepared_input_sha256 = _prepared_input_digest(
                        prepared_input, endpoint.serializer_id
                    )
                    if prepared_input_sha256 != endpoint_prepared_identity["prepared_input_sha256"]:
                        raise EvaluationRunConflict("evaluation_preparation_identity_changed")
                    preparation = PreparationIdentity(
                        endpoint=endpoint.ref,
                        serializer_id=endpoint.serializer_id,
                        counter_id=None,
                        input_tokens=prepared_count.tokens,
                        count_source=preparation_counter.counter_version,
                        count_confidence=prepared_count.kind,
                        source_reference_sha256s=source_digests,
                        prepared_input_sha256=endpoint_prepared_identity[
                            "prepared_input_sha256"
                        ],
                        prepared_at=self.routing_service.current_time(owner_id=self.owner_id),
                    )
                    try:
                        permit = self.routing_service.finalize(
                            owner_id=self.owner_id,
                            scope=self.scope,
                            decision_id=decision.routing_decision_id,
                            preparation=preparation,
                            operation=operation,
                        )
                    except Exception as error:  # noqa: BLE001 - reservation failure means no send
                        case = case_for(
                            evaluation_run_id,
                            fixture,
                            endpoint,
                            policy_version,
                            tested_revision,
                            status="failed",
                            reason=_safe_code(error, "evaluation_dispatch_not_authorized"),
                            routing_decision_id=decision.routing_decision_id,
                            single_provider_baseline=endpoint.ref == single_provider_baseline,
                            deterministic_strategy_rank=position[0] if position else None,
                            deterministic_strategy_score=position[1] if position else None,
                            deterministic_strategy_baseline=bool(position and position[0] == 1),
                        )
                        self.repository.save_case(case)
                        summaries.append(case)
                        continue
                    attempt_results: list[AttemptResult] = []
                    send_state: list[bool] = []

                    def send(
                        selected_profile,
                        invocation,
                        attempt,
                        *,
                        generator=generator,
                        prepared_input=prepared_input,
                        fixture=fixture,
                        operation=operation,
                        output_tokens=output_tokens,
                        policy_version=policy_version,
                        permit=permit,
                        attempt_results=attempt_results,
                        send_state=send_state,
                    ):
                        send_state.append(True)
                        monotonic_started = monotonic()
                        context = InferenceContext(
                            effective_sensitivity="public",
                            maximum_sensitivity=selected_profile.data_use_policy.max_sensitivity,
                            policy_version=policy_version,
                        )
                        if operation == "structured_generation":
                            result = generator.generate_structured(
                                prepared_input,
                                response_schema=_response_schema(fixture),
                                max_output_tokens=output_tokens,
                                timeout_seconds=_remaining_seconds(permit),
                                inference_context=context,
                            )
                        else:
                            result = generator.complete(
                                prepared_input,
                                max_output_tokens=output_tokens,
                                timeout_seconds=_remaining_seconds(permit),
                                inference_context=context,
                            )
                        latency = min(600_000, max(0, int((monotonic() - monotonic_started) * 1000)))
                        if (
                            result.metadata.identity.provider_id != selected_profile.provider_id
                            or result.metadata.identity.model_id != selected_profile.model_id
                            or result.metadata.identity.serializer_id != selected_profile.serializer_id
                            or result.metadata.invocation_id not in {
                                None,
                                str(invocation.invocation_id),
                            }
                            or (
                                result.metadata.attempt_ids
                                and result.metadata.attempt_ids != (str(attempt.attempt_id),)
                            )
                        ):
                            outcome = "failure"
                            error_code = "provider_identity_mismatch"
                        else:
                            outcome = result.metadata.status
                            error_code = _safe_result_code(
                                result.metadata.error_code, "provider_generation_failed"
                            )
                        usage = result.metadata.usage
                        usage_confidence = _usage_confidence(usage)
                        if usage is None:
                            usage_source = "unknown"
                            unit_usage = ()
                            unit_confidence = "unknown"
                        else:
                            usage_source = usage.source
                            total = usage.total_tokens
                            if total is None and usage.input_tokens is not None and usage.output_tokens is not None:
                                total = usage.input_tokens + usage.output_tokens
                            unit_usage = (("tokens", total),) if total is not None else ()
                            unit_confidence = usage_confidence if unit_usage else "unknown"
                        attempt_result = AttemptResult(
                            outcome=outcome,
                            completed_at=max(datetime.now(UTC), attempt.started_at),
                            latency_ms=latency,
                            error_code=error_code,
                            input_tokens=usage.input_tokens if usage else None,
                            output_tokens=usage.output_tokens if usage else None,
                            total_tokens=usage.total_tokens if usage else None,
                            usage_source=usage_source,
                            usage_confidence=usage_confidence,
                            unit_usage=unit_usage,
                            unit_usage_source=usage_source if unit_usage else "unknown",
                            unit_usage_confidence=unit_confidence,
                            rate_limits=result.metadata.rate_limits,
                        )
                        attempt_results.append(attempt_result)
                        return result, attempt_result

                    try:
                        result = self.routing_service.dispatch(
                            owner_id=self.owner_id,
                            scope=self.scope,
                            permit=permit,
                            operation=operation,
                            send=send,
                        )
                    except Exception as error:  # noqa: BLE001 - P21 already settled the send outcome
                        attempt = attempt_results[-1] if attempt_results else None
                        physical_send_started = bool(send_state)
                        case = case_for(
                            evaluation_run_id,
                            fixture,
                            endpoint,
                            policy_version,
                            tested_revision,
                            status="failed" if physical_send_started else "not_run",
                            reason=_safe_code(error, "evaluation_provider_outcome_unknown"),
                            routing_decision_id=decision.routing_decision_id,
                            invocation_id=permit.invocation_id if physical_send_started else None,
                            attempt_id=permit.attempt_id if physical_send_started else None,
                            single_provider_baseline=endpoint.ref == single_provider_baseline,
                            deterministic_strategy_rank=position[0] if position else None,
                            deterministic_strategy_score=position[1] if position else None,
                            deterministic_strategy_baseline=bool(position and position[0] == 1),
                        )
                        self.repository.save_case(case)
                        summaries.append(case)
                        continue

                    attempt = attempt_results[-1]
                    identity_matches = (
                        result.metadata.identity.provider_id == endpoint.provider_id
                        and result.metadata.identity.model_id == endpoint.model_id
                        and result.metadata.identity.serializer_id == endpoint.serializer_id
                        and result.metadata.invocation_id in {None, str(permit.invocation_id)}
                        and (
                            not result.metadata.attempt_ids
                            or result.metadata.attempt_ids == (str(permit.attempt_id),)
                        )
                    )
                    if result.metadata.status != "success" or not identity_matches:
                        case = case_for(
                            evaluation_run_id,
                            fixture,
                            endpoint,
                            policy_version,
                            tested_revision,
                            status="failed",
                            reason=(
                                "provider_identity_mismatch"
                                if not identity_matches
                                else _safe_result_code(
                                    result.metadata.error_code,
                                    "provider_generation_incomplete",
                                )
                            ),
                            routing_decision_id=decision.routing_decision_id,
                            invocation_id=permit.invocation_id,
                            attempt_id=permit.attempt_id,
                            single_provider_baseline=endpoint.ref == single_provider_baseline,
                            deterministic_strategy_rank=position[0] if position else None,
                            deterministic_strategy_score=position[1] if position else None,
                            deterministic_strategy_baseline=bool(position and position[0] == 1),
                        )
                        self.repository.save_case(case)
                        summaries.append(case)
                        continue

                    if len(result.text) > MAX_OUTPUT_TEXT_CHARS:
                        case = case_for(
                            evaluation_run_id,
                            fixture,
                            endpoint,
                            policy_version,
                            tested_revision,
                            status="failed",
                            reason="evaluation_output_size_limit",
                            routing_decision_id=decision.routing_decision_id,
                            invocation_id=permit.invocation_id,
                            attempt_id=permit.attempt_id,
                            single_provider_baseline=endpoint.ref == single_provider_baseline,
                            deterministic_strategy_rank=position[0] if position else None,
                            deterministic_strategy_score=position[1] if position else None,
                            deterministic_strategy_baseline=bool(position and position[0] == 1),
                        )
                        self.repository.save_case(case)
                        summaries.append(case)
                        continue

                    usage = result.metadata.usage
                    input_count = (
                        usage.input_tokens
                        if usage and usage.input_tokens is not None
                        else prepared_context.token_count
                    )
                    output_count = usage.output_tokens if usage else None
                    count_confidence = _usage_confidence(usage)
                    quota_units = attempt.unit_usage
                    if not attempt.unit_usage:
                        quota_units = (
                            ("requests", 1),
                            ("tokens", prepared_context.token_count + output_tokens),
                        )
                        quota_confidence = "configured"
                    else:
                        quota_confidence = attempt.unit_usage_confidence
                    metrics = score_output(
                        fixture,
                        result.text,
                        input_tokens=input_count,
                        output_tokens=output_count,
                        usage_confidence=count_confidence,
                        latency_ms=attempt.latency_ms,
                        quota_units=quota_units,
                        quota_confidence=quota_confidence,
                    )
                    case = case_for(
                        evaluation_run_id,
                        fixture,
                        endpoint,
                        policy_version,
                        tested_revision,
                        status="measured" if source == "live" else "synthetic_baseline",
                        metrics=metrics,
                        routing_decision_id=decision.routing_decision_id,
                        invocation_id=permit.invocation_id,
                        attempt_id=permit.attempt_id,
                        single_provider_baseline=endpoint.ref == single_provider_baseline,
                        deterministic_strategy_rank=position[0] if position else None,
                        deterministic_strategy_score=position[1] if position else None,
                        deterministic_strategy_baseline=bool(position and position[0] == 1),
                    )
                    case = case.model_copy(
                        update={
                            "preparation_counter_id": preparation.counter_id,
                            "preparation_counter_confidence": preparation.count_confidence,
                            "preparation_count_source": preparation.count_source,
                            "preparation_input_tokens": preparation.input_tokens,
                            "prepared_input_sha256": preparation.prepared_input_sha256,
                        }
                    )
                    self.repository.save_case(case)
                    summaries.append(case)
                    self._buffer_raw_output(
                        raw_output_buffers,
                        raw_output_bytes,
                        evaluation_run_id,
                        endpoint,
                        fixture,
                        result,
                        permit.invocation_id,
                        permit.attempt_id,
                        attempt,
                        source,
                        raw_output_sequences,
                        artifact_publications,
                        retention_approvals,
                    )
            for case in endpoint_cases:
                if case.endpoint in cases_by_endpoint and case not in summaries:
                    self.repository.save_case(case)
                    summaries.append(case)

        self._flush_raw_output_buffers(
            raw_output_buffers,
            raw_output_bytes,
            raw_output_sequences,
            evaluation_run_id,
            profiles,
            artifact_publications,
        )
        # Persisted case summaries intentionally do not duplicate artifact references;
        # Phase20 metadata is queried by its canonical evaluation_run_id link.
        if not summaries:
            raise EvaluationRunConflict("evaluation_matrix_produced_no_cases")
        measured = sum(case.status == "measured" for case in summaries)
        synthetic = sum(case.status == "synthetic_baseline" for case in summaries)
        failed = sum(case.status == "failed" for case in summaries)
        skipped = sum(case.status == "not_run" for case in summaries)
        completed_at = (
            stored_completion.completed_at
            if stored_completion else self.routing_service.current_time(owner_id=self.owner_id)
        )
        if stored_completion is not None:
            summary = stored_completion
        elif source == "synthetic":
            status = (
                "offline_baseline"
                if synthetic == len(summaries)
                else "partial"
                if synthetic or skipped
                else "failed"
            )
        else:
            status = (
                "completed"
                if skipped == 0 and failed == 0 and measured == len(summaries)
                else "partial"
                if measured or skipped
                else "failed"
            )
        strategy_ref = self.deterministic_baseline_strategy.ref
        if stored_completion is None:
            summary = EvaluationRunSummary(
            evaluation_run_id=evaluation_run_id,
            task_profile_id=task.profile_id,
            task_profile_version=task.profile_version,
            task_configuration_sha256=task_configuration_sha256(task),
            evaluation_suite_id=suite_id,
            evaluation_suite_version=suite_version,
            scoring_policy_id=scoring_id,
            scoring_policy_version=scoring_version,
            output_tokens=output_tokens,
            source=source,
            status=status,
            tested_revision=tested_revision,
            configuration_sha256=configuration_digest,
            policy_version=policy_version,
            fixture_manifest_sha256=manifest_sha,
            seed=seed,
            total_cases=len(summaries),
            measured_cases=measured,
            synthetic_cases=synthetic,
            skipped_cases=skipped,
            failed_cases=failed,
            single_provider_baseline_endpoint_profile_id=(
                baseline_profile.endpoint_profile_id if baseline_profile else None
            ),
            single_provider_baseline_endpoint_profile_version=(
                baseline_profile.profile_version if baseline_profile else None
            ),
            single_provider_baseline_configuration_sha256=(
                endpoint_configuration_sha256(baseline_profile) if baseline_profile else None
            ),
            deterministic_strategy_id=strategy_ref.strategy_id,
            deterministic_strategy_version=strategy_ref.semantic_version,
            deterministic_baseline_endpoint_profile_ids=tuple(decision_baselines),
            artifact_publications=tuple(
                EvaluationArtifactPublication(
                    endpoint=endpoint.ref,
                    status=_artifact_publication_status(artifact_publications[endpoint.ref]),
                    artifact_ids=tuple(artifact_publications[endpoint.ref]["artifact_ids"]),
                    error_code=(
                        "artifact_write_not_ready"
                        if artifact_publications[endpoint.ref]["failed"] else None
                    ),
                )
                for endpoint in profiles
            ),
            created_at=created_at,
            completed_at=completed_at,
            )
            self.repository.complete_run(summary)

        quality_profiles: list[QualityProfile] = []
        if source == "live":
            for endpoint in profiles:
                endpoint_cases = tuple(case for case in summaries if case.endpoint == endpoint.ref)
                quality = build_quality_profile(
                    evaluation_run_id=evaluation_run_id,
                    task=task,
                    endpoint=endpoint,
                    policy_version=policy_version,
                    case_summaries=endpoint_cases,
                    tested_revision=tested_revision,
                    fixture_manifest_sha256=manifest_sha,
                    seed=seed,
                    measured_at=completed_at,
                    evaluation_configuration_sha256=configuration_digest,
                    output_tokens=output_tokens,
                    evaluation_suite_id=suite_id,
                    evaluation_suite_version=suite_version,
                    comparison_baseline=baseline_profile,
                )
                if quality is not None:
                    self.repository.save_quality_profile(quality)
                    quality_profiles.append(quality)
        return summary, tuple(summaries), tuple(quality_profiles)

    def _strategy_baseline(self, task, decisions):
        candidates = []
        for decision, _ in decisions:
            candidates.extend(candidate.strategy_view() for candidate in decision.candidates if candidate.eligible)
        if not candidates:
            return ()
        by_endpoint = {candidate.endpoint: candidate for candidate in candidates}
        if len(by_endpoint) != len(candidates):
            raise ValueError("evaluation_strategy_candidate_duplicate")
        result = tuple(
            self.deterministic_baseline_strategy.select(
                StrategyView(preferences=task.preferences, candidates=tuple(by_endpoint.values()))
            )
        )
        if not result or {row.endpoint for row in result} != set(by_endpoint):
            raise ValueError("evaluation_strategy_contract_invalid")
        return result

    def _case(
        self,
        evaluation_run_id,
        fixture,
        endpoint,
        policy_version,
        tested_revision,
        *,
        status,
        reason=None,
        metrics=None,
        routing_decision_id=None,
        invocation_id=None,
        attempt_id=None,
        single_provider_baseline=False,
        deterministic_strategy_baseline=False,
        deterministic_strategy_rank=None,
        deterministic_strategy_score=None,
        evaluation_configuration_sha256,
        output_tokens,
    ):
        return EvaluationCaseSummary(
            evaluation_run_id=evaluation_run_id,
            fixture_id=fixture.fixture_id,
            task_profile_id=fixture.task_profile_id,
            task_profile_version=fixture.task_profile_version,
            evaluation_suite_id=fixture.evaluation_suite_id,
            evaluation_suite_version=fixture.evaluation_suite_version,
            scoring_policy_id=fixture.scoring_policy_id,
            scoring_policy_version=fixture.scoring_policy_version,
            evaluation_configuration_sha256=evaluation_configuration_sha256,
            output_tokens=output_tokens,
            endpoint=endpoint.ref,
            provider_id=endpoint.provider_id,
            model_id=endpoint.model_id,
            account_scope_id=endpoint.account_scope_id,
            credential_scope_id=endpoint.credential_scope_id,
            serializer_id=endpoint.serializer_id,
            runtime_id=endpoint.runtime_id,
            counter_id=endpoint.counter.counter_id if endpoint.counter else None,
            counter_confidence=endpoint.counter.confidence if endpoint.counter else "unknown",
            endpoint_configuration_sha256=endpoint_configuration_sha256(endpoint),
            policy_version=policy_version,
            tested_revision=tested_revision,
            status=status,
            reason=reason,
            routing_decision_id=routing_decision_id,
            invocation_id=invocation_id,
            attempt_id=attempt_id,
            single_provider_baseline=single_provider_baseline,
            deterministic_strategy_baseline=deterministic_strategy_baseline,
            deterministic_strategy_rank=deterministic_strategy_rank,
            deterministic_strategy_score=deterministic_strategy_score,
            metrics=metrics,
            measured_at=self.clock(),
        )

    def _buffer_raw_output(
        self,
        buffers,
        byte_counts,
        evaluation_run_id,
        endpoint,
        fixture,
        result,
        invocation_id,
        attempt_id,
        attempt,
        source,
        sequences,
        publication_state,
        approval_cache,
    ):
        if self.artifact_service is None or len(result.text) > MAX_RETAINED_OUTPUT_CHARS:
            return
        now = self.clock()
        approval = approval_cache.get(endpoint.ref)
        if endpoint.ref not in approval_cache or approval is None or approval.valid_until <= now:
            try:
                approval = self.retention_authority.authorize(
                    evaluation_run_id=evaluation_run_id,
                    endpoint=endpoint,
                    now=now,
                )
                approval = (
                    OutputRetentionApproval.model_validate(approval.model_dump())
                    if approval is not None else None
                )
            except Exception:  # noqa: BLE001 - retention is fail closed and optional
                approval = None
            approval_cache[endpoint.ref] = approval
        if approval is None:
            return
        if (
            approval.evaluation_run_id != evaluation_run_id
            or approval.endpoint != endpoint.ref
            or approval.evidence_source != source
            or approval.account_scope_id != endpoint.account_scope_id
            or approval.valid_until <= now
            or (source == "live" and not self.artifact_service.store.store_id.startswith("gcs:"))
        ):
            return
        publication_state[endpoint.ref]["approved"] = True
        usage = result.metadata.usage
        usage_confidence = _usage_confidence(usage)
        output = {
            "case_id": fixture.fixture_id,
            "task_profile_id": fixture.task_profile_id,
            "endpoint_profile_id": endpoint.endpoint_profile_id,
            "endpoint_profile_version": endpoint.profile_version,
            "provider_id": endpoint.provider_id,
            "model_id": endpoint.model_id,
            "serializer_id": endpoint.serializer_id,
            "runtime_id": endpoint.runtime_id,
            "invocation_id": invocation_id,
            "attempt_id": attempt_id,
            "status": result.metadata.status,
            "output_text": result.text,
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "usage_confidence": usage_confidence,
            "latency_ms": attempt.latency_ms,
        }
        key = (approval.reference, approval.valid_until, endpoint.endpoint_profile_id)
        size = len(
            json.dumps(
                output,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        if key not in buffers:
            buffers[key] = []
            byte_counts[key] = 0
        if buffers[key] and (
            len(buffers[key]) >= MAX_RAW_OUTPUTS_PER_ARTIFACT
            or byte_counts[key] + size > MAX_RAW_OUTPUT_BUFFER_BYTES
        ):
            self._flush_buffer(
                key, buffers, byte_counts, evaluation_run_id, endpoint,
                approval.reference, approval.valid_until,
                sequence=sequences.get(key, 0) + 1,
                publication_state=publication_state,
            )
            sequences[key] = sequences.get(key, 0) + 1
            buffers[key] = []
            byte_counts[key] = 0
        buffers[key].append(output)
        byte_counts[key] += size

    def _flush_raw_output_buffers(
        self, buffers, byte_counts, sequences, evaluation_run_id, profiles, publication_state
    ):
        written = {}
        by_id = {profile.endpoint_profile_id: profile for profile in profiles}
        for key in tuple(buffers):
            reference, valid_until, endpoint_profile_id = key
            endpoint = by_id.get(endpoint_profile_id)
            if endpoint is None:
                buffers.pop(key, None)
                byte_counts.pop(key, None)
                continue
            sequence = sequences.get(key, 0) + 1
            written[key] = self._flush_buffer(
                key, buffers, byte_counts, evaluation_run_id, endpoint, reference, valid_until,
                sequence=sequence,
                publication_state=publication_state,
            )
            sequences[key] = sequence
        return written

    def _flush_buffer(
        self,
        key,
        buffers,
        byte_counts,
        evaluation_run_id,
        endpoint,
        retention_reference,
        retention_until,
        *,
        sequence=None,
        publication_state,
    ):
        values = buffers.pop(key, [])
        raw_bytes = byte_counts.pop(key, 0)
        if not values or self.artifact_service is None:
            return None
        if sequence is None:
            raise ValueError("evaluation_artifact_sequence_required")
        body = {
            "schema_version": "evaluation-raw-outputs-v1",
            "evaluation_run_id": evaluation_run_id,
            "retention_policy_reference": retention_reference,
            "retention_expires_at": retention_until,
            "outputs": values,
        }
        identity_digest = hashlib.sha256(
            (
                f"{evaluation_run_id}:{endpoint.endpoint_profile_id}:"
                f"{retention_reference}:{sequence}"
            ).encode()
        ).hexdigest()[:32]
        try:
            ref = self.artifact_service.write(
                body,
                owner_id=self.owner_id,
                scope=self.scope,
                kind="evaluation",
                identity=f"evaluation:{identity_digest}",
                schema_version="evaluation-raw-outputs-v1",
                sensitivity="public",
                retention_days=ARTIFACT_RETENTION_DAYS,
                source_rights_until=retention_until,
                source_rights_verified=True,
                summary={"case_count": len(values), "output_bytes": raw_bytes},
                evaluation_run_id=evaluation_run_id,
            )
        except Exception:  # noqa: BLE001 - optional retention failures are recorded safely
            ref = None
        state = publication_state[endpoint.ref]
        if ref is None:
            state["failed"] = True
        else:
            state["artifact_ids"].append(ref.artifact_id)
        return ref


def _task_operation(task: RoutingTaskProfile) -> EndpointOperation:
    required = task.required_capabilities
    if "structured_generation" in required:
        return "structured_generation"
    if "bounded_generation" in required:
        return "bounded_generation"
    raise ValueError("evaluation_task_generation_capability_required")


def _run_start_identity(run: EvaluationRunStart):
    return run.model_dump(mode="json", exclude={"created_at", "gate_bindings"})


def _requirements(*, task, fixture, input_tokens, output_tokens):
    from personal_ai.routing.contracts import EndpointCandidateRequirements

    required = task.required_capabilities
    if "token_counting" in required:
        raise ValueError("evaluation_authoritative_counter_flow_unavailable")
    schema_id = fixture.output_schema_id if "structured_generation" in required else None
    return EndpointCandidateRequirements(
        execution_mode="STRICT_FREE",
        sensitivity="public",
        required_capabilities=required,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        structured_schema_id=schema_id,
        automatic=True,
    )


def _messages(fixture: EvaluationFixture):
    return tuple(ChatMessage(role=item.role, content=item.content) for item in fixture.messages)


def _usage_confidence(usage) -> Literal["exact", "derived", "configured", "unknown"]:
    if usage is None:
        return "unknown"
    has_counts = any(
        value is not None
        for value in (usage.input_tokens, usage.output_tokens, usage.total_tokens)
    )
    if not has_counts:
        return "unknown"
    if usage.source == "provider" and usage.confidence == "reported":
        return "exact"
    return "derived"


def _prepared_input_digest(messages, serializer_id=None):
    payload = json.dumps(
        {
            "serializer_id": serializer_id,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _context_manifest_digest(manifest):
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _response_schema(fixture):
    return {
        "type": "object",
        "required": list(fixture.output_schema.required_fields),
        "properties": {
            name: {"type": kind}
            for name, kind in fixture.output_schema.field_types.items()
        },
        "additionalProperties": True,
    }


def _validate_generator(generator, endpoint, operation):
    identity = getattr(generator, "identity", None)
    capabilities = getattr(generator, "capabilities", None)
    if (
        identity is None
        or identity.provider_id != endpoint.provider_id
        or identity.model_id != endpoint.model_id
        or identity.serializer_id != endpoint.serializer_id
        or capabilities is None
        or not capabilities.supports(operation)
    ):
        raise ValueError("evaluation_generation_adapter_mismatch")


def _remaining_seconds(permit):
    remaining = (permit.expires_at - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise TimeoutError("evaluation_dispatch_permit_expired")
    return max(0.001, remaining)


def _case_identity(
    fixture,
    endpoint,
    task,
    *,
    prepared_input_sha256,
    context_manifest_sha256,
    evaluation_suite_sha256,
    output_tokens,
):
    payload = json.dumps(
        {
            "context_manifest_sha256": context_manifest_sha256,
            "evaluation_suite_sha256": evaluation_suite_sha256,
            "endpoint_configuration_sha256": endpoint_configuration_sha256(endpoint),
            "endpoint_profile_id": endpoint.endpoint_profile_id,
            "endpoint_profile_version": endpoint.profile_version,
            "fixture_identity_sha256": fixture.case_identity_sha256,
            "policy_version": fixture.policy_version,
            "prepared_input_sha256": prepared_input_sha256,
            "output_tokens": output_tokens,
            "task_configuration_sha256": task_configuration_sha256(task),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _case_request_id(evaluation_run_id, fixture, endpoint):
    identity = (
        f"{evaluation_run_id}:{fixture.fixture_id}:{endpoint.endpoint_profile_id}:"
        f"{endpoint.profile_version}"
    )
    return "evalcase:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _configuration_digest(
    fixtures,
    task,
    profiles,
    *,
    policy_version,
    tested_revision,
    source,
    seed,
    prepared_identities,
    evaluation_suite_sha256,
    scoring_policy_id,
    scoring_policy_version,
    output_tokens,
    single_provider_baseline,
):
    payload = {
        "endpoint_configurations": sorted(
            (profile.endpoint_profile_id, profile.profile_version,
             endpoint_configuration_sha256(profile))
            for profile in profiles
        ),
        "fixture_manifest_sha256": fixture_manifest_sha256(fixtures),
        "evaluation_suite_sha256": evaluation_suite_sha256,
        "prepared_contexts": sorted(
            (
                fixture_id,
                identity["fixture_input_sha256"],
                identity["context_manifest_sha256"],
                identity["input_tokens"],
                identity["count_source"],
                identity["count_confidence"],
            )
            for fixture_id, identity in prepared_identities.items()
        ),
        "policy_version": policy_version,
        "quality_policy": task.quality.model_dump(mode="json"),
        "seed": seed,
        "output_tokens": output_tokens,
        "single_provider_baseline": (
            {
                "endpoint_profile_id": single_provider_baseline.endpoint_profile_id,
                "profile_version": single_provider_baseline.profile_version,
                "configuration_sha256": endpoint_configuration_sha256(single_provider_baseline),
            }
            if single_provider_baseline is not None else None
        ),
        "scoring_policy_id": scoring_policy_id,
        "scoring_policy_version": scoring_policy_version,
        "source": source,
        "task_configuration_sha256": task_configuration_sha256(task),
        "tested_revision": tested_revision,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _safe_code(error: BaseException, default: str) -> str:
    code = getattr(error, "code", None)
    return _safe_result_code(code, default)


def _safe_result_code(code, default: str) -> str:
    if not isinstance(code, str) or not code or len(code) > 100 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:+/-"
        for character in code
    ):
        return default
    return code


def _artifact_publication_status(state):
    if not state["approved"]:
        return "not_approved"
    if state["failed"] or not state["artifact_ids"]:
        return "publication_failed"
    return "retained"
