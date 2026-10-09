"""Separate opt-in routes for bounded iterative research runs."""

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from personal_ai.agents.research.contracts import ResearchError
from personal_ai.agents.research.iterative_contracts import IterativeResearchRequest
from personal_ai.agents.research.iterative_repositories import (
    InMemoryIterativeResearchRepository,
)
from personal_ai.agents.research.iterative_service import IterativeResearchService
from personal_ai.agents.research.repositories import InMemoryResearchRepository
from personal_ai.api.dependencies import get_application_context, get_current_owner_id
from personal_ai.api.research import local_repository
from personal_ai.api.routes import SSE_RESPONSES, _LifecycleStreamingResponse
from personal_ai.applications.contracts import ApplicationContextRequest
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.decisions.repositories import InMemoryDecisionRepository
from personal_ai.llm.context import GeminiTokenCounter
from personal_ai.llm.fake import FakeResearchLLMClient
from personal_ai.llm.gemini import GeminiLLMClient
from personal_ai.persistence.factory import persistence_factory
from personal_ai.search.contracts import FakeSearchAdapter, SearchResult
from personal_ai.search.providers.brave import BraveSearchAdapter
from personal_ai.settings import Settings, get_settings
from personal_ai.storage.errors import ResourceNotFoundError

router = APIRouter(prefix="/v1/research/iterative", tags=["iterative research"])


def iterative_settings(settings: Annotated[Settings, Depends(get_settings)]):
    if not (
        settings.research_enabled
        and settings.iterative_research_enabled
        and settings.iterative_progress_enabled
    ):
        raise ResourceNotFoundError("research run not found")
    return settings


@lru_cache
def local_iterative_repository():
    sessions = local_repository()
    if not isinstance(sessions, InMemoryResearchRepository):
        raise TypeError("iterative repository requires the in-memory session store")
    return InMemoryIterativeResearchRepository(sessions)


@lru_cache
def local_iterative_decision_repository():
    return InMemoryDecisionRepository()


def iterative_research_service(
    settings: Annotated[Settings, Depends(iterative_settings)],
    owner_id: Annotated[str, Depends(get_current_owner_id)],
    application_context: Annotated[ApplicationContextRequest, Depends(get_application_context)],
):
    if settings.research_storage == "memory":
        sessions = local_repository()
        runs = local_iterative_repository()
        decisions = local_iterative_decision_repository()
    else:
        factory = persistence_factory(settings)
        sessions = factory.research_repository()
        runs = factory.iterative_research_repository()
        decisions = factory.decision_repository()
    if settings.research_search_adapter == "fake":
        adapter = FakeSearchAdapter((SearchResult(
            url="https://example.org/synthetic-research",
            title="Synthetic fixture",
            text="This is synthetic research evidence for an offline demo. "
            "It makes no claim about the real world.",
        ),))
        counter, llm = EstimatedTokenCounter(), FakeResearchLLMClient()
    else:
        usage = persistence_factory(settings).provider_usage_accounting(settings)
        adapter = BraveSearchAdapter(settings, usage_accounting=usage)
        counter = GeminiTokenCounter(settings, usage_accounting=usage)
        llm = GeminiLLMClient(settings, usage_accounting=usage)
    return IterativeResearchService(
        settings,
        sessions,
        runs,
        adapter,
        ContextAssembler(settings, counter),
        llm,
        owner_id=owner_id,
        application_context=application_context,
        decision_repository=decisions,
    )


def _event_cursor(after: int, last_event_id: str | None) -> int:
    if last_event_id is None:
        return after
    try:
        cursor = int(last_event_id)
    except ValueError as error:
        raise ResearchError("research_event_cursor_invalid", 422) from error
    if cursor < -1:
        raise ResearchError("research_event_cursor_invalid", 422)
    return cursor


def _stream(body):
    return _LifecycleStreamingResponse(
        body,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"},
    )


@router.post("", response_class=StreamingResponse, responses=SSE_RESPONSES)
async def start_iterative_research(
    request: IterativeResearchRequest,
    service: Annotated[IterativeResearchService, Depends(iterative_research_service)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    cursor = _event_cursor(-1, last_event_id)
    run, token = await service.start(request, cursor)
    return _stream(service.stream(run, token, cursor))


@router.get("/runs/{run_id}")
async def iterative_research_detail(
    run_id: UUID,
    service: Annotated[IterativeResearchService, Depends(iterative_research_service)],
):
    run, session = await service.detail(run_id)
    return {"run": run, "session": session}


@router.get("/runs/{run_id}/events", response_class=StreamingResponse, responses=SSE_RESPONSES)
async def iterative_research_events(
    run_id: UUID,
    service: Annotated[IterativeResearchService, Depends(iterative_research_service)],
    after: Annotated[int, Query(ge=-1)] = -1,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    cursor = _event_cursor(after, last_event_id)
    run = await service.get(run_id)
    service._validate_cursor(run, cursor)
    return _stream(service.event_stream(run_id, cursor))


@router.post("/runs/{run_id}/cancel")
async def cancel_iterative_research(
    run_id: UUID,
    service: Annotated[IterativeResearchService, Depends(iterative_research_service)],
):
    return await service.cancel(run_id)


@router.post("/runs/{run_id}/resume", response_class=StreamingResponse, responses=SSE_RESPONSES)
async def resume_iterative_research(
    run_id: UUID,
    service: Annotated[IterativeResearchService, Depends(iterative_research_service)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    cursor = _event_cursor(-1, last_event_id)
    run, token = await service.resume(run_id, cursor)
    return _stream(service.stream(run, token, cursor))
