"""Strict-free endpoint facts, admission, and lifecycle contracts."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from personal_ai.routing import (
    CandidateSetOverflowError,
    CounterCompatibility,
    CountRequirement,
    DataUsePolicy,
    EndpointCandidateRequirements,
    EndpointProfile,
    EndpointRegistry,
    QuotaBucket,
    RegistryConflictError,
    RegistryRevisionChangedError,
    build_initial_endpoint_profiles,
)
from personal_ai.settings import Settings


def _bucket(
    bucket_id: str,
    *,
    authority_scope_id: str = "provider-account-a",
    operations: frozenset[str] = frozenset({"bounded_generation"}),
    remaining: int | None = 400,
    fresh_until: datetime | None = None,
) -> QuotaBucket:
    return QuotaBucket(
        bucket_id=bucket_id,
        authority_scope_id=authority_scope_id,
        operations=operations,
        unit="requests",
        window_seconds=60,
        reset_at=None,
        source="provider_contract",
        confidence="verified",
        observed_at=datetime(2026, 10, 8, tzinfo=UTC) if fresh_until else None,
        fresh_until=fresh_until,
        limit=500 if remaining is not None else None,
        remaining=remaining,
    )


def _profile(
    profile_id: str = "synthetic:account-a:key-a:model-a",
    *,
    provider_id: str = "synthetic",
    model_id: str = "model-a",
    account_scope_id: str | None = "account-a",
    credential_scope_id: str | None = "credential-a",
    execution_mode: str = "STRICT_FREE",
    cost_class: str = "VERIFIED_FREE",
    billing_owner: str = "provider_account",
    strict_free_enabled: bool = True,
    tier_verified: bool = True,
    enabled: bool = True,
    quota_membership: str = "verified",
    quota_buckets: tuple[QuotaBucket, ...] | None = None,
    capabilities: frozenset[str] = frozenset({"bounded_generation"}),
    counter: CounterCompatibility | None = None,
    data_use_policy: DataUsePolicy | None = None,
    structured_schema_ids: tuple[str, ...] = (),
    serializer_id: str = "synthetic-chat-v1",
    context_limit_tokens: int | None = 4096,
    max_output_tokens: int | None = 1024,
    max_search_query_chars: int | None = None,
    max_search_results: int | None = None,
    profile_version: int = 1,
) -> EndpointProfile:
    return EndpointProfile(
        endpoint_profile_id=profile_id,
        profile_version=profile_version,
        provider_id=provider_id,
        model_id=model_id,
        endpoint_id=f"{provider_id}-endpoint-v1",
        deployment_id=f"{provider_id}-deployment-a",
        credential_source="environment",
        credential_reference="env:SYNTHETIC_MODEL_KEY",
        credential_scope_id=credential_scope_id,
        account_scope_id=account_scope_id,
        tier_id="free" if tier_verified else "unverified",
        tier_verified=tier_verified,
        execution_mode=execution_mode,
        cost_class=cost_class,
        billing_owner=billing_owner,
        enabled=enabled,
        strict_free_enabled=strict_free_enabled,
        capabilities=capabilities,
        context_limit_tokens=context_limit_tokens,
        max_output_tokens=max_output_tokens,
        data_use_policy=data_use_policy or DataUsePolicy(
            status="approved",
            max_sensitivity="personal",
            policy_reference="policy:synthetic-v1",
        ),
        serializer_id=serializer_id,
        runtime_id="synthetic-runtime-v1",
        max_search_query_chars=max_search_query_chars,
        max_search_results=max_search_results,
        structured_schema_ids=structured_schema_ids,
        counter=counter,
        quota_membership=quota_membership,
        quota_buckets=quota_buckets if quota_buckets is not None else (_bucket("bucket-a"),),
    )


def _requirements(**updates) -> EndpointCandidateRequirements:
    return EndpointCandidateRequirements(**updates)


def test_fact_based_guard_admits_unlisted_verified_free_endpoint_without_scores():
    profile = _profile(provider_id="new-provider", profile_id="new-provider:free:model")
    result = EndpointRegistry((profile,)).candidates(_requirements())

    assert result.eligible_profiles == (profile,)
    assert result.assessments[0].rejection_reasons == ()
    assert not hasattr(result.assessments[0], "score")


@pytest.mark.parametrize(
    ("profile_updates", "expected_reason"),
    [
        ({"enabled": False}, "endpoint_disabled_or_unconfigured"),
        ({"strict_free_enabled": False}, "strict_free_not_enabled"),
        ({"cost_class": "UNKNOWN", "billing_owner": "unknown"}, "cost_not_verified_free"),
        ({"execution_mode": "EXPLICIT_BYOK", "cost_class": "USER_BILLED", "billing_owner": "user", "strict_free_enabled": False}, "explicit_only_endpoint"),
        ({"tier_verified": False}, "account_tier_not_verified"),
        ({"account_scope_id": None}, "account_scope_unknown"),
        ({"credential_scope_id": None}, "credential_scope_unknown"),
        ({"quota_membership": "unknown"}, "quota_bucket_membership_unknown"),
        ({"quota_membership": "ambiguous"}, "quota_bucket_membership_ambiguous"),
    ],
)
def test_guard_rejects_unknown_paid_or_unconfigured_profiles(profile_updates, expected_reason):
    profile = _profile(**profile_updates)
    assessment = EndpointRegistry((profile,)).candidates(_requirements()).assessments[0]

    assert not assessment.eligible
    assert expected_reason in assessment.rejection_reasons


def test_unknown_data_policy_blocks_sensitive_but_public_data_can_be_admitted():
    profile = _profile(data_use_policy=DataUsePolicy(status="unknown"))
    registry = EndpointRegistry((profile,))

    sensitive = registry.candidates(_requirements(sensitivity="sensitive")).assessments[0]
    public = registry.candidates(_requirements(sensitivity="public")).assessments[0]

    assert "provider_data_policy_unknown_for_sensitivity" in sensitive.rejection_reasons
    assert public.eligible


def test_sensitivity_ceiling_and_endpoint_context_output_limits_are_hard_filters():
    profile = _profile()
    registry = EndpointRegistry((profile,))

    result = registry.candidates(_requirements(
        sensitivity="sensitive", input_tokens=4097, output_tokens=1025
    )).assessments[0]

    assert not result.eligible
    assert "sensitivity_exceeds_provider_approval" in result.rejection_reasons
    assert "input_exceeds_endpoint_context_limit" in result.rejection_reasons
    assert "output_exceeds_endpoint_limit" in result.rejection_reasons


def test_unknown_endpoint_context_or_output_limits_are_not_admitted():
    profile = _profile().model_copy(update={
        "context_limit_tokens": None,
        "max_output_tokens": None,
    })

    result = EndpointRegistry((profile,)).candidates(_requirements()).assessments[0]

    assert "endpoint_context_limit_unknown" in result.rejection_reasons
    assert "endpoint_output_limit_unknown" in result.rejection_reasons


def test_required_count_uses_exact_approved_endpoint_and_structured_schema_mapping():
    schema_id = "schema:proposal-v1"
    profile = _profile(
        capabilities=frozenset({"bounded_generation", "token_counting", "structured_generation"}),
        quota_buckets=(
            _bucket("generation", operations=frozenset({"bounded_generation", "structured_generation"})),
            _bucket("count", operations=frozenset({"token_counting"})),
        ),
        structured_schema_ids=(schema_id,),
        counter=CounterCompatibility(
            endpoint_profile_id="synthetic:account-a:key-a:model-a",
            endpoint_id="synthetic-endpoint-v1",
            deployment_id="synthetic-deployment-a",
            credential_scope_id="credential-a",
            account_scope_id="account-a",
            provider_id="synthetic",
            model_id="model-a",
            serializer_id="synthetic-chat-v1",
            counter_id="synthetic-counter-v1",
            confidence="authoritative",
            approved=True,
            provenance_reference="preflight:count-v1",
            structured_schema_ids=(schema_id,),
        ),
    )
    requirements = _requirements(
        required_capabilities=frozenset({
            "bounded_generation", "token_counting", "structured_generation"
        }),
        count=CountRequirement(
            minimum_confidence="authoritative", structured_schema_id=schema_id
        ),
        structured_schema_id=schema_id,
    )

    assessment = EndpointRegistry((profile,)).candidates(requirements).assessments[0]

    assert assessment.eligible


def test_generation_only_endpoint_is_rejected_when_authoritative_count_is_required():
    profile = _profile()
    requirements = _requirements(
        required_capabilities=frozenset({"bounded_generation", "token_counting"}),
        count=CountRequirement(minimum_confidence="authoritative"),
    )

    result = EndpointRegistry((profile,)).candidates(requirements).assessments[0]

    assert not result.eligible
    assert "capability_missing:token_counting" in result.rejection_reasons
    assert "quota_bucket_operation_missing:token_counting" in result.rejection_reasons
    assert "authoritative_counter_mapping_missing" in result.rejection_reasons


def test_count_mapping_without_approved_schema_coverage_is_rejected():
    profile = _profile(
        capabilities=frozenset({"bounded_generation", "token_counting", "structured_generation"}),
        quota_buckets=(
            _bucket("generation", operations=frozenset({"bounded_generation", "structured_generation"})),
            _bucket("count", operations=frozenset({"token_counting"})),
        ),
        structured_schema_ids=("schema:proposal-v1",),
        counter=CounterCompatibility(
            endpoint_profile_id="synthetic:account-a:key-a:model-a",
            endpoint_id="synthetic-endpoint-v1",
            deployment_id="synthetic-deployment-a",
            credential_scope_id="credential-a",
            account_scope_id="account-a",
            provider_id="synthetic",
            model_id="model-a",
            serializer_id="synthetic-chat-v1",
            counter_id="synthetic-counter-v1",
            confidence="authoritative",
            approved=True,
            provenance_reference="preflight:count-v1",
            structured_schema_ids=(),
        ),
    )
    requirements = _requirements(
        required_capabilities=frozenset({
            "bounded_generation", "token_counting", "structured_generation"
        }),
        count=CountRequirement(structured_schema_id="schema:proposal-v1"),
        structured_schema_id="schema:proposal-v1",
    )

    result = EndpointRegistry((profile,)).candidates(requirements).assessments[0]

    assert "counter_structured_schema_not_covered" in result.rejection_reasons


def test_mismatched_counter_identity_is_rejected_when_profile_is_constructed():
    with pytest.raises(ValidationError, match="counter_endpoint_identity_mismatch"):
        _profile(
            capabilities=frozenset({"bounded_generation", "token_counting"}),
            counter=CounterCompatibility(
                endpoint_profile_id="synthetic:account-a:key-a:model-a",
                endpoint_id="synthetic-endpoint-v1",
                deployment_id="synthetic-deployment-a",
                credential_scope_id="credential-a",
                account_scope_id="account-a",
                provider_id="synthetic",
                model_id="another-model",
                serializer_id="synthetic-chat-v1",
                counter_id="wrong-counter-v1",
                confidence="authoritative",
                approved=True,
                provenance_reference="preflight:count-v1",
            ),
        )


def test_operation_specific_quota_membership_is_required():
    profile = _profile(
        capabilities=frozenset({"bounded_generation", "streaming"}),
        quota_buckets=(_bucket("generation", operations=frozenset({"bounded_generation"})),),
    )

    result = EndpointRegistry((profile,)).candidates(_requirements(
        required_capabilities=frozenset({"bounded_generation", "streaming"})
    )).assessments[0]

    assert "quota_bucket_operation_missing:streaming" in result.rejection_reasons


def test_search_auxiliary_uses_its_own_bounds_and_quota_bucket():
    search_profile = _profile(
        capabilities=frozenset({"search"}),
        context_limit_tokens=None,
        max_output_tokens=None,
        max_search_query_chars=2048,
        max_search_results=8,
        quota_buckets=(_bucket("search-quota", operations=frozenset({"search"})),),
    )
    requirements = _requirements(
        required_capabilities=frozenset({"search"}),
        search_query_chars=512,
        search_results=5,
    )
    registry = EndpointRegistry((search_profile,))

    assert registry.candidates(requirements).assessments[0].eligible
    too_large = registry.candidates(
        _requirements(
            required_capabilities=frozenset({"search"}),
            search_query_chars=4096,
            search_results=9,
        )
    ).assessments[0]
    assert "search_query_exceeds_endpoint_limit" in too_large.rejection_reasons
    assert "search_results_exceed_endpoint_limit" in too_large.rejection_reasons


def test_fresh_exhausted_quota_bucket_blocks_admission():
    instant = datetime(2026, 10, 8, 12, tzinfo=UTC)
    exhausted = _bucket(
        "bucket-exhausted",
        remaining=0,
        fresh_until=instant + timedelta(minutes=1),
    )
    profile = _profile(quota_buckets=(exhausted,))

    result = EndpointRegistry((profile,)).candidates(_requirements(), now=instant).assessments[0]

    assert "quota_bucket_exhausted:bounded_generation" in result.rejection_reasons


def test_distinct_account_credential_and_cost_profiles_keep_distinct_eligibility():
    free = _profile(
        "same-model:account-a:free-key",
        provider_id="same-provider",
        model_id="same-model",
        account_scope_id="account-a",
        credential_scope_id="free-key",
        quota_buckets=(_bucket("free-account-bucket", authority_scope_id="account-a"),),
    )
    byok = _profile(
        "same-model:account-b:paid-key",
        provider_id="same-provider",
        model_id="same-model",
        account_scope_id="account-b",
        credential_scope_id="paid-key",
        execution_mode="EXPLICIT_BYOK",
        cost_class="USER_BILLED",
        billing_owner="user",
        strict_free_enabled=False,
        quota_buckets=(_bucket("paid-account-bucket", authority_scope_id="account-b"),),
    )
    candidates = EndpointRegistry((free, byok)).candidates(_requirements())

    assert free.provider_id == byok.provider_id
    assert free.model_id == byok.model_id
    assert free.endpoint_profile_id != byok.endpoint_profile_id
    assert candidates.assessments[0].eligible
    assert not candidates.assessments[1].eligible
    assert "cost_not_verified_free" in candidates.assessments[1].rejection_reasons


def test_rotated_credentials_can_share_only_the_same_verified_authority_bucket():
    shared = _bucket("provider-account-shared", authority_scope_id="account-a")
    first = _profile(
        "profile:key-a", credential_scope_id="credential-a", quota_buckets=(shared,)
    )
    rotated = _profile(
        "profile:key-b", credential_scope_id="credential-b", quota_buckets=(shared,)
    )

    registry = EndpointRegistry((first, rotated))

    assert registry.candidates(_requirements()).eligible_profiles == (first, rotated)


@pytest.mark.parametrize(
    ("second_profile_updates", "expected_error"),
    [
        ({"account_scope_id": "account-b"}, "shared_quota_bucket_scope_conflict"),
        ({"execution_mode": "EXPLICIT_BYOK", "cost_class": "USER_BILLED", "billing_owner": "user"}, "shared_quota_bucket_scope_conflict"),
        ({"cost_class": "UNKNOWN"}, "shared_quota_bucket_scope_conflict"),
    ],
)
def test_shared_bucket_cannot_aggregate_independent_accounts_or_modes(
    second_profile_updates, expected_error
):
    shared = _bucket("shared", authority_scope_id="account-a")
    first = _profile("profile:one", quota_buckets=(shared,))
    second = _profile("profile:two", quota_buckets=(shared,), **second_profile_updates)

    with pytest.raises(RegistryConflictError, match=expected_error):
        EndpointRegistry((first, second))


def test_lifecycle_updates_and_removals_invalidate_frozen_candidates():
    profile = _profile()
    registry = EndpointRegistry((profile,))
    candidates = registry.candidates(_requirements())
    assert registry.revalidate(candidates, profile.endpoint_profile_id, _requirements()) == profile

    changed = profile.model_copy(update={"profile_version": 2, "context_limit_tokens": 2048})
    registry.upsert(changed)
    assert registry.registry_version != candidates.registry_version
    with pytest.raises(RegistryRevisionChangedError):
        registry.revalidate(candidates, profile.endpoint_profile_id, _requirements())

    updated_candidates = registry.candidates(_requirements())
    registry.remove(profile.endpoint_profile_id)
    assert registry.profiles == ()
    with pytest.raises(RegistryRevisionChangedError):
        registry.revalidate(updated_candidates, profile.endpoint_profile_id, _requirements())

    registry.upsert(profile)
    with pytest.raises(RegistryRevisionChangedError):
        registry.revalidate(candidates, profile.endpoint_profile_id, _requirements())

    registry.upsert(profile)
    with pytest.raises(RegistryRevisionChangedError):
        registry.revalidate(candidates, profile.endpoint_profile_id, _requirements())


def test_profile_version_cannot_be_reused_for_changed_facts():
    profile = _profile()
    registry = EndpointRegistry((profile,))

    with pytest.raises(RegistryConflictError, match="endpoint_profile_version_must_increase"):
        registry.upsert(profile.model_copy(update={"context_limit_tokens": 2048}))


def test_over_limit_profile_set_is_rejected_without_candidate_truncation():
    profiles = tuple(
        _profile(
            f"profile:{index}",
            account_scope_id=f"account-{index}",
            quota_buckets=(_bucket(f"bucket-{index}", authority_scope_id=f"account-{index}"),),
        )
        for index in range(33)
    )

    with pytest.raises(CandidateSetOverflowError, match="endpoint_candidate_limit_exceeded"):
        EndpointRegistry(profiles)


def test_registry_version_is_order_independent_while_candidate_facts_keep_registration_order():
    first = _profile("z-provider:model")
    second = _profile("a-provider:model", provider_id="other-provider")
    left = EndpointRegistry((first, second))
    right = EndpointRegistry((second, first))

    assert left.registry_version == right.registry_version
    assert [item.profile.endpoint_profile_id for item in left.candidates(_requirements()).assessments] == [
        "z-provider:model", "a-provider:model"
    ]


def test_initial_reference_profiles_are_unverified_and_never_copy_secrets():
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="gemini-local-model",
        ai_api_key="synthetic-secret-value",
        groq_model="groq-local-model",
        groq_api_key="synthetic-groq-secret",
        cloudflare_account_id="account-123",
        cloudflare_model="@cf/synthetic/model",
        cloudflare_api_token="synthetic-cloudflare-secret",
    )

    profiles = build_initial_endpoint_profiles(settings)
    by_provider = {profile.provider_id: profile for profile in profiles}
    serialized = " ".join(profile.model_dump_json() for profile in profiles)

    assert {"gemini", "google_genai", "groq", "cloudflare_workers_ai"} <= set(by_provider)
    assert not by_provider["gemini"].strict_free_enabled
    assert by_provider["gemini"].counter is not None
    assert not by_provider["gemini"].counter.approved
    assert "token_counting" not in by_provider["groq"].capabilities
    assert "synthetic-secret-value" not in serialized
    assert "synthetic-groq-secret" not in serialized
    assert "synthetic-cloudflare-secret" not in serialized
    assert all(not item.eligible for item in EndpointRegistry(profiles).candidates(_requirements()).assessments)


def test_gemini_profile_requires_explicit_account_privacy_counter_and_quota_facts():
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="gemini-account-model",
        ai_api_key="synthetic-secret",
        gemini_account_scope_id="gemini-account-a",
        gemini_endpoint_context_limit_tokens=32768,
        gemini_endpoint_output_limit_tokens=4096,
        gemini_free_tier_verified=True,
        gemini_privacy_approved=True,
        gemini_preflight_reference="preflight:gemini-account-a-v1",
        gemini_counter_compatibility_verified=True,
        gemini_counter_preflight_reference="preflight:gemini-counter-v1",
        gemini_quota_membership_verified=True,
        gemini_quota_buckets=(
            {
                "bucket_id": "gemini-account-a-free-requests",
                "authority_scope_id": "gemini-account-a",
                "operations": ["bounded_generation", "token_counting"],
                "unit": "requests",
                "window_seconds": 60,
                "source": "provider_contract",
                "confidence": "verified",
            },
        ),
    )
    profiles = build_initial_endpoint_profiles(settings)
    generation = profiles[0]
    registry = EndpointRegistry(profiles)
    requirements = _requirements(
        required_capabilities=frozenset({"bounded_generation", "token_counting"}),
        count=CountRequirement(minimum_confidence="authoritative"),
    )

    assert generation.tier_verified
    assert generation.account_scope_id == "gemini-account-a"
    assert generation.counter is not None and generation.counter.approved
    assert registry.candidates(requirements).assessments[0].eligible


def test_configured_groq_free_generation_profile_still_fails_count_required_task():
    quota = {
        "bucket_id": "groq-account-a-requests",
        "authority_scope_id": "groq-account-a",
        "operations": ["bounded_generation", "streaming"],
        "unit": "requests",
        "window_seconds": 60,
        "source": "operator_attestation",
        "confidence": "verified",
    }
    settings = Settings(
        _env_file=None,
        ai_provider="groq",
        ai_model="unused-gemini-model",
        groq_adapter_enabled=True,
        groq_model="groq-free-model",
        groq_api_key="synthetic-groq-key",
        groq_free_tier_verified=True,
        groq_privacy_approved=True,
        groq_preflight_reference="preflight:groq-account-a-v1",
        groq_account_scope_id="groq-account-a",
        groq_quota_membership_verified=True,
        groq_quota_buckets=(quota,),
    )
    profile, = build_initial_endpoint_profiles(settings)
    requirements = _requirements(
        required_capabilities=frozenset({"bounded_generation", "token_counting"}),
        count=CountRequirement(minimum_confidence="authoritative"),
    )

    result = EndpointRegistry((profile,)).candidates(requirements).assessments[0]

    assert not result.eligible
    assert "capability_missing:token_counting" in result.rejection_reasons
    assert "authoritative_counter_mapping_missing" in result.rejection_reasons


def test_registry_profile_schema_rejects_secret_fields_and_non_symbolic_credential_refs():
    document = _profile().model_dump(mode="json")
    document["api_key"] = "synthetic-secret"
    with pytest.raises(ValidationError):
        EndpointProfile.model_validate(document)

    document.pop("api_key")
    document["credential_reference"] = "env:synthetic-secret-value"
    with pytest.raises(ValidationError, match="credential_reference_must_be_symbolic"):
        EndpointProfile.model_validate(document)
