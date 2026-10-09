"""Resolve configured, secret-free Phase 18 profiles for accounting."""

from threading import Lock

from personal_ai.routing.configured import build_initial_endpoint_profiles
from personal_ai.routing.contracts import EndpointProfile, EndpointRef, EndpointRegistrySnapshot
from personal_ai.routing.registry import EndpointRegistry
from personal_ai.usage.contracts import ProviderEndpoint
from personal_ai.usage.quota import QuotaObservation

_KNOWN_PROFILE_IDS = {
    ("gemini", "streaming"): "gemini:generation",
    ("gemini", "bounded_generation"): "gemini:generation",
    ("gemini", "structured_generation"): "gemini:generation",
    ("gemini", "token_counting"): "gemini:generation",
    ("google_genai", "embeddings"): "google_genai:embedding",
    ("groq", "streaming"): "groq:generation",
    ("groq", "bounded_generation"): "groq:generation",
    ("groq", "structured_generation"): "groq:generation",
    ("cloudflare_workers_ai", "streaming"): "cloudflare_workers_ai:generation",
    ("cloudflare_workers_ai", "bounded_generation"): "cloudflare_workers_ai:generation",
    ("cloudflare_workers_ai", "structured_generation"): "cloudflare_workers_ai:generation",
    ("brave_search", "search"): "brave:search",
}


class EndpointProfileResolver:
    """Resolve the fixed-provider path through the current durable registry."""

    def __init__(
        self,
        registry: EndpointRegistry | None = None,
        repository=None,
        *,
        settings=None,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.settings = settings
        self._registry_lock = Lock()

    @classmethod
    def from_settings(cls, settings, repository) -> "EndpointProfileResolver":
        """Build the durable registry only when a provider profile is needed."""
        return cls(repository=repository, settings=settings)

    def _current_registry(self) -> EndpointRegistry:
        if self.registry is None:
            with self._registry_lock:
                if self.registry is None:
                    if self.settings is None or self.repository is None:
                        raise RuntimeError("provider_usage_registry_not_configured")
                    self.registry = EndpointRegistry(
                        build_initial_endpoint_profiles(self.settings),
                        repository=self.repository,
                    )
        return self.registry

    def resolve(self, *, provider_id: str, model_id: str, operation: str) -> ProviderEndpoint:
        snapshot = self._current_registry().refresh()
        preferred_id = _KNOWN_PROFILE_IDS.get((provider_id, operation))
        matches = [
            profile
            for profile in snapshot.profiles
            if profile.provider_id == provider_id
            and profile.model_id == model_id
            and operation in profile.capabilities
            and (preferred_id is None or profile.endpoint_profile_id == preferred_id)
        ]
        if len(matches) != 1:
            raise ValueError("provider_usage_endpoint_profile_ambiguous")
        return from_profile(
            matches[0],
            registry_version=snapshot.registry_version,
            registry_revision=snapshot.revision,
        )

    def resolve_ref(self, ref: EndpointRef) -> ProviderEndpoint:
        snapshot = self._current_registry().refresh()
        profile = next((p for p in snapshot.profiles if p.ref == ref), None)
        if profile is None:
            raise ValueError("provider_usage_endpoint_profile_stale")
        return from_profile(profile)

    def assert_current(self, endpoint: ProviderEndpoint) -> None:
        snapshot = self._current_registry().refresh()
        self._assert_current_in_snapshot(snapshot, endpoint)

    def assert_current_in_transaction(self, connection, endpoint: ProviderEndpoint) -> None:
        if self.repository is None:
            self.assert_current(endpoint)
            return
        snapshot = self.repository.load_from_connection(connection, lock=True)
        if snapshot is None:
            raise ValueError("provider_usage_endpoint_profile_stale")
        self._assert_current_in_snapshot(snapshot, endpoint)

    @staticmethod
    def _assert_current_in_snapshot(
        snapshot: EndpointRegistrySnapshot, endpoint: ProviderEndpoint
    ) -> None:
        profile = next(
            (
                item
                for item in snapshot.profiles
                if item.endpoint_profile_id == endpoint.endpoint_profile_id
            ),
            None,
        )
        from dataclasses import replace

        if profile is None or from_profile(profile) != replace(
            endpoint, registry_version=None, registry_revision=None
        ):
            raise ValueError("provider_usage_endpoint_profile_stale")


def endpoint_for_operation(
    settings,
    *,
    provider_id: str,
    model_id: str,
    operation: str,
    resolver: EndpointProfileResolver | None = None,
) -> ProviderEndpoint:
    if resolver is not None:
        return resolver.resolve(provider_id=provider_id, model_id=model_id, operation=operation)
    profiles = build_initial_endpoint_profiles(settings)
    preferred_id = _KNOWN_PROFILE_IDS.get((provider_id, operation))
    matching = [
        profile
        for profile in profiles
        if profile.provider_id == provider_id
        and profile.model_id == model_id
        and operation in profile.capabilities
        and (preferred_id is None or profile.endpoint_profile_id == preferred_id)
    ]
    if len(matching) != 1:
        raise ValueError("provider_usage_endpoint_profile_ambiguous")
    return from_profile(matching[0])


def public_lookup_endpoint(
    *,
    provider_id: str,
    model_id: str,
    endpoint_id: str,
    deployment_id: str,
    authority_scope_id: str,
) -> ProviderEndpoint:
    """Describe a public lookup service without inventing capacity or cost facts."""
    bucket = QuotaObservation(
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
        quota_membership="verified",
        quota_buckets=(bucket,),
    )


def from_profile(
    profile: EndpointProfile,
    *,
    registry_version: str | None = None,
    registry_revision: int | None = None,
) -> ProviderEndpoint:
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
        quota_membership=profile.quota_membership,
        registry_version=registry_version,
        registry_revision=registry_revision,
        quota_buckets=tuple(QuotaObservation(**b.model_dump()) for b in profile.quota_buckets),
    )
