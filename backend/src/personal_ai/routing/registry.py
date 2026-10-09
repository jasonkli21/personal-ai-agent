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
    EndpointRef,
    EndpointRegistrySnapshot,
    QuotaBucket,
    compute_registry_version,
    confidence_meets,
    sensitivity_exceeds,
)
from personal_ai.routing.definitions import (
    EndpointProfileDefinition,
    encode_current_endpoint_profile,
)

MAX_ENDPOINT_CANDIDATES = 32
MAX_ENDPOINT_REGISTRY_JSON_BYTES = 128 * 1024


class EndpointRegistryError(RuntimeError):
    """A registry snapshot or lifecycle operation could not be trusted."""


class CandidateSetOverflowError(EndpointRegistryError):
    """The configured endpoint set exceeds the bounded decision contract."""


class RegistryPayloadTooLargeError(EndpointRegistryError):
    """The canonical registry payload exceeds its application-level byte bound."""


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

    def load_profile_version_history(self) -> dict[str, int]: ...

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
        profiles: Sequence[EndpointProfile] | None = None,
        *,
        repository: EndpointRegistryRepository | None = None,
    ) -> None:
        self._lock = RLock()
        self._definitions: dict[tuple[str, int], EndpointProfileDefinition] = {}
        self._repository = repository
        configured = self._validate_profiles(profiles) if profiles is not None else None
        if repository is not None:
            stored = repository.load()
            initialization_raced = False
            if stored is None:
                seed_profiles = configured or ()
                try:
                    stored = repository.save(seed_profiles, expected_registry_version=None)
                except RegistryConflictError:
                    # A concurrent process may have initialized the singleton
                    # row. Reload its winner; a conflicting desired state is
                    # surfaced for an explicit retry rather than overwriting it.
                    initialization_raced = True
                    stored = repository.load()
                    if stored is None:
                        raise
            self._snapshot = self._validated_snapshot(stored)
            self._profile_versions = repository.load_profile_version_history()
            self._validate_active_profile_versions(self._snapshot.profiles)
            self._remember_active_versions(self._snapshot.profiles)
            if configured is not None:
                if initialization_raced:
                    if not _configuration_matches_snapshot(configured, self._snapshot.profiles):
                        raise RegistryConflictError("endpoint_registry_initialization_conflict")
                else:
                    self._reconcile_locked(configured)
        else:
            initial = configured or ()
            self._snapshot = self._make_snapshot(initial, revision=0)
            self._profile_versions: dict[str, int] = {}
            self._remember_active_versions(self._snapshot.profiles)

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

    def refresh(self) -> EndpointRegistrySnapshot:
        """Reload the durable snapshot before attributing a provider dispatch."""
        with self._lock:
            self._refresh_from_repository_locked()
            return self._snapshot

    def candidates(
        self,
        requirements: EndpointCandidateRequirements,
        *,
        now: datetime | None = None,
        connection=None,
    ) -> EndpointCandidateSet:
        """Return every profile fact and hard-admission rejection, without scores.

        When called from routing admission, read and lock the profile snapshot
        through the caller's transaction so endpoint and P19 ledger facts share
        one admission boundary.
        """
        instant = _aware_utc(now or datetime.now(UTC))
        with self._lock:
            if connection is not None and self._repository is not None:
                snapshot = self._repository.load_from_connection(connection, lock=True)
                if snapshot is None:
                    raise EndpointRegistryError("endpoint_registry_snapshot_missing")
                snapshot = self._validated_snapshot(snapshot)
            else:
                self._refresh_from_repository_locked()
                snapshot = self._snapshot
            assessments = tuple(
                _assess(profile, requirements, instant) for profile in snapshot.profiles
            )
            return EndpointCandidateSet(
                registry_version=snapshot.registry_version,
                execution_mode=requirements.execution_mode,
                requirements=requirements,
                assessments=assessments,
            )

    def historical(self, ref: EndpointRef) -> EndpointProfileDefinition:
        """Return the exact retained schema-versioned audit definition."""
        if self._repository is not None:
            return self._repository.load_definition(ref)
        try:
            return self._definitions[(ref.endpoint_profile_id, ref.profile_version)]
        except KeyError as error:
            raise EndpointRegistryError("historical_endpoint_profile_unavailable") from error

    def revalidate_selected(self, ref: EndpointRef, requirements, *, now=None, connection=None):
        if connection is not None and self._repository is not None:
            snapshot = self._repository.load_from_connection(connection, lock=True)
            if snapshot is None:
                raise EndpointRegistryError("endpoint_registry_snapshot_missing")
        else:
            snapshot = self.refresh()
        current = next((p for p in snapshot.profiles if p.ref == ref), None)
        if current is None:
            raise RegistryRevisionChangedError("endpoint_profile_version_changed")
        assessment = _assess(current, requirements, _aware_utc(now or datetime.now(UTC)))
        if not assessment.eligible:
            raise EndpointNotAdmissibleError(assessment.rejection_reasons)
        return current

    def upsert(self, profile: EndpointProfile) -> EndpointRegistrySnapshot:
        """Add a profile or replace it at a strictly higher profile version."""
        (profile,) = self._validate_profiles((profile,))
        with self._lock:
            self._refresh_from_repository_locked(include_profile_history=True)
            current = {item.endpoint_profile_id: item for item in self._snapshot.profiles}
            previous = current.get(profile.endpoint_profile_id)
            if previous == profile:
                return self._snapshot
            if previous is not None and profile.profile_version <= previous.profile_version:
                raise RegistryConflictError("endpoint_profile_version_must_increase")
            if previous is None and profile.profile_version <= self._profile_versions.get(
                profile.endpoint_profile_id, 0
            ):
                raise RegistryConflictError("endpoint_profile_version_must_increase_after_removal")
            current[profile.endpoint_profile_id] = profile
            return self._publish(tuple(current.values()))

    def remove(self, endpoint_profile_id: str) -> EndpointRegistrySnapshot:
        """Remove a profile and advance the registry revision when it existed."""
        with self._lock:
            self._refresh_from_repository_locked()
            current = tuple(
                item
                for item in self._snapshot.profiles
                if item.endpoint_profile_id != endpoint_profile_id
            )
            if len(current) == len(self._snapshot.profiles):
                return self._snapshot
            return self._publish(current)

    def reconcile(self, configured_profiles: Sequence[EndpointProfile]) -> EndpointRegistrySnapshot:
        """Apply operator configuration as the desired endpoint profile set.

        Identical facts are a no-op. Changed facts advance the profile version
        automatically, and profiles omitted from the desired set are removed.
        A concurrent durable change fails with RegistryConflictError so the
        caller can reload and retry reconciliation against current state.
        """
        configured = self._validate_profiles(configured_profiles)
        with self._lock:
            self._refresh_from_repository_locked(include_profile_history=True)
            return self._reconcile_locked(configured)

    def _reconcile_locked(
        self, configured: tuple[EndpointProfile, ...]
    ) -> EndpointRegistrySnapshot:
        current = {profile.endpoint_profile_id: profile for profile in self._snapshot.profiles}
        desired: list[EndpointProfile] = []
        for profile in configured:
            previous = current.get(profile.endpoint_profile_id)
            if previous is not None and _same_profile_facts(previous, profile):
                desired.append(previous)
                continue
            last_version = self._profile_versions.get(profile.endpoint_profile_id, 0)
            minimum_version = (
                previous.profile_version + 1 if previous is not None else last_version + 1
            )
            next_version = max(profile.profile_version, minimum_version)
            desired.append(_with_profile_version(profile, next_version))

        desired_tuple = tuple(desired)
        if {item.endpoint_profile_id: item for item in desired_tuple} == current:
            # Preserve persisted ordering when the facts are unchanged.
            return self._snapshot
        return self._publish(desired_tuple)

    def _publish(self, profiles: tuple[EndpointProfile, ...]) -> EndpointRegistrySnapshot:
        profiles = self._validate_profiles(profiles)
        self._make_snapshot(profiles, revision=self._snapshot.revision + 1)
        expected = self._snapshot.registry_version
        if self._repository is not None:
            candidate = self._repository.save(profiles, expected_registry_version=expected)
        else:
            candidate = self._make_snapshot(profiles, revision=self._snapshot.revision + 1)
        candidate = self._validated_snapshot(candidate)
        self._snapshot = candidate
        self._remember_active_versions(candidate.profiles)
        return candidate

    def _refresh_from_repository_locked(self, *, include_profile_history: bool = False) -> None:
        if self._repository is None:
            return
        stored = self._repository.load()
        if stored is None:
            raise EndpointRegistryError("endpoint_registry_snapshot_missing")
        current = self._validated_snapshot(stored)
        self._snapshot = current
        if include_profile_history:
            self._profile_versions = self._repository.load_profile_version_history()
            self._validate_active_profile_versions(current.profiles)
        else:
            self._validate_no_profile_version_regression(current.profiles)
        self._remember_active_versions(current.profiles)

    def _validate_active_profile_versions(self, profiles: Sequence[EndpointProfile]) -> None:
        for profile in profiles:
            last_version = self._profile_versions.get(profile.endpoint_profile_id)
            if last_version is not None and last_version != profile.profile_version:
                raise EndpointRegistryError("endpoint_profile_version_history_mismatch")

    def _validate_no_profile_version_regression(self, profiles: Sequence[EndpointProfile]) -> None:
        for profile in profiles:
            last_version = self._profile_versions.get(profile.endpoint_profile_id, 0)
            if profile.profile_version < last_version:
                raise EndpointRegistryError("endpoint_profile_version_history_mismatch")

    def _remember_active_versions(self, profiles: Sequence[EndpointProfile]) -> None:
        for profile in profiles:
            self._definitions[(profile.endpoint_profile_id, profile.profile_version)] = (
                encode_current_endpoint_profile(profile)
            )
            self._profile_versions[profile.endpoint_profile_id] = max(
                profile.profile_version,
                self._profile_versions.get(profile.endpoint_profile_id, 0),
            )

    @staticmethod
    def _make_snapshot(
        profiles: Sequence[EndpointProfile], *, revision: int
    ) -> EndpointRegistrySnapshot:
        profile_tuple = EndpointRegistry._validate_profiles(profiles)
        snapshot = EndpointRegistrySnapshot(
            revision=revision,
            registry_version=compute_registry_version(profile_tuple, revision=revision),
            profiles=profile_tuple,
        )
        payload_bytes = len(snapshot.model_dump_json().encode("utf-8"))
        if payload_bytes > MAX_ENDPOINT_REGISTRY_JSON_BYTES:
            raise RegistryPayloadTooLargeError("endpoint_registry_payload_too_large")
        return snapshot

    @staticmethod
    def _validate_profiles(
        profiles: Sequence[EndpointProfile] | None,
    ) -> tuple[EndpointProfile, ...]:
        canonical = tuple(
            EndpointProfile.model_validate(
                profile.model_dump(mode="python")
                if isinstance(profile, EndpointProfile)
                else profile
            )
            for profile in (profiles or ())
        )
        if len(canonical) > MAX_ENDPOINT_CANDIDATES:
            raise CandidateSetOverflowError("endpoint_candidate_limit_exceeded")
        ids = [item.endpoint_profile_id for item in canonical]
        if len(set(ids)) != len(ids):
            raise RegistryConflictError("endpoint_profile_id_duplicate")
        _validate_shared_quota_authorities(canonical)
        return canonical

    @staticmethod
    def _validated_snapshot(
        snapshot: EndpointRegistrySnapshot,
    ) -> EndpointRegistrySnapshot:
        if not isinstance(snapshot, EndpointRegistrySnapshot):
            snapshot = EndpointRegistrySnapshot.model_validate(snapshot)
        profiles = EndpointRegistry._validate_profiles(snapshot.profiles)
        canonical = EndpointRegistrySnapshot(
            schema_version=snapshot.schema_version,
            revision=snapshot.revision,
            registry_version=compute_registry_version(profiles, revision=snapshot.revision),
            profiles=profiles,
        )
        if canonical.registry_version != snapshot.registry_version:
            raise EndpointRegistryError("endpoint_registry_snapshot_invalid")
        EndpointRegistry._make_snapshot(profiles, revision=snapshot.revision)
        return canonical


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
    attestation = profile.strict_free_attestation
    if (
        attestation is not None
        and attestation.valid_until is not None
        and attestation.valid_until <= now
    ):
        reasons.append("strict_free_attestation_expired")
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
        & {
            "streaming",
            "bounded_generation",
            "structured_generation",
            "token_counting",
            "embeddings",
        }
    )
    needs_output_limit = bool(
        requirements.required_capabilities
        & {"streaming", "bounded_generation", "structured_generation"}
    )
    if needs_input_limit and profile.context_limit_tokens is None:
        reasons.append("endpoint_context_limit_unknown")
    elif needs_input_limit and requirements.input_tokens is None:
        reasons.append("prepared_input_bound_missing")
    elif (
        needs_input_limit
        and profile.context_limit_tokens is not None
        and requirements.input_tokens is not None
        and requirements.input_tokens > profile.context_limit_tokens
    ):
        reasons.append("input_exceeds_endpoint_context_limit")
    if needs_output_limit and profile.max_output_tokens is None:
        reasons.append("endpoint_output_limit_unknown")
    elif needs_output_limit and requirements.output_tokens is None:
        reasons.append("requested_output_bound_missing")
    elif (
        needs_output_limit
        and profile.max_output_tokens is not None
        and requirements.output_tokens is not None
        and requirements.output_tokens > profile.max_output_tokens
    ):
        reasons.append("output_exceeds_endpoint_limit")
    if "search" in requirements.required_capabilities:
        if profile.max_search_query_chars is None:
            reasons.append("search_query_limit_unknown")
        elif requirements.search_query_chars is None:
            reasons.append("search_query_bound_missing")
        elif requirements.search_query_chars > profile.max_search_query_chars:
            reasons.append("search_query_exceeds_endpoint_limit")
        if profile.max_search_results is None:
            reasons.append("search_result_limit_unknown")
        elif requirements.search_results is None:
            reasons.append("search_results_bound_missing")
        elif requirements.search_results > profile.max_search_results:
            reasons.append("search_results_exceed_endpoint_limit")
    if "embeddings" in requirements.required_capabilities:
        if requirements.embedding_dimensions is None:
            reasons.append("embedding_dimensions_missing")
        elif requirements.embedding_dimensions != profile.embedding_dimensions:
            reasons.append("embedding_space_dimensions_mismatch")

    if profile.quota_membership == "ambiguous":
        reasons.append("quota_bucket_membership_ambiguous")
    elif profile.quota_membership != "verified" or not profile.quota_buckets:
        reasons.append("quota_bucket_membership_unknown")
    else:
        for capability in sorted(requirements.required_capabilities):
            covered = tuple(
                bucket for bucket in profile.quota_buckets if capability in bucket.operations
            )
            if not covered:
                reasons.append(f"quota_bucket_operation_missing:{capability}")
                continue
            if any(bucket.source == "unknown" for bucket in covered):
                reasons.append(f"quota_bucket_source_unknown:{capability}")

    schema_id = requirements.structured_schema_id
    if schema_id is not None and schema_id not in profile.structured_schema_ids:
        reasons.append("structured_schema_not_covered")

    count = requirements.count
    if "token_counting" in requirements.required_capabilities and count is None:
        reasons.append("token_count_requirement_missing")
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


def _same_profile_facts(left: EndpointProfile, right: EndpointProfile) -> bool:
    left_document = left.model_dump(mode="python")
    right_document = right.model_dump(mode="python")
    left_document.pop("profile_version")
    right_document.pop("profile_version")
    return left_document == right_document


def _configuration_matches_snapshot(
    configured: Sequence[EndpointProfile], current: Sequence[EndpointProfile]
) -> bool:
    configured_by_id = {profile.endpoint_profile_id: profile for profile in configured}
    current_by_id = {profile.endpoint_profile_id: profile for profile in current}
    return configured_by_id.keys() == current_by_id.keys() and all(
        _same_profile_facts(configured_by_id[profile_id], current_by_id[profile_id])
        for profile_id in configured_by_id
    )


def _with_profile_version(profile: EndpointProfile, version: int) -> EndpointProfile:
    document = profile.model_dump(mode="python")
    document["profile_version"] = version
    return EndpointProfile.model_validate(document)


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
                and prior_bucket.source == bucket.source
                and prior_bucket.confidence == bucket.confidence
                and prior_bucket.limit == bucket.limit
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
