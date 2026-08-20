"""Gemini implementation of the internal streamed LLM contract."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

from personal_ai.entities.conversation import MessageRole
from personal_ai.llm.client import ChatMessage
from personal_ai.llm.errors import (
    LLMError,
    LLMInvalidConfigurationError,
    LLMInvalidRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from personal_ai.settings import Settings

_SYSTEM_INSTRUCTION = (
    "You are a helpful personal AI chat assistant. "
    "Answer directly and clearly based on this conversation."
)


class GeminiLLMClient:
    """Stream Gemini responses while containing all SDK details in ``llm``."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        """Yield Gemini text chunks, translating provider errors to safe codes.

        Cancelling this iterator cancels the timeout scope and stops consuming the
        provider's async stream, allowing the caller to persist an incomplete turn.
        """
        self._validate_request(messages)
        try:
            client = self._client or self._build_client()
            async with asyncio.timeout(self._settings.request_timeout_seconds):
                stream = await client.aio.models.generate_content_stream(
                    model=self._settings.ai_model,
                    contents=_gemini_contents(messages),
                    config={"system_instruction": _SYSTEM_INSTRUCTION},
                )
                async for chunk in stream:
                    text = _chunk_text(chunk)
                    if text:
                        yield text
        except asyncio.CancelledError:
            raise
        except LLMError:
            raise
        except Exception as error:
            raise _translate_error(error) from error

    def _validate_request(self, messages: Sequence[ChatMessage]) -> None:
        if self._settings.ai_provider.lower() != "gemini":
            raise LLMInvalidConfigurationError("AI_PROVIDER must be 'gemini'")
        if not self._settings.ai_api_key.get_secret_value():
            raise LLMInvalidConfigurationError("AI_API_KEY is not configured")
        if not messages:
            raise LLMInvalidRequestError("at least one chat message is required")
        if len(messages) > self._settings.max_phase_1_history_messages:
            raise LLMInvalidRequestError("chat history exceeds the Phase 1 limit")
        if any(not message.content.strip() for message in messages):
            raise LLMInvalidRequestError("chat messages must not be empty")

    def _build_client(self) -> Any:
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise LLMInvalidConfigurationError("google-genai SDK is not installed") from error

        # The SDK also receives a transport-level timeout; asyncio.timeout covers
        # the entire async iterator, including slow first and later chunks.
        return genai.Client(
            api_key=self._settings.ai_api_key.get_secret_value(),
            http_options=types.HttpOptions(
                timeout=int(self._settings.request_timeout_seconds * 1000)
            ),
        )


def _gemini_contents(messages: Sequence[ChatMessage]) -> list[dict[str, object]]:
    """Convert neutral messages to the Gemini SDK's request-only representation."""
    return [
        {
            "role": "model" if message.role == MessageRole.ASSISTANT else "user",
            "parts": [{"text": message.content}],
        }
        for message in messages
    ]


def _chunk_text(chunk: Any) -> str:
    """Read text defensively because non-text Gemini chunks are valid."""
    try:
        text = chunk.text
    except (AttributeError, ValueError):
        return ""
    return text if isinstance(text, str) else ""


def _translate_error(error: BaseException) -> LLMError:
    """Map SDK/network exceptions without exposing provider details to callers."""
    if isinstance(error, TimeoutError):
        return LLMTimeoutError("language model request timed out")

    status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
    name = type(error).__name__.lower()
    message = str(error).lower()
    if status_code == 400 or "invalidargument" in name or "invalid argument" in message:
        return LLMInvalidRequestError("language model rejected the request")
    if status_code in {401, 403} or "authentication" in name or "permission" in name:
        return LLMInvalidConfigurationError("language model credentials are invalid")
    return LLMUnavailableError("language model is unavailable")
