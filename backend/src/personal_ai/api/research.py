"""Thin, gated research routes and composition; normal chat remains independent."""

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from personal_ai.agents.research.contracts import ResearchRequest, ResearchSession
from personal_ai.agents.research.repositories import (
    InMemoryResearchRepository,
)
from personal_ai.agents.research.service import ResearchService
from personal_ai.api.dependencies import get_current_owner_id
from personal_ai.api.routes import SSE_RESPONSES, _LifecycleStreamingResponse
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.llm.context import GeminiTokenCounter
from personal_ai.llm.fake import FakeResearchLLMClient
from personal_ai.llm.gemini import GeminiLLMClient
from personal_ai.persistence.factory import persistence_factory
from personal_ai.search.contracts import FakeSearchAdapter, SearchResult
from personal_ai.search.providers.brave import BraveSearchAdapter
from personal_ai.settings import Settings, get_settings
from personal_ai.storage.errors import ResourceNotFoundError

router = APIRouter(prefix="/v1/research", tags=["research"])


def research_settings(settings: Annotated[Settings, Depends(get_settings)]):
    if not settings.research_enabled:
        raise ResourceNotFoundError("research not found")
    return settings


@lru_cache
def local_repository():
    return InMemoryResearchRepository()


def research_repository(settings: Annotated[Settings, Depends(research_settings)]):
    if settings.research_storage == "memory":
        return local_repository()
    return persistence_factory(settings).research_repository()


def research_service(
    settings: Annotated[Settings, Depends(research_settings)],
    repository: Annotated[object, Depends(research_repository)],
    owner_id: Annotated[str, Depends(get_current_owner_id)],
):
    if settings.research_search_adapter == "fake":
        adapter = FakeSearchAdapter(
            (
                SearchResult(
                    url="https://example.org/synthetic-research",
                    title="Synthetic fixture",
                    text="This is synthetic research evidence for an offline demo. "
                    "It makes no claim about the real world.",
                ),
            )
        )
        counter, llm = EstimatedTokenCounter(), FakeResearchLLMClient()
    else:
        adapter = BraveSearchAdapter(settings)
        counter, llm = GeminiTokenCounter(settings), GeminiLLMClient(settings)
    return ResearchService(
        settings, repository, adapter, ContextAssembler(settings, counter), llm, owner_id=owner_id
    )


@router.post("", response_model=ResearchSession, status_code=201)
async def create_research(
    request: ResearchRequest, service: Annotated[ResearchService, Depends(research_service)]
):
    return await service.create(request)


@router.get("/{session_id}", response_model=ResearchSession)
async def research_detail(
    session_id: UUID, service: Annotated[ResearchService, Depends(research_service)]
):
    return await service.detail(session_id)


@router.post("/{session_id}/run", response_class=StreamingResponse, responses=SSE_RESPONSES)
async def run_research(
    session_id: UUID, service: Annotated[ResearchService, Depends(research_service)]
):
    session = await service.prepare_run(session_id)
    return _LifecycleStreamingResponse(
        service.stream(session),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/inspection")
async def inspect_research(
    session_id: UUID, service: Annotated[ResearchService, Depends(research_service)]
):
    if not service.settings.research_inspection_enabled:
        raise ResourceNotFoundError("research not found")
    session = await service.detail(session_id)
    return {
        "schema_version": "research-v1",
        "session_id": str(session.id),
        "state": session.state,
        "policy_version": session.policy_version,
        "query_count": len(session.queries),
        "source_count": len(session.observations),
        "evidence_count": len(session.evidence),
        "selection": session.selection.model_dump(mode="json") if session.selection else None,
        "source_exclusions": {
            str(s.id): s.status for s in session.observations if s.status != "accepted"
        },
        "duplicates_merged": sum(len(e.source_observation_ids) - 1 for e in session.evidence),
        "near_duplicates": {
            str(e.id): [str(i) for i in e.near_duplicate_ids]
            for e in session.evidence
            if e.near_duplicate_ids
        },
    }
