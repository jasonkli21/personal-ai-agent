"""Bounded buffered task orchestration over the P21/P19 lifecycle.

No public workflow enables this coordinator. Preparation and validation are
trusted registered capabilities; output is returned only after durable acceptance.
"""

from dataclasses import dataclass, replace
from uuid import uuid5

from personal_ai.llm.client import GenerationResult, InferenceContext
from personal_ai.routing.phase21 import PreparationIdentity, sources_allowed
from personal_ai.validation.tasks import ValidationInput, ValidationResult


class CascadeRejected(RuntimeError):
    pass


class EndpointLocalPreparationFailure(CascadeRejected):
    """Known endpoint-specific failure before generation, safe to reselect."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PreparedCascadeInput:
    identity: PreparationIdentity
    validation: ValidationInput
    send: object  # one-send neutral callback(profile, invocation, attempt) -> (value, AttemptResult)
    synthetic: bool = False


@dataclass(frozen=True)
class CascadeResult:
    generation: GenerationResult
    root_decision_id: object
    accepted_decision_id: object
    accepted_attempt_id: object
    endpoint: object


class CascadeCoordinator:
    def __init__(self, routing, validators):
        self.routing = routing
        self.validators = validators

    def execute(self, *, owner_id, scope, task, request, prepare, quality_evidence=(),
                dependency_expires_at=None):
        # Revalidate caller-owned containers before any source/model work.
        task = type(task).model_validate(task.model_dump())
        request = type(request).model_validate(request.model_dump())
        policy = task.cascade_policy
        if policy is None:
            raise CascadeRejected("cascade_policy_required")
        validator = self.validators.resolve(task.validator_id, task.validator_version)
        if (validator.input_contract_id != policy.input_contract_id
            or validator.output_contract_id != policy.output_contract_id):
            raise CascadeRejected("cascade_validator_contract_mismatch")
        if request.operation not in {"bounded_generation", "structured_generation"}:
            raise CascadeRejected("cascade_buffered_operation_required")
        if (request.operation == "structured_generation"
            and request.requirements.structured_schema_id != policy.output_contract_id):
            raise CascadeRejected("cascade_output_schema_contract_mismatch")
        parent = None
        frozen_validation = None
        for _ in policy.endpoint_order:
            decision = self.routing.route(
                owner_id=owner_id, scope=scope, task=task, request=request,
                quality_evidence=quality_evidence, parent_decision_id=parent,
                dependency_expires_at=dependency_expires_at,
            )
            if decision.selected is None:
                raise CascadeRejected("cascade_no_eligible_endpoint")
            # Recovery never repeats completed, dispatched, or uncertain sends.
            with self.routing.observations.transaction(owner_id=owner_id) as c:
                record = self.routing.observations.lock_root(
                    c, owner_id=owner_id, scope=scope, decision_id=decision.routing_decision_id
                )
                if record.status != "selected":
                    raise CascadeRejected("cascade_operation_already_started")
            remaining = (
                decision.root_deadline_at - self.routing.current_time(owner_id=owner_id)
            ).total_seconds()
            if remaining <= 0:
                raise CascadeRejected("cascade_deadline_exhausted")
            try:
                prepared = prepare(decision, remaining)
            except Exception as error:
                safe_to_reselect = isinstance(error, EndpointLocalPreparationFailure) or (
                    getattr(error, "safe_to_reselect", False) is True
                )
                if not safe_to_reselect:
                    raise
                reason = getattr(error, "code", "cascade_endpoint_preparation_failed")
                self._reselect_after_known_endpoint_failure(
                    owner_id=owner_id, scope=scope, decision=decision, reason=reason
                )
                parent = decision.routing_decision_id
                continue
            identity = PreparationIdentity.model_validate(prepared.identity.model_dump())
            inputs = ValidationInput.model_validate(prepared.validation.model_dump())
            profile = self.routing.registry.revalidate_selected(
                decision.selected, decision.request.requirements,
                now=self.routing.current_time(owner_id=owner_id),
            )
            if prepared.synthetic:
                if (profile.strict_free_attestation is None
                    or profile.strict_free_attestation.source != "synthetic_test"):
                    raise CascadeRejected("cascade_synthetic_endpoint_required")
            elif identity.count_confidence != "authoritative" or identity.counter_id is None:
                raise CascadeRejected("cascade_authoritative_preparation_required")
            if (inputs.input_contract_id != policy.input_contract_id
                or inputs.output_contract_id != policy.output_contract_id
                or not sources_allowed(decision, identity.source_reference_sha256s)
                or {s.reference_sha256 for s in inputs.sources}
                != set(identity.source_reference_sha256s)):
                raise CascadeRejected("cascade_prepared_contract_mismatch")
            if frozen_validation is None:
                frozen_validation = inputs
            else:
                frozen_sources = {s.source_id: s for s in frozen_validation.sources}
                if (inputs.model_dump(exclude={"sources"})
                    != frozen_validation.model_dump(exclude={"sources"})
                    or any(frozen_sources.get(s.source_id) != s for s in inputs.sources)):
                    raise CascadeRejected("cascade_frozen_validation_changed")
            try:
                permit = self.routing.finalize(
                    owner_id=owner_id, scope=scope, decision_id=decision.routing_decision_id,
                    preparation=identity, operation=request.operation,
                )
            except Exception as error:
                code = getattr(error, "code", "")
                if code not in {
                    "routing_preparation_does_not_fit",
                    "routing_counter_incompatible",
                    "routing_quality_evidence_expired",
                    "provider_quota_exhausted",
                    "provider_endpoint_cooling_down",
                }:
                    raise
                parent = decision.routing_decision_id
                continue

            def validate(value, decision=decision, inputs=inputs, identity=identity):
                if not isinstance(value, GenerationResult):
                    return ValidationResult(accepted=False, reasons=("generation_contract_invalid",))
                if value.metadata.status != "success":
                    return ValidationResult(accepted=False, reasons=("generation_incomplete",))
                if (value.metadata.usage is not None
                    and value.metadata.usage.output_tokens is not None
                    and value.metadata.usage.output_tokens > decision.request.requirements.output_tokens):
                    return ValidationResult(accepted=False, reasons=("token_budget_exceeded",))
                if len(value.text.encode("utf-8")) > policy.max_output_bytes:
                    return ValidationResult(accepted=False, reasons=("output_budget_exceeded",))
                if self.routing.current_time(owner_id=owner_id) >= decision.root_deadline_at:
                    return ValidationResult(accepted=False, reasons=("deadline_exhausted",))
                return validator.validate(inputs, value.text)

            value = self.routing.dispatch(
                owner_id=owner_id, scope=scope, permit=permit, operation=request.operation,
                send=prepared.send, validate=validate,
            )
            with self.routing.observations.transaction(owner_id=owner_id) as c:
                record = self.routing.observations.lock_root(
                    c, owner_id=owner_id, scope=scope, decision_id=decision.routing_decision_id
                )
            if record.status == "closed" and record.events[-1].validation.accepted:
                value = replace(value, metadata=replace(
                    value.metadata, invocation_id=str(permit.invocation_id),
                    attempt_ids=(str(permit.attempt_id),),
                ))
                return CascadeResult(value, decision.root_decision_id, decision.routing_decision_id,
                                     permit.attempt_id, decision.selected)
            # P19 fences unknown/timeout outcomes before any child can be created.
            parent = decision.routing_decision_id
        raise CascadeRejected("cascade_validation_exhausted")

    def _reselect_after_known_endpoint_failure(self, *, owner_id, scope, decision, reason):
        """Persist a known pre-dispatch failure for P21's linked child transition."""
        try:
            self.routing.finish(
                owner_id=owner_id, scope=scope,
                decision_id=decision.routing_decision_id, reason=reason,
            )
        except Exception as error:
            raise CascadeRejected("cascade_endpoint_failure_not_terminal") from error


class EndpointInputPreparer:
    """Shared assembler + endpoint counter/generator, frozen authorized source policy.

    `assemble` is a trusted context capability returning a ContextBuildResult and
    exact ValidationInput for the injected sources. It must use a local counter;
    the single exact external count below is admitted by P21/P19. Domain rules
    remain in this capability and the validator, never in the coordinator.
    """

    def __init__(self, routing, *, owner_id, scope, assemble, resolve_runtime,
                 response_schema=None):
        self.routing = routing
        self.owner_id = owner_id
        self.scope = scope
        self.assemble = assemble
        self.resolve_runtime = resolve_runtime
        self.response_schema = response_schema

    def __call__(self, decision, remaining):
        import json
        from hashlib import sha256
        from time import monotonic

        from personal_ai.llm.preparation import prepare_bounded_input
        from personal_ai.usage.contracts import AttemptResult

        profile = self.routing.registry.revalidate_selected(
            decision.selected, decision.request.requirements,
            now=self.routing.current_time(owner_id=self.owner_id),
        )
        if decision.request.operation == "structured_generation" and self.response_schema is None:
            raise CascadeRejected("cascade_response_schema_required")
        generator, counter = self.resolve_runtime(profile)
        if (getattr(generator, "endpoint_profile", None) != profile
            or getattr(counter, "endpoint_profile", None) != profile
            or getattr(generator, "gateway_accounting_enabled", None) is not False
            or getattr(counter, "gateway_accounting_enabled", None) is not False
            or getattr(generator, "transport_retries", None) != 0
            or getattr(counter, "transport_retries", None) != 0
            or getattr(generator, "max_http_requests_per_call", None) != 1
            or getattr(counter, "max_http_requests_per_call", None) != 1
            or profile.counter is None
            or getattr(counter, "counter_id", None) != profile.counter.counter_id
            or generator.identity.provider_id != profile.provider_id
            or generator.identity.model_id != profile.model_id
            or generator.identity.serializer_id != profile.serializer_id
            or not generator.capabilities.supports(decision.request.operation)):
            raise CascadeRejected("cascade_runtime_binding_mismatch")
        context, inputs = self.assemble(profile, decision)
        if context.manifest.effective_sensitivity != decision.request.requirements.sensitivity:
            raise CascadeRejected("cascade_context_policy_changed")
        if context.token_count > decision.request.requirements.input_tokens:
            raise EndpointLocalPreparationFailure("cascade_context_does_not_fit")
        injected_item_keys = {
            (item.source_id, item.item_id) for item in context.manifest.items if item.injected
        }
        validation_item_keys = {
            (source.context_source_id, source.context_item_id) for source in inputs.sources
        }
        if injected_item_keys != validation_item_keys or any(
            source.context_source_id is None or source.context_item_id is None
            for source in inputs.sources
        ):
            raise CascadeRejected("cascade_source_manifest_mismatch")
        if not sources_allowed(decision, tuple(s.reference_sha256 for s in inputs.sources)):
            raise CascadeRejected("cascade_source_disclosure_changed")
        envelope = InferenceContext(
            effective_sensitivity=decision.request.requirements.sensitivity,
            maximum_sensitivity=decision.request.requirements.sensitivity,
            policy_version=decision.request.policy_version,
        )
        limit = min(decision.request.requirements.input_tokens,
                    profile.context_limit_tokens - decision.request.requirements.output_tokens)

        def count_send(endpoint, invocation, attempt):
            started = monotonic()
            counted = prepare_bounded_input(
                context.messages, counter, generator=generator, input_limit=limit,
                timeout_seconds=self._remaining(decision),
                response_schema=self.response_schema, inference_context=envelope,
                enforce_input_limit=False,
            )
            return counted, AttemptResult(
                outcome="success", completed_at=self.routing.current_time(owner_id=self.owner_id), latency_ms=int((monotonic()-started)*1000),
            )

        counted = self.routing.dispatch_auxiliary(
            owner_id=self.owner_id, scope=self.scope, decision_id=decision.routing_decision_id,
            event_id=uuid5(decision.routing_decision_id, "cascade:exact-count"),
            operation="token_counting", input_tokens=context.token_count,
            source_references=tuple(s.reference_sha256 for s in inputs.sources), send=count_send,
        )
        if counted.token_count.tokens > limit:
            raise EndpointLocalPreparationFailure("cascade_authoritative_count_does_not_fit")
        preparation = PreparationIdentity(
            endpoint=profile.ref, serializer_id=profile.serializer_id,
            counter_id=profile.counter.counter_id, input_tokens=counted.token_count.tokens,
            count_source="provider", count_confidence="authoritative",
            source_reference_sha256s=tuple(s.reference_sha256 for s in inputs.sources),
            prepared_input_sha256=sha256(json.dumps({
                "serializer_id": profile.serializer_id,
                "schema": self.response_schema,
                "messages": [{"role": m.role, "content": m.content} for m in counted.messages],
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            prepared_at=self.routing.current_time(owner_id=self.owner_id),
        )

        def send(endpoint, invocation, attempt):
            started = monotonic()
            kwargs = {
                "max_output_tokens": decision.request.requirements.output_tokens,
                "timeout_seconds": self._remaining(decision), "inference_context": envelope,
            }
            if decision.request.operation == "structured_generation":
                result = generator.generate_structured(
                    counted.messages, response_schema=self.response_schema, **kwargs
                )
            else:
                result = generator.complete(counted.messages, **kwargs)
            usage = result.metadata.usage
            return result, AttemptResult(
                outcome=result.metadata.status, completed_at=self.routing.current_time(owner_id=self.owner_id),
                latency_ms=int((monotonic()-started)*1000), input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                usage_source=usage.source if usage else "unknown",
                rate_limits=result.metadata.rate_limits, error_code=result.metadata.error_code,
                usage_confidence="exact" if usage and usage.confidence == "reported" else "unknown",
            )

        return PreparedCascadeInput(preparation, inputs, send)

    def _remaining(self, decision):
        remaining = (
            decision.root_deadline_at - self.routing.current_time(owner_id=self.owner_id)
        ).total_seconds()
        if remaining <= 0:
            raise CascadeRejected("cascade_deadline_exhausted")
        return remaining


def replay_cascade(records, strategy, *, now):
    """Replay retained compact chain only; never substitute today's registry.

    Missing/deleted dependencies or an incomplete chain are explicitly unavailable.
    No output/artifact body is needed to distinguish initial/final selections.
    """
    from personal_ai.routing.strategy import RoutingReplayUnavailable, replay_deterministic_decision

    if not records:
        raise RoutingReplayUnavailable("cascade_replay_unavailable")
    by_id = {r.decision.routing_decision_id: r for r in records}
    roots = [r for r in records if r.decision.parent_decision_id is None]
    if len(roots) != 1 or len(by_id) != len(records):
        raise RoutingReplayUnavailable("cascade_replay_unavailable")
    chain = []
    current = roots[0]
    while True:
        decision = current.decision
        if decision.task.cascade_policy is None or len(chain) >= 5:
            raise RoutingReplayUnavailable("cascade_replay_unavailable")
        replay_deterministic_decision(decision, strategy, now=now)
        chain.append(decision.routing_decision_id)
        if current.status == "reselected":
            linked = current.events[-1].linked_decision_id
            child = by_id.get(linked)
            if (child is None or child.decision.parent_decision_id != decision.routing_decision_id
                or child.decision.root_decision_id != roots[0].decision.root_decision_id):
                raise RoutingReplayUnavailable("cascade_replay_unavailable")
            current = child
        else:
            break
    if len(chain) != len(records):
        raise RoutingReplayUnavailable("cascade_replay_unavailable")
    terminal = current.events[-1]
    if current.status == "closed":
        if terminal.kind != "closed" or terminal.validation is None or not terminal.validation.accepted:
            raise RoutingReplayUnavailable("cascade_replay_unavailable")
        accepted = True
    elif current.status == "failed":
        if terminal.kind != "failed" or terminal.validation is None or terminal.validation.accepted:
            raise RoutingReplayUnavailable("cascade_replay_unavailable")
        accepted = False
    elif current.status == "no_route":
        if terminal.kind != "no_route" or current.decision.selected is not None:
            raise RoutingReplayUnavailable("cascade_replay_unavailable")
        accepted = False
    else:
        # selected/authorized/dispatched and unclassified failed decisions can
        # be interrupted work; never turn them into negative replay labels.
        raise RoutingReplayUnavailable("cascade_replay_unavailable")
    return {
        "initial_endpoint": roots[0].decision.selected,
        "final_endpoint": current.decision.selected if accepted else None,
        "decision_ids": tuple(chain),
        "accepted_decision_id": current.decision.routing_decision_id if accepted else None,
        "accepted_attempt_id": next((e.attempt_id for e in reversed(current.events)
                                     if e.kind == "dispatched"), None) if accepted else None,
    }
