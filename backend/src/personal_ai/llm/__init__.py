"""Replaceable language-model clients for the chat application."""

from personal_ai.llm.client import ChatMessage, LLMClient
from personal_ai.llm.errors import (
    LLMError,
    LLMInvalidConfigurationError,
    LLMInvalidRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from personal_ai.llm.fake import FakeLLMClient
from personal_ai.llm.gemini import GeminiLLMClient

__all__ = [
    "ChatMessage",
    "FakeLLMClient",
    "GeminiLLMClient",
    "LLMClient",
    "LLMError",
    "LLMInvalidConfigurationError",
    "LLMInvalidRequestError",
    "LLMTimeoutError",
    "LLMUnavailableError",
]
