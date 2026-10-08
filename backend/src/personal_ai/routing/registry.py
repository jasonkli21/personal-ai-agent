"""Deterministic strict-free admission and version-frozen endpoint lifecycle."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from personal_ai.routing.contracts import (
    CandidateAssessment,
    EndpointCandidateRequirements,
    EndpointCandidateSet,
    EndpointProfile,
    EndpointRegistrySnapshot,
    QuotaBucket,
    compute_registry_version,
    confidence_meets,
    sensitivity_exceeds,
)

MAX_ENDPOINT_CANDIDATES = 32


class EndpointRegistryError(RuntimeError):
    """A registry snapshot or lifecycle operation could not be trusted."""


class CandidateSetOverflowError(EndpointRegistryError):
    """The configured endpoint set exceeds the bounded decision contract."""


class RegistryConflictError(EndpointRegistryError):
    """A stale profile version or concurrent durable registry write was found."""


class RegistryRevisionChangedError(EndpointRegistryError):
    """A decision used candidates from an older endpoint registry revision."""


class EndpointNotAdmissibleError(EndpointRegistryError):
    """A candidate no longer passes hard admission at dispatch revalidation."""

    def __init__(self, rejection_reasons: tuple[str, ...]):
        self.rejection_reasons = rejection_reasons
        super().__init__("endpoint_not_admissible")


class EndpointRegistryRepository(Protocol):
    """Durable owner for registry snapshots under the Phase 10 Postgres boundary."""

    def load(self) -> EndpointRegistrySnapshot | None: ...

    def save(
        self,
        profiles: Sequence[EndpointProfile],
        *,
        expected_registry_version: str | None,
    ) -> EndpointRegistrySnapshot: ...


class EndpointRegistry:
    """Bounded, versioned profile catalog with a fact-only candidate API.

    An optional repository persists the same immutable snapshot in Postgres.
    Candidates retain the version used to assess them; every dispatch handoff
    must revalidate that exact version and profile against current facts.
    """

    def __init__(
        self,
        profiles: Sequence[EndpointProfile] = (),
        *,
        repository: EndpointRegistryRepository | None = None,
    ) -> None:
        self._lock = RLock()
        self._repository = repository
        configured = tuple(profiles)
        self._validate_profiles(configured)
        stored = repository.load() if repository is not None else None
        if stored is not None:
            self._validate_profiles(stored.profiles)
            self._snapshot = stored
        elif repository is not None:
            self._snapshot = repository.save(
                configured, expected_registry_version=None
            )
            self._validate_profiles(self._snapshot.profiles)
        else:
            self._snapshot = self._make_snapshot(configured, revision=0)

    @property
    def snapshot(self) -> EndpointRegistrySnapshot:
        with self._lock:
            return self._snapshot

    @property
    def profiles(self) -> tuple[EndpointProfile, ...]:
        return self.snapshot.profiles

    @property
    def registry_version(self) -> str:
        return self.snapshot.registry_version

    def candidates(
        self,
        requirements: EndpointCandidateRequirements,
        *,
        now: datetime | None = None,
    ) -> EndpointCandidateSet:
        """Return every profile fact and hard-admission rejection, without scores."""
        instant = _aware_utc(now or datetime.now(UTC))
        with self._lock:
            snapshot = self._snapshot
            assessments = tuple(
                _assess(profile, requirements, instant) for profile in snapshot.profiles
            )
            return EndpointCandidateSet(
                registry_version=snapshot.registry_version,
                execution_mode=requirements.execution_mode,
                assessments=assessments,
            )

    def revalidate(
        self,
        candidates: EndpointCandidateSet,
        endpoint_profile_id: str,
        requirements: EndpointCandidateRequirements,
        *,
        now: datetime | None = None,
    ) -> EndpointProfile:
        """Recheck frozen registry/profile eligibility immediately before use."""
        with self._lock:
            snapshot = self._snapshot
            if candidates.registry_version != snapshot.registry_version:
                raise RegistryRevisionChangedError("endpoint_registry_revision_changed")
            assessment = next(
                (
                    item
                    for item in candidates.assessments
                    if item.profile.endpoint_profile_id == endpoint_profile_id
                ),
                None,
            )
            if assessment is None:
                raise EndpointNotAdmissibleError(("candidate_not_in_frozen_set",))
            current = next(
                (
                    profile for profile in snapshot.profiles
                    if profile.endpoint_profile_id == endpoint_profile_id
                ),
                None,
            )
            if current is None or current.profile_version != assessment.profile.profile_version:
                raise RegistryRevisionChangedError("endpoint_profile_version_changed")
            current_assessment = _assess(current, requirements, _aware_utc(now or datetime.now(UTC)))
            if not current_assessment.eligible:
                raise EndpointNotAdmissibleError(current_assessment.rejection_reasons)
            return current

    def upsert(self, profile: EndpointProfile) -> EndpointRegistrySnapshot:
        """Add a profile or replace it at a strictly higher profile version."""
        with self._lock:
            current = {item.endpoint_profile_id: item for item in self._snapshot.profiles}
            previous = current.get(profile.endpoint_profile_id)
            if previous == profile:
                return self._snapshot
            if previous is not None and profile.profile_version <= previous.profile_version:
                raise RegistryConflictError("endpoint_profile_version_must_increase")
            current[profile.endpoint_profile_id] = profile
            return self._publish(tuple(current.values()))

    def remove(self, endpoint_profile_id: str) -> EndpointRegistrySnapshot:
        """Remove a profile and advance the registry revision when it existed."""
        with self._lock:
            current = tuple(
                item for item in self._snapshot.profiles
                if item.endpoint_profile_id != endpoint_profile_id
            )
            if len(current) == len(self._snapshot.profiles):
                return self._snapshot
            return self._publish(current)

    def _publish(self, profiles: tuple[EndpointProfile, ...]) -> EndpointRegistrySnapshot:
        self._validate_profiles(profiles)
        expected = self._snapshot.registry_version
        if self._repository is not None:
            candidate = self._repository.save(
                profiles, expected_registry_version=expected
            )
        else:
            candidate = self._make_snapshot(profiles, revision=self._snapshot.revision + 1)
        self._validate_profiles(candidate.profiles)
        self._snapshot = candidate
        return candidate

    @staticmethod
    def _make_snapshot(
        profiles: Sequence[EndpointProfile], *, revision: int
    ) -> EndpointRegistrySnapshot:
        profile_tuple = tuple(profiles)
        return EndpointRegistrySnapshot(
            revision=revision,
            registry_version=compute_registry_version(profile_tuple, revision=revision),
            profiles=profile_tuple,
        )

    @staticmethod
    def _validate_profiles(profiles: Sequence[EndpointProfile]) -> None:
        if len(profiles) > MAX_ENDPOINT_CANDIDATES:
            raise CandidateSetOverflowError("endpoint_candidate_limit_exceeded")
        ids = [item.endpoint_profile_id for item in profiles]
        if len(set(ids)) != len(ids):
            raise RegistryConflictError("endpoint_profile_id_duplicate")
        _validate_shared_quota_authorities(profiles)


def _assess(
    profile: EndpointProfile,
    requirements: EndpointCandidateRequirements,
    now: datetime,
) -> CandidateAssessment:
    reasons: list[str] = []
    if requirements.execution_mode != "STRICT_FREE":
        reasons.append("execution_mode_not_automatic_strict_free")
    if not profile.enabled:
        reasons.append("endpoint_disabled_or_unconfigured")
    if profile.execution_mode != requirements.execution_mode:
        reasons.append("execution_mode_mismatch")
    if requirements.automatic and profile.execution_mode != "STRICT_FREE":
        reasons.append("explicit_only_endpoint")
    if profile.execution_mode != "STRICT_FREE" or profile.cost_class != "VERIFIED_FREE":
        reasons.append("cost_not_verified_free")
    if profile.execution_mode == "STRICT_FREE" and not profile.strict_free_enabled:
        reasons.append("strict_free_not_enabled")
    if not profile.tier_verified:
        reasons.append("account_tier_not_verified")
    if profile.billing_owner != "provider_account":
        reasons.append("billing_owner_not_verified_provider_account")
    if profile.account_scope_id is None:
        reasons.append("account_scope_unknown")
    if profile.credential_scope_id is None or profile.credential_source == "none":
        reasons.append("credential_scope_unknown")

    privacy = profile.data_use_policy
    if privacy.status == "denied":
        reasons.append("provider_data_use_denied")
    elif privacy.status == "unknown" and requirements.sensitivity != "public":
        reasons.append("provider_data_policy_unknown_for_sensitivity")
    elif sensitivity_exceeds(requirements.sensitivity, privacy.max_sensitivity):
        reasons.append("sensitivity_exceeds_provider_approval")

    missing = requirements.required_capabilities - profile.capabilities
    for capability in sorted(missing):
        reasons.append(f"capability_missing:{capability}")
    needs_input_limit = bool(
        requirements.required_capabilities
        & {"streaming", "bounded_generation", "structured_generation", "token_counting", "embeddings"}
    )
    needs_output_limit = bool(
        requirements.required_capabilities
        & {"streaming", "bounded_generation", "structured_generation"}
    )
    if needs_input_limit and profile.context_limit_tokens is None:
        reasons.append("endpoint_context_limit_unknown")
    elif profile.context_limit_tokens is not None and requirements.input_tokens > profile.context_limit_tokens:
        reasons.append("input_exceeds_endpoint_context_limit")
    if needs_output_limit and profile.max_output_tokens is None:
        reasons.append("endpoint_output_limit_unknown")
    elif profile.max_output_tokens is not None and requirements.output_tokens > profile.max_output_tokens:
        reasons.append("output_exceeds_endpoint_limit")
    if "search" in requirements.required_capabilities:
        if profile.max_search_query_chars is None:
            reasons.append("search_query_limit_unknown")
        elif requirements.search_query_chars > profile.max_search_query_chars:
            reasons.append("search_query_exceeds_endpoint_limit")
        if profile.max_search_results is None:
            reasons.append("search_result_limit_unknown")
        elif requirements.search_results > profile.max_search_results:
            reasons.append("search_results_exceed_endpoint_limit")
    if (
        requirements.embedding_dimensions is not None
        and requirements.embedding_dimensions != profile.embedding_dimensions
    ):
        reasons.append("embedding_space_dimensions_mismatch")

    if profile.quota_membership == "ambiguous":
        reasons.append("quota_bucket_membership_ambiguous")
    elif profile.quota_membership != "verified" or not profile.quota_buckets:
        reasons.append("quota_bucket_membership_unknown")
    else:
        for capability in sorted(requirements.required_capabilities):
            covered = tuple(
                bucket for bucket in profile.quota_buckets
                if capability in bucket.operations
            )
            if not covered:
                reasons.append(f"quota_bucket_operation_missing:{capability}")
                continue
            if any(bucket.source == "unknown" for bucket in covered):
                reasons.append(f"quota_bucket_source_unknown:{capability}")
            if any(
                bucket.remaining == 0
                and bucket.fresh_until is not None
                and bucket.fresh_until >= now
                for bucket in covered
            ):
                reasons.append(f"quota_bucket_exhausted:{capability}")

    schema_id = requirements.structured_schema_id
    if schema_id is not None and schema_id not in profile.structured_schema_ids:
        reasons.append("structured_schema_not_covered")

    count = requirements.count
    if count is not None:
        mapping = profile.counter
        if mapping is None:
            reasons.append("authoritative_counter_mapping_missing")
        else:
            identity_matches = (
                mapping.provider_id == profile.provider_id
                and mapping.model_id == profile.model_id
                and mapping.serializer_id == profile.serializer_id
            )
            if not identity_matches:
                reasons.append("counter_endpoint_identity_mismatch")
            if not mapping.approved or mapping.provenance_reference is None:
                reasons.append("counter_mapping_not_approved")
            if not confidence_meets(mapping.confidence, count.minimum_confidence):
                reasons.append("counter_confidence_insufficient")
            required_schema = count.structured_schema_id or schema_id
            if required_schema is not None and required_schema not in mapping.structured_schema_ids:
                reasons.append("counter_structured_schema_not_covered")

    return CandidateAssessment(
        profile=profile,
        eligible=not reasons,
        rejection_reasons=tuple(reasons),
    )


def _validate_shared_quota_authorities(profiles: Sequence[EndpointProfile]) -> None:
    """Prevent accidental aggregation across independent account or cost scopes."""
    seen: dict[str, tuple[EndpointProfile, QuotaBucket]] = {}
    for profile in profiles:
        for bucket in profile.quota_buckets:
            prior = seen.get(bucket.bucket_id)
            if prior is None:
                seen[bucket.bucket_id] = (profile, bucket)
                continue
            prior_profile, prior_bucket = prior
            same_authority = (
                prior_bucket.authority_scope_id == bucket.authority_scope_id
                and prior_bucket.unit == bucket.unit
                and prior_bucket.window_seconds == bucket.window_seconds
                and prior_bucket.reset_at == bucket.reset_at
                and prior_bucket.source == bucket.source
                and prior_bucket.confidence == bucket.confidence
                and prior_bucket.observed_at == bucket.observed_at
                and prior_bucket.fresh_until == bucket.fresh_until
                and prior_bucket.limit == bucket.limit
                and prior_bucket.remaining == bucket.remaining
                and prior_profile.account_scope_id is not None
                and prior_profile.account_scope_id == profile.account_scope_id
                and prior_profile.execution_mode == profile.execution_mode
                and prior_profile.cost_class == profile.cost_class
                and prior_profile.billing_owner == profile.billing_owner
            )
            if not same_authority:
                raise RegistryConflictError("shared_quota_bucket_scope_conflict")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("routing_timestamp_must_be_aware")
    return value.astimezone(UTC)
