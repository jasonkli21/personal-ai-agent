"""Deterministic, fixture-defined providers; no random or real vectors."""

from personal_ai.memory.contracts import vector


class FakeEmbedder:
    def __init__(self, vectors, *, dimensions=3):
        self.vectors, self.dimensions, self.calls = vectors, dimensions, []

    def embed(self, texts, *, query=False, timeout=None):
        self.calls.append((tuple(texts), query))
        return tuple(vector(self.vectors[t], self.dimensions) for t in texts)


class FakeMemoryExtractor:
    def __init__(self, candidates=()):
        self.candidates, self.calls = candidates, []

    def extract(self, source_turn, *, timeout):
        self.calls.append(tuple(source_turn))
        return self.candidates
