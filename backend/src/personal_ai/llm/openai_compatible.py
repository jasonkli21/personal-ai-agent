"""Small OpenAI Chat Completions transport shared by reference adapters.

Provider names, endpoints, credentials, structured-output serializers, and
readiness gates are supplied only by the provider-specific adapter modules.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from time import monotonic
from typing import Any

import anyio
import httpx

from personal_ai.llm.client import (
    BoundedTextStream,
    ChatMessage,
    GenerationEvent,
    GenerationMetadata,
    GenerationResult,
    InferenceContext,
    ProviderCapabilities,
    ProviderIdentity,
    ProviderRateLimitMetadata,
    UsageMetadata,
)
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
)
from personal_ai.settings import Settings

_RESET_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
_SENSITIVITY_RANK = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3}
_MAX_COMPLETION_RESPONSE_BYTES = 1_048_576
_MAX_STREAM_RESPONSE_BYTES = 2_097_152
_MAX_SSE_EVENT_BYTES = 131_072
_MAX_SSE_LINE_BYTES = 131_072


class OpenAICompatibleGenerationClient:
    """Neutral generation behavior for the narrow chat-completions subset."""

    requires_inference_context = True

    def __init__(
        self,
        settings: Settings,
        *,
        provider_id: str,
        model_id: str,
        serializer_id: str,
        endpoint: str,
        api_key: str,
        adapter_enabled: bool,
        free_tier_verified: bool,
        privacy_approved: bool,
        privacy_max_sensitivity: str,
        approved_model_aliases: Sequence[str],
        structured_output_verified: bool,
        preflight_reference: str,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._endpoint = endpoint
        self._api_key = api_key
        self._adapter_enabled = adapter_enabled
        self._free_tier_verified = free_tier_verified
        self._privacy_approved = privacy_approved
        self._privacy_max_sensitivity = privacy_max_sensitivity
        self._approved_models = frozenset((model_id, *approved_model_aliases))
        self._structured_output_verified = structured_output_verified
        self._preflight_reference = preflight_reference
        self._client = client
        self._async_client = async_client
        self.identity = ProviderIdentity(provider_id, model_id or "unconfigured", serializer_id)
        operations = {"streaming", "bounded_generation"}
        if structured_output_verified:
            operations.add("structured_generation")
        self.capabilities = ProviderCapabilities(frozenset(operations))

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[str]:
        bounded = self.stream_bounded(
            messages,
            max_output_tokens=self._settings.max_response_tokens,
            timeout_seconds=self._settings.request_timeout_seconds,
            inference_context=inference_context,
        )

        async def consume() -> AsyncIterator[str]:
            try:
                async for delta in bounded:
                    yield delta
            finally:
                await bounded.aclose()

        return consume()

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

    async def stream_events(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        inference_context: InferenceContext | None = None,
    ) -> AsyncIterator[GenerationEvent]:
        self.capabilities.require("streaming")
        self._validate_request(messages, inference_context)
        timeout_seconds = self._bounded_timeout(max_output_tokens, timeout_seconds)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        client = self._async_client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(follow_redirects=False)
        body = self._request_body(messages, max_output_tokens, stream=True)
        finish_reason: str | None = None
        usage: UsageMetadata | None = None
        rate_limits: ProviderRateLimitMetadata | None = None
        done_seen = False
        try:
            async with client.stream(
                "POST",
                self._endpoint,
                headers=self._headers(stream=True),
                json=body,
                timeout=timeout_seconds,
            ) as response:
                rate_limits = _rate_limit_metadata(response.headers)
                _raise_for_status(response.status_code, rate_limits)
                _validate_wire_response(response.headers, _MAX_STREAM_RESPONSE_BYTES)
                response_model_id: str | None = None
                has_non_whitespace_text = False
                async for data in _sse_data(
                    response, deadline, max_body_bytes=_MAX_STREAM_RESPONSE_BYTES
                ):
                    if done_seen:
                        raise LLMInvalidResponseError(
                            "language model emitted data after stream completion"
                        )
                    if data == "[DONE]":
                        done_seen = True
                        continue
                    payload = _decode_json_object(data)
                    chunk_model_id = _response_model_id(payload, required=False)
                    if chunk_model_id is not None:
                        self._validate_response_model(chunk_model_id)
                        if response_model_id is not None and response_model_id != chunk_model_id:
                            raise LLMInvalidResponseError(
                                "language model emitted conflicting model identities"
                            )
                        response_model_id = chunk_model_id
                    chunk_reason, chunk_usage, deltas = _read_stream_payload(payload)
                    if chunk_reason is not None:
                        if finish_reason is not None and finish_reason != chunk_reason:
                            raise LLMInvalidResponseError(
                                "language model emitted conflicting terminal metadata"
                            )
                        finish_reason = chunk_reason
                    usage = chunk_usage or usage
                    for delta in deltas:
                        has_non_whitespace_text = has_non_whitespace_text or bool(delta.strip())
                        yield GenerationEvent.text_delta(delta)
            if response_model_id is None:
                raise LLMInvalidResponseError("language model response omitted its model identity")
            status = _terminal_status(finish_reason) if done_seen else "incomplete"
            if status == "success" and not has_non_whitespace_text:
                status = "incomplete"
            yield GenerationEvent.terminal(GenerationMetadata(
                status=status,
                identity=ProviderIdentity(
                    self.identity.provider_id, response_model_id, self.identity.serializer_id
                ),
                usage=usage,
                error_code=_terminal_error_code(status),
                rate_limits=rate_limits,
            ))
        except asyncio.CancelledError:
            raise
        except LLMError:
            raise
        except (TimeoutError, httpx.TimeoutException) as error:
            raise LLMTimeoutError("language model request timed out") from error
        except httpx.HTTPError as error:
            raise LLMUnavailableError("language model is unavailable") from error
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise LLMInvalidResponseError("language model response was invalid") from error
        finally:
            if owns_client:
                await _close_async_client(client)

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
            response_schema=None,
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
        try:
            json.dumps(response_schema, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise LLMInvalidRequestError("structured response schema is invalid") from error
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
        response_schema: Mapping[str, object] | None,
    ) -> GenerationResult:
        self.capabilities.require("bounded_generation")
        self._validate_request(messages, inference_context)
        timeout_seconds = self._bounded_timeout(max_output_tokens, timeout_seconds)
        body = self._request_body(
            messages, max_output_tokens, stream=False, response_schema=response_schema
        )
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.Client(follow_redirects=False)
        deadline = monotonic() + timeout_seconds
        try:
            with client.stream(
                "POST",
                self._endpoint,
                headers=self._headers(stream=False),
                json=body,
                timeout=timeout_seconds,
            ) as response:
                rate_limits = _rate_limit_metadata(response.headers)
                _raise_for_status(response.status_code, rate_limits)
                response_body = _read_limited_response_body(
                    response, _MAX_COMPLETION_RESPONSE_BYTES
                )
            payload = json.loads(response_body)
            text, finish_reason, usage = _read_completion_payload(payload)
            response_model_id = _response_model_id(payload, required=True)
            self._validate_response_model(response_model_id)
            if monotonic() > deadline:
                raise LLMTimeoutError("language model request timed out")
            status = _terminal_status(finish_reason)
            if _has_refusal(payload):
                status = "rejected"
            elif status == "success" and not text.strip():
                status = "incomplete"
            return GenerationResult(
                text=text,
                metadata=GenerationMetadata(
                    status=status,
                    identity=ProviderIdentity(
                        self.identity.provider_id,
                        response_model_id,
                        self.identity.serializer_id,
                    ),
                    usage=usage,
                    error_code=_terminal_error_code(status),
                    rate_limits=rate_limits,
                ),
            )
        except LLMError:
            raise
        except httpx.TimeoutException as error:
            raise LLMTimeoutError("language model request timed out") from error
        except httpx.HTTPError as error:
            raise LLMUnavailableError("language model is unavailable") from error
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise LLMInvalidResponseError("language model response was invalid") from error
        finally:
            if owns_client:
                client.close()

    def _validate_request(
        self,
        messages: Sequence[ChatMessage],
        inference_context: InferenceContext | None,
    ) -> None:
        if not self._adapter_enabled:
            raise LLMInvalidConfigurationError("provider adapter is disabled")
        if not self._free_tier_verified or not self._privacy_approved:
            raise LLMInvalidConfigurationError("provider preflight is incomplete")
        if not self._preflight_reference.strip():
            raise LLMInvalidConfigurationError("provider preflight reference is required")
        if not self._api_key:
            raise LLMInvalidConfigurationError("provider credentials are not configured")
        if self._settings.external_providers_kill_switch_enabled:
            raise LLMUnavailableError("external provider calls are disabled")
        if not messages or any(not isinstance(message, ChatMessage) for message in messages):
            raise LLMInvalidRequestError("at least one valid chat message is required")
        if any(
            message.role not in {"system", "user", "assistant"}
            or not isinstance(message.content, str)
            or not message.content.strip()
            for message in messages
        ):
            raise LLMInvalidRequestError("chat messages must not be empty")
        if inference_context is None:
            raise LLMInvalidRequestError("context disclosure policy is required")
        try:
            validated_context = InferenceContext(
                effective_sensitivity=inference_context.effective_sensitivity,
                maximum_sensitivity=inference_context.maximum_sensitivity,
                policy_version=inference_context.policy_version,
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise LLMInvalidRequestError("context disclosure policy denied") from error
        effective_rank = _SENSITIVITY_RANK.get(validated_context.effective_sensitivity, 4)
        approved_rank = _SENSITIVITY_RANK.get(self._privacy_max_sensitivity, -1)
        if effective_rank > approved_rank:
            raise LLMInvalidRequestError("provider privacy preflight does not allow this sensitivity")

    def _validate_response_model(self, response_model_id: str) -> None:
        if response_model_id not in self._approved_models:
            raise LLMInvalidResponseError("language model returned an unapproved model identity")

    def _bounded_timeout(self, max_output_tokens: int, timeout_seconds: float) -> float:
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise LLMInvalidRequestError("generation bounds are invalid")
        return min(timeout_seconds, self._settings.request_timeout_seconds)

    def _headers(self, *, stream: bool) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "Accept-Encoding": "identity",
        }

    def _request_body(
        self,
        messages: Sequence[ChatMessage],
        max_output_tokens: int,
        *,
        stream: bool,
        response_schema: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self.identity.model_id,
            "messages": [
                {"role": message.role.value if hasattr(message.role, "value") else message.role,
                 "content": message.content}
                for message in messages
            ],
            self._max_output_field(): max_output_tokens,
            "stream": stream,
        }
        if response_schema is not None:
            body["response_format"] = self._structured_format(response_schema)
        return body

    def _max_output_field(self) -> str:
        raise NotImplementedError

    def _structured_format(self, schema: Mapping[str, object]) -> Mapping[str, object]:
        raise NotImplementedError


async def _sse_data(
    response: httpx.Response,
    deadline: float,
    *,
    max_body_bytes: int,
) -> AsyncIterator[str]:
    """Read bounded SSE events while enforcing one wall-clock deadline."""
    data_lines: list[str] = []
    event_bytes = 0
    loop = asyncio.get_running_loop()
    lines = _bounded_sse_lines(response, deadline, max_body_bytes).__aiter__()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise LLMTimeoutError("language model request timed out")
        try:
            async with asyncio.timeout(remaining):
                line = await anext(lines)
        except StopAsyncIteration:
            break
        event_bytes += len(line.encode("utf-8")) + 1
        if event_bytes > _MAX_SSE_EVENT_BYTES:
            raise LLMInvalidResponseError("language model stream event exceeded the size limit")
        if line == "":
            if data_lines:
                yield "\n".join(data_lines).strip()
                data_lines.clear()
            event_bytes = 0
        elif line.startswith(":"):
            continue
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield "\n".join(data_lines).strip()


async def _bounded_sse_lines(
    response: httpx.Response,
    deadline: float,
    max_body_bytes: int,
) -> AsyncIterator[str]:
    """Yield UTF-8 SSE lines without buffering an oversized line or body."""
    if response.is_stream_consumed:
        buffered_body = response.content
        if len(buffered_body) > max_body_bytes:
            raise LLMInvalidResponseError("language model stream exceeded the size limit")
        chunks = _single_async_chunk(buffered_body).__aiter__()
    else:
        chunks = response.aiter_raw().__aiter__()
    pending = bytearray()
    total_bytes = 0
    loop = asyncio.get_running_loop()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise LLMTimeoutError("language model request timed out")
        try:
            async with asyncio.timeout(remaining):
                chunk = await anext(chunks)
        except StopAsyncIteration:
            break
        total_bytes += len(chunk)
        if total_bytes > max_body_bytes:
            raise LLMInvalidResponseError("language model stream exceeded the size limit")
        start = 0
        while start < len(chunk):
            newline = chunk.find(b"\n", start)
            if newline < 0:
                part = chunk[start:]
                if len(pending) + len(part) > _MAX_SSE_LINE_BYTES:
                    raise LLMInvalidResponseError("language model stream line exceeded the size limit")
                pending.extend(part)
                break
            part = chunk[start:newline]
            if len(pending) + len(part) > _MAX_SSE_LINE_BYTES:
                raise LLMInvalidResponseError("language model stream line exceeded the size limit")
            pending.extend(part)
            line = bytes(pending)
            pending.clear()
            if line.endswith(b"\r"):
                line = line[:-1]
            try:
                yield line.decode("utf-8")
            except UnicodeDecodeError as error:
                raise LLMInvalidResponseError("language model stream encoding was invalid") from error
            start = newline + 1
    if pending:
        line = bytes(pending)
        if line.endswith(b"\r"):
            line = line[:-1]
        try:
            yield line.decode("utf-8")
        except UnicodeDecodeError as error:
            raise LLMInvalidResponseError("language model stream encoding was invalid") from error


def _validate_wire_response(headers: Mapping[str, str], max_bytes: int) -> None:
    encoding = headers.get("content-encoding", "identity").strip().lower()
    if encoding not in {"", "identity"}:
        raise LLMInvalidResponseError("language model response encoding was unsupported")
    content_length = headers.get("content-length")
    if content_length is not None:
        normalized = content_length.strip()
        if not normalized.isdecimal():
            raise LLMInvalidResponseError("language model response length was invalid")
        if int(normalized) > max_bytes:
            raise LLMInvalidResponseError("language model response exceeded the size limit")


def _read_limited_response_body(response: httpx.Response, max_bytes: int) -> bytes:
    """Read an identity-encoded completion only up to its wire-byte limit."""
    _validate_wire_response(response.headers, max_bytes)
    if response.is_stream_consumed:
        body = response.content
        if len(body) > max_bytes:
            raise LLMInvalidResponseError("language model response exceeded the size limit")
        return body
    body = bytearray()
    for chunk in response.iter_raw():
        if len(body) + len(chunk) > max_bytes:
            raise LLMInvalidResponseError("language model response exceeded the size limit")
        body.extend(chunk)
    return bytes(body)


async def _single_async_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _decode_json_object(value: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError) as error:
        raise LLMInvalidResponseError("language model emitted malformed stream data") from error
    if not isinstance(payload, Mapping):
        raise LLMInvalidResponseError("language model emitted an invalid stream event")
    if payload.get("error") is not None:
        raise LLMUnavailableError("language model stream failed")
    return payload


def _read_stream_payload(
    payload: Mapping[str, Any],
) -> tuple[str | None, UsageMetadata | None, tuple[str, ...]]:
    choices = payload.get("choices", [])
    if not isinstance(choices, list):
        raise LLMInvalidResponseError("language model stream event was invalid")
    reason: str | None = None
    deltas: list[str] = []
    for choice in choices:
        if not isinstance(choice, Mapping):
            raise LLMInvalidResponseError("language model stream choice was invalid")
        raw_reason = choice.get("finish_reason")
        if raw_reason is not None:
            if not isinstance(raw_reason, str) or not raw_reason:
                raise LLMInvalidResponseError("language model terminal metadata was invalid")
            reason = raw_reason
        delta = choice.get("delta", {})
        if delta is None:
            continue
        if not isinstance(delta, Mapping):
            raise LLMInvalidResponseError("language model stream delta was invalid")
        if delta.get("refusal"):
            reason = "content_filter"
        content = delta.get("content")
        if content is not None:
            if not isinstance(content, str):
                raise LLMInvalidResponseError("language model stream text was invalid")
            if content:
                deltas.append(content)
    usage = _usage(payload.get("usage"))
    return reason, usage, tuple(deltas)


def _read_completion_payload(
    payload: Any,
) -> tuple[str, str | None, UsageMetadata | None]:
    if not isinstance(payload, Mapping):
        raise LLMInvalidResponseError("language model response was invalid")
    if payload.get("error") is not None:
        raise LLMUnavailableError("language model request failed")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise LLMInvalidResponseError("language model response had no completion choice")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise LLMInvalidResponseError("language model completion message was invalid")
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise LLMInvalidResponseError("language model completion text was invalid")
    reason = choice.get("finish_reason")
    if reason is not None and not isinstance(reason, str):
        raise LLMInvalidResponseError("language model terminal metadata was invalid")
    return content, reason, _usage(payload.get("usage"))


def _has_refusal(payload: Mapping[str, Any]) -> bool:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if isinstance(choice, Mapping):
            message = choice.get("message")
            if isinstance(message, Mapping) and message.get("refusal"):
                return True
    return False


def _usage(raw: Any) -> UsageMetadata | None:
    if not isinstance(raw, Mapping):
        return None
    input_tokens = _non_negative_int(raw.get("prompt_tokens", raw.get("input_tokens")))
    output_tokens = _non_negative_int(raw.get("completion_tokens", raw.get("output_tokens")))
    total_tokens = _non_negative_int(raw.get("total_tokens"))
    if input_tokens is output_tokens is total_tokens is None:
        return None
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        source="provider",
        confidence="reported",
    )


def _terminal_status(reason: str | None) -> str:
    if reason is None:
        return "incomplete"
    normalized = reason.strip().lower()
    if normalized in {"stop", "end_turn", "completed"}:
        return "success"
    if normalized in {"length", "max_tokens", "token_limit"}:
        return "incomplete"
    if normalized in {"content_filter", "safety", "tool_calls", "function_call"}:
        return "rejected"
    return "incomplete"


def _terminal_error_code(status: str) -> str | None:
    if status == "incomplete":
        return LLMIncompleteGenerationError.code
    if status == "rejected":
        return LLMRejectedError.code
    if status == "failure":
        return LLMUnavailableError.code
    return None


def _response_model_id(payload: Mapping[str, Any], *, required: bool) -> str | None:
    model_id = payload.get("model")
    if model_id is None and not required:
        return None
    if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 200:
        raise LLMInvalidResponseError("language model response model identity was invalid")
    return model_id


def _raise_for_status(
    status_code: int,
    rate_limits: ProviderRateLimitMetadata | None,
) -> None:
    if status_code < 400:
        return
    if status_code == 429:
        raise LLMRateLimitedError(rate_limits=rate_limits)
    if status_code in {401, 403}:
        raise LLMInvalidConfigurationError("provider credentials or model access are invalid")
    if status_code in {408, 504}:
        raise LLMTimeoutError("language model request timed out")
    if status_code in {400, 404, 413, 422}:
        raise LLMInvalidRequestError("language model rejected the request")
    if status_code >= 500:
        raise LLMUnavailableError("language model is unavailable")
    raise LLMUnavailableError("language model is unavailable")


def _rate_limit_metadata(headers: Mapping[str, str]) -> ProviderRateLimitMetadata | None:
    values = {
        "requests_limit": _non_negative_int(headers.get("x-ratelimit-limit-requests")),
        "requests_remaining": _non_negative_int(headers.get("x-ratelimit-remaining-requests")),
        "requests_reset_seconds": _duration(headers.get("x-ratelimit-reset-requests")),
        "tokens_limit": _non_negative_int(headers.get("x-ratelimit-limit-tokens")),
        "tokens_remaining": _non_negative_int(headers.get("x-ratelimit-remaining-tokens")),
        "tokens_reset_seconds": _duration(headers.get("x-ratelimit-reset-tokens")),
        "retry_after_seconds": _duration(headers.get("retry-after")),
    }
    if not any(value is not None for value in values.values()):
        return None
    return ProviderRateLimitMetadata(**values)


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _duration(value: str | None) -> float | None:
    if not value:
        return None
    try:
        numeric = float(value)
    except ValueError:
        numeric = None
    if numeric is not None:
        return numeric if numeric >= 0 else None
    parts = tuple(_RESET_PART.finditer(value.strip().lower()))
    if not parts or "".join(part.group(0) for part in parts) != value.strip().lower():
        return None
    factors = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return sum(float(part.group(1)) * factors[part.group(2)] for part in parts)


async def _close_async_client(client: httpx.AsyncClient) -> None:
    with anyio.CancelScope(shield=True):
        with anyio.move_on_after(1):
            try:
                await client.aclose()
            except (Exception, asyncio.CancelledError):  # noqa: BLE001
                return
