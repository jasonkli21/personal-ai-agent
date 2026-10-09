"""Canonical compact persistence for bounded provider-matrix evaluation."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import timedelta
from math import isclose
from statistics import fmean

from personal_ai.evaluation.provider_matrix import wilson_lower_bound
from personal_ai.evaluation.provider_matrix_contracts import (
    EvaluationCaseSummary,
    EvaluationRunStart,
    EvaluationRunSummary,
    QualityProfile,
)
from personal_ai.persistence.postgres import PersistenceConflict, _ensure_namespace
from personal_ai.persistence.postgres_owner_lifecycle import assert_owner_unfenced
from personal_ai.routing.phase21 import (
    EvaluationQualityGate,
    RoutingRequestFacts,
    RoutingTaskProfile,
)

_SYSTEM_OWNER = "personal-ai-system"


class ProviderMatrixRecordUnavailable(LookupError):
    pass


class PostgresProviderMatrixRepository:
    """Postgres owns run/case summaries and versioned quality evidence."""

    def __init__(self, database):
        self.database = database

    @contextmanager
    def transaction(self, *, owner_id):
        with self.database.transaction() as connection:
            assert_owner_unfenced(connection, owner_id)
            yield connection

    def begin_run(self, run: EvaluationRunStart) -> None:
        run = EvaluationRunStart.model_validate(run.model_dump())
        with self.transaction(owner_id=run.owner_id) as connection:
            scope_id = _ensure_namespace(
                connection,
                run.owner_id,
                _scope(run.application_id, run.workspace_id),
            )
            now = _database_time(connection)
            if run.created_at > now:
                raise PersistenceConflict("evaluation_run_creation_in_future")
            payload = run.model_dump(mode="json", exclude={"gate_bindings", "created_at"})
            inserted = connection.execute(
                "INSERT INTO provider_matrix_runs(scope_id,evaluation_run_id,owner_id,application_id,"
                "workspace_id,status,start_payload,created_at) VALUES(%s,%s,%s,%s,%s,'running',%s::jsonb,%s) "
                "ON CONFLICT DO NOTHING RETURNING evaluation_run_id",
                (
                    scope_id,
                    run.evaluation_run_id,
                    run.owner_id,
                    run.application_id,
                    run.workspace_id,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    run.created_at,
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    "SELECT start_payload,created_at FROM provider_matrix_runs "
                    "WHERE scope_id=%s AND evaluation_run_id=%s",
                    (scope_id, run.evaluation_run_id),
                ).fetchone()
                if existing is None or _json_payload(existing[0]) != payload:
                    raise PersistenceConflict("evaluation_run_idempotency_conflict")
                stored_gates = connection.execute(
                    "SELECT gate_payload FROM provider_matrix_cases WHERE scope_id=%s "
                    "AND evaluation_run_id=%s ORDER BY fixture_id,endpoint_profile_id,endpoint_profile_version",
                    (scope_id, run.evaluation_run_id),
                ).fetchall()
                if tuple(EvaluationQualityGate.model_validate(row[0]) for row in stored_gates) != tuple(
                    sorted(
                        run.gate_bindings,
                        key=lambda gate: (
                            gate.fixture_id,
                            gate.endpoint.endpoint_profile_id,
                            gate.endpoint.profile_version,
                        ),
                    )
                ):
                    raise PersistenceConflict("evaluation_run_gate_binding_conflict")
                return
            for gate in run.gate_bindings:
                connection.execute(
                    "INSERT INTO provider_matrix_cases(scope_id,evaluation_run_id,fixture_id,"
                    "endpoint_profile_id,endpoint_profile_version,request_id,case_identity_sha256,status,"
                    "gate_payload,created_at,updated_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,'planned',%s::jsonb,%s,%s)",
                    (
                        scope_id,
                        run.evaluation_run_id,
                        gate.fixture_id,
                        gate.endpoint.endpoint_profile_id,
                        gate.endpoint.profile_version,
                        gate.request_id,
                        gate.case_identity_sha256,
                        gate.model_dump_json(),
                        run.created_at,
                        run.created_at,
                    ),
                )

    def get_run_state(self, evaluation_run_id, *, owner_id=_SYSTEM_OWNER, scope=None):
        scope = scope or _system_scope()
        with self.transaction(owner_id=owner_id) as connection:
            scope_id = _ensure_namespace(connection, owner_id, scope)
            row = connection.execute(
                "SELECT status,start_payload,completion_payload,created_at FROM provider_matrix_runs "
                "WHERE scope_id=%s AND evaluation_run_id=%s",
                (scope_id, evaluation_run_id),
            ).fetchone()
            if row is None:
                raise ProviderMatrixRecordUnavailable("evaluation_run_unavailable")
            gate_rows = connection.execute(
                "SELECT gate_payload FROM provider_matrix_cases WHERE scope_id=%s "
                "AND evaluation_run_id=%s ORDER BY fixture_id,endpoint_profile_id,endpoint_profile_version",
                (scope_id, evaluation_run_id),
            ).fetchall()
            gates = tuple(EvaluationQualityGate.model_validate(item[0]) for item in gate_rows)
            start_payload = _json_payload(row[1])
            start = EvaluationRunStart.model_validate(
                {**start_payload, "created_at": row[3], "gate_bindings": gates}
            )
            completion = (
                EvaluationRunSummary.model_validate(_json_payload(row[2]))
                if row[2] is not None else None
            )
            case_rows = connection.execute(
                "SELECT case_payload FROM provider_matrix_cases WHERE scope_id=%s "
                "AND evaluation_run_id=%s AND status<>'planned' "
                "ORDER BY fixture_id,endpoint_profile_id,endpoint_profile_version",
                (scope_id, evaluation_run_id),
            ).fetchall()
            cases = tuple(EvaluationCaseSummary.model_validate(_json_payload(item[0])) for item in case_rows)
            return start, completion, cases

    def authorize(
        self,
        *,
        connection,
        owner_id,
        scope,
        gate: EvaluationQualityGate,
        task: RoutingTaskProfile,
        request: RoutingRequestFacts,
        now,
    ) -> bool:
        del now
        scope_id = _ensure_namespace(connection, owner_id, scope)
        lock_identity = int.from_bytes(
            hashlib.sha256(f"{scope_id}:{gate.case_identity_sha256}".encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock_identity,))
        run = connection.execute(
            "SELECT status,owner_id,application_id,workspace_id,created_at FROM provider_matrix_runs "
            "WHERE scope_id=%s AND evaluation_run_id=%s",
            (scope_id, gate.evaluation_run_id),
        ).fetchone()
        if run is None or run[:4] != ("running", owner_id, scope.application_id, scope.workspace_id):
            return False
        row = connection.execute(
            "SELECT status,gate_payload FROM provider_matrix_cases WHERE scope_id=%s AND evaluation_run_id=%s "
            "AND fixture_id=%s AND endpoint_profile_id=%s AND endpoint_profile_version=%s",
            (
                scope_id,
                gate.evaluation_run_id,
                gate.fixture_id,
                gate.endpoint.endpoint_profile_id,
                gate.endpoint.profile_version,
            ),
        ).fetchone()
        if row is None or row[0] != "planned":
            return False
        unresolved = connection.execute(
            "SELECT 1 FROM provider_matrix_cases prior "
            "JOIN provider_matrix_runs prior_run ON prior_run.scope_id=prior.scope_id "
            "AND prior_run.evaluation_run_id=prior.evaluation_run_id "
            "LEFT JOIN provider_invocations i ON i.owner_id=prior_run.owner_id "
            "AND i.application_id=prior_run.application_id "
            "AND i.workspace_id IS NOT DISTINCT FROM prior_run.workspace_id "
            "AND i.request_id=prior.request_id "
            "LEFT JOIN provider_attempts a USING(invocation_id) "
            "WHERE prior.scope_id=%s AND prior.case_identity_sha256=%s "
            "AND prior.endpoint_profile_id=%s AND prior.endpoint_profile_version=%s "
                "AND prior.evaluation_run_id<>%s "
                "AND (prior_run.created_at,prior_run.evaluation_run_id)<(%s,%s) "
                "AND (prior_run.status='running' OR a.status IN ('pending','unknown','timeout')) LIMIT 1",
            (
                scope_id,
                gate.case_identity_sha256,
                gate.endpoint.endpoint_profile_id,
                gate.endpoint.profile_version,
                gate.evaluation_run_id,
                run[4],
                gate.evaluation_run_id,
            ),
        ).fetchone()
        if unresolved is not None:
            return False
        try:
            stored_gate = EvaluationQualityGate.model_validate(row[1])
        except (TypeError, ValueError) as error:
            raise RuntimeError("evaluation_gate_binding_invalid") from error
        return stored_gate == gate and (
            request.request_id == gate.request_id
            and request.run_id == str(gate.evaluation_run_id)
            and request.policy_version == gate.policy_version
            and task.profile_id == gate.task_profile_id
            and task.profile_version == gate.task_profile_version
            and task.quality.quality_profile_id == gate.quality_profile_id
            and task.quality.quality_profile_version == gate.quality_profile_version
        )

    def save_case(self, case: EvaluationCaseSummary) -> None:
        case = EvaluationCaseSummary.model_validate(case.model_dump())
        with self.transaction(owner_id=_SYSTEM_OWNER) as connection:
            scope_id = _ensure_namespace(connection, _SYSTEM_OWNER, _system_scope())
            row = connection.execute(
                "SELECT status,gate_payload,case_payload FROM provider_matrix_cases WHERE scope_id=%s "
                "AND evaluation_run_id=%s AND fixture_id=%s AND endpoint_profile_id=%s "
                "AND endpoint_profile_version=%s FOR UPDATE",
                (
                    scope_id,
                    case.evaluation_run_id,
                    case.fixture_id,
                    case.endpoint.endpoint_profile_id,
                    case.endpoint.profile_version,
                ),
            ).fetchone()
            if row is None:
                raise ProviderMatrixRecordUnavailable("evaluation_case_binding_unavailable")
            if row[0] == "planned":
                gate = EvaluationQualityGate.model_validate(row[1])
                if (
                    gate.endpoint != case.endpoint
                    or gate.fixture_id != case.fixture_id
                    or gate.task_profile_id != case.task_profile_id
                    or gate.task_profile_version != case.task_profile_version
                    or gate.policy_version != case.policy_version
                    or gate.endpoint_configuration_sha256 != case.endpoint_configuration_sha256
                ):
                    raise PersistenceConflict("evaluation_case_binding_mismatch")
                connection.execute(
                    "UPDATE provider_matrix_cases SET status=%s,case_payload=%s::jsonb,updated_at=%s "
                    "WHERE scope_id=%s AND evaluation_run_id=%s AND fixture_id=%s "
                    "AND endpoint_profile_id=%s AND endpoint_profile_version=%s AND status='planned'",
                    (
                        case.status,
                        case.model_dump_json(),
                        case.measured_at,
                        scope_id,
                        case.evaluation_run_id,
                        case.fixture_id,
                        case.endpoint.endpoint_profile_id,
                        case.endpoint.profile_version,
                    ),
                )
                return
            existing = EvaluationCaseSummary.model_validate(row[2])
            if existing != case:
                raise PersistenceConflict("evaluation_case_idempotency_conflict")

    def complete_run(self, summary: EvaluationRunSummary) -> None:
        summary = EvaluationRunSummary.model_validate(summary.model_dump())
        with self.transaction(owner_id=_SYSTEM_OWNER) as connection:
            scope_id = _ensure_namespace(connection, _SYSTEM_OWNER, _system_scope())
            run = connection.execute(
                "SELECT status,completion_payload,created_at FROM provider_matrix_runs WHERE scope_id=%s "
                "AND evaluation_run_id=%s FOR UPDATE",
                (scope_id, summary.evaluation_run_id),
            ).fetchone()
            if run is None:
                raise ProviderMatrixRecordUnavailable("evaluation_run_unavailable")
            if run[0] != "running":
                if run[1] == summary.model_dump(mode="json"):
                    return
                raise PersistenceConflict("evaluation_run_completion_conflict")
            if summary.completed_at < run[2]:
                raise PersistenceConflict("evaluation_run_time_invalid")
            counts = connection.execute(
                "SELECT count(*),count(*) FILTER(WHERE status='measured'),"
                "count(*) FILTER(WHERE status='synthetic_baseline'),"
                "count(*) FILTER(WHERE status='not_run'),"
                "count(*) FILTER(WHERE status='failed') "
                "FROM provider_matrix_cases WHERE scope_id=%s AND evaluation_run_id=%s "
                "AND status<>'planned'",
                (scope_id, summary.evaluation_run_id),
            ).fetchone()
            if counts != (
                summary.total_cases,
                summary.measured_cases,
                summary.synthetic_cases,
                summary.skipped_cases,
                summary.failed_cases,
            ):
                raise PersistenceConflict("evaluation_run_case_count_mismatch")
            connection.execute(
                "UPDATE provider_matrix_runs SET status=%s,completion_payload=%s::jsonb,completed_at=%s "
                "WHERE scope_id=%s AND evaluation_run_id=%s AND status='running'",
                (
                    summary.status,
                    summary.model_dump_json(),
                    summary.completed_at,
                    scope_id,
                    summary.evaluation_run_id,
                ),
            )

    def save_quality_profile(self, profile: QualityProfile) -> None:
        profile = QualityProfile.model_validate(profile.model_dump())
        if profile.status != "unpromoted" or profile.revision != 1:
            raise ValueError("quality_profile_must_start_unpromoted")
        with self.transaction(owner_id=_SYSTEM_OWNER) as connection:
            scope_id = _ensure_namespace(connection, _SYSTEM_OWNER, _system_scope())
            self._validate_profile_run(connection, scope_id, profile)
            inserted = connection.execute(
                "INSERT INTO provider_matrix_quality_profiles(scope_id,quality_evidence_id,revision,"
                "evaluation_run_id,task_profile_id,task_profile_version,endpoint_profile_id,"
                "endpoint_profile_version,quality_profile_id,quality_profile_version,policy_version,status,"
                "measured_at,fresh_until,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
                "ON CONFLICT DO NOTHING RETURNING quality_evidence_id",
                _profile_parameters(scope_id, profile),
            ).fetchone()
            if inserted is None:
                row = connection.execute(
                    "SELECT payload FROM provider_matrix_quality_profiles WHERE scope_id=%s "
                    "AND quality_evidence_id=%s AND revision=1",
                    (scope_id, profile.quality_evidence_id),
                ).fetchone()
                if row is None or QualityProfile.model_validate(row[0]) != profile:
                    raise PersistenceConflict("quality_profile_identity_conflict")
                return
            connection.execute(
                "INSERT INTO provider_matrix_quality_heads(scope_id,quality_evidence_id,current_revision,updated_at) "
                "VALUES(%s,%s,1,%s)",
                (scope_id, profile.quality_evidence_id, profile.measured_at),
            )

    def get_quality_profile(self, evidence_id, *, owner_id=_SYSTEM_OWNER, scope=None) -> QualityProfile:
        scope = scope or _system_scope()
        with self.transaction(owner_id=owner_id) as connection:
            scope_id = _ensure_namespace(connection, owner_id, scope)
            row = connection.execute(
                "SELECT p.payload FROM provider_matrix_quality_heads h JOIN provider_matrix_quality_profiles p "
                "ON p.scope_id=h.scope_id AND p.quality_evidence_id=h.quality_evidence_id "
                "AND p.revision=h.current_revision WHERE h.scope_id=%s AND h.quality_evidence_id=%s",
                (scope_id, evidence_id),
            ).fetchone()
            if row is None:
                raise ProviderMatrixRecordUnavailable("quality_profile_unavailable")
            return QualityProfile.model_validate(row[0])

    def publish_quality_profile(
        self,
        profile: QualityProfile,
        *,
        expected_revision: int,
        owner_id=_SYSTEM_OWNER,
        scope=None,
    ) -> None:
        profile = QualityProfile.model_validate(profile.model_dump())
        if profile.revision != expected_revision + 1 or profile.status != "qualified":
            raise ValueError("quality_profile_publication_invalid")
        scope = scope or _system_scope()
        with self.transaction(owner_id=owner_id) as connection:
            scope_id = _ensure_namespace(connection, owner_id, scope)
            row = connection.execute(
                "SELECT p.payload,h.current_revision FROM provider_matrix_quality_heads h "
                "JOIN provider_matrix_quality_profiles p ON p.scope_id=h.scope_id "
                "AND p.quality_evidence_id=h.quality_evidence_id AND p.revision=h.current_revision "
                "WHERE h.scope_id=%s AND h.quality_evidence_id=%s FOR UPDATE OF h",
                (scope_id, profile.quality_evidence_id),
            ).fetchone()
            if row is None:
                raise ProviderMatrixRecordUnavailable("quality_profile_unavailable")
            previous = QualityProfile.model_validate(row[0])
            if row[1] != expected_revision or previous.status != "unpromoted":
                raise PersistenceConflict("quality_profile_revision_conflict")
            _assert_promotion_preserves_measurement(previous, profile)
            now = _database_time(connection)
            if profile.measured_at > now or profile.fresh_until <= now:
                raise PersistenceConflict("quality_profile_freshness_invalid")
            if profile.baseline_evidence_id is not None:
                baseline = connection.execute(
                    "SELECT payload FROM provider_matrix_quality_heads h JOIN provider_matrix_quality_profiles p "
                    "ON p.scope_id=h.scope_id AND p.quality_evidence_id=h.quality_evidence_id "
                    "AND p.revision=h.current_revision WHERE h.scope_id=%s AND h.quality_evidence_id=%s",
                    (scope_id, profile.baseline_evidence_id),
                ).fetchone()
                if baseline is None:
                    raise PersistenceConflict("quality_profile_baseline_unavailable")
                baseline_profile = QualityProfile.model_validate(baseline[0])
                if (
                    not _compatible_baseline(profile, baseline_profile)
                    or baseline_profile.measured_at > now
                    or baseline_profile.fresh_until <= now
                    or profile.score - baseline_profile.score < profile.promotion_minimum_benefit
                ):
                    raise PersistenceConflict("quality_profile_baseline_mismatch")
            elif profile.promotion_minimum_benefit is not None:
                raise PersistenceConflict("quality_profile_baseline_mismatch")
            connection.execute(
                "INSERT INTO provider_matrix_quality_profiles(scope_id,quality_evidence_id,revision,"
                "evaluation_run_id,task_profile_id,task_profile_version,endpoint_profile_id,"
                "endpoint_profile_version,quality_profile_id,quality_profile_version,policy_version,status,"
                "measured_at,fresh_until,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                _profile_parameters(scope_id, profile),
            )
            updated = connection.execute(
                "UPDATE provider_matrix_quality_heads SET current_revision=%s,updated_at=%s "
                "WHERE scope_id=%s AND quality_evidence_id=%s AND current_revision=%s "
                "RETURNING quality_evidence_id",
                (
                    profile.revision,
                    profile.measured_at,
                    scope_id,
                    profile.quality_evidence_id,
                    expected_revision,
                ),
            ).fetchone()
            if updated is None:
                raise PersistenceConflict("quality_profile_revision_conflict")

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
        owner_id=_SYSTEM_OWNER,
        scope=None,
    ):
        scope = scope or _system_scope()
        with self.transaction(owner_id=owner_id) as connection:
            scope_id = _ensure_namespace(connection, owner_id, scope)
            rows = connection.execute(
                "SELECT p.payload FROM provider_matrix_quality_heads h JOIN provider_matrix_quality_profiles p "
                "ON p.scope_id=h.scope_id AND p.quality_evidence_id=h.quality_evidence_id "
                "AND p.revision=h.current_revision WHERE h.scope_id=%s AND p.task_profile_id=%s "
                "AND p.task_profile_version=%s AND p.endpoint_profile_id=%s "
                "AND p.endpoint_profile_version=%s AND p.quality_profile_id=%s "
                "AND p.quality_profile_version=%s AND p.policy_version=%s AND p.status='qualified' "
                "AND p.measured_at<=%s AND p.fresh_until>%s "
                "ORDER BY p.measured_at DESC,p.quality_evidence_id DESC LIMIT 1",
                (
                    scope_id,
                    task_profile_id,
                    task_profile_version,
                    endpoint.endpoint_profile_id,
                    endpoint.profile_version,
                    quality_profile_id,
                    quality_profile_version,
                    policy_version,
                    now,
                    now,
                ),
            ).fetchall()
            profiles = [QualityProfile.model_validate(row[0]) for row in rows]
            return profiles[0].as_routing_evidence() if profiles else None

    def _validate_profile_run(self, connection, scope_id, profile):
        run = connection.execute(
            "SELECT status,completion_payload FROM provider_matrix_runs WHERE scope_id=%s "
            "AND evaluation_run_id=%s",
            (scope_id, profile.evaluation_run_id),
        ).fetchone()
        if run is None or run[0] not in {"completed", "partial"}:
            raise PersistenceConflict("quality_profile_run_not_complete")
        try:
            summary = EvaluationRunSummary.model_validate(run[1])
        except (TypeError, ValueError) as error:
            raise RuntimeError("evaluation_run_completion_invalid") from error
        if (
            summary.tested_revision != profile.tested_revision
            or summary.fixture_manifest_sha256 != profile.fixture_manifest_sha256
            or summary.configuration_sha256 != profile.evaluation_configuration_sha256
            or summary.evaluation_suite_id != profile.evaluation_suite_id
            or summary.evaluation_suite_version != profile.evaluation_suite_version
            or summary.scoring_policy_id != profile.scoring_policy_id
            or summary.scoring_policy_version != profile.scoring_policy_version
            or summary.output_tokens != profile.output_tokens
            or summary.policy_version != profile.policy_version
            or summary.source != "live"
            or summary.task_profile_id != profile.task_profile_id
            or summary.task_profile_version != profile.task_profile_version
            or summary.task_configuration_sha256 != profile.task_configuration_sha256
            or summary.single_provider_baseline_endpoint_profile_id
            != (
                profile.comparison_baseline_endpoint.endpoint_profile_id
                if profile.comparison_baseline_endpoint else None
            )
            or summary.single_provider_baseline_endpoint_profile_version
            != (
                profile.comparison_baseline_endpoint.profile_version
                if profile.comparison_baseline_endpoint else None
            )
            or summary.single_provider_baseline_configuration_sha256
            != profile.comparison_baseline_configuration_sha256
        ):
            raise PersistenceConflict("quality_profile_run_identity_mismatch")
        rows = connection.execute(
            "SELECT gate_payload,status,case_payload FROM provider_matrix_cases WHERE scope_id=%s "
            "AND evaluation_run_id=%s AND endpoint_profile_id=%s AND endpoint_profile_version=%s",
            (
                scope_id,
                profile.evaluation_run_id,
                profile.endpoint.endpoint_profile_id,
                profile.endpoint.profile_version,
            ),
        ).fetchall()
        if not rows:
            raise PersistenceConflict("quality_profile_case_evidence_missing")
        gates = [EvaluationQualityGate.model_validate(row[0]) for row in rows]
        measured = sum(row[1] == "measured" for row in rows)
        cases = [
            EvaluationCaseSummary.model_validate(row[2])
            for row in rows
            if row[1] == "measured" and row[2] is not None
        ]
        if not profile.coverage or abs(profile.coverage - measured / len(rows)) > 1e-9:
            raise PersistenceConflict("quality_profile_coverage_mismatch")
        if (
            measured != profile.sample_count
            or any(row[1] == "planned" for row in rows)
            or any(
                gate.mode != "live"
                or gate.endpoint_configuration_sha256 != profile.endpoint_configuration_sha256
                or gate.task_configuration_sha256 != profile.task_configuration_sha256
                or gate.policy_version != profile.policy_version
                or gate.task_profile_id != profile.task_profile_id
                or gate.task_profile_version != profile.task_profile_version
                for gate in gates
            )
            or len(cases) != measured
        ):
            raise PersistenceConflict("quality_profile_case_evidence_mismatch")
        metrics = [case.metrics for case in cases]
        if not metrics:
            raise PersistenceConflict("quality_profile_measurements_missing")
        expected_score = fmean(metric.overall_score for metric in metrics)
        expected_passed = sum(
            metric.hard_boundaries_passed and metric.overall_score >= profile.minimum_score
            for metric in metrics
        )
        expected_confidence = wilson_lower_bound(expected_passed, len(rows))
        expected_hard = len(cases) == len(rows) and all(
            metric.hard_boundaries_passed for metric in metrics
        )
        expected_metrics = {
            name: fmean(getattr(metric, name) for metric in metrics)
            for name in (
                "schema_validity",
                "citation_precision",
                "citation_coverage",
                "provenance",
                "answer_support",
                "answer_relevance",
                "hard_constraint_satisfaction",
                "privacy",
            )
        }
        if (
            profile.sample_count != len(metrics)
            or not isclose(profile.score, expected_score, abs_tol=1e-9)
            or not isclose(profile.confidence, expected_confidence, abs_tol=1e-9)
            or profile.hard_boundaries_passed != expected_hard
            or any(
                not isclose(profile.mean_metrics.get(key, -1), value, abs_tol=1e-9)
                for key, value in expected_metrics.items()
            )
            or profile.measured_at != summary.completed_at
            or profile.fresh_until - profile.measured_at
            > timedelta(seconds=profile.max_age_seconds)
        ):
            raise PersistenceConflict("quality_profile_measurement_projection_mismatch")


def _profile_parameters(scope_id, profile):
    return (
        scope_id,
        profile.quality_evidence_id,
        profile.revision,
        profile.evaluation_run_id,
        profile.task_profile_id,
        profile.task_profile_version,
        profile.endpoint.endpoint_profile_id,
        profile.endpoint.profile_version,
        profile.quality_profile_id,
        profile.quality_profile_version,
        profile.policy_version,
        profile.status,
        profile.measured_at,
        profile.fresh_until,
        profile.model_dump_json(),
    )


def _assert_promotion_preserves_measurement(previous, current):
    mutable = {
        "revision",
        "status",
        "baseline_evidence_id",
        "promotion_minimum_benefit",
        "quality_evidence_version",
    }
    old = previous.model_dump(mode="json")
    new = current.model_dump(mode="json")
    for key in mutable:
        old.pop(key)
        new.pop(key)
    if old != new or current.quality_evidence_version != previous.quality_evidence_version + 1:
        raise PersistenceConflict("quality_profile_measurement_mutated")


def _compatible_baseline(candidate, baseline):
    return (
        baseline.quality_evidence_id == candidate.baseline_evidence_id
        and baseline.status in {"unpromoted", "qualified"}
        and baseline.endpoint != candidate.endpoint
        and baseline.task_profile_id == candidate.task_profile_id
        and baseline.task_profile_version == candidate.task_profile_version
        and baseline.quality_profile_id == candidate.quality_profile_id
        and baseline.quality_profile_version == candidate.quality_profile_version
        and baseline.policy_version == candidate.policy_version
        and baseline.tested_revision == candidate.tested_revision
        and baseline.seed == candidate.seed
        and baseline.fixture_manifest_sha256 == candidate.fixture_manifest_sha256
        and baseline.evaluation_suite_id == candidate.evaluation_suite_id
        and baseline.evaluation_suite_version == candidate.evaluation_suite_version
        and baseline.evaluation_configuration_sha256 == candidate.evaluation_configuration_sha256
        and baseline.output_tokens == candidate.output_tokens
        and baseline.preparation_counter_id == candidate.preparation_counter_id
        and baseline.preparation_counter_confidence == candidate.preparation_counter_confidence
        and baseline.preparation_count_source == candidate.preparation_count_source
        and baseline.task_configuration_sha256 == candidate.task_configuration_sha256
        and baseline.scoring_policy_id == candidate.scoring_policy_id
        and baseline.scoring_policy_version == candidate.scoring_policy_version
        and baseline.endpoint == candidate.comparison_baseline_endpoint
        and baseline.endpoint_configuration_sha256
        == candidate.comparison_baseline_configuration_sha256
        and baseline.minimum_score == candidate.minimum_score
        and baseline.minimum_coverage == candidate.minimum_coverage
        and baseline.minimum_confidence == candidate.minimum_confidence
        and baseline.minimum_samples == candidate.minimum_samples
        and baseline.minimum_benefit == candidate.minimum_benefit
        and baseline.max_age_seconds == candidate.max_age_seconds
        and baseline.sample_count == candidate.sample_count
        and baseline.coverage >= candidate.minimum_coverage
        and baseline.score >= candidate.minimum_score
        and baseline.confidence >= candidate.minimum_confidence
        and baseline.hard_boundaries_passed
    )


def _database_time(connection):
    return connection.execute("SELECT clock_timestamp()").fetchone()[0]


def _json_payload(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def _scope(application_id, workspace_id):
    from personal_ai.auth.scope import ApplicationScope

    return ApplicationScope(application_id=application_id, workspace_id=workspace_id)


def _system_scope():
    return _scope("personal_ai", None)
