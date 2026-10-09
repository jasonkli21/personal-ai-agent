"""Build initial endpoint profiles from safe operator configuration facts."""

from __future__ import annotations

from collections.abc import Sequence

from personal_ai.routing.contracts import (
    CounterCompatibility,
    DataUsePolicy,
    EndpointProfile,
    QuotaBucket,
    StrictFreeEligibilityAttestation,
)
from personal_ai.settings import Settings


def build_initial_endpoint_profiles(settings: Settings) -> tuple[EndpointProfile, ...]:
    """Seed configured reference endpoints without treating provider flags as proof.

    Credentials are inspected only for presence. Profiles contain symbolic
    environment-variable references, account/credential scope labels, and
    operator evidence references; secret values never cross this boundary.
    """
    profiles: list[EndpointProfile] = []
    if settings.ai_provider.lower() == "gemini":
        profiles.append(_gemini_profile(settings))
        profiles.append(_gemini_embedding_profile(settings))
    if settings.groq_model:
        profiles.append(_groq_profile(settings))
    if settings.cloudflare_model:
        profiles.append(_cloudflare_profile(settings))
    if settings.research_search_adapter == "brave":
        profiles.append(_brave_search_profile(settings))
    by_id = {profile.endpoint_profile_id: profile for profile in profiles}
    for raw_profile in settings.inference_additional_endpoint_profiles:
        profile = EndpointProfile.model_validate(raw_profile)
        previous = by_id.get(profile.endpoint_profile_id)
        if previous is not None and profile.profile_version <= previous.profile_version:
            raise ValueError("endpoint_profile_version_must_increase")
        by_id[profile.endpoint_profile_id] = profile
    return tuple(by_id.values())


def _gemini_profile(settings: Settings) -> EndpointProfile:
    account_scope = settings.gemini_account_scope_id.strip() or None
    # This is one operator-managed profile slot. Account, credential and model
    # changes advance its version during registry reconciliation.
    profile_id = "gemini:generation"
    endpoint_id = "gemini-generate-content-v1beta"
    deployment_id = "generativelanguage.googleapis.com-v1beta"
    verified_free = settings.gemini_free_tier_verified
    counter_approved = settings.gemini_counter_compatibility_verified
    structured_approved = settings.gemini_structured_output_verified
    api_key_configured = bool(settings.ai_api_key.get_secret_value())
    return EndpointProfile(
        endpoint_profile_id=profile_id,
        profile_version=1,
        provider_id="gemini",
        model_id=settings.ai_model,
        endpoint_id=endpoint_id,
        deployment_id=deployment_id,
        credential_source="environment",
        credential_reference="env:AI_API_KEY",
        credential_scope_id=settings.gemini_credential_scope_id,
        account_scope_id=account_scope,
        tier_id="free" if verified_free else "unverified",
        tier_verified=verified_free,
        execution_mode="STRICT_FREE",
        cost_class="VERIFIED_FREE" if verified_free else "UNKNOWN",
        billing_owner="provider_account" if verified_free else "unknown",
        enabled=api_key_configured,
        strict_free_enabled=verified_free,
        capabilities=frozenset(
            {
                "streaming",
                "bounded_generation",
                "token_counting",
                *({"structured_generation"} if structured_approved else set()),
            }
        ),
        context_limit_tokens=settings.gemini_endpoint_context_limit_tokens,
        max_output_tokens=settings.gemini_endpoint_output_limit_tokens,
        data_use_policy=DataUsePolicy(
            status="approved" if settings.gemini_privacy_approved else "unknown",
            max_sensitivity=settings.gemini_privacy_max_sensitivity,
            policy_reference=(settings.gemini_preflight_reference or None),
        ),
        strict_free_attestation=(
            _strict_free_attestation(
                endpoint_profile_id=profile_id,
                provider_id="gemini",
                model_id=settings.ai_model,
                endpoint_id=endpoint_id,
                deployment_id=deployment_id,
                account_scope_id=account_scope,
                credential_scope_id=settings.gemini_credential_scope_id,
                tier_id="free",
                reference=settings.gemini_preflight_reference,
                verified=verified_free,
            )
        ),
        serializer_id="gemini-content-v1",
        runtime_id="litellm-1.102.1",
        structured_schema_ids=(
            settings.gemini_structured_schema_ids if structured_approved else ()
        ),
        counter=CounterCompatibility(
            endpoint_profile_id=profile_id,
            endpoint_id=endpoint_id,
            deployment_id=deployment_id,
            credential_scope_id=settings.gemini_credential_scope_id,
            account_scope_id=account_scope,
            provider_id="gemini",
            model_id=settings.ai_model,
            serializer_id="gemini-content-v1",
            counter_id="gemini-count-tokens-v1",
            confidence="authoritative" if counter_approved else "unknown",
            approved=counter_approved,
            provenance_reference=(settings.gemini_counter_preflight_reference or None),
            structured_schema_ids=settings.gemini_structured_schema_ids,
        ),
        quota_membership=(
            "verified" if settings.gemini_quota_membership_verified else "unknown"
        ),
        quota_buckets=_parse_buckets(settings.gemini_quota_buckets),
    )


def _gemini_embedding_profile(settings: Settings) -> EndpointProfile:
    """Keep embedding dispatch separately admissible and separately quota scoped."""
    return EndpointProfile(
        endpoint_profile_id="google_genai:embedding",
        profile_version=1,
        provider_id="google_genai",
        model_id=settings.memory_embedding_model,
        endpoint_id="gemini-batch-embed-contents-v1beta",
        deployment_id="generativelanguage.googleapis.com-v1beta",
        credential_source="environment",
        credential_reference="env:AI_API_KEY",
        credential_scope_id=settings.gemini_credential_scope_id,
        account_scope_id=settings.gemini_account_scope_id.strip() or None,
        tier_id="unverified",
        tier_verified=False,
        execution_mode="STRICT_FREE",
        cost_class="UNKNOWN",
        billing_owner="unknown",
        enabled=bool(settings.ai_api_key.get_secret_value()),
        strict_free_enabled=False,
        capabilities=frozenset({"embeddings"}),
        context_limit_tokens=settings.gemini_embedding_context_limit_tokens,
        max_output_tokens=None,
        embedding_dimensions=settings.memory_embedding_dimensions,
        data_use_policy=DataUsePolicy(),
        serializer_id="gemini-embedding-v1",
        runtime_id="litellm-1.102.1",
        quota_membership="unknown",
        quota_buckets=(),
    )


def _groq_profile(settings: Settings) -> EndpointProfile:
    verified_free = settings.groq_free_tier_verified
    structured = settings.groq_structured_output_verified
    model = settings.groq_model
    return EndpointProfile(
        endpoint_profile_id="groq:generation",
        profile_version=1,
        provider_id="groq",
        model_id=model,
        endpoint_id="groq-chat-completions-v1",
        deployment_id="api.groq.com-openai-v1",
        credential_source="environment",
        credential_reference="env:GROQ_API_KEY",
        credential_scope_id=settings.groq_credential_scope_id,
        account_scope_id=settings.groq_account_scope_id.strip() or None,
        tier_id="free" if verified_free else "unverified",
        tier_verified=verified_free,
        execution_mode="STRICT_FREE",
        cost_class="VERIFIED_FREE" if verified_free else "UNKNOWN",
        billing_owner="provider_account" if verified_free else "unknown",
        enabled=settings.groq_adapter_enabled,
        strict_free_enabled=verified_free,
        capabilities=frozenset(
            {"streaming", "bounded_generation"}
            | ({"structured_generation"} if structured else set())
        ),
        context_limit_tokens=settings.groq_endpoint_context_limit_tokens,
        max_output_tokens=settings.groq_endpoint_output_limit_tokens,
        structured_schema_ids=(settings.groq_structured_schema_ids if structured else ()),
        data_use_policy=DataUsePolicy(
            status="approved" if settings.groq_privacy_approved else "unknown",
            max_sensitivity=settings.groq_privacy_max_sensitivity,
            policy_reference=settings.groq_preflight_reference or None,
        ),
        strict_free_attestation=_strict_free_attestation(
            endpoint_profile_id="groq:generation",
            provider_id="groq",
            model_id=model,
            endpoint_id="groq-chat-completions-v1",
            deployment_id="api.groq.com-openai-v1",
            account_scope_id=settings.groq_account_scope_id.strip() or None,
            credential_scope_id=settings.groq_credential_scope_id,
            tier_id="free",
            reference=settings.groq_preflight_reference,
            verified=verified_free,
        ),
        serializer_id="groq-chat-completions-v1",
        runtime_id="litellm-1.102.1",
        quota_membership=(
            "verified" if settings.groq_quota_membership_verified else "unknown"
        ),
        quota_buckets=_parse_buckets(settings.groq_quota_buckets),
    )


def _cloudflare_profile(settings: Settings) -> EndpointProfile:
    verified_free = settings.cloudflare_free_tier_verified
    structured = settings.cloudflare_structured_output_verified
    model = settings.cloudflare_model
    account_scope = settings.cloudflare_account_id.strip() or None
    return EndpointProfile(
        endpoint_profile_id="cloudflare_workers_ai:generation",
        profile_version=1,
        provider_id="cloudflare_workers_ai",
        model_id=model,
        endpoint_id="cloudflare-workers-ai-chat-v1",
        deployment_id="api.cloudflare.com-client-v4-accounts-ai-v1",
        credential_source="environment",
        credential_reference="env:CLOUDFLARE_API_TOKEN",
        credential_scope_id=settings.cloudflare_credential_scope_id,
        account_scope_id=account_scope,
        project_scope_id=settings.cloudflare_account_id.strip() or None,
        tier_id="free" if verified_free else "unverified",
        tier_verified=verified_free,
        execution_mode="STRICT_FREE",
        cost_class="VERIFIED_FREE" if verified_free else "UNKNOWN",
        billing_owner="provider_account" if verified_free else "unknown",
        enabled=settings.cloudflare_adapter_enabled,
        strict_free_enabled=verified_free,
        capabilities=frozenset(
            {"streaming", "bounded_generation"}
            | ({"structured_generation"} if structured else set())
        ),
        context_limit_tokens=settings.cloudflare_endpoint_context_limit_tokens,
        max_output_tokens=settings.cloudflare_endpoint_output_limit_tokens,
        structured_schema_ids=(settings.cloudflare_structured_schema_ids if structured else ()),
        data_use_policy=DataUsePolicy(
            status="approved" if settings.cloudflare_privacy_approved else "unknown",
            max_sensitivity=settings.cloudflare_privacy_max_sensitivity,
            policy_reference=settings.cloudflare_preflight_reference or None,
        ),
        strict_free_attestation=_strict_free_attestation(
            endpoint_profile_id="cloudflare_workers_ai:generation",
            provider_id="cloudflare_workers_ai",
            model_id=model,
            endpoint_id="cloudflare-workers-ai-chat-v1",
            deployment_id="api.cloudflare.com-client-v4-accounts-ai-v1",
            account_scope_id=account_scope,
            credential_scope_id=settings.cloudflare_credential_scope_id,
            tier_id="free",
            reference=settings.cloudflare_preflight_reference,
            verified=verified_free,
        ),
        serializer_id="cloudflare-workers-ai-chat-v1",
        runtime_id="litellm-1.102.1",
        quota_membership=(
            "verified" if settings.cloudflare_quota_membership_verified else "unknown"
        ),
        quota_buckets=_parse_buckets(settings.cloudflare_quota_buckets),
    )


def _brave_search_profile(settings: Settings) -> EndpointProfile:
    """Represent search's account and prepaid no-overflow facts explicitly."""
    account_scope = settings.research_brave_account_scope_id.strip() or None
    preflight_reference = settings.research_brave_preflight_reference.strip()
    prepaid_attested = bool(
        settings.research_brave_prepaid_verified
        and settings.research_brave_auto_reload_disabled
        and settings.research_brave_no_paid_balance_verified
        and account_scope
        and preflight_reference
    )
    quota_buckets = _parse_buckets(settings.research_brave_quota_buckets)
    if not quota_buckets and account_scope is not None:
        quota_buckets = (
            QuotaBucket(
                bucket_id=f"brave:{account_scope}:requests",
                authority_scope_id=account_scope,
                operations=frozenset({"search"}),
                unit="requests",
                source="unknown",
                confidence="unknown",
            ),
        )
    source_rights_verified = (
        settings.research_provider_storage_approved
        and settings.research_brave_source_rights_verified
    )
    return EndpointProfile(
        endpoint_profile_id="brave:search",
        profile_version=1,
        provider_id="brave_search",
        model_id="web-search-v1",
        endpoint_id="brave-web-search-v1",
        deployment_id="api.search.brave.com-res-v1",
        credential_source="environment",
        credential_reference="env:RESEARCH_API_KEY",
        credential_scope_id=settings.research_brave_credential_scope_id,
        account_scope_id=account_scope,
        tier_id="prepaid" if prepaid_attested else "unverified",
        tier_verified=prepaid_attested,
        execution_mode="STRICT_FREE",
        cost_class="UNKNOWN",
        billing_owner="unknown",
        enabled=(
            settings.research_enabled
            and settings.research_search_adapter == "brave"
            and bool(settings.research_api_key.get_secret_value())
        ),
        strict_free_enabled=False,
        capabilities=frozenset({"search"}),
        max_search_query_chars=500,
        max_search_results=12,
        data_use_policy=DataUsePolicy(
            status=("approved" if source_rights_verified else "unknown"),
            policy_reference=(
                settings.research_brave_preflight_reference.strip() or None
                if source_rights_verified
                else None
            ),
        ),
        serializer_id="brave-search-query-v1",
        runtime_id="httpx-v1",
        quota_membership=("verified" if settings.research_brave_quota_buckets else "unknown"),
        quota_buckets=quota_buckets,
        strict_free_attestation=(
            StrictFreeEligibilityAttestation(
                endpoint_profile_id="brave:search",
                provider_id="brave_search",
                model_id="web-search-v1",
                endpoint_id="brave-web-search-v1",
                deployment_id="api.search.brave.com-res-v1",
                account_scope_id=account_scope,
                credential_scope_id=settings.research_brave_credential_scope_id,
                tier_id="prepaid",
                reference=preflight_reference,
                source="operator_preflight",
                zero_cost_verified=True,
                paid_overflow_excluded=True,
            )
            if prepaid_attested
            else None
        ),
    )


def _parse_buckets(values: Sequence[dict[str, object]]) -> tuple[QuotaBucket, ...]:
    return tuple(QuotaBucket.model_validate(value) for value in values)


def _strict_free_attestation(
    *,
    endpoint_profile_id: str,
    provider_id: str,
    model_id: str,
    endpoint_id: str,
    deployment_id: str,
    account_scope_id: str | None,
    credential_scope_id: str,
    tier_id: str,
    reference: str,
    verified: bool,
) -> StrictFreeEligibilityAttestation | None:
    if not verified:
        return None
    return StrictFreeEligibilityAttestation(
        endpoint_profile_id=endpoint_profile_id,
        provider_id=provider_id,
        model_id=model_id,
        endpoint_id=endpoint_id,
        deployment_id=deployment_id,
        account_scope_id=account_scope_id,
        credential_scope_id=credential_scope_id,
        tier_id=tier_id,
        reference=reference,
        source="operator_preflight",
        zero_cost_verified=True,
        paid_overflow_excluded=True,
    )
