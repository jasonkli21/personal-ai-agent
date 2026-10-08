"""Provider-neutral endpoint registration and deterministic admission."""

from personal_ai.routing.configured import build_initial_endpoint_profiles
from personal_ai.routing.contracts import (
    CounterCompatibility,
    CountRequirement,
    DataUsePolicy,
    EndpointCandidateRequirements,
    EndpointCandidateSet,
    EndpointOperation,
    EndpointProfile,
    EndpointRegistrySnapshot,
    QuotaBucket,
    StrictFreeEligibilityAttestation,
    compute_registry_version,
)
from personal_ai.routing.registry import (
    CandidateRequirementsChangedError,
    CandidateSetOverflowError,
    EndpointNotAdmissibleError,
    EndpointRegistry,
    RegistryConflictError,
    RegistryPayloadTooLargeError,
    RegistryRevisionChangedError,
)

__all__ = [
    "CandidateRequirementsChangedError",
    "CandidateSetOverflowError",
    "CountRequirement",
    "CounterCompatibility",
    "DataUsePolicy",
    "EndpointCandidateRequirements",
    "EndpointCandidateSet",
    "EndpointNotAdmissibleError",
    "EndpointOperation",
    "EndpointProfile",
    "EndpointRegistry",
    "EndpointRegistrySnapshot",
    "QuotaBucket",
    "RegistryConflictError",
    "RegistryPayloadTooLargeError",
    "RegistryRevisionChangedError",
    "StrictFreeEligibilityAttestation",
    "build_initial_endpoint_profiles",
    "compute_registry_version",
]
