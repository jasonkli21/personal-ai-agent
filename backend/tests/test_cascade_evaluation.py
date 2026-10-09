"""Paired P22 fixtures through P23/P24 service/ledger contracts, synthetic only."""

import hashlib
import json
from types import SimpleNamespace

from personal_ai.context.builder import SOURCE_CLASSES, ContextBuildPolicy
from personal_ai.context.cascade import FrozenContextAssembler
from personal_ai.evaluation.cascade import CascadeMeasurement, run_paired_cascade_baseline
from personal_ai.evaluation.provider_matrix import score_output
from personal_ai.llm.client import (
    ChatMessage,
    GenerationMetadata,
    GenerationResult,
    ProviderCapabilities,
    ProviderIdentity,
    TokenCount,
)
from personal_ai.routing import EndpointRegistry, RoutingDecisionService
from personal_ai.routing.cascade import CascadeCoordinator, EndpointInputPreparer
from personal_ai.routing.contracts import CounterCompatibility
from personal_ai.validation.tasks import (
    StructuredTaskValidator,
    TaskValidatorRegistry,
    ValidationResult,
)
from tests.test_cascade_phase24 import cascade_task, install_budget_adapter, validation_input
from tests.test_endpoint_registry import _bucket, _profile
from tests.test_routing_phase21 import SCOPE, Authorization, MemoryRepository, Usage, request


def test_paired_baseline_counts_every_attempt_and_keeps_direct(tmp_path):
    def execute(fixture, arm):
        repo = MemoryRepository()
        usage = Usage(repo)
        profiles = []
        for endpoint in ("endpoint-a", "endpoint-b"):
            counter = CounterCompatibility(
                endpoint_profile_id=endpoint, endpoint_id="synthetic-endpoint-v1",
                deployment_id="synthetic-deployment-a", provider_id="synthetic", model_id="model-a",
                serializer_id="synthetic-chat-v1", counter_id="counter-v1", approved=True,
                confidence="authoritative", provenance_reference="test:v1",
                account_scope_id="account-a", credential_scope_id="credential-a",
            )
            profiles.append(_profile(endpoint, counter=counter, context_limit_tokens=8192,
                capabilities=frozenset({"bounded_generation", "token_counting"}),
                quota_buckets=(_bucket("shared", operations=frozenset({"bounded_generation", "token_counting"})),)))
        routing = RoutingDecisionService(
            EndpointRegistry(profiles), repo,
            usage=usage, authorization=Authorization(),
        )
        system = routing, repo, usage, Authorization()
        reference = json.dumps(fixture.reference_output)
        # Fixed fixture-order independent synthetic weak failure distribution.
        weak_bad = int(hashlib.sha256(fixture.fixture_id.encode()).hexdigest()[:2], 16) % 3 == 0
        install_budget_adapter(system)
        assembler = FrozenContextAssembler(
            messages=tuple(ChatMessage(m.role, m.content) for m in fixture.messages), entries=(),
            policy=ContextBuildPolicy(global_input_tokens=8192, source_max_tokens={k:8192 for k in SOURCE_CLASSES}),
            validation=validation_input(),
        )

        def runtime(profile):
            identity = ProviderIdentity(profile.provider_id, profile.model_id, profile.serializer_id)

            def count(messages, timeout_seconds, **kwargs):
                return TokenCount(32, "provider", "synthetic", "model-a", profile.serializer_id, "authoritative")

            def complete(messages, **kwargs):
                text = "invalid" if weak_bad and profile.endpoint_profile_id == "endpoint-a" else reference
                return GenerationResult(text, GenerationMetadata(status="success", identity=identity))

            return (SimpleNamespace(identity=identity, complete=complete,
                capabilities=ProviderCapabilities(frozenset({"bounded_generation"}))),
                SimpleNamespace(identity=identity, count_with_timeout=count))

        prepare = EndpointInputPreparer(routing, owner_id="owner", scope=SCOPE,
                                       assemble=assembler, resolve_runtime=runtime)
        t = cascade_task()
        t = t.model_copy(update={"cascade_policy": t.cascade_policy.model_copy(update={"max_reserved_tokens":32768})})
        if arm == "direct":
            t = t.model_copy(update={"cascade_policy": t.cascade_policy.model_copy(
                update={"endpoint_order": ("endpoint-b",)})})

        class FixtureValidator(StructuredTaskValidator):
            def validate(self, inputs, output):
                passed = score_output(fixture, output).hard_boundaries_passed
                return ValidationResult(accepted=passed, reasons=() if passed else ("fixture_rejected",))

        validators = TaskValidatorRegistry()
        validators.register(FixtureValidator())
        result = CascadeCoordinator(routing, validators).execute(
            owner_id="owner", scope=SCOPE, task=t,
            request=request(operation="bounded_generation").model_copy(update={"requirements": request().requirements.model_copy(update={"input_tokens": 8192})}), prepare=prepare,
        )
        attempts = tuple(repo.attempts.values())
        return CascadeMeasurement(
            output=result.generation.text, physical_attempts=len(attempts),
            auxiliary_calls=sum(repo.auxiliary.values()),
            input_tokens=sum(a.reserved_tokens - (i.output_tokens_bound or 0) for i, a, _ in attempts),
            output_tokens=sum(i.output_tokens_bound or 0 for i, _, _ in attempts), quota_units=(("shared", len(attempts)),),
            latency_ms=sum(5 if i.operation == "token_counting" else 10 for i, _, _ in attempts),
            rejected=sum(e.validation is not None and not e.validation.accepted
                         for record in repo.records.values() for e in record.events),
        )

    report = run_paired_cascade_baseline(
        execute, configuration_sha256=hashlib.sha256(b"phase24-synthetic-p23-runtime-v1").hexdigest(),
        tested_revision="working-tree-phase24",
    )
    assert report["quality_safe"]
    assert report["totals"]["direct"]["accepted"] == len(report["cases"])
    assert report["totals"]["cascade"]["physical_attempts"] > report["totals"]["direct"]["physical_attempts"]
    assert report["totals"]["cascade"]["auxiliary_calls"] > report["totals"]["direct"]["auxiliary_calls"]
    assert not report["live_promotion_eligible"]
    assert not report["qualifies_for_further_evaluation"]
    assert report["runtime_default"] == "direct"
    (tmp_path / "cascade-baseline.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report["totals"], sort_keys=True))
