"""Real routing/dispatch/context seams with synthetic transports; no live claims."""

from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid5

import pytest

from personal_ai.llm.client import GenerationMetadata, GenerationResult, ProviderIdentity
from personal_ai.routing.cascade import CascadeCoordinator, CascadeRejected, PreparedCascadeInput
from personal_ai.routing.phase21 import CascadePolicy, PreparationIdentity
from personal_ai.routing.strategy import (
    QuotaAwareDeterministicStrategy,
    replay_deterministic_decision,
)
from personal_ai.usage.contracts import AttemptResult, UsageAdmissionDenied
from personal_ai.validation.tasks import (
    Constraint,
    PreparedSource,
    StructuredTaskValidator,
    TaskValidatorRegistry,
    ValidationInput,
)
from tests import test_routing_phase21 as routing_test
from tests.test_routing_phase21 import SCOPE, request, task


@pytest.fixture
def system():
    return routing_test.system.__wrapped__()


def cascade_task(**changes):
    policy = CascadePolicy(
        endpoint_order=("endpoint-a", "endpoint-b"),
        input_contract_id="prepared-sources-v1", output_contract_id="structured-sources-v1",
        max_reserved_tokens=192, quota_limits={"shared": 4},
    )
    return task(
        cascade_allowed=True, escalation_allowed=True, max_physical_attempts=4,
        max_reselections=1, max_auxiliary_calls=2, validator_id="structured-sources",
        validator_version="1", cascade_policy=changes.pop("cascade_policy", policy), **changes,
    )


def validators():
    registry = TaskValidatorRegistry()
    registry.register(StructuredTaskValidator())
    return registry


def validation_input(**changes):
    return ValidationInput(
        input_contract_id="prepared-sources-v1", output_contract_id="structured-sources-v1",
        required_fields=("answer",), field_types={"answer": "string"}, **changes,
    )


def install_budget_adapter(system):
    service, repo, usage, _ = system

    def budget(c, invocation, *, max_reserved_tokens, quota_limits):
        attempts = [a for i, a, _ in repo.attempts.values() if i.request_id == invocation.request_id]
        if sum(a.reserved_tokens for a in attempts) > max_reserved_tokens:
            raise UsageAdmissionDenied("cascade_token_budget_exceeded")
        if len(attempts) > quota_limits.get("shared", 0):
            raise UsageAdmissionDenied("cascade_quota_budget_exceeded")

    def unstarted(c, invocation):
        if any(i.invocation_id == invocation.invocation_id for i, _, _ in repo.attempts.values()):
            raise UsageAdmissionDenied("provider_invocation_already_started")

    usage.assert_request_budget_in_transaction = budget
    usage.assert_invocation_unstarted_in_transaction = unstarted
    return service, repo


def preparer(system, outputs, *, transform=None, outcomes=None):
    service, repo = install_budget_adapter(system)
    calls = []

    def prepare(decision, remaining):
        assert remaining > 0
        service.consume_auxiliary_call(
            owner_id="owner", scope=SCOPE, decision_id=decision.routing_decision_id,
            event_id=uuid5(decision.routing_decision_id, "local-assembly"),
        )
        profile = service.registry.revalidate_selected(
            decision.selected, decision.request.requirements, now=repo.now
        )
        inputs = validation_input()
        if transform:
            inputs = transform(decision, inputs)
        identity = PreparationIdentity(
            endpoint=decision.selected, serializer_id=profile.serializer_id,
            input_tokens=32, count_source="fixture", count_confidence="estimated",
            prepared_input_sha256=sha256(profile.endpoint_profile_id.encode()).hexdigest(),
            source_reference_sha256s=tuple(s.reference_sha256 for s in inputs.sources),
            prepared_at=repo.now,
        )

        def send(profile, invocation, attempt):
            calls.append((profile.ref, invocation, attempt))
            outcome = outcomes[len(calls)-1] if outcomes else "success"
            result = GenerationResult(
                outputs[len(calls)-1], GenerationMetadata(
                    status="success", identity=ProviderIdentity(
                        profile.provider_id, profile.model_id, profile.serializer_id
                    ),
                ),
            )
            return result, AttemptResult(outcome=outcome, completed_at=repo.now, latency_ms=10)

        return PreparedCascadeInput(identity, inputs, send, synthetic=True)

    return prepare, calls


def execute(system, prepare, **changes):
    return CascadeCoordinator(system[0], validators()).execute(
        owner_id="owner", scope=SCOPE, task=changes.pop("task", cascade_task()),
        request=changes.pop("request", request(operation="bounded_generation")),
        prepare=prepare, **changes,
    )


def test_invalid_buffered_output_escalates_once_and_replays_frozen_links(system):
    prepare, calls = preparer(system, ['bad', '{"answer":"valid"}'])
    result = execute(system, prepare)
    assert result.generation.text == '{"answer":"valid"}'
    assert len(calls) == 2
    assert result.endpoint.endpoint_profile_id == "endpoint-b"
    records = list(system[1].records.values())
    assert [r.status for r in records] == ["reselected", "closed"]
    assert records[0].events[-2].validation.reasons == ("schema_invalid",)
    assert records[1].decision.parent_decision_id == records[0].decision.routing_decision_id
    assert records[1].events[-1].validation.accepted
    assert len({a.attempt_id for _, _, a in calls}) == 2
    for record in records:
        assert replay_deterministic_decision(
            record.decision, QuotaAwareDeterministicStrategy(), now=system[1].now
        )[0].endpoint == record.decision.selected
    with pytest.raises(CascadeRejected, match="already_started"):
        execute(system, prepare)
    assert len(calls) == 2


@pytest.mark.parametrize("policy_change,code", [
    ({"max_reserved_tokens": 47}, "token_budget"),
    ({"quota_limits": {"shared": 1}}, "quota_budget"),
])
def test_cumulative_reservations_fail_before_exhausted_send(system, policy_change, code):
    prepare, calls = preparer(system, ['bad', '{"answer":"valid"}'])
    policy = cascade_task().cascade_policy.model_copy(update=policy_change)
    with pytest.raises(Exception, match=code):
        execute(system, prepare, task=cascade_task(cascade_policy=policy))
    assert len(calls) == (0 if code == "token_budget" else 1)


def test_unknown_physical_outcome_fences_escalation(system):
    prepare, calls = preparer(system, ['bad', '{"answer":"valid"}'], outcomes=["unknown"])
    with pytest.raises(Exception, match="provider_outcome_unresolved"):
        execute(system, prepare)
    assert len(calls) == 1


def test_missing_validator_prevents_prepare_and_send(system):
    with pytest.raises(ValueError, match="validator_unavailable"):
        CascadeCoordinator(system[0], TaskValidatorRegistry()).execute(
            owner_id="owner", scope=SCOPE, task=cascade_task(),
            request=request(operation="bounded_generation"),
            prepare=lambda *_: pytest.fail("must not prepare"),
        )
    assert not system[1].records


def test_changed_source_text_under_same_digest_rejected_before_next_send(system):
    digest = "1" * 64

    def transform(decision, inputs):
        return inputs.model_copy(update={"sources": (PreparedSource(
            source_id="source", reference_sha256=digest,
            text="original" if not decision.parent_decision_id else "changed",
        ),)})

    prepare, calls = preparer(system, ['bad', '{"answer":"valid"}'], transform=transform)
    with pytest.raises(CascadeRejected, match="frozen_validation_changed"):
        execute(system, prepare, request=request(
            operation="bounded_generation", source_reference_sha256s=(digest,),
        ))
    assert len(calls) == 1


def test_source_widening_rejected_before_send(system):
    def transform(decision, inputs):
        return inputs.model_copy(update={"sources": (PreparedSource(
            source_id="source", reference_sha256="2" * 64, text="private",
        ),)})

    prepare, calls = preparer(system, ['bad'], transform=transform)
    with pytest.raises(CascadeRejected, match="prepared_contract_mismatch"):
        execute(system, prepare)
    assert not calls


def test_deadline_and_denied_reauthorization_prevent_send(system):
    prepare, calls = preparer(system, ['bad', '{"answer":"valid"}'])

    def revoked(decision, remaining):
        prepared = prepare(decision, remaining)
        system[3].deny = True
        return prepared

    with pytest.raises(Exception, match="authorization"):
        execute(system, revoked)
    assert not calls


def test_source_spans_citations_and_hard_constraints_share_deterministic_checks():
    inputs = validation_input(
        sources=(PreparedSource(source_id="s", reference_sha256="1" * 64, text="abc"),),
        required_citations=("s",), require_source_spans=True,
        hard_constraints=(Constraint(path="price", operator="lte", value=10),),
    )
    validator = StructuredTaskValidator()
    good = '{"answer":"ok","citations":["s"],"price":9,"source_spans":[{"source_id":"s","start":0,"end":3,"quote":"abc"}]}'
    assert validator.validate(inputs, good).accepted
    assert not validator.validate(inputs, good.replace('"abc"', '"fake"')).accepted
    assert not validator.validate(inputs, good.replace('"price":9', '"price":11')).accepted
    assert not validator.validate(inputs, good.replace('["s"]', '["other"]')).accepted
    assert not validator.validate(inputs, '{"answer":[]}').accepted


def test_depth_and_output_bytes_are_bounded(system):
    policy = cascade_task().cascade_policy.model_copy(update={"max_output_bytes": 8})
    prepare, calls = preparer(system, ['{"answer":"valid"}'] * 2)
    with pytest.raises(CascadeRejected, match="validation_exhausted"):
        execute(system, prepare, task=cascade_task(cascade_policy=policy))
    assert len(calls) == 2
    assert all(r.events[-1].validation.reasons == ("output_budget_exceeded",)
               for r in system[1].records.values() if r.status == "failed")


def test_custom_domain_validator_can_register_without_coordinator_changes(system):
    class DomainValidator(StructuredTaskValidator):
        validator_id = "synthetic-domain"

        def validate(self, inputs, output):
            from personal_ai.validation.tasks import ValidationResult
            base = super().validate(inputs, output)
            if not base.accepted or '"valid"' not in output:
                return ValidationResult(accepted=False, reasons=("domain_rule_failed",))
            return base

    registry = TaskValidatorRegistry()
    registry.register(DomainValidator())
    prepare, calls = preparer(system, ['{"answer":"wrong"}', '{"answer":"valid"}'])
    result = CascadeCoordinator(system[0], registry).execute(
        owner_id="owner", scope=SCOPE,
        task=cascade_task().model_copy(update={"validator_id": "synthetic-domain"}),
        request=request(operation="bounded_generation"), prepare=prepare,
    )
    assert result.endpoint.endpoint_profile_id == "endpoint-b"
    assert len(calls) == 2


def test_replay_needs_complete_unexpired_chain_and_no_current_registry(system):
    from personal_ai.routing.cascade import replay_cascade
    from personal_ai.routing.strategy import RoutingReplayUnavailable

    prepare, _ = preparer(system, ['bad', '{"answer":"valid"}'])
    result = execute(system, prepare)
    records = tuple(system[1].records.values())
    replay = replay_cascade(records, QuotaAwareDeterministicStrategy(), now=system[1].now)
    assert replay["initial_endpoint"].endpoint_profile_id == "endpoint-a"
    assert replay["final_endpoint"] == result.endpoint
    assert replay["accepted_attempt_id"] == result.accepted_attempt_id
    with pytest.raises(RoutingReplayUnavailable):
        replay_cascade(records[:1], QuotaAwareDeterministicStrategy(), now=system[1].now)
    with pytest.raises(RoutingReplayUnavailable):
        replay_cascade(records, QuotaAwareDeterministicStrategy(), now=records[0].decision.replay_until + timedelta(seconds=1))


def test_endpoint_preparer_uses_shared_context_builder_and_admitted_exact_counts(system):
    from personal_ai.context.builder import SOURCE_CLASSES, ContextBuilder, ContextBuildPolicy
    from personal_ai.context.tokens import FakeTokenCounter
    from personal_ai.llm.client import ChatMessage, ProviderCapabilities, TokenCount
    from personal_ai.routing.cascade import EndpointInputPreparer
    from personal_ai.routing.contracts import CounterCompatibility
    from personal_ai.routing.registry import EndpointRegistry
    from tests.test_endpoint_registry import _bucket, _profile

    service, repo = install_budget_adapter(system)
    profiles = []
    for endpoint in ("endpoint-a", "endpoint-b"):
        counter = CounterCompatibility(
            endpoint_profile_id=endpoint, endpoint_id="synthetic-endpoint-v1",
            deployment_id="synthetic-deployment-a", provider_id="synthetic", model_id="model-a",
            serializer_id="synthetic-chat-v1" if endpoint == "endpoint-a" else "synthetic-chat-v2", counter_id="counter-v1", approved=True,
            confidence="authoritative", provenance_reference="test:v1",
            account_scope_id="account-a", credential_scope_id="credential-a",
        )
        profiles.append(_profile(endpoint, counter=counter, serializer_id=counter.serializer_id,
                                 quota_buckets=(_bucket("shared", operations=frozenset({"bounded_generation", "token_counting"})),),
                                 capabilities=frozenset({"bounded_generation", "token_counting"})))
    service.registry = EndpointRegistry(profiles)
    sends = []
    builds = []

    def assemble(profile, decision):
        builds.append(profile.ref)
        context = ContextBuilder(FakeTokenCounter()).build(
            (ChatMessage("user", "synthetic"),), (),
            ContextBuildPolicy(global_input_tokens=64, source_max_tokens={k:64 for k in SOURCE_CLASSES}),
            base_sensitivity="public",
        )
        return context, validation_input()

    def runtime(profile):
        identity = ProviderIdentity(profile.provider_id, profile.model_id, profile.serializer_id)

        def count(messages, timeout_seconds, **kwargs):
            sends.append((profile.ref, "count", kwargs))
            return TokenCount(32 if profile.endpoint_profile_id == "endpoint-a" else 40,
                              "provider", "synthetic", "model-a", profile.serializer_id, "authoritative")

        def complete(messages, **kwargs):
            sends.append((profile.ref, "generation", kwargs))
            return GenerationResult(
                'bad' if profile.endpoint_profile_id == "endpoint-a" else '{"answer":"valid"}',
                GenerationMetadata(status="success", identity=identity),
            )

        generator = SimpleNamespace(identity=identity, capabilities=ProviderCapabilities(
            frozenset({"bounded_generation"})), complete=complete)
        counter = SimpleNamespace(identity=identity, count_with_timeout=count)
        return generator, counter

    prepared = EndpointInputPreparer(service, owner_id="owner", scope=SCOPE,
                                     assemble=assemble, resolve_runtime=runtime)
    result = execute(system, prepared)
    assert result.endpoint.endpoint_profile_id == "endpoint-b"
    assert [op for _, op, _ in sends] == ["count", "generation", "count", "generation"]
    assert len(repo.attempts) == 4
    assert len(builds) == 2
    preparations = [e.preparation for r in repo.records.values() for e in r.events if e.preparation]
    assert [p.input_tokens for p in preparations] == [32, 40]
    assert len({p.prepared_input_sha256 for p in preparations}) == 2  # endpoint serializers differ
    assert all(kwargs["inference_context"].policy_version == "policy:v1" for _, _, kwargs in sends)


def test_auxiliary_unknown_outcome_and_duplicate_identity_never_resend(system):
    from personal_ai.routing.contracts import CounterCompatibility
    from personal_ai.routing.registry import EndpointRegistry
    from tests.test_endpoint_registry import _bucket, _profile

    service, repo = install_budget_adapter(system)
    counter = CounterCompatibility(
        endpoint_profile_id="endpoint-a", endpoint_id="synthetic-endpoint-v1",
        deployment_id="synthetic-deployment-a", provider_id="synthetic", model_id="model-a",
        serializer_id="synthetic-chat-v1", counter_id="counter-v1", approved=True,
        confidence="authoritative", provenance_reference="test:v1",
        account_scope_id="account-a", credential_scope_id="credential-a",
    )
    service.registry = EndpointRegistry((_profile(
        "endpoint-a", counter=counter, capabilities=frozenset({"bounded_generation", "token_counting"}),
        quota_buckets=(_bucket("shared", operations=frozenset({"bounded_generation", "token_counting"})),),
    ),))
    decision = service.route(owner_id="owner", scope=SCOPE, task=cascade_task(),
                             request=request(operation="bounded_generation"))
    sends = []

    def send(*_):
        sends.append(1)
        return "unavailable", AttemptResult(outcome="unknown", completed_at=repo.now, latency_ms=1)

    kwargs = {"owner_id": "owner", "scope": SCOPE, "decision_id": decision.routing_decision_id,
              "event_id": uuid5(decision.routing_decision_id, "count"), "operation": "token_counting",
              "input_tokens": 32, "source_references": (), "send": send}
    with pytest.raises(Exception, match="auxiliary_incomplete"):
        service.dispatch_auxiliary(**kwargs)
    with pytest.raises(Exception, match="already_started"):
        service.dispatch_auxiliary(**kwargs)
    assert sends == [1]


def test_expired_root_fails_before_any_provider_send(system):
    prepare, calls = preparer(system, ['{"answer":"valid"}'])

    def expired(decision, remaining):
        prepared = prepare(decision, remaining)
        system[1].now = decision.root_deadline_at
        return prepared

    with pytest.raises(Exception, match="deadline"):
        execute(system, expired)
    assert not calls


def test_cascade_task_rejects_user_visible_streaming():
    with pytest.raises(ValueError, match="cascade_task_bounds_invalid"):
        t = cascade_task().model_copy(update={"required_capabilities": frozenset({"streaming"})})
        type(t).model_validate(t.model_dump())


def test_returned_output_is_never_exposed_on_validator_exception(system):
    from personal_ai.validation.tasks import ValidationResult

    class FailingValidator(StructuredTaskValidator):
        def validate(self, inputs, output):
            raise ValueError("contains output and sources")

    registry = TaskValidatorRegistry()
    registry.register(FailingValidator())
    prepare, calls = preparer(system, ['{"answer":"secret"}'] * 2)
    with pytest.raises(CascadeRejected, match="validation_exhausted"):
        CascadeCoordinator(system[0], registry).execute(
            owner_id="owner", scope=SCOPE, task=cascade_task(),
            request=request(operation="bounded_generation"), prepare=prepare,
        )
    assert len(calls) == 2
    assert all(e.validation == ValidationResult(accepted=False, reasons=("validator_failed",))
               for r in system[1].records.values() for e in r.events if e.validation)
    assert "secret" not in str(system[1].records)


@pytest.mark.parametrize("output", ['{"answer":NaN}', '{"answer":"ok","answer":"wrong"}', '['*2000])
def test_invalid_json_is_rejected_deterministically(output):
    assert not StructuredTaskValidator().validate(validation_input(), output).accepted
