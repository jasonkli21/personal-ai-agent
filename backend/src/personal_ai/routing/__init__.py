"""Endpoint admission and compact deterministic routing."""

from personal_ai.routing.configured import build_initial_endpoint_profiles
from personal_ai.routing.contracts import (
    CandidateAssessment,
    CounterCompatibility,
    CountRequirement,
    DataUsePolicy,
    EndpointCandidateRequirements,
    EndpointCandidateSet,
    EndpointProfile,
    EndpointRef,
    EndpointRegistrySnapshot,
    QuotaBucket,
    StrictFreeEligibilityAttestation,
    compute_registry_version,
)
from personal_ai.routing.phase21 import (
    AuthorizationEvidence,
    CandidateFact,
    DispatchPermit,
    EndpointPriority,
    PreparationIdentity,
    QualityEvidence,
    QualityPolicy,
    QuotaBucketDecisionFact,
    RankedCandidate,
    RoutingDecision,
    RoutingEvent,
    RoutingPreferences,
    RoutingRecord,
    RoutingRequestFacts,
    RoutingSignals,
    RoutingTaskProfile,
    StrategyCandidate,
    StrategyRef,
    StrategyView,
    source_reference_manifest_sha256,
)
from personal_ai.routing.registry import (
    CandidateSetOverflowError,
    EndpointNotAdmissibleError,
    EndpointRegistry,
    EndpointRegistryError,
    RegistryConflictError,
    RegistryPayloadTooLargeError,
    RegistryRevisionChangedError,
)
from personal_ai.routing.strategy import (
    DeterministicScoringStrategy,
    QuotaAwareDeterministicStrategy,
    RoutingReplayUnavailable,
    RoutingStrategy,
    replay_deterministic_decision,
)


def __getattr__(name):
    if name in {"RoutingDecisionService", "RoutingFinalizationError"}:
        from personal_ai.routing import service

        return getattr(service, name)
    raise AttributeError(name)


__all__ = [
    "AuthorizationEvidence",
    "CandidateAssessment",
    "CandidateFact",
    "CandidateSetOverflowError",
    "CountRequirement",
    "CounterCompatibility",
    "DataUsePolicy",
    "DeterministicScoringStrategy",
    "DispatchPermit",
    "EndpointCandidateRequirements",
    "EndpointCandidateSet",
    "EndpointNotAdmissibleError",
    "EndpointPriority",
    "EndpointProfile",
    "EndpointRef",
    "EndpointRegistry",
    "EndpointRegistryError",
    "EndpointRegistrySnapshot",
    "PreparationIdentity",
    "QualityEvidence",
    "QualityPolicy",
    "QuotaAwareDeterministicStrategy",
    "QuotaBucket",
    "QuotaBucketDecisionFact",
    "RankedCandidate",
    "RegistryConflictError",
    "RegistryPayloadTooLargeError",
    "RegistryRevisionChangedError",
    "RoutingDecision",
    "RoutingDecisionService",
    "RoutingEvent",
    "RoutingFinalizationError",
    "RoutingPreferences",
    "RoutingRecord",
    "RoutingReplayUnavailable",
    "RoutingRequestFacts",
    "RoutingSignals",
    "RoutingStrategy",
    "RoutingTaskProfile",
    "StrategyCandidate",
    "StrategyRef",
    "StrategyView",
    "StrictFreeEligibilityAttestation",
    "build_initial_endpoint_profiles",
    "compute_registry_version",
    "replay_deterministic_decision",
    "source_reference_manifest_sha256",
]
