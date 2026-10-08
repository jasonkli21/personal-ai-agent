"""Gemini embedding capability and compatibility facade for memory tasks."""

import logging
from collections.abc import Sequence
from time import monotonic
from typing import Any

from personal_ai.llm.client import (
    ChatMessage,
    EmbeddingResult,
    EmbeddingSpace,
    ProviderCapabilities,
    ProviderIdentity,
)
from personal_ai.llm.context import GeminiTokenCounter
from personal_ai.llm.errors import LLMError, LLMInvalidResponseError
from personal_ai.llm.gemini import GeminiLLMClient, _translate_error
from personal_ai.memory.contracts import vector
from personal_ai.memory.extraction import MemoryCandidateExtractor
from personal_ai.settings import Settings

logger = logging.getLogger(__name__)


EMBEDDING_SPACE_VERSION = "v1"


class GeminiEmbeddingClient:
    """Gemini embedding adapter returning vectors with immutable space metadata."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client
        self.identity = ProviderIdentity(
            "google_genai", settings.memory_embedding_model, "gemini-embedding-v1"
        )
        self.capabilities = ProviderCapabilities(frozenset({"embeddings"}))

    def embed(
        self,
        texts: Sequence[str],
        *,
        query: bool = False,
        timeout: float | None = None,
    ) -> tuple[EmbeddingResult, ...]:
        self.capabilities.require("embeddings")
        if not texts or any(not text.strip() or len(text) > 20_000 for text in texts):
            raise LLMInvalidResponseError("embedding input invalid")
        duration = timeout if timeout is not None else self.settings.memory_timeout_seconds
        if duration <= 0:
            raise LLMInvalidResponseError("embedding deadline expired")
        deadline = monotonic() + duration
        client = self.client
        owns = client is None
        try:
            adapter = GeminiLLMClient(self.settings, client)
            adapter._validate_request([ChatMessage("user", "embedding")])
            if client is None:
                client = adapter._build_client()
            results: list[EmbeddingResult] = []
            space = EmbeddingSpace(
                provider_id="google_genai",
                model_id=self.settings.memory_embedding_model,
                dimensions=self.settings.memory_embedding_dimensions,
                normalization="l2",
                document_task="RETRIEVAL_DOCUMENT",
                query_task="RETRIEVAL_QUERY",
                version=EMBEDDING_SPACE_VERSION,
            )
            task = "query" if query else "document"
            task_name = space.query_task if query else space.document_task
            size = self.settings.memory_embedding_batch_size
            for start in range(0, len(texts), size):
                left = deadline - monotonic()
                if left <= 0:
                    raise TimeoutError("memory_timeout")
                batch = texts[start : start + size]
                response = client.models.embed_content(
                    model=self.settings.memory_embedding_model,
                    contents=list(batch),
                    config={
                        "output_dimensionality": self.settings.memory_embedding_dimensions,
                        "task_type": task_name,
                        "http_options": {
                            "timeout": max(1, int(left * 1000)),
                            "retry_options": {"attempts": 1},
                        },
                    },
                )
                if response.embeddings is None or len(response.embeddings) != len(batch):
                    raise ValueError("embedding_count_invalid")
                for item in response.embeddings:
                    results.append(EmbeddingResult(
                        values=vector(item.values, space.dimensions),
                        space=space,
                        task=task,
                    ))
            if monotonic() > deadline:
                raise TimeoutError("memory_timeout")
            return tuple(results)
        except LLMError:
            raise
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            raise LLMInvalidResponseError("embedding response invalid") from error
        except Exception as error:
            raise _translate_error(error) from error
        finally:
            if owns and client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001 - owned-client cleanup is best effort
                    logger.info("Embedding provider cleanup failed")


class GeminiMemoryAdapter:
    """Compatibility composition of neutral generation, count, and embedding seams."""

    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self.client = client
        self.generator = GeminiLLMClient(settings, client)
        self.counter = GeminiTokenCounter(settings, client)
        self.embedder = GeminiEmbeddingClient(settings, client)
        self.extractor = MemoryCandidateExtractor(settings, self.generator, self.counter)

    def embed(self, texts: Sequence[str], *, query: bool = False, timeout: float | None = None):
        return self.embedder.embed(texts, query=query, timeout=timeout)

    def extract(self, source_turn, *, timeout):
        try:
            return self.extractor.extract(source_turn, timeout=timeout)
        finally:
            self.counter.close()
