"""Versioned, secret-free endpoint facts and strict-free candidate contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sensitivity = Literal["public", "personal", "sensitive", "restricted"]
ExecutionMode = Literal["STRICT_FREE", "EXPLICIT_BYOK", "CHATGPT_PLAN"]
CostClass = Literal["VERIFIED_FREE", "USER_BILLED", "SUBSCRIPTION", "UNKNOWN"]
CounterConfidence = Literal["authoritative", "reported", "estimated", "unknown"]
EndpointOperation = Literal[
    "streaming",
    "bounded_generation",
    "structured_generation",
    "token_counting",
    "embeddings",
    "search",
    "lookup",
]

_SAFE_FACT_ID = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._:/@+-]{0,199}$")
_SAFE_CREDENTIAL_REF = re.compile(
    r"^(?:env|secret_manager|workload_identity|user_runtime|none):[A-Za-z0-9._:/-]{0,200}$"
)
_SAFE_ENV_NAME = re.compile(r"^(?=[A-Z0-9_]*_)[A-Z][A-Z0-9_]{1,127}$")
_SAFE_PROVENANCE_REF = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._:/@+-]{0,499}$")
_SENSITIVITY_RANK = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3}
_CONFIDENCE_RANK = {"unknown": 0, "estimated": 1, "reported": 2, "authoritative": 3}


def _valid_fact_id(value: str) -> str:
    if not value or not _SAFE_FACT_ID.fullmatch(value):
        raise ValueError("endpoint_fact_id_invalid")
    return value


def _require_aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("endpoint_timestamp_invalid")
    return value.astimezone(UTC) if value is not None else None


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class DataUsePolicy(_FrozenContract):
    """Endpoint-specific provider data-use approval and sensitivity ceiling."""

    status: Literal["approved", "denied", "unknown"] = "unknown"
    max_sensitivity: Sensitivity = "public"
    policy_reference: str | None = Field(default=None, max_length=500)

    @field_validator("policy_reference")
    @classmethod
    def valid_policy_reference(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("endpoint_policy_reference_invalid")
        return value

    @model_validator(mode="after")
    def approved_policy_has_provenance(self) -> DataUsePolicy:
        if self.status == "approved" and self.policy_reference is None:
            raise ValueError("approved_data_policy_requires_reference")
        return self


class StrictFreeEligibilityAttestation(_FrozenContract):
    """Evidence scoped to the exact endpoint/account facts admitted as free."""

    endpoint_profile_id: str
    provider_id: str
    model_id: str
    endpoint_id: str
    deployment_id: str
    account_scope_id: str
    credential_scope_id: str
    tier_id: str
    reference: str = Field(min_length=1, max_length=500)
    source: Literal[
        "provider_contract", "provider_console", "operator_preflight", "synthetic_test"
    ]
    zero_cost_verified: bool = False
    paid_overflow_excluded: bool = False
    verified_at: datetime | None = None
    valid_until: datetime | None = None

    @field_validator(
        "endpoint_profile_id", "provider_id", "model_id", "endpoint_id", "deployment_id",
        "account_scope_id", "credential_scope_id", "tier_id",
    )
    @classmethod
    def valid_attested_identity(cls, value: str) -> str:
        return _valid_fact_id(value)

    @field_validator("reference")
    @classmethod
    def valid_attestation_reference(cls, value: str) -> str:
        if value != value.strip() or not _SAFE_PROVENANCE_REF.fullmatch(value):
            raise ValueError("strict_free_attestation_reference_invalid")
        return value

    @field_validator("verified_at", "valid_until")
    @classmethod
    def attestation_timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value)

    @model_validator(mode="after")
    def validate_attestation_interval(self) -> StrictFreeEligibilityAttestation:
        if not self.zero_cost_verified or not self.paid_overflow_excluded:
            raise ValueError("strict_free_attestation_incomplete")
        if self.valid_until is not None and self.verified_at is None:
            raise ValueError("strict_free_attestation_freshness_requires_observation")
        if (
            self.verified_at is not None
            and self.valid_until is not None
            and self.valid_until < self.verified_at
        ):
            raise ValueError("strict_free_attestation_interval_invalid")
        return self


class QuotaBucket(_FrozenContract):
    """A typed reference to provider-authoritative capacity shared by endpoints."""

    bucket_id: str = Field(min_length=1, max_length=200)
    authority_scope_id: str = Field(min_length=1, max_length=200)
    operations: frozenset[EndpointOperation] = Field(min_length=1, max_length=7)
    unit: str = Field(min_length=1, max_length=80)
    window_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    reset_at: datetime | None = None
    source: Literal["provider_contract", "provider_headers", "operator_attestation", "unknown"]
    confidence: Literal["verified", "reported", "unknown"]
    reservation_units_per_request: int | None = Field(default=None, ge=0)
    observed_at: datetime | None = None
    fresh_until: datetime | None = None
    evidence_reference: str | None = Field(default=None, max_length=500)
    limit: int | None = Field(default=None, ge=0)
    remaining: int | None = Field(default=None, ge=0)

    @field_validator("bucket_id", "authority_scope_id", "unit")
    @classmethod
    def valid_bucket_identity(cls, value: str) -> str:
        return _valid_fact_id(value)

    @field_validator("reset_at", "observed_at", "fresh_until")
    @classmethod
    def timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value)

    @field_validator("evidence_reference")
    @classmethod
    def valid_evidence_reference(cls, value: str | None) -> str | None:
        if value is not None and (
            value != value.strip() or not _SAFE_PROVENANCE_REF.fullmatch(value)
        ):
            raise ValueError("quota_evidence_reference_invalid")
        return value

    @model_validator(mode="after")
    def validate_snapshot(self) -> QuotaBucket:
        if self.confidence == "verified" and self.evidence_reference is None:
            raise ValueError("verified_quota_requires_evidence")
        if self.fresh_until is not None and self.observed_at is None:
            raise ValueError("quota_freshness_requires_observation")
        if (
            self.observed_at is not None
            and self.fresh_until is not None
            and self.fresh_until < self.observed_at
        ):
            raise ValueError("quota_freshness_interval_invalid")
        if self.remaining is not None and self.limit is not None and self.remaining > self.limit:
            raise ValueError("quota_remaining_exceeds_limit")
        return self


class CounterCompatibility(_FrozenContract):
    """Approved exact endpoint/serializer/count mapping and covered schemas."""

    endpoint_profile_id: str
    endpoint_id: str
    deployment_id: str
    credential_scope_id: str | None = Field(default=None, max_length=200)
    account_scope_id: str | None = Field(default=None, max_length=200)
    provider_id: str
    model_id: str
    serializer_id: str
    counter_id: str
    confidence: CounterConfidence = "unknown"
    approved: bool = False
    provenance_reference: str | None = Field(default=None, max_length=500)
    structured_schema_ids: tuple[str, ...] = Field(default=(), max_length=128)

    @field_validator(
        "endpoint_profile_id", "endpoint_id", "deployment_id", "provider_id", "model_id",
        "serializer_id", "counter_id",
    )
    @classmethod
    def valid_counter_identity(cls, value: str) -> str:
        return _valid_fact_id(value)

    @field_validator("provenance_reference")
    @classmethod
    def valid_provenance(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("counter_provenance_invalid")
        return value

    @field_validator("structured_schema_ids")
    @classmethod
    def unique_schema_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(not _SAFE_FACT_ID.fullmatch(v) for v in values):
            raise ValueError("counter_schema_coverage_invalid")
        return values

    @model_validator(mode="after")
    def validate_approval(self) -> CounterCompatibility:
        if self.approved and (self.confidence == "unknown" or not self.provenance_reference):
            raise ValueError("approved_counter_requires_evidence")
        if self.credential_scope_id is not None:
            _valid_fact_id(self.credential_scope_id)
        if self.account_scope_id is not None:
            _valid_fact_id(self.account_scope_id)
        if self.approved and (self.credential_scope_id is None or self.account_scope_id is None):
            raise ValueError("approved_counter_requires_endpoint_scope")
        return self


class EndpointProfile(_FrozenContract):
    """A callable provider/model/account/credential/cost combination."""

    endpoint_profile_id: str = Field(min_length=1, max_length=200)
    profile_version: int = Field(ge=1, le=2_147_483_647)
    provider_id: str
    model_id: str
    endpoint_id: str
    deployment_id: str
    credential_source: Literal[
        "environment", "secret_manager", "workload_identity", "user_runtime", "none"
    ]
    credential_reference: str
    credential_scope_id: str | None = Field(default=None, max_length=200)
    account_scope_id: str | None = Field(default=None, max_length=200)
    project_scope_id: str | None = Field(default=None, max_length=200)
    tier_id: str
    tier_verified: bool = False
    execution_mode: ExecutionMode
    cost_class: CostClass
    billing_owner: Literal["provider_account", "user", "subscription", "unknown"] = "unknown"
    enabled: bool = False
    strict_free_enabled: bool = False
    capabilities: frozenset[EndpointOperation] = Field(default_factory=frozenset, max_length=6)
    context_limit_tokens: int | None = Field(default=None, ge=1, le=2_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    embedding_dimensions: int | None = Field(default=None, ge=1, le=65_536)
    max_search_query_chars: int | None = Field(default=None, ge=1, le=1_000_000)
    max_search_results: int | None = Field(default=None, ge=1, le=10_000)
    data_use_policy: DataUsePolicy = Field(default_factory=DataUsePolicy)
    strict_free_attestation: StrictFreeEligibilityAttestation | None = None
    serializer_id: str
    runtime_id: str
    structured_schema_ids: tuple[str, ...] = Field(default=(), max_length=128)
    counter: CounterCompatibility | None = None
    quota_membership: Literal["verified", "unknown", "ambiguous"] = "unknown"
    quota_buckets: tuple[QuotaBucket, ...] = Field(default=(), max_length=32)

    @field_validator(
        "endpoint_profile_id", "provider_id", "model_id", "endpoint_id", "deployment_id",
        "tier_id", "serializer_id", "runtime_id",
    )
    @classmethod
    def valid_profile_identity(cls, value: str) -> str:
        return _valid_fact_id(value)

    @field_validator("credential_scope_id", "account_scope_id", "project_scope_id")
    @classmethod
    def valid_optional_scopes(cls, value: str | None) -> str | None:
        return _valid_fact_id(value) if value is not None else None

    @field_validator("credential_reference")
    @classmethod
    def valid_symbolic_credential_reference(cls, value: str) -> str:
        if not _SAFE_CREDENTIAL_REF.fullmatch(value):
            raise ValueError("credential_reference_must_be_symbolic")
        source, reference = value.split(":", 1)
        if source == "env" and not _SAFE_ENV_NAME.fullmatch(reference):
            raise ValueError("credential_reference_must_be_symbolic")
        return value

    @field_validator("structured_schema_ids")
    @classmethod
    def valid_profile_schema_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(not _SAFE_FACT_ID.fullmatch(v) for v in values):
            raise ValueError("structured_schema_coverage_invalid")
        return values

    @model_validator(mode="after")
    def validate_profile_contract(self) -> EndpointProfile:
        bucket_ids = [bucket.bucket_id for bucket in self.quota_buckets]
        if len(set(bucket_ids)) != len(bucket_ids):
            raise ValueError("endpoint_quota_bucket_duplicate")
        if self.quota_membership == "verified" and not self.quota_buckets:
            raise ValueError("verified_quota_membership_requires_bucket")
        if self.quota_membership == "verified" and any(
            bucket.evidence_reference is None for bucket in self.quota_buckets
        ):
            raise ValueError("verified_quota_membership_requires_evidence")
        attestation_required = (
            self.tier_verified
            or self.strict_free_enabled
            or self.cost_class == "VERIFIED_FREE"
        )
        if attestation_required and self.strict_free_attestation is None:
            raise ValueError("strict_free_claim_requires_attestation")
        attestation = self.strict_free_attestation
        if attestation is not None and (
            attestation.endpoint_profile_id != self.endpoint_profile_id
            or attestation.provider_id != self.provider_id
            or attestation.model_id != self.model_id
            or attestation.endpoint_id != self.endpoint_id
            or attestation.deployment_id != self.deployment_id
            or attestation.account_scope_id != self.account_scope_id
            or attestation.credential_scope_id != self.credential_scope_id
            or attestation.tier_id != self.tier_id
        ):
            raise ValueError("strict_free_attestation_scope_mismatch")
        if self.counter is not None and (
            self.counter.endpoint_profile_id != self.endpoint_profile_id
            or self.counter.endpoint_id != self.endpoint_id
            or self.counter.deployment_id != self.deployment_id
            or self.counter.credential_scope_id != self.credential_scope_id
            or self.counter.account_scope_id != self.account_scope_id
            or self.counter.provider_id != self.provider_id
            or self.counter.model_id != self.model_id
            or self.counter.serializer_id != self.serializer_id
        ):
            raise ValueError("counter_endpoint_identity_mismatch")
        if self.counter is not None and "token_counting" not in self.capabilities:
            raise ValueError("counter_mapping_without_count_capability")
        if ("embeddings" in self.capabilities) != (self.embedding_dimensions is not None):
            raise ValueError("embedding_dimensions_capability_mismatch")
        expected_prefix = {
            "environment": "env",
            "secret_manager": "secret_manager",
            "workload_identity": "workload_identity",
            "user_runtime": "user_runtime",
            "none": "none",
        }[self.credential_source]
        if (
            self.credential_reference.split(":", 1)[0] != expected_prefix
            or (self.credential_source == "none" and self.credential_reference != "none:")
        ):
            raise ValueError("credential_reference_source_mismatch")
        return self


class CountRequirement(_FrozenContract):
    """Hard requirement for the pre-dispatch count confidence and schema."""

    minimum_confidence: CounterConfidence = "authoritative"
    structured_schema_id: str | None = Field(default=None, max_length=200)

    @field_validator("structured_schema_id")
    @classmethod
    def valid_required_schema(cls, value: str | None) -> str | None:
        return _valid_fact_id(value) if value is not None else None


class EndpointCandidateRequirements(_FrozenContract):
    """Non-disclosing request facts that the hard admission guard evaluates."""

    execution_mode: ExecutionMode = "STRICT_FREE"
    sensitivity: Sensitivity = "public"
    required_capabilities: frozenset[EndpointOperation] = Field(
        default_factory=lambda: frozenset({"bounded_generation"}), max_length=6
    )
    input_tokens: int | None = Field(default=None, ge=0, le=2_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    embedding_dimensions: int | None = Field(default=None, ge=1, le=65_536)
    search_query_chars: int | None = Field(default=None, ge=0, le=1_000_000)
    search_results: int | None = Field(default=None, ge=0, le=10_000)
    count: CountRequirement | None = None
    structured_schema_id: str | None = Field(default=None, max_length=200)
    automatic: bool = True

    @field_validator("structured_schema_id")
    @classmethod
    def valid_requested_schema(cls, value: str | None) -> str | None:
        return _valid_fact_id(value) if value is not None else None

    @model_validator(mode="after")
    def validate_request_shape(self) -> EndpointCandidateRequirements:
        if not self.required_capabilities:
            raise ValueError("required_capabilities_empty")
        if self.structured_schema_id is not None and "structured_generation" not in self.required_capabilities:
            raise ValueError("structured_schema_requires_structured_generation")
        if self.embedding_dimensions is not None and "embeddings" not in self.required_capabilities:
            raise ValueError("embedding_dimensions_requires_embedding_capability")
        if (self.search_query_chars or self.search_results) and "search" not in self.required_capabilities:
            raise ValueError("search_bounds_require_search_capability")
        if self.count is not None and "token_counting" not in self.required_capabilities:
            raise ValueError("count_requirement_requires_count_capability")
        generation_capabilities = {
            "streaming", "bounded_generation", "structured_generation"
        }
        input_bounded_capabilities = generation_capabilities | {
            "token_counting", "embeddings"
        }
        if self.required_capabilities & input_bounded_capabilities and self.input_tokens is None:
            raise ValueError("prepared_input_bound_required")
        if self.required_capabilities & generation_capabilities and self.output_tokens is None:
            raise ValueError("requested_output_bound_required")
        if "token_counting" in self.required_capabilities and self.count is None:
            raise ValueError("token_count_requirement_required")
        if "embeddings" in self.required_capabilities and self.embedding_dimensions is None:
            raise ValueError("embedding_dimensions_required")
        if "search" in self.required_capabilities and (
            self.search_query_chars is None or self.search_results is None
        ):
            raise ValueError("search_bounds_required")
        if (
            self.count is not None
            and self.count.structured_schema_id is not None
            and self.structured_schema_id is not None
            and self.count.structured_schema_id != self.structured_schema_id
        ):
            raise ValueError("count_schema_requirement_mismatch")
        return self


class CandidateAssessment(_FrozenContract):
    """Complete admission result for one registered endpoint profile."""

    profile: EndpointProfile
    eligible: bool
    rejection_reasons: tuple[str, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def validate_result(self) -> CandidateAssessment:
        if self.eligible != (not self.rejection_reasons):
            raise ValueError("candidate_assessment_inconsistent")
        return self


class EndpointCandidateSet(_FrozenContract):
    """Frozen, bounded endpoint facts and every eligibility/rejection outcome."""

    schema_version: Literal["endpoint-candidates-v1"] = "endpoint-candidates-v1"
    registry_version: str = Field(min_length=1, max_length=80)
    execution_mode: ExecutionMode
    requirements: EndpointCandidateRequirements
    assessments: tuple[CandidateAssessment, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def candidate_requirements_match_mode(self) -> EndpointCandidateSet:
        if self.execution_mode != self.requirements.execution_mode:
            raise ValueError("candidate_execution_mode_mismatch")
        return self

    @property
    def eligible_profiles(self) -> tuple[EndpointProfile, ...]:
        return tuple(item.profile for item in self.assessments if item.eligible)

    @property
    def rejected_profiles(self) -> tuple[CandidateAssessment, ...]:
        return tuple(item for item in self.assessments if not item.eligible)


class EndpointRegistrySnapshot(_FrozenContract):
    """Versioned Postgres-owned catalog snapshot used to invalidate decisions."""

    schema_version: Literal["endpoint-registry-v1"] = "endpoint-registry-v1"
    revision: int = Field(ge=0)
    registry_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    profiles: tuple[EndpointProfile, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def validate_registry_snapshot(self) -> EndpointRegistrySnapshot:
        identifiers = [profile.endpoint_profile_id for profile in self.profiles]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("endpoint_profile_id_duplicate")
        if self.registry_version != compute_registry_version(
            self.profiles, revision=self.revision
        ):
            raise ValueError("endpoint_registry_version_mismatch")
        return self


def compute_registry_version(
    profiles: Sequence[EndpointProfile], *, revision: int = 0
) -> str:
    """Hash canonical facts and lifecycle revision, independent of list ordering."""
    documents = []
    for profile in sorted(profiles, key=lambda item: item.endpoint_profile_id):
        document = profile.model_dump(mode="json")
        document["capabilities"] = sorted(profile.capabilities)
        document["structured_schema_ids"] = sorted(profile.structured_schema_ids)
        document["quota_buckets"] = []
        for bucket in sorted(profile.quota_buckets, key=lambda item: item.bucket_id):
            bucket_document = bucket.model_dump(mode="json")
            bucket_document["operations"] = sorted(bucket.operations)
            document["quota_buckets"].append(bucket_document)
        if profile.counter is not None:
            document["counter"]["structured_schema_ids"] = sorted(
                profile.counter.structured_schema_ids
            )
        documents.append(document)
    payload = json.dumps(
        {"revision": revision, "profiles": documents},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def sensitivity_exceeds(actual: Sensitivity, maximum: Sensitivity) -> bool:
    return _SENSITIVITY_RANK[actual] > _SENSITIVITY_RANK[maximum]


def confidence_meets(actual: CounterConfidence, minimum: CounterConfidence) -> bool:
    return _CONFIDENCE_RANK[actual] >= _CONFIDENCE_RANK[minimum]
