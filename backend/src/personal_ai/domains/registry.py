"""Small, explicit registry for the two in-repository Phase 7 domains."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from personal_ai.decisions.contracts import (
    Constraint,
    DecisionCreateRequest,
    FeatureScore,
    Preference,
)
from personal_ai.domains.contracts import DomainRegistration
from personal_ai.entities.research import CanonicalEntity, EntityClaim


class DomainModule(Protocol):
    registration: DomainRegistration
    policy_version: str
    feature_weights: dict[str, float]

    def registration_for(self, enabled: bool) -> DomainRegistration: ...

    def prepare_decision(self, request: DecisionCreateRequest) -> DecisionCreateRequest: ...

    def validate_decision(self, request: DecisionCreateRequest) -> None: ...

    def get_adapter(self, settings, *, rate_limiter=None): ...

    def calculate_features(
        self,
        *,
        entities: tuple[CanonicalEntity, ...],
        claims_by_entity: dict,
        constraints: tuple[Constraint, ...],
        preferences: tuple[Preference, ...],
        evaluations,
        eligible_entity_ids: tuple[UUID, ...],
        now: datetime,
        context: dict,
    ) -> dict[UUID, tuple[FeatureScore, ...]]:
        """Return explainable features for eligible candidates only."""
        ...

    def format_claim(self, attribute: str, claim: EntityClaim) -> str: ...


def registry() -> dict[str, DomainModule]:
    # Lazy imports keep the core domains package independent of either domain.
    from personal_ai.domains.shopping.module import ShoppingModule
    from personal_ai.domains.travel.module import TravelModule

    return {
        "travel": TravelModule(),
        "shopping": ShoppingModule(),
    }


def get_domain(domain_id: str) -> DomainModule:
    try:
        return registry()[domain_id]
    except KeyError as error:
        raise ValueError("domain_not_registered") from error
