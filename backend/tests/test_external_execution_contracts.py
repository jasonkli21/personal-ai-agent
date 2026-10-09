"""Prepared-execution proof and provenance foundations; no cloud issuance/UX."""

import base64
from dataclasses import asdict
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from personal_ai.auth.dispatch_grants import (
    DispatchGrant,
    DispatchGrantVerifier,
    InvalidDispatchGrant,
    SignedDispatchGrant,
)
from personal_ai.llm.client import (
    ExecutionProvenance,
    ExternalCompletion,
    GenerationMetadata,
    ProviderIdentity,
)
from personal_ai.llm.external import PreparedExecution


def execution_package(**overrides):
    values = {
        "owner_id": "synthetic-owner", "application_id": "personal_ai", "workspace_id": None,
        "conversation_id": uuid4(), "reservation_id": uuid4(), "branch_digest": "a" * 64,
        "source_authority_digest": "b" * 64, "provider_id": "openai_chatgpt_plan",
        "model_id": "account-visible-model", "connection_id": uuid4(), "connection_revision": 1,
        "messages": [{"role": "system", "content": "Be helpful"},
                     {"role": "user", "content": "Hello"}],
        "effective_sensitivity": "personal", "maximum_sensitivity": "sensitive",
        "policy_version": "synthetic-policy-v1", "max_output_bytes": 1024, "timeout_seconds": 10,
    }
    values.update(overrides)
    return PreparedExecution.model_validate(values)


def signed_grant(package, private, *, caller_id, audience, now, **overrides):
    values = dict(issuer="synthetic-authorized-issuer", key_id="key-v1", audience=audience,
                  caller_id=caller_id, grant_id=uuid4(), package_hash=package.fingerprint,
                  connection_id=package.connection_id, provider_id=package.provider_id,
                  model_id=package.model_id, policy_version=package.policy_version,
                  effective_sensitivity=package.effective_sensitivity, issued_at=now,
                  expires_at=now + 60)
    values.update(overrides)
    claims = DispatchGrant(**values)
    return SignedDispatchGrant(claims=claims, signature=base64.urlsafe_b64encode(
        private.sign(claims.canonical())).decode().rstrip("="))


def test_manual_completion_needs_no_bridge_and_cannot_claim_observed_identity():
    manual = ExecutionProvenance("manual_external", "user_declared", model_id="User label")
    assert ExternalCompletion("Imported text", manual).generation is None
    assert asdict(manual)["connection_id"] is None
    for source in ("bridge_observed", "provider_reported"):
        with pytest.raises(ValueError):
            ExecutionProvenance("manual_external", source)
    with pytest.raises(ValueError):
        ExecutionProvenance("manual_external", "user_declared", connection_id=str(uuid4()))
    metadata = GenerationMetadata("success", ProviderIdentity("fake", "fake", "fake"))
    with pytest.raises(ValueError):
        ExternalCompletion("text", manual, metadata)
    with pytest.raises(ValueError):
        GenerationMetadata("success", metadata.identity, provenance=manual)


def test_connected_completion_requires_matching_terminal_generation():
    provenance = ExecutionProvenance("connected_provider", "bridge_observed", "provider", "model",
                                     str(uuid4()))
    metadata = GenerationMetadata("success", ProviderIdentity("provider", "model", "serializer"),
                                  provenance=provenance)
    assert ExternalCompletion("output", provenance, metadata).generation == metadata
    with pytest.raises(ValueError):
        GenerationMetadata("success", ProviderIdentity("provider", "other", "serializer"),
                           provenance=provenance)
    with pytest.raises(ValueError):
        ExternalCompletion("output", provenance)


def test_pinned_proof_verification_and_scoped_idempotency_are_independent_of_proof_id():
    package = execution_package()
    caller, audience = uuid4(), uuid4()
    private = Ed25519PrivateKey.generate()
    verifier = DispatchGrantVerifier(issuer="synthetic-authorized-issuer",
                                     keys={"key-v1": private.public_key()}, audience=audience)
    proof = signed_grant(package, private, caller_id=caller, audience=audience, now=1000)
    assert verifier.verify(proof, package, caller_id=caller, now=1001) == proof.claims
    second = signed_grant(package, private, caller_id=caller, audience=audience, now=1000)
    assert proof.claims.grant_id != second.claims.grant_id
    edited = package.model_copy(update={"model_id": "other-model"})
    assert edited.fingerprint != package.fingerprint
    assert edited.dispatch_identity == package.dispatch_identity
    with pytest.raises(InvalidDispatchGrant):
        verifier.verify(proof, edited, caller_id=caller, now=1001)


@pytest.mark.parametrize("field,value", [
    ("issuer", "foreign"), ("key_id", "unknown"), ("audience", uuid4()),
    ("caller_id", uuid4()), ("connection_id", uuid4()), ("package_hash", "f" * 64),
    ("provider_id", "foreign"), ("model_id", "other"), ("policy_version", "other"),
    ("effective_sensitivity", "public"), ("issued_at", 1002), ("expires_at", 1001),
    ("expires_at", 1121),
])
def test_even_valid_signatures_cannot_weaken_claim_bindings(field, value):
    package = execution_package()
    private = Ed25519PrivateKey.generate()
    caller, audience = uuid4(), uuid4()
    options = {"caller_id": caller, "audience": audience, "now": 1000, field: value}
    proof = signed_grant(package, private, **options)
    verifier = DispatchGrantVerifier(issuer="synthetic-authorized-issuer",
                                     keys={"key-v1": private.public_key()}, audience=audience)
    with pytest.raises(InvalidDispatchGrant):
        verifier.verify(proof, package, caller_id=caller, now=1001)


def test_forged_proof_and_unknown_keys_fail_without_fetching_remote_authority():
    package = execution_package()
    attacker, trusted = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    caller, audience = uuid4(), uuid4()
    proof = signed_grant(package, attacker, caller_id=caller, audience=audience, now=1000)
    verifier = DispatchGrantVerifier(issuer="synthetic-authorized-issuer",
                                     keys={"key-v1": trusted.public_key()}, audience=audience)
    with pytest.raises(InvalidDispatchGrant):
        verifier.verify(proof, package, caller_id=caller, now=1001)


@pytest.mark.parametrize("override", [
    {"tools": []}, {"max_output_tokens": 10}, {"timeout_seconds": True},
    {"messages": [{"role": "tool", "content": "foo"}]},
    {"maximum_sensitivity": "public"}, {"max_output_bytes": 262145},
])
def test_prepared_contract_rejects_ordinary_api_fields_and_invalid_policy(override):
    with pytest.raises((ValidationError, ValueError)):
        execution_package(**override)
