"""Deterministic LLM implementation for offline tests."""

from collections.abc import AsyncIterator, Sequence

from personal_ai.llm.client import ChatMessage, InferenceContext


class FakeLLMClient:
    """Yield configured deltas in order without network or credentials."""

    requires_inference_context = False

    def __init__(self, deltas: Sequence[str] = ()) -> None:
        self.deltas = tuple(deltas)
        self.requests: list[tuple[ChatMessage, ...]] = []
        self.inference_contexts: list[InferenceContext | None] = []

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        self.requests.append(tuple(messages))
        self.inference_contexts.append(inference_context)
        for delta in self.deltas:
            yield delta

    async def stream_bounded(
        self, messages, *, max_output_tokens: int, timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ):
        async for delta in self.stream(messages, inference_context=inference_context):
            yield delta


class FakeResearchLLMClient:
    """Offline literal-excerpt synthesis; no model or search network calls."""

    async def stream(self, messages, *, inference_context: InferenceContext | None = None):
        del inference_context
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

    async def stream_bounded(
        self, messages, *, max_output_tokens: int, timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ):
        del max_output_tokens, timeout_seconds
        async for delta in self.stream(messages, inference_context=inference_context):
            yield delta
