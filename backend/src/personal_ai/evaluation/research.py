"""Offline full-pipeline fixtures and a no-research baseline; no private data."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from personal_ai.agents.research.contracts import ResearchRequest
from personal_ai.agents.research.repositories import InMemoryResearchRepository
from personal_ai.agents.research.service import ResearchService
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.llm.fake import FakeLLMClient, FakeResearchLLMClient
from personal_ai.search.contracts import FakeSearchAdapter, SearchResult
from personal_ai.search.providers.brave import SearchError
from personal_ai.settings import Settings

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def load_fixtures():
    return json.loads(Path(__file__).with_name("research-fixtures.json").read_text())


def build_fixture(fixture, **overrides):
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        research_enabled=True,
        research_storage="memory",
        **overrides,
    )
    repository = InMemoryResearchRepository()
    error = SearchError(fixture["adapter_error"]) if fixture.get("adapter_error") else None
    adapter = FakeSearchAdapter(
        tuple(SearchResult.model_validate(s) for s in fixture["sources"]), error=error
    )
    llm = (
        FakeLLMClient(("Unsupported factual claim [99]",))
        if fixture.get("invalid_output")
        else (FakeResearchLLMClient())
    )
    service = ResearchService(
        settings,
        repository,
        adapter,
        ContextAssembler(settings, EstimatedTokenCounter()),
        llm,
        clock=lambda: NOW,
    )
    request = ResearchRequest(
        question=fixture["question"],
        idempotency_key=uuid4(),
        freshness=fixture.get("freshness", "general"),
    )
    return service, request


async def run_fixture(fixture):
    service, request = build_fixture(fixture)
    session = await service.create(request)
    claimed = await service.prepare_run(session.id)
    events = [e async for e in service.stream(claimed)]
    result = await service.detail(session.id)
    success = (
        result.state == fixture["expected"]
        and len(result.evidence) == fixture["evidence_count"]
        and len(result.citations) == fixture["citations"]
        and ("failure_code" not in fixture or result.failure_code == fixture["failure_code"])
    )
    return {
        "name": fixture["name"],
        "passed": success,
        "baseline_fresh_evidence": False,
        "state": result.state,
        "evidence_count": len(result.evidence),
        "citation_count": len(result.citations),
        "failure_code": result.failure_code,
        "query_count": len(result.queries),
        "event_count": len(events),
        "memory_writes": 0,
    }


async def evaluate():
    results = [await run_fixture(f) for f in load_fixtures()]
    return {
        "schema_version": "research-eval-v1",
        "synthetic": True,
        "passed": all(r["passed"] for r in results),
        "results": results,
    }


if __name__ == "__main__":
    report = asyncio.run(evaluate())
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
