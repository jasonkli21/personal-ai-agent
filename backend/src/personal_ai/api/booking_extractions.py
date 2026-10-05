"""Authenticated default-off booking document extraction capability."""

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from personal_ai.api.dependencies import get_current_owner_id
from personal_ai.booking_extractions.contracts import (
    BookingExtractionDeleteRequest,
    BookingExtractionRequest,
    BookingExtractionResult,
)
from personal_ai.booking_extractions.fakes import FakeBookingExtractionLLMClient
from personal_ai.booking_extractions.repositories import (
    BookingExtractionRepository,
    FirestoreBookingExtractionRepository,
    InMemoryBookingExtractionRepository,
)
from personal_ai.booking_extractions.service import BookingExtractionService
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.llm.context import GeminiTokenCounter
from personal_ai.llm.gemini import GeminiLLMClient
from personal_ai.settings import Settings, get_settings
from personal_ai.storage.errors import ResourceNotFoundError

router = APIRouter(prefix="/v1/travel/booking-extractions", tags=["booking extractions"])


def enabled_settings(settings: Annotated[Settings, Depends(get_settings)]) -> Settings:
    if not settings.booking_extractions_enabled:
        raise ResourceNotFoundError("booking extraction not found")
    return settings


@lru_cache
def local_repository() -> InMemoryBookingExtractionRepository:
    return InMemoryBookingExtractionRepository()


def extraction_repository(
    settings: Annotated[Settings, Depends(enabled_settings)],
) -> BookingExtractionRepository:
    if settings.booking_extraction_storage == "memory":
        return local_repository()
    return FirestoreBookingExtractionRepository(
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )


def extraction_service(
    settings: Annotated[Settings, Depends(enabled_settings)],
    repository: Annotated[BookingExtractionRepository, Depends(extraction_repository)],
    owner_id: Annotated[str, Depends(get_current_owner_id)],
) -> BookingExtractionService:
    if settings.booking_extraction_generator == "fake":
        llm, counter = FakeBookingExtractionLLMClient(), EstimatedTokenCounter()
    else:
        llm, counter = GeminiLLMClient(settings), GeminiTokenCounter(settings)
    return BookingExtractionService(
        settings,
        repository,
        ContextAssembler(settings, counter),
        llm,
        owner_id=owner_id,
    )


@router.post("", response_model=BookingExtractionResult, status_code=201)
async def create_booking_extraction(
    request: BookingExtractionRequest,
    service: Annotated[BookingExtractionService, Depends(extraction_service)],
) -> BookingExtractionResult:
    if service.settings.booking_extraction_generator == "fake" and not request.synthetic_fixture:
        raise ResourceNotFoundError("booking extraction not found")
    return await service.create(request)


@router.get("/by-key/{idempotency_key}", response_model=BookingExtractionResult)
def booking_extraction_by_key(
    idempotency_key: UUID,
    service: Annotated[BookingExtractionService, Depends(extraction_service)],
) -> BookingExtractionResult:
    return service.detail_by_key(idempotency_key)


@router.delete("/by-key/{idempotency_key}", response_model=BookingExtractionResult)
def delete_booking_extraction_by_key(
    idempotency_key: UUID,
    payload: BookingExtractionDeleteRequest,
    service: Annotated[BookingExtractionService, Depends(extraction_service)],
) -> BookingExtractionResult:
    return service.delete_by_key(idempotency_key, payload.source_sha256)


@router.get("/{extraction_id}", response_model=BookingExtractionResult)
def booking_extraction_detail(
    extraction_id: UUID,
    service: Annotated[BookingExtractionService, Depends(extraction_service)],
) -> BookingExtractionResult:
    return service.detail(extraction_id)


@router.delete("/{extraction_id}", response_model=BookingExtractionResult)
def delete_booking_extraction(
    extraction_id: UUID,
    service: Annotated[BookingExtractionService, Depends(extraction_service)],
) -> BookingExtractionResult:
    return service.delete(extraction_id)
