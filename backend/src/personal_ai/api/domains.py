"""Thin API routes for registered travel and shopping modules."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from personal_ai.agents.research.repositories import FirestoreResearchRepository
from personal_ai.api.dependencies import get_current_owner_id
from personal_ai.decisions.firestore import FirestoreDecisionRepository
from personal_ai.domains.contracts import (
    DomainComparisonCreateRequest,
    DomainComparisonResult,
    DomainFixtureDescription,
    DomainInspection,
    DomainLookupRequest,
    DomainRegistration,
)
from personal_ai.domains.fixtures import get_fixture, list_fixtures
from personal_ai.domains.repositories import FirestoreDomainRepository
from personal_ai.domains.service import DomainService
from personal_ai.settings import Settings, get_settings
from personal_ai.storage.errors import ResourceNotFoundError

router = APIRouter(prefix="/v1/domains", tags=["domains"])


def domain_settings(settings: Annotated[Settings, Depends(get_settings)]) -> Settings:
    if not settings.decision_enabled or not (settings.travel_enabled or settings.shopping_enabled):
        raise ResourceNotFoundError("domain not found")
    return settings


def domain_service(
    settings: Annotated[Settings, Depends(domain_settings)],
    owner_id: Annotated[str, Depends(get_current_owner_id)],
) -> DomainService:
    decision_repository = FirestoreDecisionRepository(
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )
    domain_repository = FirestoreDomainRepository(
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )
    if settings.research_storage == "memory":
        from personal_ai.api.research import local_repository

        research_repository = local_repository
    else:
        research_repository = lambda: FirestoreResearchRepository(
            project_id=settings.firestore_project_id,
            emulator_host=settings.firestore_emulator_host,
        )
    return DomainService(
        settings,
        decision_repository,
        domain_repository,
        research_repository=research_repository,
        owner_id=owner_id,
    )


@router.get("", response_model=tuple[DomainRegistration, ...])
def list_domains(service: Annotated[DomainService, Depends(domain_service)]):
    return service.registrations()


@router.get("/{domain_id}/fixtures", response_model=tuple[DomainFixtureDescription, ...])
def list_domain_fixtures(
    domain_id: str,
    service: Annotated[DomainService, Depends(domain_service)],
):
    service.require_domain(domain_id)
    return tuple(
        DomainFixtureDescription(
            fixture_id=item.fixture_id,
            domain_id=item.domain_id,
            title=item.title,
            description=item.description,
        )
        for item in list_fixtures(domain_id)
    )


@router.post("/{domain_id}/lookup", response_model=DomainComparisonResult, status_code=status.HTTP_201_CREATED)
async def lookup_domain(
    domain_id: str,
    request: DomainLookupRequest,
    service: Annotated[DomainService, Depends(domain_service)],
):
    return await service.lookup(domain_id, request)


@router.post("/{domain_id}/comparisons", response_model=DomainComparisonResult, status_code=status.HTTP_201_CREATED)
def create_domain_comparison(
    domain_id: str,
    request: DomainComparisonCreateRequest,
    service: Annotated[DomainService, Depends(domain_service)],
):
    return service.create(domain_id, request)


@router.post(
    "/{domain_id}/fixtures/{fixture_id}/compare",
    response_model=DomainComparisonResult,
    status_code=status.HTTP_201_CREATED,
)
def run_domain_fixture(
    domain_id: str,
    fixture_id: str,
    service: Annotated[DomainService, Depends(domain_service)],
):
    service.require_domain(domain_id)
    try:
        fixture = get_fixture(domain_id, fixture_id)
    except KeyError as error:
        raise ResourceNotFoundError("domain fixture not found") from error
    return service.create(domain_id, fixture.request)


@router.get("/{domain_id}/comparisons/{comparison_id}", response_model=DomainComparisonResult)
def get_domain_comparison(
    domain_id: str,
    comparison_id: UUID,
    service: Annotated[DomainService, Depends(domain_service)],
):
    return service.detail(domain_id, comparison_id)


@router.get(
    "/{domain_id}/comparisons/{comparison_id}/inspection",
    response_model=DomainInspection,
)
def inspect_domain_comparison(
    domain_id: str,
    comparison_id: UUID,
    service: Annotated[DomainService, Depends(domain_service)],
):
    return service.inspect(domain_id, comparison_id)
