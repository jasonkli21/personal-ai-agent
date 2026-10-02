"""Replaceable search/planning/extraction/reranking interfaces."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import Field

from personal_ai.evidence.contracts import Evidence, ResearchRecord


class SearchResult(ResearchRecord):
    url: str = Field(max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    text: str = Field(max_length=10000)
    published_at: datetime | None = None


class SearchAdapter(Protocol):
    name: str

    async def search(self, query: str, limit: int) -> Sequence[SearchResult]: ...


class QueryPlanner(Protocol):
    def plan(self, question: str, max_queries: int) -> Sequence[str]: ...


class ContentExtractor(Protocol):
    def extract(self, text: str) -> str: ...


class EvidenceReranker(Protocol):
    def rank(self, question: str, evidence: Sequence[Evidence]) -> Sequence[Evidence]: ...


class FakeSearchAdapter:
    name = "fake"

    def __init__(self, results: Sequence[SearchResult] = (), error: Exception | None = None):
        self.results, self.error = tuple(results), error
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int):
        self.calls.append((query, limit))
        if self.error:
            raise self.error
        return self.results[:limit]
