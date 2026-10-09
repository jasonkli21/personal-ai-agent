"""Hard admission, deterministic strategy selection, and plan finalization."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from personal_ai.auth.scope import ApplicationScope
from personal_ai.routing.contracts import (
    CandidateAssessment,
    EndpointCandidateSet,
    confidence_meets,
)
from personal_ai.routing.phase21 import (
    CandidateDecision,
    DispatchRevalidation,
    ExecutionPlan,
    OverflowCandidateRef,
    PreparationIdentity,
    QualityEvidence,
    QuotaReservationRef,
    RoutingDecisionEvent,
    RoutingDecisionObservation,
    RoutingRequestFacts,
    RoutingSignals,
    RoutingStrategyCandidate,
    RoutingStrategyInput,
    RoutingStrategyResult,
    RoutingTaskProfile,
    RuntimeCandidateFacts,
)
from personal_ai.routing.registry import EndpointRegistry, EndpointRegistryError
from personal_ai.routing.strategy import DeterministicScoringStrategy, RoutingStrategy


class RoutingDecisionRepository(Protocol):
    """Structural protocol for the required fail-closed durable decision writer."""

    def begin(self, *, owner_id, scope, observation, initial_event) -> None: ...

    def append_event(self, *, owner_id, scope, decision_id, event): ...

    def get(self, *, owner_id, scope, decision_id): ...

    def begin_reselection(
        self, *, owner_id, scope, observation, initial_event, parent_decision_id,
        max_reselections
    ) -> None: ...


class RoutingFinalizationError(RuntimeError):
    """Preparation, policy, profile, or reservation did not authorize a final plan."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RoutingDecisionResult:
    """Result of a persisted provisional decision; a plan is not a provider call."""

    __slots__ = ("observation", "plan")

    def __init__(self, observation: RoutingDecisionObservation, plan: ExecutionPlan | None):
        self.observation = observation
        self.plan = plan


class RoutingDecisionService:
    """Select only from deterministic hard-eligible endpoint facts.

    This service has no inference client and makes no external provider calls.
    Callers must persist the decision before doing endpoint-specific preparation.
    """

    def __init__(
        self,
        registry: EndpointRegistry,
        observations: RoutingDecisionRepository,
        strategy: RoutingStrategy | None = None,
    ) -> None:
        self.registry = registry
        self.observations = observations
        self.strategy = strategy or DeterministicScoringStrategy()

    def route(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        task: RoutingTaskProfile,
        request: RoutingRequestFacts,
        runtime_facts: Sequence[RuntimeCandidateFacts],
        quality_evidence: Sequence[QualityEvidence] = (),
        routing_signals: Sequence[RoutingSignals] = (),
        parent_decision_id: UUID | None = None,
        dependency_expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> RoutingDecisionResult:
        instant = _aware_utc(now or datetime.now(UTC))
        decision_id = uuid4()
        if request.requirements.execution_mode != "STRICT_FREE" or not request.requirements.automatic:
            raise ValueError("automatic_router_requires_strict_free")
        if not task.required_capabilities.issubset(request.requirements.required_capabilities):
            raise ValueError("routing_task_capability_requirement_mismatch")
        if request.source_manifest_sha256 is None and request.source_count not in {None, 0}:
            raise ValueError("routing_source_manifest_required")

        parent_observation = None
        root_decision_id = decision_id
        reselection_depth = 0
        if parent_decision_id is not None:
            if task.max_reselections < 1:
                raise ValueError("routing_reselection_not_permitted")
            parent_record = self.observations.get(
                owner_id=owner_id,
                scope=scope,
                decision_id=parent_decision_id,
            )
            parent_observation = getattr(parent_record, "observation", parent_record)
            parent_events = getattr(parent_record, "events", ())
            if (
                parent_observation.owner_id != owner_id
                or parent_observation.application_id != scope.application_id
                or parent_observation.workspace_id != scope.workspace_id
                or parent_observation.routing_decision_id != parent_decision_id
                or parent_observation.lifecycle_status != "preparing"
                or parent_observation.provisional_plan is None
                or parent_observation.task != task
                or parent_observation.request.request_id != request.request_id
                or parent_observation.policy_version != request.policy_version
                or parent_observation.request.source_manifest_sha256
                != request.source_manifest_sha256
                or not parent_events
                or parent_events[-1].event_type not in {
                    "preparation_failed", "reservation_failed", "dispatch_failed"
                }
            ):
                raise ValueError("routing_reselection_parent_not_retryable")
            reselection_depth = parent_observation.reselection_depth + 1
            if reselection_depth > task.max_reselections:
                raise ValueError("routing_reselection_budget_exceeded")
            root_decision_id = parent_observation.root_decision_id
            excluded_ids = set(request.excluded_endpoint_profile_ids)
            excluded_ids.add(parent_observation.provisional_plan.selected_endpoint_profile_id)
            request = RoutingRequestFacts.model_validate({
                **request.model_dump(mode="python"),
                "excluded_endpoint_profile_ids": tuple(sorted(excluded_ids)),
            })

        static = self.registry.candidates(request.requirements, now=instant)
        runtime_by_id = _unique_by_id(runtime_facts, lambda row: row.endpoint_profile_id)
        quality_by_id = _unique_by_id(quality_evidence, lambda row: row.endpoint_profile_id)
        signals_by_id = _unique_by_id(routing_signals, lambda row: row.endpoint_profile_id)
        decisions: list[CandidateDecision] = []
        strategy_candidates: list[RoutingStrategyCandidate] = []

        for assessment in static.assessments:
            profile = assessment.profile
            runtime = runtime_by_id.get(profile.endpoint_profile_id)
            quality = quality_by_id.get(profile.endpoint_profile_id)
            signals = signals_by_id.get(profile.endpoint_profile_id)
            reasons = list(assessment.rejection_reasons)
            reasons.extend(_runtime_rejections(profile, runtime, instant))
            if profile.endpoint_profile_id in request.excluded_endpoint_profile_ids:
                reasons.append("endpoint-excluded-after-reselection")
            quality_reasons, quality_is_current = _quality_rejections(
                task, profile, quality, instant
            )
            reasons.extend(quality_reasons)
            eligible = not reasons
            decision = CandidateDecision(
                profile=profile,
                eligible=eligible,
                rejection_reasons=tuple(dict.fromkeys(reasons)),
                runtime_facts=runtime,
                quality_evidence=quality,
                routing_signals=signals,
                configured_priority=task.priority_for(profile.endpoint_profile_id),
            )
            decisions.append(decision)
            if not eligible:
                continue
            usable_signal = _current_signal(signals, profile, instant)
            quality_score = (
                quality.score
                if quality_is_current and quality is not None and task.preferences.quality_weight
                else None
            )
            strategy_candidates.append(RoutingStrategyCandidate(
                profile=profile,
                configured_priority=decision.configured_priority,
                quality_score=quality_score,
                latency_ms=(
                    usable_signal.latency_ms
                    if usable_signal is not None
                    and task.preferences.latency_penalty_per_second
                    else None
                ),
                reliability=(
                    usable_signal.reliability
                    if usable_signal is not None and task.preferences.reliability_weight
                    else None
                ),
                quality_evidence_reference=(
                    quality.evidence_reference if quality_score is not None and quality else None
                ),
                signal_evidence_reference=(
                    usable_signal.evidence_reference if usable_signal is not None else None
                ),
            ))

        eligible_ids = {row.profile.endpoint_profile_id for row in strategy_candidates}
        strategy_task = RoutingTaskProfile.model_validate({
            **task.model_dump(mode="python"),
            "endpoint_priorities": tuple(
                row for row in task.endpoint_priorities
                if row.endpoint_profile_id in eligible_ids
            ),
        })
        strategy_input = RoutingStrategyInput(
            task=strategy_task,
            requirements=request.requirements,
            policy_version=request.policy_version,
            registry_version=static.registry_version,
            candidates=tuple(strategy_candidates),
        )
        strategy_identity = self.strategy.identity(strategy_input)
        strategy_result: RoutingStrategyResult | None = None
        no_route_reason: str | None = None
        plan: ExecutionPlan | None = None
        if not strategy_candidates:
            no_route_reason = "no-eligible-endpoint"
        else:
            try:
                strategy_result = self.strategy.select(strategy_input)
                _validate_strategy_result(strategy_result, strategy_input, strategy_identity)
                selected = next(
                    row.profile for row in strategy_candidates
                    if row.profile.endpoint_profile_id == strategy_result.selected_endpoint_profile_id
                )
                alternative_refs = tuple(
                    (row.profile.endpoint_profile_id, row.profile.profile_version)
                    for row in sorted(
                        strategy_candidates,
                        key=lambda item: item.profile.endpoint_profile_id,
                    )
                    if row.profile.endpoint_profile_id != selected.endpoint_profile_id
                )
                plan = ExecutionPlan(
                    routing_decision_id=decision_id,
                    parent_decision_id=parent_decision_id,
                    reselection_depth=reselection_depth,
                    task_id=task.task_id,
                    task_profile_id=task.profile_id,
                    task_profile_version=task.profile_version,
                    selected_endpoint_profile_id=selected.endpoint_profile_id,
                    selected_profile_version=selected.profile_version,
                    reselection_candidate_refs=alternative_refs,
                    execution_mode=request.requirements.execution_mode,
                    required_capabilities=request.requirements.required_capabilities,
                    validator_id=task.validator_id,
                    validator_version=task.validator_version,
                    escalation_allowed=task.escalation_allowed,
                    cascade_allowed=task.cascade_allowed,
                    max_physical_attempts=task.max_physical_attempts,
                    max_reselections=task.max_reselections,
                    max_auxiliary_calls=task.max_auxiliary_calls,
                    deadline_ms=task.deadline_ms,
                    input_tokens_bound=request.requirements.input_tokens or 0,
                    output_tokens_bound=request.requirements.output_tokens or 0,
                    registry_version=static.registry_version,
                    policy_version=request.policy_version,
                    strategy_id=strategy_identity.strategy_id,
                    strategy_version=strategy_identity.strategy_version,
                    strategy_reason_code=strategy_result.reason_code,
                )
            except Exception:  # noqa: BLE001 - persist a fail-closed no-route for strategy failures.
                no_route_reason = "routing-strategy-contract-invalid"
                plan = None

        replay_until = instant + timedelta(seconds=task.replay_retention_seconds)
        if parent_observation is not None:
            replay_until = min(replay_until, parent_observation.replay_until)
        if dependency_expires_at is not None:
            dependency_expiry = _aware_utc(dependency_expires_at)
            if dependency_expiry <= instant:
                replay_until = min(replay_until, instant + timedelta(seconds=1))
                no_route_reason = no_route_reason or "routing-dependency-expired"
                plan = None
            else:
                replay_until = min(replay_until, dependency_expiry)
        if replay_until <= instant:
            raise ValueError("routing_replay_horizon_invalid")
        lifecycle_status = "preparing" if plan is not None else "no_route"
        observation_values = {
            "routing_decision_id": decision_id,
            "parent_decision_id": parent_decision_id,
            "root_decision_id": root_decision_id,
            "reselection_depth": reselection_depth,
            "owner_id": owner_id,
            "application_id": scope.application_id,
            "workspace_id": scope.workspace_id,
            "created_at": instant,
            "replay_until": replay_until,
            "request": request,
            "task": task,
            "registry_version": static.registry_version,
            "policy_version": request.policy_version,
            "strategy_identity": strategy_identity,
            "lifecycle_status": lifecycle_status,
            "candidates": tuple(decisions),
            "strategy_input": strategy_input,
            "strategy_result": strategy_result,
            "provisional_plan": plan,
            "no_route_reason": no_route_reason,
        }
        observation_probe = RoutingDecisionObservation.model_construct(**observation_values)
        if len(observation_probe.model_dump_json().encode("utf-8")) > 65_536:
            overflow_candidates = tuple(
                OverflowCandidateRef(
                    endpoint_profile_id=row.profile.endpoint_profile_id,
                    profile_version=row.profile.profile_version,
                    profile_facts_sha256=hashlib.sha256(
                        row.profile.model_dump_json().encode("utf-8")
                    ).hexdigest(),
                )
                for row in decisions
            )
            observation_values.update({
                "lifecycle_status": "no_route",
                "replay_completeness": "incomplete",
                "incomplete_reason": "decision-facts-over-64-kib",
                "candidates": (),
                "overflow_candidates": overflow_candidates,
                "strategy_input": None,
                "strategy_result": None,
                "provisional_plan": None,
                "no_route_reason": "routing-observation-overflow",
            })
            plan = None
        observation = RoutingDecisionObservation.model_validate(observation_values)
        initial_event = RoutingDecisionEvent(
            event_type="decision_preparing" if plan is not None else "decision_no_route",
            occurred_at=instant,
            reason_code=no_route_reason,
            endpoint_profile_id=plan.selected_endpoint_profile_id if plan else None,
            outcome_code="provisional-selection" if plan is not None else no_route_reason,
        )
        # A failed observation write aborts before endpoint-specific remote work.
        if parent_decision_id is None:
            self.observations.begin(
                owner_id=owner_id,
                scope=scope,
                observation=observation,
                initial_event=initial_event,
            )
        else:
            self.observations.begin_reselection(
                owner_id=owner_id,
                scope=scope,
                observation=observation,
                initial_event=initial_event,
                parent_decision_id=parent_decision_id,
                max_reselections=task.max_reselections,
            )
        return RoutingDecisionResult(observation, plan)

    def finalize(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        observation: RoutingDecisionObservation,
        preparation: PreparationIdentity,
        reservation: QuotaReservationRef,
        revalidation: DispatchRevalidation,
        now: datetime | None = None,
    ) -> ExecutionPlan:
        """Create a ready plan only after revalidation and durable reservation proof."""
        instant = _aware_utc(now or datetime.now(UTC))
        if (
            observation.owner_id != owner_id
            or observation.application_id != scope.application_id
            or observation.workspace_id != scope.workspace_id
        ):
            raise RoutingFinalizationError("routing_decision_scope_mismatch")
        plan = observation.provisional_plan
        if plan is None or observation.lifecycle_status != "preparing":
            raise RoutingFinalizationError("routing_decision_has_no_plan")
        if instant >= observation.created_at + timedelta(milliseconds=plan.deadline_ms):
            self._record_failure(owner_id, scope, observation, "routing-deadline-expired", instant, revalidation)
            raise RoutingFinalizationError("routing_deadline_expired")
        if revalidation.validated_at > instant or revalidation.fresh_until <= instant:
            self._record_failure(owner_id, scope, observation, "routing-dispatch-revalidation-stale", instant, revalidation)
            raise RoutingFinalizationError("routing_dispatch_revalidation_stale")
        if revalidation.policy_version != observation.policy_version:
            self._record_failure(owner_id, scope, observation, "routing-policy-changed", instant, revalidation)
            raise RoutingFinalizationError("routing_policy_changed")
        if not revalidation.authorization_current or not revalidation.credential_usable:
            self._record_failure(owner_id, scope, observation, "routing-authorization-or-credential-changed", instant, revalidation)
            raise RoutingFinalizationError("routing_authorization_or_credential_changed")
        if revalidation.health_status != "healthy" or not revalidation.quota_not_exhausted:
            self._record_failure(owner_id, scope, observation, "routing-endpoint-health-or-quota-changed", instant, revalidation)
            raise RoutingFinalizationError("routing_endpoint_health_or_quota_changed")
        if not revalidation.sources_authorized:
            self._record_failure(owner_id, scope, observation, "routing-source-permission-revoked", instant, revalidation)
            raise RoutingFinalizationError("routing_source_permission_revoked")
        if (
            revalidation.endpoint_profile_id != plan.selected_endpoint_profile_id
            or revalidation.endpoint_profile_version != plan.selected_profile_version
        ):
            self._record_failure(owner_id, scope, observation, "routing-endpoint-profile-stale", instant, revalidation)
            raise RoutingFinalizationError("routing_endpoint_profile_stale")
        source_identity_matches = (
            observation.request.source_manifest_sha256
            == preparation.source_manifest_sha256
            == revalidation.source_manifest_sha256
        )
        allowed_narrowing = (
            observation.task.allow_source_narrowing
            and revalidation.source_set_narrowed
            and preparation.source_manifest_sha256 == revalidation.source_manifest_sha256
        )
        if not source_identity_matches and not allowed_narrowing:
            self._record_failure(owner_id, scope, observation, "routing-source-set-changed", instant, revalidation)
            raise RoutingFinalizationError("routing_source_set_changed")

        try:
            current = self.registry.revalidate(
                EndpointCandidateSet(
                    registry_version=observation.registry_version,
                    execution_mode=observation.request.requirements.execution_mode,
                    requirements=observation.request.requirements,
                    assessments=tuple(
                        CandidateAssessment(
                            profile=row.profile,
                            eligible=row.eligible,
                            rejection_reasons=row.rejection_reasons,
                        )
                        for row in observation.candidates
                    ),
                ),
                plan.selected_endpoint_profile_id,
                now=instant,
            )
        except EndpointRegistryError as error:
            self._record_failure(owner_id, scope, observation, "routing-endpoint-profile-stale", instant, revalidation)
            raise RoutingFinalizationError("routing_endpoint_profile_stale") from error
        if current.profile_version != plan.selected_profile_version:
            self._record_failure(owner_id, scope, observation, "routing-endpoint-profile-stale", instant, revalidation)
            raise RoutingFinalizationError("routing_endpoint_profile_stale")
        if not _preparation_fits(observation, current, preparation, instant):
            self._record_failure(owner_id, scope, observation, "routing-endpoint-preparation-does-not-fit", instant, revalidation)
            raise RoutingFinalizationError("routing_endpoint_preparation_does_not_fit")
        applicable_buckets = {
            bucket.bucket_id
            for bucket in current.quota_buckets
            if bucket.operations & observation.request.requirements.required_capabilities
        }
        reserved_buckets = {bucket_id for bucket_id, _ in reservation.buckets}
        if reserved_buckets != applicable_buckets:
            self._record_failure(owner_id, scope, observation, "routing-reservation-incomplete", instant, revalidation)
            raise RoutingFinalizationError("routing_reservation_incomplete")

        ready_plan = ExecutionPlan.model_validate({
            **plan.model_dump(mode="python"),
            "state": "ready",
            "preparation": preparation,
            "final_fit": True,
            "reservation": reservation,
        })
        event = RoutingDecisionEvent(
            event_type="reservation_succeeded",
            occurred_at=instant,
            endpoint_profile_id=current.endpoint_profile_id,
            preparation=preparation,
            reservation_id=reservation.reservation_id,
            outcome_code="execution-plan-ready",
            dispatch_revalidation=revalidation,
        )
        # This append must complete before the caller can dispatch the plan.
        self.observations.append_event(
            owner_id=owner_id,
            scope=scope,
            decision_id=observation.routing_decision_id,
            event=event,
        )
        return ready_plan

    def _record_failure(
        self,
        owner_id: str,
        scope: ApplicationScope,
        observation: RoutingDecisionObservation,
        reason_code: str,
        at: datetime,
        revalidation: DispatchRevalidation | None = None,
    ) -> None:
        event_type = (
            "reservation_failed"
            if reason_code == "routing-reservation-incomplete"
            else "preparation_failed"
        )
        self.observations.append_event(
            owner_id=owner_id,
            scope=scope,
            decision_id=observation.routing_decision_id,
            event=RoutingDecisionEvent(
                event_type=event_type,
                occurred_at=at,
                reason_code=reason_code,
                outcome_code="dispatch-denied",
                dispatch_revalidation=revalidation,
            ),
        )


def _runtime_rejections(
    profile,
    facts: RuntimeCandidateFacts | None,
    now: datetime,
) -> tuple[str, ...]:
    if facts is None:
        return ("runtime_admission_facts_missing",)
    reasons: list[str] = []
    if facts.observed_at > now or facts.fresh_until <= now:
        reasons.append("endpoint_runtime_admission_facts_stale")
    if (
        facts.endpoint_profile_id != profile.endpoint_profile_id
        or facts.endpoint_profile_version != profile.profile_version
    ):
        reasons.append("runtime_profile_version_mismatch")
    if facts.authorization != "authorized":
        reasons.append(
            "endpoint_authorization_denied"
            if facts.authorization == "denied"
            else "endpoint_authorization_unknown"
        )
    if facts.credential_status != "usable":
        reasons.append(
            "credential_account_unusable"
            if facts.credential_status == "unusable"
            else "credential_account_usability_unknown"
        )
    if facts.health_status != "healthy":
        reasons.append(f"endpoint_health_{facts.health_status}")
    if facts.cooldown_until is not None and facts.cooldown_until > now:
        reasons.append("endpoint_cooldown_active")
    if facts.exhausted is True:
        reasons.append("endpoint_quota_exhausted")
    return tuple(reasons)


def _quality_rejections(task, profile, evidence, now: datetime) -> tuple[tuple[str, ...], bool]:
    policy = task.quality
    current = _quality_is_current(task, profile, evidence, now)
    if policy.mode == "unmeasured_baseline":
        return (), current
    if evidence is None:
        return ("required_quality_evidence_missing",), False
    if not current:
        return ("required_quality_evidence_stale_or_mismatched",), False
    reasons = []
    if evidence.coverage < policy.minimum_coverage:
        reasons.append("required_quality_coverage_insufficient")
    if evidence.score < policy.minimum_score:
        reasons.append("required_quality_floor_not_met")
    return tuple(reasons), current


def _quality_is_current(task, profile, evidence, now: datetime) -> bool:
    if evidence is None:
        return False
    policy = task.quality
    return (
        evidence.task_profile_id == task.profile_id
        and evidence.task_profile_version == task.profile_version
        and evidence.endpoint_profile_id == profile.endpoint_profile_id
        and evidence.endpoint_profile_version == profile.profile_version
        and (
            policy.quality_profile_id is None
            or evidence.quality_profile_id == policy.quality_profile_id
        )
        and (
            policy.quality_profile_version is None
            or evidence.quality_profile_version == policy.quality_profile_version
        )
        and evidence.measured_at <= now
        and evidence.fresh_until > now
        and (now - evidence.measured_at).total_seconds() <= policy.max_age_seconds
    )


def _current_signal(signals, profile, now: datetime) -> RoutingSignals | None:
    if signals is None:
        return None
    if (
        signals.endpoint_profile_id != profile.endpoint_profile_id
        or signals.endpoint_profile_version != profile.profile_version
        or signals.observed_at > now
        or signals.fresh_until <= now
    ):
        return None
    return signals


def _validate_strategy_result(result, value, identity) -> None:
    if result is None:
        raise ValueError("routing_strategy_returned_no_result")
    if (
        result.strategy_id != identity.strategy_id
        or result.strategy_version != identity.strategy_version
        or result.strategy_implementation_sha256 != identity.strategy_implementation_sha256
        or result.configuration_version != identity.configuration_version
        or result.configuration_sha256 != identity.configuration_sha256
        or result.tie_break_version != identity.tie_break_version
    ):
        raise ValueError("routing_strategy_identity_mismatch")
    available = {
        (row.profile.endpoint_profile_id, row.profile.profile_version)
        for row in value.candidates
    }
    ranked = {
        (row.endpoint_profile_id, row.profile_version)
        for row in result.ranked_candidates
    }
    if not ranked.issubset(available):
        raise ValueError("routing_strategy_ranked_ineligible_endpoint")
    if (
        result.selected_endpoint_profile_id,
        result.selected_profile_version,
    ) not in available:
        raise ValueError("routing_strategy_selected_ineligible_endpoint")


def _preparation_fits(
    observation,
    profile,
    preparation: PreparationIdentity,
    now: datetime,
) -> bool:
    requirements = observation.request.requirements
    if (
        preparation.endpoint_profile_id != profile.endpoint_profile_id
        or preparation.endpoint_profile_version != profile.profile_version
        or preparation.serializer_id != profile.serializer_id
        or preparation.input_tokens > (profile.context_limit_tokens or 0)
        or preparation.input_tokens > (requirements.input_tokens or 0)
    ):
        return False
    if requirements.output_tokens is not None and (
        requirements.output_tokens > (profile.max_output_tokens or 0)
    ):
        return False
    if observation.task.quality.mode == "measured_floor":
        evidence = next(
            (
                row.quality_evidence for row in observation.candidates
                if row.profile.endpoint_profile_id == profile.endpoint_profile_id
            ),
            None,
        )
        if evidence is None or _quality_rejections(
            observation.task, profile, evidence, now
        )[0]:
            return False
    if requirements.count is not None:
        counter = profile.counter
        if (
            counter is None
            or preparation.counter_id != counter.counter_id
            or not confidence_meets(
                preparation.count_confidence, requirements.count.minimum_confidence
            )
        ):
            return False
        required_schema = requirements.count.structured_schema_id or requirements.structured_schema_id
        if required_schema is not None and required_schema not in counter.structured_schema_ids:
            return False
    elif preparation.counter_id is not None and (
        profile.counter is None or preparation.counter_id != profile.counter.counter_id
    ):
        return False
    return True


def _unique_by_id(values: Sequence, get_id) -> dict:
    result = {}
    for value in values:
        identity = get_id(value)
        if identity in result:
            raise ValueError("routing_decision_input_duplicate")
        result[identity] = value
    return result


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("routing_timestamp_must_be_aware")
    return value.astimezone(UTC)
