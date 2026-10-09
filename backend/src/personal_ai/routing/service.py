"""Routing coordination: admission, selection, durable decision and dispatch authority."""

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from personal_ai.persistence.postgres_routing_observations import database_time
from personal_ai.routing.contracts import confidence_meets
from personal_ai.routing.phase21 import (
    MAX_ROUTING_OUTCOME_BYTES,
    MAX_ROUTING_TERMINAL_EVENT_BYTES,
    AuthorizationEvidence,
    CandidateFact,
    DispatchPermit,
    EvaluationQualityGate,
    PreparationIdentity,
    QualityEvidence,
    QuotaBucketDecisionFact,
    QuotaReservationRequirement,
    RoutingDecision,
    RoutingEvent,
    RoutingRequestFacts,
    RoutingSignals,
    RoutingTaskProfile,
    StrategyView,
    endpoint_configuration_sha256,
    quality_identity_sha256,
    reselection_requirements_preserved,
    routing_strategy_configuration_sha256,
    sources_allowed,
    task_configuration_sha256,
)
from personal_ai.routing.strategy import (
    QuotaAwareDeterministicStrategy,
    implementation_sha256_for,
)
from personal_ai.routing.strategy import (
    strategy_dependencies as strategy_dependencies_for,
)
from personal_ai.usage.accounting import unit_reservations
from personal_ai.usage.contracts import AttemptMetadata, InvocationMetadata, UsageAdmissionDenied
from personal_ai.usage.profiles import from_profile


class RoutingAuthorizationAuthority(Protocol):
    """Trusted current endpoint access, credential, policy and source authority.

    Implementations deny by raising, read current authoritative state and never
    authorize from decision-time evidence. No default permissive implementation.
    """

    def authorize(
        self,
        *,
        connection,
        owner_id,
        scope,
        endpoint,
        requirements,
        policy_version,
        source_references,
        now,
    ) -> AuthorizationEvidence: ...


class EvaluationQualityGateAuthority(Protocol):
    """Current run/case authority for the one-case quality bootstrap."""

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


class RoutingFinalizationError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class RoutingAuxiliaryFailure(RoutingFinalizationError):
    """A settled auxiliary send whose known failure may be endpoint-local."""

    def __init__(self, code, *, outcome=None, safe_to_reselect=False):
        self.outcome = outcome
        self.safe_to_reselect = safe_to_reselect
        super().__init__(code)


class RoutingDecisionService:
    def __init__(
        self,
        registry,
        observations,
        strategy=None,
        *,
        usage=None,
        authorization=None,
        evaluation_quality_authority=None,
    ):
        self.registry = registry
        self.observations = observations
        self.strategy = strategy or QuotaAwareDeterministicStrategy()
        self.usage = usage
        self.authorization = authorization
        self.evaluation_quality_authority = evaluation_quality_authority

    def current_time(self, *, owner_id):
        """Return the routing store's clock for persisted lifecycle timestamps."""
        with self.observations.transaction(owner_id=owner_id) as connection:
            return database_time(connection)

    def _authorize_evaluation_gate(self, c, owner_id, scope, gate, task, request, now):
        if gate is None:
            return
        if self.evaluation_quality_authority is None:
            raise RoutingFinalizationError("routing_evaluation_quality_authority_unavailable")
        try:
            allowed = self.evaluation_quality_authority.authorize(
                connection=c,
                owner_id=owner_id,
                scope=scope,
                gate=gate,
                task=task,
                request=request,
                now=now,
            )
        except Exception as error:
            raise RoutingFinalizationError("routing_evaluation_quality_gate_unavailable") from error
        if allowed is not True:
            raise RoutingFinalizationError("routing_evaluation_quality_gate_denied")

    def _authorize(self, c, owner_id, scope, endpoint, request, sources, now):
        if self.authorization is None:
            raise RoutingFinalizationError("routing_authorization_authority_unavailable")
        try:
            evidence = self.authorization.authorize(
                connection=c,
                owner_id=owner_id,
                scope=scope,
                endpoint=endpoint,
                requirements=request.requirements,
                policy_version=request.policy_version,
                source_references=sources,
                now=now,
            )
            evidence = AuthorizationEvidence.model_validate(evidence.model_dump())
        except Exception as error:
            raise RoutingFinalizationError("routing_authorization_unavailable") from error
        checked = database_time(c)
        if (
            evidence.checked_at > checked
            or evidence.checked_at < now
            or evidence.valid_until <= checked
        ):
            raise RoutingFinalizationError("routing_authorization_evidence_stale")
        return evidence

    def route(
        self,
        *,
        owner_id,
        scope,
        task: RoutingTaskProfile,
        request: RoutingRequestFacts,
        quality_evidence: Sequence[QualityEvidence] = (),
        routing_signals: Sequence[RoutingSignals] = (),
        evaluation_quality_gate: EvaluationQualityGate | None = None,
        parent_decision_id=None,
        dependency_expires_at=None,
    ):
        task = RoutingTaskProfile.model_validate(task.model_dump())
        request = RoutingRequestFacts.model_validate(request.model_dump())
        if request.operation is None:
            if len(request.requirements.required_capabilities) != 1:
                raise ValueError("routing_operation_required")
            request = RoutingRequestFacts.model_validate(
                {
                    **request.model_dump(),
                    "operation": next(iter(request.requirements.required_capabilities)),
                }
            )
        if evaluation_quality_gate is not None:
            evaluation_quality_gate = EvaluationQualityGate.model_validate(
                evaluation_quality_gate.model_dump()
            )
            if (
                task.quality.mode != "measured_floor"
                or request.run_id != str(evaluation_quality_gate.evaluation_run_id)
                or evaluation_quality_gate.task_profile_id != task.profile_id
                or evaluation_quality_gate.task_profile_version != task.profile_version
                or evaluation_quality_gate.quality_profile_id != task.quality.quality_profile_id
                or evaluation_quality_gate.quality_profile_version
                != task.quality.quality_profile_version
                or evaluation_quality_gate.policy_version != request.policy_version
            ):
                raise ValueError("routing_evaluation_quality_gate_invalid")
        if (
            request.requirements.execution_mode != "STRICT_FREE"
            or not request.requirements.automatic
        ):
            raise ValueError("automatic_router_requires_strict_free")
        if not task.required_capabilities.issubset(request.requirements.required_capabilities):
            raise ValueError("routing_task_capability_requirement_mismatch")
        decision_id = uuid5(
            NAMESPACE_URL,
            json.dumps(
                [
                    "phase21-root-v1",
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                    request.request_id,
                    request.run_id,
                ],
                separators=(",", ":"),
            ),
        )
        with self.observations.transaction(owner_id=owner_id) as c:
            now = database_time(c)
            self._authorize_evaluation_gate(
                c, owner_id, scope, evaluation_quality_gate, task, request, now
            )
            root_id = decision_id
            depth = 0
            deadline = now + timedelta(milliseconds=task.deadline_ms)
            replay_until = now + timedelta(seconds=task.replay_retention_seconds)
            if parent_decision_id:
                parent = self.observations.lock_root(
                    c, owner_id=owner_id, scope=scope, decision_id=parent_decision_id
                )
                p = parent.decision
                if (
                    p.selected is None
                    or p.task != task
                    or p.request.request_id != request.request_id
                    or p.request.run_id != request.run_id
                    or p.request.operation != request.operation
                    or p.request.policy_version != request.policy_version
                    or not reselection_requirements_preserved(
                        p.request.requirements, request.requirements
                    )
                    or not sources_allowed(p, request.source_reference_sha256s)
                ):
                    raise ValueError("routing_reselection_parent_not_retryable")
                depth = p.reselection_depth + 1
                decision_id = uuid5(parent_decision_id, f"phase21-reselection-v1:{depth}")
                root_id, deadline = p.root_decision_id, p.root_deadline_at
                replay_until = min(replay_until, p.replay_until)
                request = RoutingRequestFacts.model_validate(
                    {
                        **request.model_dump(),
                        "excluded_endpoint_profile_ids": tuple(
                            sorted(
                                set(request.excluded_endpoint_profile_ids)
                                | set(p.request.excluded_endpoint_profile_ids)
                                | {p.selected.endpoint_profile_id}
                            )
                        ),
                    }
                )
            try:
                existing = self.observations.get_in_transaction(
                    c, owner_id=owner_id, scope=scope, decision_id=decision_id, lock=True
                )
            except LookupError:
                existing = None
            if existing:
                if existing.decision.task != task or existing.decision.request != request:
                    raise ValueError("routing_decision_idempotency_conflict")
                return existing.decision
            static = self.registry.candidates(
                request.requirements, now=now, connection=c
            )
            quality = _by_id(quality_evidence, QualityEvidence)
            signals = _by_id(routing_signals, RoutingSignals)
            candidates = []
            quota_snapshots = {}
            quota_snapshot_overflow = False
            assessments = tuple(sorted(
                static.assessments,
                key=lambda item: (item.profile.endpoint_profile_id, item.profile.profile_version),
            ))
            cascade_endpoint = None
            if task.cascade_policy is not None:
                if depth >= len(task.cascade_policy.endpoint_order):
                    raise ValueError("cascade_depth_exhausted")
                cascade_endpoint = task.cascade_policy.endpoint_order[depth]
            authorization_references = {}
            authorization_failures = set()
            authorized_profiles = []
            for assessment in assessments:
                if (cascade_endpoint is not None and assessment.profile.endpoint_profile_id != cascade_endpoint):
                    continue
                if assessment.rejection_reasons or (
                    assessment.profile.endpoint_profile_id in request.excluded_endpoint_profile_ids
                ):
                    continue
                profile = assessment.profile
                try:
                    auth = self._authorize(
                        c,
                        owner_id,
                        scope,
                        profile.ref,
                        request,
                        request.source_reference_sha256s,
                        now,
                    )
                    authorization_references[profile.endpoint_profile_id] = auth.reference
                    authorized_profiles.append(profile)
                except Exception:  # noqa: BLE001 - missing authority/invalid strategy fails closed
                    authorization_failures.add(profile.endpoint_profile_id)

            applicable_bucket_ids = {
                bucket.bucket_id
                for profile in authorized_profiles
                for bucket in profile.quota_buckets
                if request.operation in bucket.operations
            }
            if len(applicable_bucket_ids) > 128:
                # Bound P19 lock work as well as the persisted replay record.
                quota_snapshot_overflow = True

            runtime_by_profile = {}
            runtime_batch_failed = False
            if authorized_profiles:
                if self.usage is None or quota_snapshot_overflow:
                    runtime_batch_failed = True
                else:
                    try:
                        runtime_by_profile = self.usage.routing_snapshots(
                            c,
                            tuple(authorized_profiles),
                            request.requirements,
                            operation=request.operation,
                            now=now,
                        )
                        if set(runtime_by_profile) != {
                            profile.endpoint_profile_id for profile in authorized_profiles
                        }:
                            raise ValueError("provider_usage_batch_snapshot_incomplete")
                    except Exception:  # noqa: BLE001 - a partial batch is not a consistent snapshot
                        runtime_batch_failed = True
                        runtime_by_profile = {}

            for assessment in assessments:
                profile = assessment.profile
                reasons = list(assessment.rejection_reasons)
                if cascade_endpoint is not None and profile.endpoint_profile_id != cascade_endpoint:
                    reasons.append("cascade-stage-excluded")
                references = (
                    [authorization_references[profile.endpoint_profile_id]]
                    if profile.endpoint_profile_id in authorization_references
                    else []
                )
                until = None
                runtime = None
                if profile.endpoint_profile_id in request.excluded_endpoint_profile_ids:
                    reasons.append("endpoint-excluded-after-reselection")
                if not assessment.rejection_reasons and profile.endpoint_profile_id not in request.excluded_endpoint_profile_ids:
                    if profile.endpoint_profile_id in authorization_failures:
                        reasons.append("endpoint_authorization_unavailable")
                    elif self.usage is None or runtime_batch_failed:
                        reasons.append("routing_runtime_authority_unavailable")
                    else:
                        runtime = runtime_by_profile.get(profile.endpoint_profile_id)
                        if runtime is None:
                            reasons.append("routing_runtime_authority_unavailable")
                        else:
                            reasons.extend(runtime.rejection_reasons)
                            for bucket in runtime.quota_buckets:
                                prior = quota_snapshots.get(bucket.bucket_id)
                                if prior is not None and prior != bucket:
                                    reasons.append("routing_runtime_authority_unavailable")
                                    runtime = None
                                    break
                                quota_snapshots[bucket.bucket_id] = bucket
                            if len(quota_snapshots) > 128:
                                quota_snapshot_overflow = True
                q = quality.get(profile.endpoint_profile_id)
                q_current = _quality_current(task, request.policy_version, profile, q, now)
                gate_target = (
                    evaluation_quality_gate is not None
                    and evaluation_quality_gate.endpoint == profile.ref
                )
                evaluation_target = _evaluation_gate_matches(
                    evaluation_quality_gate, task, request, profile
                )
                q_applied = q_current and not evaluation_target
                if gate_target and not evaluation_target:
                    reasons.append("evaluation-gate-profile-identity-mismatch")
                if evaluation_quality_gate is not None and not evaluation_target:
                    reasons.append("evaluation-target-only")
                if task.quality.mode == "measured_floor":
                    if not q_current and not evaluation_target:
                        reasons.append("required_quality_evidence_stale_or_missing")
                    elif q_current and not evaluation_target and (
                        q.score < task.quality.minimum_score
                        or q.coverage < task.quality.minimum_coverage
                        or q.confidence < task.quality.minimum_confidence
                        or q.sample_count < task.quality.minimum_samples
                    ):
                        reasons.append("required_quality_floor_not_met")
                    elif q_current and not evaluation_target:
                        references.append(q.evidence_reference)
                        until = min(
                            q.fresh_until,
                            q.measured_at + timedelta(seconds=task.quality.max_age_seconds),
                        )
                if (
                    q_applied
                    and task.preferences.quality_weight
                    and q.evidence_reference not in references
                ):
                    references.append(q.evidence_reference)
                signal = signals.get(profile.endpoint_profile_id)
                signal_current = (
                    signal is not None
                    and signal.endpoint_profile_version == profile.profile_version
                    and signal.observed_at <= now < signal.fresh_until
                )
                if signal_current:
                    references.append(signal.evidence_reference)
                candidates.append(
                    CandidateFact(
                        endpoint=profile.ref,
                        rejection_reasons=tuple(dict.fromkeys(reasons)),
                        configured_priority=task.priority_for(profile.endpoint_profile_id),
                        quality_score=q.score
                        if q_applied and task.preferences.quality_weight
                        else None,
                        latency_ms=signal.latency_ms
                        if signal_current and task.preferences.latency_penalty_per_second
                        else None,
                        reliability=signal.reliability
                        if signal_current and task.preferences.reliability_weight
                        else None,
                        quota_bucket_ids=(
                            tuple(sorted(bucket.bucket_id for bucket in runtime.quota_buckets))
                            if runtime is not None
                            else ()
                        ),
                        quota_requirements=(
                            tuple(
                                QuotaReservationRequirement(
                                    bucket_id=row.bucket_id,
                                    reservation_units=row.reservation_units,
                                )
                                for row in runtime.quota_requirements
                            )
                            if runtime is not None
                            else ()
                        ),
                        health_status=runtime.health_status if runtime is not None else "unknown",
                        cooldown_until=runtime.cooldown_until if runtime is not None else None,
                        health_failure_streak=(
                            runtime.failure_streak if runtime is not None else 0
                        ),
                        evidence_references=tuple(references),
                        quality_valid_until=until,
                        quality_profile_id=q.quality_profile_id if q_applied else None,
                        quality_profile_version=q.quality_profile_version if q_applied else None,
                        quality_evidence_id=q.quality_evidence_id if q_applied else None,
                        quality_evidence_version=q.quality_evidence_version if q_applied else None,
                        quality_coverage=q.coverage if q_applied else None,
                        quality_confidence=q.confidence if q_applied else None,
                        quality_sample_count=q.sample_count if q_applied else None,
                        quality_identity_sha256=q.quality_identity_sha256 if q_applied else None,
                    )
                )
            if quota_snapshot_overflow:
                quota_snapshots.clear()
                candidates = [
                    candidate.model_copy(
                        update={
                            "rejection_reasons": tuple(
                                dict.fromkeys(
                                    (*candidate.rejection_reasons, "quota-snapshot-overflow")
                                )
                            ),
                            "quota_bucket_ids": (),
                            "quota_requirements": (),
                        }
                    )
                    for candidate in candidates
                ]
            quota_facts = {
                bucket_id: QuotaBucketDecisionFact(
                    bucket_id=bucket.bucket_id,
                    unit=bucket.unit,
                    window_seconds=bucket.window_seconds,
                    window_start=bucket.window_start,
                    reset_at=bucket.reset_at,
                    time_to_reset_seconds=bucket.time_to_reset_seconds,
                    source=bucket.source,
                    confidence=bucket.confidence,
                    evidence_reference=bucket.evidence_reference,
                    limit_units=bucket.limit_units,
                    reported_remaining_units=bucket.reported_remaining_units,
                    consumed_units=bucket.consumed_units,
                    reserved_units=bucket.reserved_units,
                    remaining_units=bucket.remaining_units,
                    observed_at=bucket.observed_at,
                    fresh_until=bucket.fresh_until,
                )
                for bucket_id, bucket in quota_snapshots.items()
            }
            eligible_candidates = tuple(c for c in candidates if c.eligible)
            eligible_bucket_ids = {
                bucket_id
                for candidate in eligible_candidates
                for bucket_id in candidate.quota_bucket_ids
            }
            view = StrategyView(
                preferences=task.preferences,
                candidates=tuple(r.strategy_view() for r in eligible_candidates),
                quota_buckets=tuple(
                    quota_facts[bucket_id]
                    for bucket_id in sorted(eligible_bucket_ids)
                    if bucket_id in quota_facts
                ),
                observed_at=now,
            )
            reason = (
                "quota-snapshot-overflow"
                if quota_snapshot_overflow
                else "no-eligible-endpoint"
                if not view.candidates
                else None
            )
            ranking = ()
            if view.candidates and not quota_snapshot_overflow:
                try:
                    from personal_ai.routing.phase21 import RankedCandidate

                    ranking = tuple(
                        RankedCandidate.model_validate(r.model_dump())
                        for r in self.strategy.select(view)
                    )
                    if (
                        not ranking
                        or len(ranking) != len(view.candidates)
                        or {r.endpoint for r in ranking} != {v.endpoint for v in view.candidates}
                    ):
                        # Strategies rank each eligible endpoint exactly once; decisions validate duplicates.
                        raise ValueError("routing_strategy_contract_invalid")
                except Exception:  # noqa: BLE001 - missing authority/invalid strategy fails closed
                    ranking = ()
                    reason = "routing-strategy-contract-invalid"
            if dependency_expires_at is not None:
                if dependency_expires_at.tzinfo is None:
                    raise ValueError("routing_timestamp_must_be_aware")
                if dependency_expires_at <= now:
                    reason, ranking = "routing-dependency-expired", ()
                else:
                    replay_until = min(replay_until, dependency_expires_at)
            if database_time(c) >= deadline:
                reason, ranking = "routing-deadline-expired", ()
            strategy_dependencies = strategy_dependencies_for(self.strategy)
            strategy_implementation = implementation_sha256_for(self.strategy)
            decision_fields = {
                "schema_version": 5,
                "routing_decision_id": decision_id,
                "root_decision_id": root_id,
                "parent_decision_id": parent_decision_id,
                "reselection_depth": depth,
                "owner_id": owner_id,
                "application_id": scope.application_id,
                "workspace_id": scope.workspace_id,
                "created_at": now,
                "root_deadline_at": deadline,
                "replay_until": replay_until,
                "request": request,
                "task": task,
                "evaluation_quality_gate": evaluation_quality_gate,
                "strategy": self.strategy.ref,
                "strategy_dependencies": strategy_dependencies,
                "strategy_implementation_sha256": strategy_implementation,
                "strategy_tie_break_version": getattr(
                    self.strategy, "tie_break_version", "custom-tie-break-unspecified"
                ),
                "strategy_configuration_sha256": routing_strategy_configuration_sha256(
                    task.preferences, strategy_dependencies
                ),
                "registry_version": static.registry_version,
                "candidates": tuple(candidates),
                "quota_buckets": tuple(
                    quota_facts[bucket_id] for bucket_id in sorted(quota_facts)
                ),
                "ranking": ranking,
                "no_route_reason": reason,
            }
            try:
                decision = RoutingDecision(**decision_fields)
            except ValidationError as error:
                if not any(
                    str(item.get("ctx", {}).get("error", ""))
                    == "routing_decision_payload_too_large"
                    for item in error.errors()
                ):
                    raise
                # Preserve the existing byte bound and persist an explicit
                # no-route outcome rather than truncating replay facts.
                decision_fields.update(
                    candidates=(),
                    quota_buckets=(),
                    ranking=(),
                    no_route_reason="routing-decision-overflow",
                )
                decision = RoutingDecision(**decision_fields)
            # Nested begin would acquire a second connection. Use this exact transaction.
            self.observations.begin_in_transaction(
                c, owner_id=owner_id, scope=scope, decision=decision
            )
            return decision

    def _check_dispatch(self, c, owner_id, scope, record, preparation, operation):
        decision = record.decision
        now = database_time(c)
        if decision.selected is None or now >= decision.root_deadline_at:
            raise RoutingFinalizationError("routing_deadline_or_selection_invalid")
        if preparation.prepared_at < decision.created_at or preparation.prepared_at > now:
            raise RoutingFinalizationError("routing_preparation_stale")
        if preparation.endpoint != decision.selected or not sources_allowed(
            decision, preparation.source_reference_sha256s
        ):
            raise RoutingFinalizationError("routing_preparation_identity_or_sources_changed")
        profile = self.registry.revalidate_selected(
            decision.selected, decision.request.requirements, now=now, connection=c
        )
        requirements = decision.request.requirements
        if operation not in requirements.required_capabilities or (
            decision.request.operation is not None and operation != decision.request.operation
        ):
            raise RoutingFinalizationError("routing_operation_invalid")
        if (
            preparation.serializer_id != profile.serializer_id
            or preparation.input_tokens > (requirements.input_tokens or 0)
            or preparation.input_tokens > (profile.context_limit_tokens or 0)
            or (
                requirements.output_tokens is not None
                and profile.context_limit_tokens is not None
                and preparation.input_tokens + requirements.output_tokens
                > profile.context_limit_tokens
            )
        ):
            raise RoutingFinalizationError("routing_preparation_does_not_fit")
        if requirements.count is not None:
            if (
                profile.counter is None
                or preparation.counter_id != profile.counter.counter_id
                or not confidence_meets(
                    preparation.count_confidence, requirements.count.minimum_confidence
                )
            ):
                raise RoutingFinalizationError("routing_counter_incompatible")
        elif preparation.counter_id is not None and (
            profile.counter is None or preparation.counter_id != profile.counter.counter_id
        ):
            raise RoutingFinalizationError("routing_counter_incompatible")
        candidate = next(r for r in decision.candidates if r.endpoint == decision.selected)
        gate = decision.evaluation_quality_gate
        self._authorize_evaluation_gate(
            c, owner_id, scope, gate, decision.task, decision.request, now
        )
        evaluation_gate_matches = _evaluation_gate_matches(
            gate, decision.task, decision.request, profile
        )
        if gate is not None and not evaluation_gate_matches:
            raise RoutingFinalizationError("routing_evaluation_quality_gate_stale")
        if gate is not None and preparation.prepared_input_sha256 != gate.prepared_input_sha256:
            raise RoutingFinalizationError("routing_evaluation_preparation_identity_mismatch")
        if decision.task.quality.mode == "measured_floor" and not evaluation_gate_matches and (
            candidate.quality_valid_until is None or candidate.quality_valid_until <= now
        ):
            raise RoutingFinalizationError("routing_quality_evidence_expired")
        evidence = self._authorize(
            c,
            owner_id,
            scope,
            profile.ref,
            decision.request,
            preparation.source_reference_sha256s,
            now,
        )
        if self.usage is None:
            raise RoutingFinalizationError("routing_runtime_authority_unavailable")
        reasons = self.usage.runtime_rejections(
            c,
            profile,
            requirements,
            now=database_time(c),
            check_capacity=False,
            operation=operation,
        )
        if reasons:
            raise RoutingFinalizationError(reasons[0])
        return profile, evidence

    def finalize(self, *, owner_id, scope, decision_id, preparation, operation):
        preparation = PreparationIdentity.model_validate(preparation.model_dump())
        failure = None
        permit = None
        with self.observations.transaction(owner_id=owner_id) as c:
            record = self.observations.lock_root(
                c, owner_id=owner_id, scope=scope, decision_id=decision_id
            )
            if record.status == "authorized":
                event = record.events[-1]
                if event.preparation != preparation:
                    raise RoutingFinalizationError("routing_finalization_idempotency_conflict")
                profile, evidence = self._check_dispatch(
                    c, owner_id, scope, record, preparation, operation
                )
                self.usage.reserved_attempt_in_transaction(
                    c,
                    _invocation(record.decision, profile, preparation, operation),
                    event.permit.attempt_id,
                    expected_units=unit_reservations(
                        input_tokens=preparation.input_tokens,
                        output_tokens=record.decision.request.requirements.output_tokens,
                    ),
                    max_attempts=record.decision.task.max_physical_attempts,
                    now=database_time(c),
                )
                if database_time(c) >= event.permit.expires_at:
                    raise RoutingFinalizationError("routing_permit_expired")
                return event.permit
            if record.decision.task.cascade_policy is not None and any(e.validation is not None for e in record.events):
                raise RoutingFinalizationError("cascade_attempt_already_validated")
            if record.status not in {"selected", "failed"}:
                raise RoutingFinalizationError("routing_decision_not_finalizable")
            try:
                # Authorization consumes one event and the next required terminal
                # transition consumes another. Check both before reserving P19.
                record.ensure_append_capacity(
                    event_count=2,
                    event_bytes=(
                        MAX_ROUTING_OUTCOME_BYTES + MAX_ROUTING_TERMINAL_EVENT_BYTES
                    ),
                )
            except ValueError as error:
                raise RoutingFinalizationError(str(error)) from error
            try:
                # A savepoint ensures failed authorization/publication rolls back every reserve.
                with c.transaction():
                    profile, evidence = self._check_dispatch(
                        c, owner_id, scope, record, preparation, operation
                    )
                    now = database_time(c)
                    invocation = _invocation(record.decision, profile, preparation, operation)
                    attempt = self._reserve_physical_attempt(c, record, invocation, now=now)
                    expiry = min(
                        record.decision.root_deadline_at,
                        evidence.valid_until,
                        now + timedelta(seconds=30),
                    )
                    if database_time(c) >= expiry:
                        raise RoutingFinalizationError("routing_permit_expired")
                    permit = DispatchPermit(
                        decision_id=decision_id,
                        invocation_id=invocation.invocation_id,
                        attempt_id=attempt.attempt_id,
                        expires_at=expiry,
                    )
                    self.observations.append_in_transaction(
                        c,
                        scope=scope,
                        record=record,
                        event=RoutingEvent(
                            kind="authorized",
                            occurred_at=database_time(c),
                            preparation=preparation,
                            permit=permit,
                            authorization_reference=evidence.reference,
                            attempt_id=attempt.attempt_id,
                        ),
                    )
            except Exception as error:  # noqa: BLE001 - rollback reserve, record denial
                failure = error
                if record.status == "selected":
                    code = (
                        error.code
                        if isinstance(error, (RoutingFinalizationError, UsageAdmissionDenied))
                        else "routing_authority_unavailable"
                    )
                    self.observations.append_in_transaction(
                        c,
                        scope=scope,
                        record=record,
                        event=RoutingEvent(
                            kind="failed", occurred_at=database_time(c), reason=code
                        ),
                    )
        if failure:
            raise RoutingFinalizationError(
                getattr(failure, "code", "routing_authority_unavailable")
            ) from failure
        return permit

    def claim(self, *, owner_id, scope, permit, operation):
        """Claim once. Receipt validation never substitutes for direct current checks."""
        permit = DispatchPermit.model_validate(permit.model_dump())
        with self.observations.transaction(owner_id=owner_id) as c:
            record = self.observations.lock_root(
                c, owner_id=owner_id, scope=scope, decision_id=permit.decision_id
            )
            if record.status != "authorized" or record.events[-1].permit != permit:
                raise RoutingFinalizationError("routing_permit_not_claimable")
            preparation = record.events[-1].preparation
            profile, evidence = self._check_dispatch(
                c, owner_id, scope, record, preparation, operation
            )
            now = database_time(c)
            if now >= min(permit.expires_at, evidence.valid_until):
                raise RoutingFinalizationError("routing_permit_expired")
            dispatched_event = RoutingEvent(
                kind="dispatched",
                occurred_at=now,
                attempt_id=permit.attempt_id,
                authorization_reference=evidence.reference,
            )
            try:
                # The provider callback is enabled only after both the dispatch
                # event and its eventual closed/failed event fit in the record.
                record.ensure_append_capacity(
                    event_count=2,
                    event_bytes=(
                        len(dispatched_event.model_dump_json().encode("utf-8"))
                        + MAX_ROUTING_TERMINAL_EVENT_BYTES
                    ),
                )
            except ValueError as error:
                raise RoutingFinalizationError(str(error)) from error
            invocation = _invocation(record.decision, profile, preparation, operation)
            attempt = self.usage.reserved_attempt_in_transaction(
                c,
                invocation,
                permit.attempt_id,
                expected_units=unit_reservations(
                    input_tokens=preparation.input_tokens,
                    output_tokens=record.decision.request.requirements.output_tokens,
                ),
                max_attempts=record.decision.task.max_physical_attempts,
                now=now,
            )
            self._claim_physical_attempt(c, record, invocation, attempt, now=now)
            self.observations.append_in_transaction(
                c,
                scope=scope,
                record=record,
                event=dispatched_event,
            )
            invocation = _invocation(record.decision, profile, preparation, operation)
            if database_time(c) >= min(
                permit.expires_at, evidence.valid_until, record.decision.root_deadline_at
            ):
                raise RoutingFinalizationError("routing_permit_expired")
        if self.current_time(owner_id=owner_id) >= min(permit.expires_at, evidence.valid_until):
            raise RoutingFinalizationError("routing_permit_expired")
        return profile, invocation, attempt

    def dispatch(self, *, owner_id, scope, permit, operation, send, validate=None):
        """Internal transport seam. Callback receives the exact committed attempt.

        Callback must perform one send and return (value, neutral AttemptResult).
        Any exception keeps conservative unknown accounting and closes no success.
        Application workflows remain gated on Phase 15; there is no HTTP route.
        """
        with self.observations.transaction(owner_id=owner_id) as c:
            record = self.observations.get_in_transaction(
                c, owner_id=owner_id, scope=scope, decision_id=permit.decision_id, lock=True
            )
        if record.decision.task.cascade_policy is not None and validate is None:
            raise RoutingFinalizationError("cascade_validation_required")
        profile, invocation, attempt = self.claim(
            owner_id=owner_id, scope=scope, permit=permit, operation=operation
        )
        if self.current_time(owner_id=owner_id) >= record.decision.root_deadline_at:
            # Keep the claimed attempt fenced; no callback has run, and an
            # incomplete dispatch event must not be replayed as a terminal result.
            raise RoutingFinalizationError("routing_deadline_expired")
        try:
            value, _result = self._send_and_settle(profile, invocation, attempt, send)
        except BaseException:
            self.finish(owner_id=owner_id, scope=scope, decision_id=permit.decision_id)
            raise
        validation = None
        if validate is not None:
            from personal_ai.validation.tasks import ValidationResult
            try:
                from personal_ai.llm.client import GenerationResult
                if record.decision.task.cascade_policy is not None and (
                    not isinstance(value, GenerationResult)
                    or (value.metadata.identity.provider_id, value.metadata.identity.model_id,
                        value.metadata.identity.serializer_id)
                    != (profile.provider_id, profile.model_id, profile.serializer_id)
                ):
                    validation = ValidationResult(accepted=False, reasons=("producing_endpoint_mismatch",))
                elif self.current_time(owner_id=owner_id) >= record.decision.root_deadline_at:
                    validation = ValidationResult(accepted=False, reasons=("deadline_exhausted",))
                else:
                    validation = ValidationResult.model_validate(validate(value).model_dump())
            except Exception:  # noqa: BLE001 - validator failure never exposes buffered output
                validation = ValidationResult(accepted=False, reasons=("validator_failed",))
        self.finish(
            owner_id=owner_id,
            scope=scope,
            decision_id=permit.decision_id,
            validation=validation,
        )
        if validation is not None and not validation.accepted:
            return None
        return value

    def _send_and_settle(self, profile, invocation, attempt, send):
        try:
            value, result = send(profile, invocation, attempt)
            from personal_ai.usage.contracts import AttemptResult

            if (
                not isinstance(result, AttemptResult)
                or result.outcome
                not in {
                    "success",
                    "incomplete",
                    "rejected",
                    "rate_limited",
                    "server_error",
                    "timeout",
                    "failure",
                    "unknown",
                }
                or result.completed_at.tzinfo is None
            ):
                raise TypeError("routing_transport_result_invalid")
        except BaseException:
            from personal_ai.usage.contracts import AttemptResult

            result = AttemptResult(
                outcome="unknown",
                completed_at=max(
                    self.current_time(owner_id=invocation.owner_id), attempt.started_at
                ),
                latency_ms=0,
            )
            self.usage.settle_attempt(invocation, attempt, result)
            self.usage.complete_invocation(
                invocation, outcome=result.outcome, completed_at=result.completed_at
            )
            raise
        authoritative_completion = max(
            self.current_time(owner_id=invocation.owner_id), attempt.started_at
        )
        result = replace(result, completed_at=authoritative_completion)
        self.usage.settle_attempt(invocation, attempt, result)
        self.usage.complete_invocation(
            invocation, outcome=result.outcome, completed_at=result.completed_at
        )
        return value, result

    def dispatch_auxiliary(self, *, owner_id, scope, decision_id, event_id,
                           operation, input_tokens, source_references, send):
        """One explicitly admitted auxiliary physical send, under root bounds.

        The auxiliary event is the single-use identity; incomplete or unknown
        outcomes fence the same P19 request. No nested SDK accounting/retry.
        """
        from dataclasses import replace

        from personal_ai.routing.contracts import CountRequirement, EndpointCandidateRequirements

        if operation != "token_counting":
            raise RoutingFinalizationError("routing_auxiliary_operation_unsupported")
        self.consume_auxiliary_call(owner_id=owner_id, scope=scope,
                                    decision_id=decision_id, event_id=event_id)
        with self.observations.transaction(owner_id=owner_id) as c:
            record = self.observations.lock_root(
                c, owner_id=owner_id, scope=scope, decision_id=decision_id
            )
            decision = record.decision
            now = database_time(c)
            if (record.status != "selected" or now >= decision.root_deadline_at
                or decision.task.cascade_policy is None
                or not sources_allowed(decision, source_references)
                or not 0 <= input_tokens <= decision.request.requirements.input_tokens):
                raise RoutingFinalizationError("routing_auxiliary_not_permitted")
            requirements = EndpointCandidateRequirements(
                execution_mode="STRICT_FREE", sensitivity=decision.request.requirements.sensitivity,
                required_capabilities=frozenset({"token_counting"}), input_tokens=input_tokens,
                count=CountRequirement(minimum_confidence="authoritative",
                    structured_schema_id=decision.request.requirements.structured_schema_id),
            )
            profile = self.registry.revalidate_selected(
                decision.selected, requirements, now=now, connection=c
            )
            auxiliary_request = decision.request.model_copy(update={
                "operation": operation, "requirements": requirements,
            })
            evidence = self._authorize(c, owner_id, scope, profile.ref, auxiliary_request,
                                       source_references, now)
            invocation = replace(
                _invocation(decision, profile, None, operation),
                invocation_id=uuid5(decision_id, f"auxiliary:{event_id}"),
                input_tokens_estimate=input_tokens, output_tokens_bound=0,
            )
            self.usage.assert_invocation_unstarted_in_transaction(c, invocation)
            try:
                attempt = self._reserve_physical_attempt(c, record, invocation, now=now)
            except UsageAdmissionDenied as error:
                if error.code in {"provider_quota_exhausted", "provider_endpoint_cooling_down"}:
                    raise RoutingAuxiliaryFailure(
                        error.code, safe_to_reselect=True
                    ) from error
                raise
            self._claim_physical_attempt(c, record, invocation, attempt, now=now)
            expiry = min(decision.root_deadline_at, evidence.valid_until)
            if database_time(c) >= expiry:
                raise RoutingFinalizationError("routing_auxiliary_expired")
        if self.current_time(owner_id=owner_id) >= expiry:
            raise RoutingFinalizationError("routing_auxiliary_expired")
        value, result = self._send_and_settle(profile, invocation, attempt, send)
        if result.outcome != "success":
            raise RoutingAuxiliaryFailure(
                "routing_auxiliary_incomplete", outcome=result.outcome,
                safe_to_reselect=result.outcome not in {"unknown", "timeout"},
            )
        if self.current_time(owner_id=owner_id) >= expiry:
            raise RoutingAuxiliaryFailure(
                "routing_auxiliary_expired", outcome=result.outcome,
                safe_to_reselect=False,
            )
        return value

    def _reserve_physical_attempt(self, c, record, invocation, *, now):
        units = unit_reservations(input_tokens=invocation.input_tokens_estimate,
                                  output_tokens=invocation.output_tokens_bound)
        attempt = AttemptMetadata(
            attempt_id=uuid5(invocation.invocation_id, "provider-attempt:1"),
            parent_attempt_id=None, send_number=1, started_at=now,
            reservation_units=units, reserved_tokens=dict(units).get("tokens", 0),
        )
        attempt = self.usage.reserve_attempt_in_transaction(
            c, invocation, attempt, max_attempts=record.decision.task.max_physical_attempts,
        )
        self._check_cascade_budget(c, record, invocation)
        return attempt

    def _claim_physical_attempt(self, c, record, invocation, attempt, *, now):
        self._check_cascade_budget(c, record, invocation)
        self.usage.claim_attempt_in_transaction(c, attempt.attempt_id, now=now)

    def _check_cascade_budget(self, connection, record, invocation):
        policy = record.decision.task.cascade_policy
        if policy is not None:
            self.usage.assert_request_budget_in_transaction(
                connection, invocation, max_reserved_tokens=policy.max_reserved_tokens,
                quota_limits=policy.quota_limits,
            )

    def finish(self, *, owner_id, scope, decision_id, reason="coordination-failed", validation=None):
        with self.observations.transaction(owner_id=owner_id) as c:
            record = self.observations.lock_root(
                c, owner_id=owner_id, scope=scope, decision_id=decision_id
            )
            kind = "failed"
            terminal_attempt_id = None
            if record.status == "dispatched":
                dispatched = next(e for e in reversed(record.events) if e.kind == "dispatched")
                receipt = next(
                    e.permit
                    for e in reversed(record.events)
                    if e.kind == "authorized" and e.attempt_id == dispatched.attempt_id
                )
                terminal_attempt_id = dispatched.attempt_id
                if (validation is not None and validation.accepted
                    and database_time(c) >= record.decision.root_deadline_at):
                    from personal_ai.validation.tasks import ValidationResult
                    validation = ValidationResult(
                        accepted=False, reasons=("deadline_exhausted",)
                    )
                outcome = self.usage.attempt_outcome_in_transaction(
                    c, receipt.invocation_id, dispatched.attempt_id
                )
                if record.decision.task.cascade_policy is not None and validation is None and outcome == "success":
                    from personal_ai.validation.tasks import ValidationResult
                    validation = ValidationResult(accepted=False, reasons=("validation_unavailable",))
                accepted = validation is None or validation.accepted
                kind = "closed" if outcome == "success" and accepted else "failed"
                if validation is not None and outcome != "success" and validation.accepted:
                    raise RoutingFinalizationError("cascade_non_success_validation")
                reason = "validation-rejected" if validation is not None and not validation.accepted else "attempt-completed"
            self.observations.append_in_transaction(
                c,
                scope=scope,
                record=record,
                event=RoutingEvent(
                    kind=kind,
                    occurred_at=database_time(c),
                    reason=reason,
                    validation=validation,
                    attempt_id=terminal_attempt_id,
                ),
            )

    def consume_auxiliary_call(self, **kwargs):
        return self.observations.consume_auxiliary_call(**kwargs)


def _invocation(decision, profile, preparation, operation):
    return InvocationMetadata(
        invocation_id=uuid5(decision.routing_decision_id, f"invocation:{operation}"),
        owner_id=decision.owner_id,
        application_id=decision.application_id,
        workspace_id=decision.workspace_id,
        task_id=decision.task.task_id,
        operation=operation,
        request_id=decision.request.request_id,
        run_id=decision.request.run_id,
        endpoint=from_profile(profile),
        routing_decision_id=str(decision.routing_decision_id),
        routing_strategy_id=decision.strategy.strategy_id,
        routing_strategy_version=decision.strategy.semantic_version,
        policy_version=decision.request.policy_version,
        input_tokens_estimate=preparation.input_tokens if preparation else None,
        output_tokens_bound=decision.request.requirements.output_tokens,
    )


def _by_id(values, model):
    result = {}
    for value in values:
        value = model.model_validate(value.model_dump())
        if value.endpoint_profile_id in result:
            raise ValueError("routing_evidence_duplicate")
        result[value.endpoint_profile_id] = value
    return result


def _evaluation_gate_matches(gate, task, request, profile):
    return gate is not None and (
        gate.endpoint == profile.ref
        and gate.request_id == request.request_id
        and request.run_id == str(gate.evaluation_run_id)
        and gate.task_profile_id == task.profile_id
        and gate.task_profile_version == task.profile_version
        and gate.quality_profile_id == task.quality.quality_profile_id
        and gate.quality_profile_version == task.quality.quality_profile_version
        and gate.policy_version == request.policy_version
        and gate.endpoint_configuration_sha256 == endpoint_configuration_sha256(profile)
        and gate.task_configuration_sha256 == task_configuration_sha256(task)
    )


def _quality_current(task, policy_version, profile, evidence, now):
    policy = task.quality
    return evidence is not None and (
        evidence.task_profile_id == task.profile_id
        and evidence.task_profile_version == task.profile_version
        and evidence.endpoint_profile_id == profile.endpoint_profile_id
        and evidence.endpoint_profile_version == profile.profile_version
        and evidence.provider_id == profile.provider_id
        and evidence.model_id == profile.model_id
        and evidence.endpoint_id == profile.endpoint_id
        and evidence.deployment_id == profile.deployment_id
        and evidence.account_scope_id == profile.account_scope_id
        and evidence.credential_scope_id == profile.credential_scope_id
        and evidence.serializer_id == profile.serializer_id
        and evidence.runtime_id == profile.runtime_id
        and evidence.counter_id == (profile.counter.counter_id if profile.counter else None)
        and evidence.counter_confidence
        == (profile.counter.confidence if profile.counter else "unknown")
        and evidence.endpoint_configuration_sha256 == endpoint_configuration_sha256(profile)
        and evidence.task_configuration_sha256 == task_configuration_sha256(task)
        and evidence.quality_identity_sha256
        == quality_identity_sha256(
            endpoint_digest=evidence.endpoint_configuration_sha256,
            task_digest=evidence.task_configuration_sha256,
            policy_version=policy_version,
            quality_profile_id=evidence.quality_profile_id,
            quality_profile_version=evidence.quality_profile_version,
            scoring_policy_id=evidence.scoring_policy_id,
            scoring_policy_version=evidence.scoring_policy_version,
            tested_revision=evidence.tested_revision,
            evaluation_suite_id=evidence.evaluation_suite_id,
            evaluation_suite_version=evidence.evaluation_suite_version,
            fixture_manifest_sha256=evidence.fixture_manifest_sha256,
            evaluation_configuration_sha256=evidence.evaluation_configuration_sha256,
            output_tokens=evidence.output_tokens,
            preparation_counter_id=evidence.preparation_counter_id,
            preparation_counter_confidence=evidence.preparation_counter_confidence,
            preparation_count_source=evidence.preparation_count_source,
        )
        and evidence.policy_version == policy_version
        and (
            policy.quality_profile_id is None
            or policy.quality_profile_id == evidence.quality_profile_id
        )
        and (
            policy.quality_profile_version is None
            or policy.quality_profile_version == evidence.quality_profile_version
        )
        and evidence.measured_at <= now < evidence.fresh_until
        and (now - evidence.measured_at).total_seconds() <= policy.max_age_seconds
    )
