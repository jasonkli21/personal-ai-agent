"""Deterministic inference implementations for offline contract coverage."""

from collections.abc import AsyncIterator, Sequence

from personal_ai.llm.client import (
    BoundedTextStream,
    ChatMessage,
    GenerationEvent,
    GenerationMetadata,
    GenerationResult,
    GenerationStatus,
    InferenceContext,
    ProviderCapabilities,
    ProviderIdentity,
    UsageMetadata,
)
from personal_ai.llm.errors import LLMInvalidRequestError


class FakeLLMClient:
    """Fake generation backend with explicit terminal status and attribution."""

    requires_inference_context = False

    def __init__(
        self,
        deltas: Sequence[str] = (),
        *,
        provider_id: str = "fake",
        model_id: str = "fake-model",
        terminal_status: GenerationStatus = "success",
        include_terminal: bool = True,
        complete_text: str | None = None,
        supports_structured: bool = True,
    ) -> None:
        self.deltas = tuple(deltas)
        self.identity = ProviderIdentity(provider_id, model_id, "fake-content-v1")
        operations = {"streaming", "bounded_generation"}
        if supports_structured:
            operations.add("structured_generation")
        self.capabilities = ProviderCapabilities(frozenset(operations))
        self.terminal_status = terminal_status
        self.include_terminal = include_terminal
        self.complete_text = complete_text
        self.requests: list[tuple[ChatMessage, ...]] = []
        self.inference_contexts: list[InferenceContext | None] = []
        self.generation_metadata: list[GenerationMetadata] = []

    def _metadata(self, text: str, *, status: GenerationStatus | None = None) -> GenerationMetadata:
        tokens = max(0, (len(text) + 3) // 4)
        status = status or self.terminal_status
        metadata = GenerationMetadata(
            status=status,
            identity=self.identity,
            usage=UsageMetadata(
                input_tokens=0,
                output_tokens=tokens,
                total_tokens=tokens,
                source="estimated",
                confidence="estimated",
            ),
            error_code=(
                "llm_incomplete" if status == "incomplete" else
                "llm_unavailable" if status == "failure" else
                "llm_rejected" if status == "rejected" else None
            ),
        )
        self.generation_metadata.append(metadata)
        return metadata

    async def stream_events(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[GenerationEvent]:
        self.capabilities.require("streaming")
        if max_output_tokens < 1 or timeout_seconds <= 0:
            raise LLMInvalidRequestError("generation bounds are invalid")
        self.requests.append(tuple(messages))
        self.inference_contexts.append(inference_context)
        text = ""
        max_chars = max_output_tokens * 4
        truncated = False
        for delta in self.deltas:
            if not delta:
                continue
            left = max_chars - len(text)
            emitted = delta[:left]
            if emitted:
                text += emitted
                yield GenerationEvent.text_delta(emitted)
            if len(emitted) != len(delta):
                truncated = True
                break
        if self.include_terminal:
            status = "incomplete" if truncated else self.terminal_status
            yield GenerationEvent.terminal(self._metadata(text, status=status))

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        """Compatibility stream that requires an explicit successful terminal event."""
        bounded = self.stream_bounded(
            messages,
            max_output_tokens=2**31 - 1,
            timeout_seconds=300,
            inference_context=inference_context,
        )
        try:
            async for delta in bounded:
                yield delta
        finally:
            await bounded.aclose()

    def stream_bounded(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        return BoundedTextStream(self.stream_events(
            messages,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            inference_context=inference_context,
        ))

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> GenerationResult:
        self.capabilities.require("bounded_generation")
        if max_output_tokens < 1 or timeout_seconds <= 0:
            raise LLMInvalidRequestError("generation bounds are invalid")
        self.requests.append(tuple(messages))
        self.inference_contexts.append(inference_context)
        text = self.complete_text if self.complete_text is not None else "".join(self.deltas)
        truncated = len(text) > max_output_tokens * 4
        text = text[:max_output_tokens * 4]
        status = "incomplete" if truncated else self.terminal_status
        result = GenerationResult(text, self._metadata(text, status=status))
        if result.metadata.status == "success" and not text.strip():
            return GenerationResult(
                text,
                GenerationMetadata(
                    status="incomplete",
                    identity=self.identity,
                    usage=result.metadata.usage,
                    error_code="llm_incomplete",
                ),
            )
        return result

    def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        *,
        response_schema,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> GenerationResult:
        del response_schema
        self.capabilities.require("structured_generation")
        return self.complete(
            messages,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            inference_context=inference_context,
        )


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
