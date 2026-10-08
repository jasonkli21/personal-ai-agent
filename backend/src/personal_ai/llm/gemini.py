"""Gemini adapter for the provider-neutral generation contracts."""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import anyio

from personal_ai.entities.conversation import MessageRole
from personal_ai.llm.client import (
    SYSTEM_INSTRUCTION,
    ChatMessage,
    GenerationEvent,
    GenerationMetadata,
    GenerationResult,
    InferenceContext,
    ProviderCapabilities,
    ProviderIdentity,
    UsageMetadata,
)
from personal_ai.llm.errors import (
    LLMError,
    LLMIncompleteGenerationError,
    LLMInvalidConfigurationError,
    LLMInvalidRequestError,
    LLMInvalidResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from personal_ai.settings import Settings


class GeminiLLMClient:
    """Gemini implementation of neutral streamed and bounded generation."""

    requires_inference_context = True

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client
        self.identity = ProviderIdentity("gemini", settings.ai_model, "gemini-content-v1")
        self.capabilities = ProviderCapabilities(frozenset({
            "streaming", "bounded_generation", "structured_generation"
        }))

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        """Compatibility text stream that requires explicit terminal success."""
        async for delta in self.stream_bounded(
            messages,
            max_output_tokens=self._settings.max_response_tokens,
            timeout_seconds=self._settings.request_timeout_seconds,
            inference_context=inference_context,
        ):
            yield delta

    async def stream_bounded(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        terminal: GenerationMetadata | None = None
        async for event in self.stream_events(
            messages,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            inference_context=inference_context,
        ):
            if event.kind == "delta":
                yield event.delta
            else:
                terminal = event.metadata
        if terminal is None:
            raise LLMIncompleteGenerationError("language model ended without a terminal result")
        GenerationResult("", terminal).require_success()

    async def stream_events(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[GenerationEvent]:
        self.capabilities.require("streaming")
        self._validate_request(
            messages,
            inference_context=inference_context,
            require_inference_context=True,
        )
        if max_output_tokens < 1 or timeout_seconds <= 0:
            raise LLMInvalidRequestError("generation bounds are invalid")
        # The service deadline is a stricter per-request bound; provider settings
        # still cap the total attempt when callers pass a longer remaining time.
        timeout_seconds = min(timeout_seconds, self._settings.request_timeout_seconds)
        client = self._client
        owns_client = client is None
        last_chunk: Any | None = None
        finish_reason: Any | None = None
        had_text = False
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        try:
            if client is None:
                client = self._build_client()
            async with asyncio.timeout(_remaining_timeout(deadline)):
                stream = await client.aio.models.generate_content_stream(
                    model=self._settings.ai_model,
                    contents=_gemini_contents(messages),
                    config={
                        "system_instruction": _system_instruction(messages),
                        "max_output_tokens": max_output_tokens,
                        "http_options": _http_options(timeout_seconds),
                    },
                )
            provider_iterator = stream.__aiter__()
            try:
                while True:
                    try:
                        # Keep each read inside the timeout scope. The generator
                        # yields deltas to its consumer between reads, so a single
                        # timeout context around the whole loop would cancel the
                        # producer task while the generator is suspended at yield.
                        async with asyncio.timeout(_remaining_timeout(deadline)):
                            chunk = await anext(provider_iterator)
                    except StopAsyncIteration:
                        break
                    last_chunk = chunk
                    finish_reason = _finish_reason(chunk) or finish_reason
                    text = _chunk_text(chunk)
                    if text:
                        had_text = True
                        yield GenerationEvent.text_delta(text)
            finally:
                await _close_async_resource(provider_iterator)
            status = _terminal_status(finish_reason, had_text)
            yield GenerationEvent.terminal(
                GenerationMetadata(
                    status=status,
                    identity=self._identity_for(last_chunk),
                    usage=_usage(last_chunk),
                    error_code=_terminal_error_code(status),
                )
            )
        except asyncio.CancelledError:
            raise
        except LLMError:
            raise
        except Exception as error:
            raise _translate_error(error) from error
        finally:
            if owns_client and client is not None:
                await _close_owned_client(client)

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> GenerationResult:
        return self._generate(
            messages,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            inference_context=inference_context,
        )

    def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        *,
        response_schema: Mapping[str, object],
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> GenerationResult:
        self.capabilities.require("structured_generation")
        if not isinstance(response_schema, Mapping) or not response_schema:
            raise LLMInvalidRequestError("structured response schema is required")
        return self._generate(
            messages,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            inference_context=inference_context,
            response_schema=response_schema,
        )

    def _generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None,
        response_schema: Mapping[str, object] | None = None,
    ) -> GenerationResult:
        self.capabilities.require("bounded_generation")
        self._validate_request(
            messages,
            inference_context=inference_context,
            require_inference_context=True,
        )
        if max_output_tokens < 1 or timeout_seconds <= 0:
            raise LLMInvalidRequestError("generation bounds are invalid")
        client = self._client
        owns_client = client is None
        try:
            if client is None:
                client = self._build_client()
            config: dict[str, object] = {
                "system_instruction": _system_instruction(messages),
                "max_output_tokens": max_output_tokens,
                "http_options": _http_options(timeout_seconds),
            }
            if response_schema is not None:
                config["response_mime_type"] = "application/json"
                config["response_schema"] = dict(response_schema)
            response = client.models.generate_content(
                model=self._settings.ai_model,
                contents=_gemini_contents(messages),
                config=config,
            )
            text = _response_text(response)
            status = _terminal_status(_finish_reason(response), bool(text.strip()))
            return GenerationResult(
                text=text,
                metadata=GenerationMetadata(
                    status=status,
                    identity=self._identity_for(response),
                    usage=_usage(response),
                    error_code=_terminal_error_code(status),
                ),
            )
        except LLMError:
            raise
        except Exception as error:
            raise _translate_error(error) from error
        finally:
            if owns_client and client is not None:
                _close_owned_client_sync(client)

    def _validate_request(
        self,
        messages: Sequence[ChatMessage],
        *,
        inference_context: InferenceContext | None = None,
        require_inference_context: bool = False,
    ) -> None:
        if self._settings.ai_provider.lower() != "gemini":
            raise LLMInvalidConfigurationError("AI_PROVIDER must be 'gemini'")
        if self._client is None and not self._settings.ai_api_key.get_secret_value():
            raise LLMInvalidConfigurationError("AI_API_KEY is not configured")
        if not messages:
            raise LLMInvalidRequestError("at least one chat message is required")
        if any(not message.content.strip() for message in messages):
            raise LLMInvalidRequestError("chat messages must not be empty")
        self._validate_inference_context(
            inference_context, required=require_inference_context
        )

    @staticmethod
    def _validate_inference_context(
        inference_context: InferenceContext | None, *, required: bool
    ) -> None:
        if required and inference_context is None:
            raise LLMInvalidRequestError("context disclosure policy is required")
        if inference_context is not None:
            try:
                InferenceContext(
                    effective_sensitivity=inference_context.effective_sensitivity,
                    maximum_sensitivity=inference_context.maximum_sensitivity,
                    policy_version=inference_context.policy_version,
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise LLMInvalidRequestError("context disclosure policy denied") from error

    def _identity_for(self, response: Any | None) -> ProviderIdentity:
        model = getattr(response, "model_version", None) or getattr(response, "model", None)
        if not isinstance(model, str) or not model or len(model) > 200:
            return self.identity
        return ProviderIdentity("gemini", model, "gemini-content-v1")

    def _build_client(self) -> Any:
        try:
            from google import genai
            from google.genai import types
        except ImportError as error:
            raise LLMInvalidConfigurationError("google-genai SDK is not installed") from error

        return genai.Client(
            api_key=self._settings.ai_api_key.get_secret_value(),
            http_options=types.HttpOptions(
                timeout=int(self._settings.request_timeout_seconds * 1000)
            ),
        )


def _http_options(timeout_seconds: float) -> dict[str, object]:
    return {
        "timeout": max(1, int(timeout_seconds * 1000)),
        "retry_options": {"attempts": 1},
    }


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError("generation deadline expired")
    return remaining


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
    try:
        text = chunk.text
    except (AttributeError, ValueError):
        return ""
    return text if isinstance(text, str) else ""


def _response_text(response: Any) -> str:
    try:
        text = response.text
    except (AttributeError, ValueError):
        return ""
    return text if isinstance(text, str) else ""


def _finish_reason(response: Any) -> str | None:
    try:
        candidates = response.candidates
    except (AttributeError, ValueError):
        candidates = None
    if not candidates:
        return None
    candidate = candidates[0]
    try:
        reason = candidate.finish_reason
    except (AttributeError, ValueError):
        return None
    if reason is None:
        return None
    name = getattr(reason, "name", None)
    normalized = str(name if name is not None else reason).upper().split(".")[-1]
    return normalized if normalized not in {"", "NONE", "0"} else None


def _terminal_status(reason: str | None, has_text: bool):
    if reason is None:
        return "success" if has_text else "incomplete"
    if reason in {"STOP", "FINISH_REASON_STOP"}:
        return "success"
    if reason in {"MAX_TOKENS", "FINISH_REASON_MAX_TOKENS"}:
        return "incomplete"
    return "rejected"


def _terminal_error_code(status: str) -> str | None:
    if status == "incomplete":
        return "llm_incomplete"
    if status == "rejected":
        return "llm_rejected"
    return None


def _usage(response: Any | None) -> UsageMetadata | None:
    if response is None:
        return None
    try:
        raw = response.usage_metadata
    except (AttributeError, ValueError):
        raw = None
    if raw is None:
        return None

    def read(name: str) -> int | None:
        try:
            value = getattr(raw, name)
        except (AttributeError, ValueError):
            return None
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    input_tokens = read("prompt_token_count")
    output_tokens = read("candidates_token_count")
    total_tokens = read("total_token_count")
    if input_tokens is output_tokens is total_tokens is None:
        return None
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        source="provider",
        confidence="reported",
    )


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
    if isinstance(error, (ValueError, TypeError, AttributeError, KeyError)):
        return LLMInvalidResponseError("language model response was invalid")
    return LLMUnavailableError("language model is unavailable")


async def _close_async_resource(resource: Any) -> None:
    """Close an SDK async resource under a bounded cancellation shield."""
    close = getattr(resource, "aclose", None)
    if close is None:
        return
    with anyio.CancelScope(shield=True):
        with anyio.move_on_after(1):
            try:
                await close()
            except Exception:  # noqa: BLE001 - cleanup must not replace provider outcomes
                return


async def _close_owned_client(client: Any) -> None:
    aio_client = getattr(client, "aio", None)
    if aio_client is not None:
        close_async = getattr(aio_client, "aclose", None)
        if close_async is not None:
            await _close_async_resource(aio_client)
    _close_owned_client_sync(client)


def _close_owned_client_sync(client: Any) -> None:
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
