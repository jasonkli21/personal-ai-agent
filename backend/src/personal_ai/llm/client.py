"""Provider-neutral generation, counting, and embedding contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import anyio

from personal_ai.entities.conversation import MessageRole
from personal_ai.llm.errors import (
    LLMIncompleteGenerationError,
    LLMInvalidResponseError,
    LLMRejectedError,
    LLMUnavailableError,
    LLMUnsupportedCapabilityError,
)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A single ordered, active-path chat message supplied to an LLM."""

    role: MessageRole | Literal["system"]
    content: str


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    """Safe identity of the endpoint and serializer used for one operation."""

    provider_id: str
    model_id: str
    serializer_id: str

    def __post_init__(self) -> None:
        if any(not value or len(value) > 200 for value in (
            self.provider_id, self.model_id, self.serializer_id
        )):
            raise ValueError("provider_identity_invalid")


ProviderOperation = Literal[
    "streaming",
    "bounded_generation",
    "structured_generation",
    "token_counting",
    "embeddings",
]


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Declared operations for a provider runtime; unsupported calls fail closed."""

    operations: frozenset[ProviderOperation]

    def supports(self, operation: ProviderOperation) -> bool:
        return operation in self.operations

    def require(self, operation: ProviderOperation) -> None:
        if not self.supports(operation):
            raise LLMUnsupportedCapabilityError("inference capability is unsupported")


@dataclass(frozen=True, slots=True)
class UsageMetadata:
    """Provider-reported or estimated token usage with an explicit confidence source."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    source: Literal["provider", "estimated"] = "provider"
    confidence: Literal["reported", "estimated"] = "reported"

    def __post_init__(self) -> None:
        for value in (self.input_tokens, self.output_tokens, self.total_tokens):
            if value is not None and (isinstance(value, bool) or value < 0):
                raise ValueError("usage_metadata_invalid")
        if self.source == "estimated" and self.confidence != "estimated":
            raise ValueError("usage_confidence_invalid")


GenerationStatus = Literal["success", "incomplete", "failure", "rejected"]


@dataclass(frozen=True, slots=True)
class GenerationMetadata:
    """Terminal status and per-invocation attribution without provider payloads."""

    status: GenerationStatus
    identity: ProviderIdentity
    usage: UsageMetadata | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    metadata: GenerationMetadata

    def require_success(self) -> GenerationResult:
        if self.metadata.status == "incomplete":
            raise LLMIncompleteGenerationError("language model response was incomplete")
        if self.metadata.status == "failure":
            raise LLMUnavailableError("language model generation failed")
        if self.metadata.status == "rejected":
            raise LLMRejectedError("language model rejected the request")
        return self


class BoundedTextStream(AsyncIterator[str]):
    """Text facade that retains terminal attribution and owns its event iterator."""

    def __init__(self, events: AsyncIterator[GenerationEvent], *, cleanup_seconds: float = 1):
        self._events = events.__aiter__()
        self._cleanup_seconds = cleanup_seconds
        self._closed = False
        self.metadata: GenerationMetadata | None = None

    def __aiter__(self) -> BoundedTextStream:
        return self

    async def __anext__(self) -> str:
        if self._closed:
            raise StopAsyncIteration
        try:
            event = await anext(self._events)
        except StopAsyncIteration as error:
            self._closed = True
            raise LLMIncompleteGenerationError(
                "language model ended without a terminal result"
            ) from error
        if not isinstance(event, GenerationEvent):
            await self.aclose()
            raise LLMInvalidResponseError("language model emitted an invalid event")
        if event.kind == "delta":
            return event.delta

        self.metadata = event.metadata
        try:
            GenerationResult("", event.metadata).require_success()
            try:
                await anext(self._events)
            except StopAsyncIteration:
                self._closed = True
                raise StopAsyncIteration
            await self.aclose()
            raise LLMInvalidResponseError(
                "language model emitted data after its terminal event"
            )
        except StopAsyncIteration:
            raise
        except Exception:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self._events, "aclose", None)
        if close is None:
            return
        with anyio.CancelScope(shield=True):
            with anyio.move_on_after(self._cleanup_seconds) as timeout_scope:
                try:
                    await close()
                except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001
                    logging.getLogger(__name__).debug(
                        "Generation stream cleanup failed error_class=%s",
                        type(error).__name__,
                    )
            if timeout_scope.cancel_called:
                logging.getLogger(__name__).debug("Generation stream cleanup timed out")


@dataclass(frozen=True, slots=True)
class GenerationEvent:
    """One text delta or an explicit terminal event from a streamed generation."""

    kind: Literal["delta", "terminal"]
    delta: str = ""
    metadata: GenerationMetadata | None = None

    def __post_init__(self) -> None:
        if self.kind == "delta" and (self.metadata is not None or not self.delta):
            raise ValueError("generation_delta_invalid")
        if self.kind == "terminal" and (self.metadata is None or self.delta):
            raise ValueError("generation_terminal_invalid")

    @classmethod
    def text_delta(cls, text: str) -> GenerationEvent:
        return cls(kind="delta", delta=text)

    @classmethod
    def terminal(cls, metadata: GenerationMetadata) -> GenerationEvent:
        return cls(kind="terminal", metadata=metadata)


@dataclass(frozen=True, slots=True)
class TokenCount:
    tokens: int
    kind: Literal["provider", "estimated"]
    provider_id: str | None = None
    model_id: str | None = None
    serializer_id: str | None = None
    confidence: Literal["authoritative", "reported", "estimated"] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.tokens, bool) or self.tokens < 0:
            raise ValueError("token_count_invalid")
        if self.kind == "provider" and self.confidence == "estimated":
            raise ValueError("token_count_confidence_invalid")


@dataclass(frozen=True, slots=True)
class EmbeddingSpace:
    """Immutable logical identity for a compatible family of embedding vectors."""

    provider_id: str
    model_id: str
    dimensions: int
    normalization: str
    document_task: str
    query_task: str
    version: str

    def __post_init__(self) -> None:
        if any(not value or len(value) > 200 for value in (
            self.provider_id,
            self.model_id,
            self.normalization,
            self.document_task,
            self.query_task,
            self.version,
        )) or isinstance(self.dimensions, bool) or self.dimensions < 1:
            raise ValueError("embedding_space_invalid")

    @property
    def identity(self) -> str:
        payload = {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "dimensions": self.dimensions,
            "normalization": self.normalization,
            "document_task": self.document_task,
            "query_task": self.query_task,
            "version": self.version,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    values: tuple[float, ...]
    space: EmbeddingSpace
    task: Literal["document", "query"]

    def __post_init__(self) -> None:
        if len(self.values) != self.space.dimensions or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in self.values
        ):
            raise ValueError("embedding_result_invalid")
        if self.space.normalization == "l2":
            norm = math.sqrt(sum(value * value for value in self.values))
            if not math.isfinite(norm) or not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
                raise ValueError("embedding_result_not_normalized")


class LLMClient(Protocol):
    """Compatibility facade for callers that consume only text deltas."""

    requires_inference_context: bool

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        """Yield text deltas, raising unless the provider reports terminal success."""


@dataclass(frozen=True, slots=True)
class InferenceContext:
    """Server-computed sensitivity decision carried to the inference boundary."""

    effective_sensitivity: Literal["public", "personal", "sensitive", "restricted", "unknown"]
    maximum_sensitivity: Literal["public", "personal", "sensitive", "restricted"]
    policy_version: str

    def __post_init__(self) -> None:
        rank = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3, "unknown": 4}
        if not self.policy_version or rank[self.effective_sensitivity] > rank[self.maximum_sensitivity]:
            raise ValueError("inference_context_not_authorized")


class GenerationClient(LLMClient, Protocol):
    identity: ProviderIdentity
    capabilities: ProviderCapabilities

    def stream_events(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[GenerationEvent]: ...

    def stream_bounded(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        """Compatibility facade that requires terminal success before exhaustion."""

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> GenerationResult: ...

    def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        *,
        response_schema: Mapping[str, object],
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> GenerationResult: ...


class TokenCountingClient(Protocol):
    requires_inference_context: bool
    identity: ProviderIdentity
    capabilities: ProviderCapabilities

    def count(
        self,
        messages: Sequence[ChatMessage],
        *,
        response_schema: Mapping[str, object] | None = None,
        inference_context: InferenceContext | None = None,
    ) -> TokenCount: ...


class EmbeddingClient(Protocol):
    requires_inference_context: bool
    identity: ProviderIdentity
    capabilities: ProviderCapabilities

    def embed(
        self,
        texts: Sequence[str],
        *,
        query: bool = False,
        timeout: float | None = None,
        inference_context: InferenceContext | None = None,
    ) -> Sequence[EmbeddingResult]: ...


SYSTEM_INSTRUCTION = (
    "You are a helpful personal AI chat assistant. "
    "Answer directly and clearly based on this conversation."
)
