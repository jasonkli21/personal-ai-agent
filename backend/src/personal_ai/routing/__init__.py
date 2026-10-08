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
    compute_registry_version,
)
from personal_ai.routing.registry import (
    CandidateSetOverflowError,
    EndpointNotAdmissibleError,
    EndpointRegistry,
    RegistryConflictError,
    RegistryRevisionChangedError,
)

__all__ = [
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
    "RegistryRevisionChangedError",
    "build_initial_endpoint_profiles",
    "compute_registry_version",
]
