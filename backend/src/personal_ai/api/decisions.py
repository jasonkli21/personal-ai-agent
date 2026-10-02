"""Thin opt-in API routes for evidence-grounded decision support."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from personal_ai.agents.research.repositories import FirestoreResearchRepository
from personal_ai.api.dependencies import get_current_owner_id
from personal_ai.decisions.contracts import (
    DecisionCreateRequest,
    DecisionInspection,
    DecisionResult,
)
from personal_ai.decisions.firestore import FirestoreDecisionRepository
from personal_ai.decisions.service import DecisionService
from personal_ai.settings import Settings, get_settings
from personal_ai.storage.errors import ResourceNotFoundError

router = APIRouter(prefix="/v1/decisions", tags=["decisions"])


def decision_settings(settings: Annotated[Settings, Depends(get_settings)]) -> Settings:
    if not settings.decision_enabled:
        raise ResourceNotFoundError("decision not found")
    return settings


def decision_repository(settings: Annotated[Settings, Depends(decision_settings)]):
    return FirestoreDecisionRepository(
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )


def _research_repository_factory(settings: Settings):
    if settings.research_storage == "memory":
        from personal_ai.api.research import local_repository

        return local_repository

    return lambda: FirestoreResearchRepository(
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )


def decision_service(
    settings: Annotated[Settings, Depends(decision_settings)],
    repository: Annotated[FirestoreDecisionRepository, Depends(decision_repository)],
    owner_id: Annotated[str, Depends(get_current_owner_id)],
) -> DecisionService:
    return DecisionService(
        settings,
        repository,
        research_repository=_research_repository_factory(settings),
        owner_id=owner_id,
    )


@router.post("", response_model=DecisionResult, status_code=status.HTTP_201_CREATED)
def create_decision(
    request: DecisionCreateRequest,
    service: Annotated[DecisionService, Depends(decision_service)],
) -> DecisionResult:
    """Persist a reproducible decision from selected or explicitly supplied evidence."""
    return service.create(request)


@router.get("/{decision_id}", response_model=DecisionResult)
def get_decision(
    decision_id: UUID,
    service: Annotated[DecisionService, Depends(decision_service)],
) -> DecisionResult:
    return service.detail(decision_id)


def _inspection_settings(
    settings: Annotated[Settings, Depends(decision_settings)],
) -> Settings:
    if not settings.decision_inspection_enabled:
        raise ResourceNotFoundError("decision not found")
    return settings


@router.get("/{decision_id}/inspection", response_model=DecisionInspection)
def inspect_decision(
    decision_id: UUID,
    settings: Annotated[Settings, Depends(_inspection_settings)],
    service: Annotated[DecisionService, Depends(decision_service)],
) -> DecisionInspection:
    del settings
    return service.inspect(decision_id)
