"""Gemini implementation of the internal streamed LLM contract."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import anyio

from personal_ai.entities.conversation import MessageRole
from personal_ai.llm.client import SYSTEM_INSTRUCTION, ChatMessage, InferenceContext
from personal_ai.llm.errors import (
    LLMError,
    LLMInvalidConfigurationError,
    LLMInvalidRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from personal_ai.settings import Settings


class GeminiLLMClient:
    """Stream Gemini responses while containing all SDK details in ``llm``."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        """Yield Gemini text chunks, translating provider errors to safe codes.

        Cancelling this iterator cancels the timeout scope and stops consuming the
        provider's async stream, allowing the caller to persist an incomplete turn.
        """
        bounded = self.stream_bounded(
            messages,
            max_output_tokens=self._settings.max_response_tokens,
            timeout_seconds=self._settings.request_timeout_seconds,
            inference_context=inference_context,
        )
        try:
            async for item in bounded:
                yield item
        finally:
            await _close_async_resource(bounded)

    async def stream_bounded(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        self._validate_request(messages, inference_context=inference_context)
        client = self._client
        owns_client = client is None
        try:
            if client is None:
                client = self._build_client()
            async with asyncio.timeout(timeout_seconds):
                stream = await client.aio.models.generate_content_stream(
                    model=self._settings.ai_model,
                    contents=_gemini_contents(messages),
                    config={"system_instruction": _system_instruction(messages),
                            "max_output_tokens": max_output_tokens},
                )
                provider_iterator = stream.__aiter__()
                try:
                    async for chunk in provider_iterator:
                        text = _chunk_text(chunk)
                        if text:
                            yield text
                finally:
                    await _close_async_resource(provider_iterator)
        except asyncio.CancelledError:
            raise
        except LLMError:
            raise
        except Exception as error:
            raise _translate_error(error) from error
        finally:
            if owns_client and client is not None:
                await _close_owned_client(client)

    def _validate_request(
        self,
        messages: Sequence[ChatMessage],
        *,
        inference_context: InferenceContext | None = None,
    ) -> None:
        if self._settings.ai_provider.lower() != "gemini":
            raise LLMInvalidConfigurationError("AI_PROVIDER must be 'gemini'")
        if not self._settings.ai_api_key.get_secret_value():
            raise LLMInvalidConfigurationError("AI_API_KEY is not configured")
        if not messages:
            raise LLMInvalidRequestError("at least one chat message is required")
        if any(not message.content.strip() for message in messages):
            raise LLMInvalidRequestError("chat messages must not be empty")
        if inference_context is not None:
            try:
                InferenceContext(
                    effective_sensitivity=inference_context.effective_sensitivity,
                    maximum_sensitivity=inference_context.maximum_sensitivity,
                    policy_version=inference_context.policy_version,
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise LLMInvalidRequestError("context disclosure policy denied") from error

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
        for message in messages if message.role != "system"
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
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        return LLMTimeoutError("language model request timed out")

    status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
    name = type(error).__name__.lower()
    message = str(error).lower()
    if status_code == 400 or "invalidargument" in name or "invalid argument" in message:
        return LLMInvalidRequestError("language model rejected the request")
    if status_code in {401, 403} or "authentication" in name or "permission" in name:
        return LLMInvalidConfigurationError("language model credentials are invalid")
    return LLMUnavailableError("language model is unavailable")


async def _close_async_resource(
    resource: Any,
) -> None:
    """Close an SDK async resource under a bounded cancellation shield."""
    close = getattr(resource, "aclose", None)
    if close is None:
        return
    with anyio.CancelScope(shield=True):
        with anyio.move_on_after(1):
            try:
                await close()
            # Iterator cleanup must not replace the provider result or cancellation.
            except (Exception, asyncio.CancelledError):  # noqa: BLE001
                return


async def _close_owned_client(client: Any) -> None:
    """Release resources for the client constructed for this one request."""
    aio_client = getattr(client, "aio", None)
    if aio_client is not None:
        close_async = getattr(aio_client, "aclose", None)
        if close_async is not None:
            await _close_async_resource(aio_client)

    close = getattr(client, "close", None)
    if close is not None:
        try:
            close()
        except Exception:  # noqa: BLE001 - owned-client cleanup is best effort
            return


def _system_instruction(messages: Sequence[ChatMessage]) -> str:
    return "\n\n".join([SYSTEM_INSTRUCTION, *[
        message.content for message in messages if message.role == "system"
    ]])
