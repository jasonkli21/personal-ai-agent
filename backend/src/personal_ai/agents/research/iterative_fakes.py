"""Deterministic clock and ordered work queues for iterative tests/evaluations."""

import inspect
from collections import deque
from datetime import UTC, datetime, timedelta

from personal_ai.search.contracts import SearchResult


class DeterministicClock:
    def __init__(self, start: datetime | None = None):
        self.value = start or datetime(2026, 1, 1, tzinfo=UTC)
        self.elapsed_seconds = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds: float):
        self.value += timedelta(seconds=seconds)
        self.elapsed_seconds += seconds
        return self.value

    def elapsed(self):
        return self.elapsed_seconds


class DeterministicQueue:
    def __init__(self, values=()):
        self.values = deque(values)

    def pop(self, default=None):
        return self.values.popleft() if self.values else default

    def __len__(self):
        return len(self.values)


class FakeIterativeSearchAdapter:
    name = "fake"

    def __init__(self, scripts: dict[str, list[SearchResult] | Exception], default=(), *, on_search=None):
        self.scripts = {" ".join(key.split()).casefold(): value for key, value in scripts.items()}
        self.default = tuple(default)
        self.calls: list[tuple[str, int]] = []
        self.responses = DeterministicQueue()
        self.on_search = on_search

    @classmethod
    def queued(cls, responses, *, on_search=None):
        adapter = cls({}, ())
        adapter.responses = DeterministicQueue(responses)
        adapter.on_search = on_search
        return adapter

    async def search(self, query: str, limit: int):
        normalized = " ".join(query.split()).casefold()
        self.calls.append((query, limit))
        if self.on_search is not None:
            result = self.on_search(query, limit)
            if inspect.isawaitable(result):
                await result
        result = self.responses.pop(self.scripts.get(normalized, self.default))
        if isinstance(result, Exception):
            raise result
        if isinstance(result, DeterministicQueue):
            result = result.pop(())
        return tuple(result[:limit])
