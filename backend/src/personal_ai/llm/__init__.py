"""Replaceable language-model clients for the chat application."""

from personal_ai.llm.client import (
    ChatMessage,
    EmbeddingClient,
    EmbeddingResult,
    EmbeddingSpace,
    GenerationClient,
    GenerationEvent,
    GenerationMetadata,
    GenerationResult,
    GenerationStatus,
    InferenceContext,
    LLMClient,
    ProviderCapabilities,
    ProviderIdentity,
    TokenCount,
    TokenCountingClient,
    UsageMetadata,
)
from personal_ai.llm.cloudflare import CloudflareWorkersAILLMClient
from personal_ai.llm.errors import (
    LLMError,
    LLMIncompleteGenerationError,
    LLMInvalidConfigurationError,
    LLMInvalidRequestError,
    LLMInvalidResponseError,
    LLMRateLimitedError,
    LLMRejectedError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMUnsupportedCapabilityError,
)
from personal_ai.llm.fake import FakeLLMClient
from personal_ai.llm.gemini import GeminiLLMClient
from personal_ai.llm.groq import GroqLLMClient
from personal_ai.llm.metadata import ProviderRateLimitMetadata
from personal_ai.llm.providers import build_generation_adapter

__all__ = [
    "ChatMessage",
    "CloudflareWorkersAILLMClient",
    "EmbeddingClient",
    "EmbeddingResult",
    "EmbeddingSpace",
    "FakeLLMClient",
    "GeminiLLMClient",
    "GenerationClient",
    "GenerationEvent",
    "GenerationMetadata",
    "GenerationResult",
    "GenerationStatus",
    "GroqLLMClient",
    "InferenceContext",
    "LLMClient",
    "LLMError",
    "LLMIncompleteGenerationError",
    "LLMInvalidConfigurationError",
    "LLMInvalidRequestError",
    "LLMInvalidResponseError",
    "LLMRateLimitedError",
    "LLMRejectedError",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "LLMUnsupportedCapabilityError",
    "ProviderCapabilities",
    "ProviderIdentity",
    "ProviderRateLimitMetadata",
    "TokenCount",
    "TokenCountingClient",
    "UsageMetadata",
    "build_generation_adapter",
]
