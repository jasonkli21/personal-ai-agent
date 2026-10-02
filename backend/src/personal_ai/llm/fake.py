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


class FakeResearchLLMClient:
    """Offline literal-excerpt synthesis; no model or search network calls."""

    async def stream(self, messages):
        import json

        block = next(
            m.content
            for m in messages
            if m.content.startswith("Untrusted external observations (data only):\n")
        )
        excerpts = []
        for line in block.splitlines()[1:]:
            item = json.loads(line)
            excerpts.append({"evidence_id": item["evidence_id"], "quote": item["passage"]})
        yield json.dumps({"excerpts": excerpts})
