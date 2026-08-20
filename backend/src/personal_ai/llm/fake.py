"""Deterministic LLM implementation for offline tests."""

from collections.abc import AsyncIterator, Sequence

from personal_ai.llm.client import ChatMessage


class FakeLLMClient:
    """Yield configured deltas in order without network or credentials."""

    def __init__(self, deltas: Sequence[str] = ()) -> None:
        self.deltas = tuple(deltas)
        self.requests: list[tuple[ChatMessage, ...]] = []

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        self.requests.append(tuple(messages))
        for delta in self.deltas:
            yield delta
