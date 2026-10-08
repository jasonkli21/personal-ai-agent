"""Gemini memory capability composed from Personal AI's neutral seams."""

from collections.abc import Callable, Sequence

import httpx

from personal_ai.llm.client import EmbeddingResult, InferenceContext
from personal_ai.llm.context import GeminiTokenCounter
from personal_ai.llm.gemini import GeminiLLMClient
from personal_ai.llm.litellm_gateway import LiteLLMEmbeddingClient
from personal_ai.memory.extraction import MemoryCandidateExtractor
from personal_ai.settings import Settings

EMBEDDING_SPACE_VERSION = "v1"


class GeminiEmbeddingClient(LiteLLMEmbeddingClient):
    """Gemini embeddings preserving the persisted logical memory space."""


class GeminiMemoryAdapter:
    """Composition of generation, authoritative counting, and embeddings."""

    requires_inference_context = True

    def __init__(
        self,
        settings: Settings,
        *,
        sync_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    ) -> None:
        self.settings = settings
        self.generator = GeminiLLMClient(
            settings, sync_transport_factory=sync_transport_factory
        )
        self.counter = GeminiTokenCounter(
            settings, sync_transport_factory=sync_transport_factory
        )
        self.embedder = GeminiEmbeddingClient(
            settings, sync_transport_factory=sync_transport_factory
        )
        self.extractor = MemoryCandidateExtractor(settings, self.generator, self.counter)

    def embed(
        self,
        texts: Sequence[str],
        *,
        query: bool = False,
        timeout: float | None = None,
        inference_context: InferenceContext | None = None,
    ) -> tuple[EmbeddingResult, ...]:
        return self.embedder.embed(
            texts, query=query, timeout=timeout, inference_context=inference_context
        )

    def extract(
        self,
        source_turn,
        *,
        timeout: float,
        inference_context: InferenceContext | None = None,
    ):
        return self.extractor.extract(
            source_turn, timeout=timeout, inference_context=inference_context
        )
