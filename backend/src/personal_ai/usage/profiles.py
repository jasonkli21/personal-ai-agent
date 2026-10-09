"""Resolve configured, secret-free Phase 18 profiles for accounting."""

from personal_ai.routing.configured import build_initial_endpoint_profiles
from personal_ai.routing.contracts import EndpointProfile, QuotaBucket
from personal_ai.usage.contracts import ProviderEndpoint


def endpoint_for_operation(settings, *, provider_id: str, model_id: str, operation: str) -> ProviderEndpoint:
    profiles = build_initial_endpoint_profiles(settings)
    matching = [
        profile for profile in profiles
        if profile.provider_id == provider_id
        and profile.model_id == model_id
        and operation in profile.capabilities
    ]
    if len(matching) != 1:
        raise ValueError("provider_usage_endpoint_profile_ambiguous")
    return from_profile(matching[0])


def public_lookup_endpoint(
    *, provider_id: str, model_id: str, endpoint_id: str, deployment_id: str,
    authority_scope_id: str,
) -> ProviderEndpoint:
    """Describe a public lookup service without inventing capacity or cost facts."""
    bucket = QuotaBucket(
        bucket_id=f"{authority_scope_id}:requests",
        authority_scope_id=authority_scope_id,
        operations=frozenset({"lookup"}),
        unit="requests",
        source="unknown",
        confidence="unknown",
    )
    return ProviderEndpoint(
        endpoint_profile_id=f"{provider_id}:lookup",
        profile_version=1,
        provider_id=provider_id,
        model_id=model_id,
        endpoint_id=endpoint_id,
        deployment_id=deployment_id,
        credential_source="none",
        credential_scope_id=None,
        account_scope_id=authority_scope_id,
        project_scope_id=None,
        tier_id="public",
        execution_mode="STRICT_FREE",
        cost_class="UNKNOWN",
        billing_owner="unknown",
        serializer_id=f"{provider_id}-lookup-v1",
        runtime_id="httpx-v1",
        quota_buckets=(bucket,),
    )


def from_profile(profile: EndpointProfile) -> ProviderEndpoint:
    return ProviderEndpoint(
        endpoint_profile_id=profile.endpoint_profile_id,
        profile_version=profile.profile_version,
        provider_id=profile.provider_id,
        model_id=profile.model_id,
        endpoint_id=profile.endpoint_id,
        deployment_id=profile.deployment_id,
        credential_source=profile.credential_source,
        credential_scope_id=profile.credential_scope_id,
        account_scope_id=profile.account_scope_id,
        project_scope_id=profile.project_scope_id,
        tier_id=profile.tier_id,
        execution_mode=profile.execution_mode,
        cost_class=profile.cost_class,
        billing_owner=profile.billing_owner,
        serializer_id=profile.serializer_id,
        runtime_id=profile.runtime_id,
        quota_buckets=profile.quota_buckets,
    )
