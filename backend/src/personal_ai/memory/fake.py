"""Deterministic, fixture-defined providers; no random or real vectors."""

from personal_ai.llm.client import EmbeddingResult, EmbeddingSpace
from personal_ai.memory.contracts import vector


class FakeEmbedder:
    def __init__(self, vectors, *, dimensions=3, provider="fake", model="fake-v1", version="v1"):
        self.vectors, self.dimensions, self.calls = vectors, dimensions, []
        self.space = EmbeddingSpace(
            provider_id=provider,
            model_id=model,
            dimensions=dimensions,
            normalization="l2",
            document_task="RETRIEVAL_DOCUMENT",
            query_task="RETRIEVAL_QUERY",
            version=version,
        )

    def embed(self, texts, *, query=False, timeout=None):
        self.calls.append((tuple(texts), query))
        task = "query" if query else "document"
        return tuple(
            EmbeddingResult(vector(self.vectors[text], self.dimensions), self.space, task)
            for text in texts
        )


class FakeMemoryExtractor:
    def __init__(self, candidates=()):
        self.candidates, self.calls = candidates, []

    def extract(self, source_turn, *, timeout):
        self.calls.append(tuple(source_turn))
        return self.candidates
