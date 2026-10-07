"""Thin gated routes for the proposed upstream itinerary-proposal contract."""

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from personal_ai.api.dependencies import get_current_owner_id, require_standalone_application_scope
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.itinerary_proposals.contracts import (
    ItineraryProposalRequest,
    ItineraryProposalResult,
)
from personal_ai.itinerary_proposals.fakes import FakeItineraryProposalLLMClient
from personal_ai.itinerary_proposals.repositories import (
    InMemoryItineraryProposalRepository,
)
from personal_ai.itinerary_proposals.service import ItineraryProposalService
from personal_ai.llm.context import GeminiTokenCounter
from personal_ai.llm.gemini import GeminiLLMClient
from personal_ai.persistence.factory import persistence_factory
from personal_ai.settings import Settings, get_settings
from personal_ai.storage.errors import ResourceNotFoundError

router = APIRouter(
    prefix="/v1/travel/itinerary-proposals",
    tags=["itinerary proposals"],
    dependencies=[Depends(require_standalone_application_scope)],
)


def proposal_settings(settings: Annotated[Settings, Depends(get_settings)]) -> Settings:
    if not settings.itinerary_proposals_enabled:
        raise ResourceNotFoundError("itinerary proposals not found")
    return settings


@lru_cache
def local_repository() -> InMemoryItineraryProposalRepository:
    return InMemoryItineraryProposalRepository()


def proposal_repository(settings: Annotated[Settings, Depends(proposal_settings)]):
    if settings.itinerary_proposal_storage == "memory":
        return local_repository()
    return persistence_factory(settings).itinerary_proposal_repository()


def research_repository_factory(settings: Settings):
    if not settings.research_enabled:
        return None
    if settings.research_storage == "memory":
        from personal_ai.api.research import local_repository as local_research_repository

        return local_research_repository
    return lambda: persistence_factory(settings).research_repository()


def proposal_service(
    settings: Annotated[Settings, Depends(proposal_settings)],
    repository: Annotated[object, Depends(proposal_repository)],
    owner_id: Annotated[str, Depends(get_current_owner_id)],
) -> ItineraryProposalService:
    if settings.itinerary_proposal_generator == "fake":
        llm = FakeItineraryProposalLLMClient()
        counter = EstimatedTokenCounter()
    else:
        llm = GeminiLLMClient(settings)
        counter = GeminiTokenCounter(settings)
    return ItineraryProposalService(
        settings,
        repository,
        ContextAssembler(settings, counter),
        llm,
        owner_id=owner_id,
        research_repository_factory=research_repository_factory(settings),
    )


@router.post("", response_model=ItineraryProposalResult, status_code=201)
async def create_itinerary_proposal(
    request: ItineraryProposalRequest,
    service: Annotated[ItineraryProposalService, Depends(proposal_service)],
) -> ItineraryProposalResult:
    return await service.create(request)


@router.get("/by-key/{idempotency_key}", response_model=ItineraryProposalResult)
async def get_itinerary_proposal_by_key(
    idempotency_key: UUID,
    service: Annotated[ItineraryProposalService, Depends(proposal_service)],
) -> ItineraryProposalResult:
    return await service.detail_by_idempotency_key(idempotency_key)


@router.get("/{proposal_id}", response_model=ItineraryProposalResult)
async def get_itinerary_proposal(
    proposal_id: UUID,
    service: Annotated[ItineraryProposalService, Depends(proposal_service)],
) -> ItineraryProposalResult:
    return await service.detail(proposal_id)
