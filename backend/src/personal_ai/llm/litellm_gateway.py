"""Personal AI's provider-neutral adapter over the pinned LiteLLM SDK.

LiteLLM is deliberately lazy-loaded here so its SDK types, callbacks, settings,
and request serialization remain below the Personal AI inference boundary.
"""

from __future__ import annotations

import asyncio
import contextvars
import importlib
import importlib.metadata
import json
import logging
import math
import os
import re
import threading
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import anyio
import httpx

from personal_ai.llm.client import (
    SYSTEM_INSTRUCTION,
    BoundedTextStream,
    ChatMessage,
    EmbeddingResult,
    EmbeddingSpace,
    GenerationEvent,
    GenerationMetadata,
    GenerationResult,
    InferenceContext,
    ProviderCapabilities,
    ProviderIdentity,
    ProviderRateLimitMetadata,
    TokenCount,
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
    LLMUnsupportedCapabilityError,
)
from personal_ai.settings import Settings

logger = logging.getLogger(__name__)

LITELLM_VERSION = "1.102.1"
_MAX_COMPLETION_RESPONSE_BYTES = 1_048_576
_MAX_STREAM_RESPONSE_BYTES = 2_097_152
_MAX_STREAM_LINE_BYTES = 131_072
_MAX_STREAM_EVENT_BYTES = 131_072
_MAX_COUNT_RESPONSE_BYTES = 65_536
_MAX_EMBEDDING_RESPONSE_BYTES = 4_194_304
_MAX_REQUEST_BYTES = 2_097_152
_RESET_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
_SENSITIVITY_RANK = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3}
_SDK_LOCK = threading.RLock()
_SDK: Any | None = None
_CF_HOOK_INSTALLED = False
_CF_HOOKS: tuple[Callable[..., Any], Callable[..., Any]] | None = None


@dataclass(frozen=True, slots=True)
class _ProviderProfile:
    provider: Literal["gemini", "groq", "cloudflare_workers_ai"]
    sdk_provider: Literal["gemini", "groq", "cloudflare"]
    provider_id: str
    model_id: str
    serializer_id: str
    api_base: str
    api_key: str
    approved_models: frozenset[str]
    structured_enabled: bool
    max_tokens_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"

    @property
    def sdk_model(self) -> str:
        return f"{self.sdk_provider}/{self.model_id}"


@dataclass(slots=True)
class _TransportState:
    profile: _ProviderProfile
    operation: Literal["generation", "token_counting", "embeddings"]
    streaming: bool
    max_response_bytes: int
    response_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    raw_body: bytearray = field(default_factory=bytearray)
    request_count: int = 0
    response_complete: bool = False
    violation: Literal[
        "endpoint", "request_size", "response_size", "response_encoding", "required_parameter",
        "generation_replay",
    ] | None = None
    line_bytes: int = 0
    event_bytes: int = 0
    line_ends_with_cr: bool = False
    request_model_id: str | None = None
    sdk_usage_supplemented: bool = False
    required_schema: Mapping[str, object] | None = None
    deadline: float | None = None
    embedding_texts: tuple[str, ...] | None = None
    sse_line_buffer: bytearray = field(default_factory=bytearray)
    sse_data_lines: list[bytes] = field(default_factory=list)
    sse_model_id: str | None = None
    sse_finish_reason: str | None = None
    sse_done: bool = False
    async_stream: Any | None = None
    stream_error: LLMError | None = None

    def record_request(self, request: httpx.Request) -> None:
        if not _request_is_approved(
            request, self.profile, self.operation, self.streaming, self.request_model_id
        ):
            self.violation = "endpoint"
            raise _TransportFault("endpoint")
        if self.operation == "generation" and self.request_count:
            self.violation = "generation_replay"
            raise _TransportFault("generation_replay")
        if self.operation == "embeddings":
            self._reset_response_evidence()
            self._rewrite_embedding_request(request)
        self._apply_deadline_to_request(request)
        content_length = _parse_non_negative_int(request.headers.get("content-length"))
        if content_length is not None and content_length > _MAX_REQUEST_BYTES:
            self.violation = "request_size"
            raise _TransportFault("request_size")
        if self.required_schema is not None:
            try:
                request_body = json.loads(request.content)
            except (UnicodeDecodeError, json.JSONDecodeError, httpx.RequestNotRead):
                self.violation = "required_parameter"
                raise _TransportFault("required_parameter") from None
            if not _request_preserves_schema(request_body, self.profile, self.required_schema):
                self.violation = "required_parameter"
                raise _TransportFault("required_parameter")
        self.request_count += 1

    def _reset_response_evidence(self) -> None:
        self.response_status = None
        self.response_headers.clear()
        self.raw_body.clear()
        self.response_complete = False
        self.violation = None
        self.line_bytes = 0
        self.event_bytes = 0
        self.line_ends_with_cr = False
        self.sse_line_buffer.clear()
        self.sse_data_lines.clear()
        self.sse_model_id = None
        self.sse_finish_reason = None
        self.sse_done = False

    def _rewrite_embedding_request(self, request: httpx.Request) -> None:
        texts = self.embedding_texts
        if texts is None:
            self.violation = "required_parameter"
            raise _TransportFault("required_parameter")
        try:
            payload = json.loads(request.content)
            items = payload["requests"]
            if not isinstance(items, list) or len(items) != len(texts):
                raise ValueError
            for item, text in zip(items, texts, strict=True):
                content = item.get("content")
                if not isinstance(content, dict):
                    raise TypeError
                content["parts"] = [{"text": text}]
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.violation = "required_parameter"
            raise _TransportFault("required_parameter") from None
        request.headers["content-length"] = str(len(body))
        request._content = body
        request.stream = httpx.ByteStream(body)

    def _apply_deadline_to_request(self, request: httpx.Request) -> None:
        if self.deadline is None:
            return
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("request deadline expired")
        request.extensions["timeout"] = httpx.Timeout(remaining).as_dict()

    def record_response(self, response: httpx.Response) -> None:
        self.response_status = response.status_code
        self.response_headers = _safe_rate_headers(response.headers)

    def record_chunk(self, chunk: bytes) -> None:
        if len(self.raw_body) + len(chunk) > self.max_response_bytes:
            self.violation = "response_size"
            raise _TransportFault("response_size")
        if self.streaming:
            self._record_sse_bounds(chunk)
            try:
                self._validate_sse_chunk(chunk)
            except LLMError as error:
                self.stream_error = error
                raise
        self.raw_body.extend(chunk)

    def _record_sse_bounds(self, chunk: bytes) -> None:
        for byte in chunk:
            self.event_bytes += 1
            if self.event_bytes > _MAX_STREAM_EVENT_BYTES:
                self.violation = "response_size"
                raise _TransportFault("response_size")
            if byte == 0x0A:
                current_line_bytes = self.line_bytes - int(self.line_ends_with_cr)
                if current_line_bytes > _MAX_STREAM_LINE_BYTES:
                    self.violation = "response_size"
                    raise _TransportFault("response_size")
                blank_line = current_line_bytes == 0
                self.line_bytes = 0
                self.line_ends_with_cr = False
                if blank_line:
                    self.event_bytes = 0
            else:
                self.line_bytes += 1
                self.line_ends_with_cr = byte == 0x0D
                if self.line_bytes > _MAX_STREAM_LINE_BYTES + 1:
                    self.violation = "response_size"
                    raise _TransportFault("response_size")

    def finish_response(self) -> None:
        if self.streaming and self.line_bytes - int(self.line_ends_with_cr) > _MAX_STREAM_LINE_BYTES:
            self.violation = "response_size"
            raise _TransportFault("response_size")
        if self.streaming:
            try:
                if self.sse_line_buffer:
                    self._consume_sse_line(bytes(self.sse_line_buffer).removesuffix(b"\r"))
                    self.sse_line_buffer.clear()
                self._consume_sse_event()
            except LLMError as error:
                self.stream_error = error
                raise

    def _validate_sse_chunk(self, chunk: bytes) -> None:
        for byte in chunk:
            if byte == 0x0A:
                line = bytes(self.sse_line_buffer).removesuffix(b"\r")
                self.sse_line_buffer.clear()
                self._consume_sse_line(line)
            else:
                self.sse_line_buffer.append(byte)

    def _consume_sse_line(self, line: bytes) -> None:
        if not line:
            self._consume_sse_event()
        elif line.startswith(b"data:"):
            self.sse_data_lines.append(line[5:].lstrip(b" "))

    def _consume_sse_event(self) -> None:
        if not self.sse_data_lines:
            return
        raw_data = b"\n".join(self.sse_data_lines)
        self.sse_data_lines.clear()
        try:
            data = raw_data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise LLMInvalidResponseError("language model stream was invalid") from None
        if data.strip() == "[DONE]":
            if self.sse_done:
                raise LLMInvalidResponseError("language model emitted duplicate terminal markers")
            self.sse_done = True
            return
        if self.sse_done:
            raise LLMInvalidResponseError("language model emitted data after stream completion")
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            raise LLMInvalidResponseError("language model emitted malformed stream data") from None
        if not isinstance(payload, Mapping):
            raise LLMInvalidResponseError("language model emitted an invalid stream event")
        if payload.get("error") is not None:
            raise LLMUnavailableError("language model stream failed")
        raw_model = (
            payload.get("modelVersion", payload.get("model_version", payload.get("model")))
            if self.profile.provider == "gemini"
            else payload.get("model")
        )
        if raw_model is not None:
            self.sse_model_id = _merge_model_identity(
                self.profile, self.sse_model_id, raw_model
            )
        has_text = _sse_payload_has_text(payload, self.profile.provider)
        if has_text and self.sse_model_id is None:
            raise LLMInvalidResponseError("language model response omitted its model identity")
        if has_text and self.sse_finish_reason is not None:
            raise LLMInvalidResponseError("language model emitted text after terminal metadata")
        reason = _sse_finish_reason(payload, self.profile.provider)
        if reason is not None:
            if self.sse_finish_reason is not None and self.sse_finish_reason != reason:
                raise LLMInvalidResponseError("language model emitted conflicting terminal metadata")
            self.sse_finish_reason = reason

    def _check_deadline(self) -> None:
        if self.deadline is not None and monotonic() >= self.deadline:
            raise TimeoutError("request deadline expired")


class _TransportFault(Exception):
    """Internal transport failure with a fixed, content-free reason code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _BoundedAsyncByteStream(httpx.AsyncByteStream):
    def __init__(self, response: httpx.Response, state: _TransportState):
        self._response = response
        self._state = state
        self._iterator: Any | None = None

    async def _iterate(self):
        try:
            buffered: list[bytes] = []
            async for chunk in self._response.aiter_raw():
                self._state.record_chunk(chunk)
                if self._state.streaming:
                    yield chunk
                else:
                    buffered.append(chunk)
            self._state.finish_response()
            self._state.response_complete = True
            if not self._state.streaming:
                body = _sdk_compatible_body(b"".join(buffered), self._state)
                if body:
                    yield body
        finally:
            await self._response.aclose()

    def __aiter__(self):
        if self._iterator is None:
            self._iterator = self._iterate()
        return self._iterator

    async def drain(self, deadline: float) -> None:
        if self._iterator is None:
            self._iterator = self._iterate()
        while not self._state.response_complete:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("generation deadline expired")
            try:
                async with asyncio.timeout(remaining):
                    await anext(self._iterator)
            except StopAsyncIteration:
                return

    async def force_close(self) -> None:
        if self._iterator is not None:
            await self._iterator.aclose()
        await self._response.aclose()

    async def aclose(self) -> None:
        if self._state.streaming and self._state.sse_done and not self._state.response_complete:
            return
        await self._response.aclose()


class _BoundedAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport, state: _TransportState):
        self._inner = inner
        self._state = state

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._state.record_request(request)
        response = await self._inner.handle_async_request(request)
        self._state.record_response(response)
        if _is_non_success_or_redirect(response.status_code):
            safe_headers = _safe_rate_headers(response.headers)
            await response.aclose()
            return httpx.Response(
                response.status_code,
                headers={**safe_headers, "content-type": "application/json"},
                content=b"{}",
                request=request,
            )
        try:
            self._check_response_headers(response)
        except _TransportFault:
            await response.aclose()
            raise
        if response.is_stream_consumed:
            content = response.content
            try:
                self._state.record_chunk(content)
                self._state.finish_response()
                self._state.response_complete = True
            except _TransportFault:
                await response.aclose()
                raise
            await response.aclose()
            content = _sdk_compatible_body(content, self._state)
            headers = httpx.Headers(response.headers)
            headers["content-length"] = str(len(content))
            return httpx.Response(
                response.status_code,
                headers=headers,
                content=content,
                extensions=response.extensions,
                request=request,
            )
        headers = response.headers
        if not self._state.streaming:
            headers = httpx.Headers(headers)
            headers.pop("content-length", None)
        stream = _BoundedAsyncByteStream(response, self._state)
        self._state.async_stream = stream
        return httpx.Response(
            response.status_code,
            headers=headers,
            stream=stream,
            extensions=response.extensions,
            request=request,
        )

    def _check_response_headers(self, response: httpx.Response) -> None:
        encoding = response.headers.get("content-encoding", "").strip().lower()
        if encoding not in {"", "identity"}:
            self._state.violation = "response_encoding"
            raise _TransportFault("response_encoding")
        content_length = _parse_non_negative_int(response.headers.get("content-length"))
        if content_length is not None and content_length > self._state.max_response_bytes:
            self._state.violation = "response_size"
            raise _TransportFault("response_size")

    async def aclose(self) -> None:
        await self._inner.aclose()


class _BoundedSyncByteStream(httpx.SyncByteStream):
    def __init__(self, response: httpx.Response, state: _TransportState):
        self._response = response
        self._state = state

    def __iter__(self):
        try:
            buffered: list[bytes] = []
            iterator = iter(self._response.iter_raw())
            while True:
                _apply_deadline_to_response(self._response, self._state)
                try:
                    chunk = next(iterator)
                except StopIteration:
                    break
                self._state._check_deadline()
                self._state.record_chunk(chunk)
                if self._state.streaming:
                    yield chunk
                else:
                    buffered.append(chunk)
            self._state.finish_response()
            self._state.response_complete = True
            if not self._state.streaming:
                body = _sdk_compatible_body(b"".join(buffered), self._state)
                if body:
                    yield body
        finally:
            self._response.close()

    def close(self) -> None:
        self._response.close()


class _BoundedSyncTransport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport, state: _TransportState):
        self._inner = inner
        self._state = state

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._state.record_request(request)
        response = self._inner.handle_request(request)
        try:
            self._state._check_deadline()
        except TimeoutError:
            response.close()
            raise
        self._state.record_response(response)
        if _is_non_success_or_redirect(response.status_code):
            safe_headers = _safe_rate_headers(response.headers)
            response.close()
            return httpx.Response(
                response.status_code,
                headers={**safe_headers, "content-type": "application/json"},
                content=b"{}",
                request=request,
            )
        encoding = response.headers.get("content-encoding", "").strip().lower()
        if encoding not in {"", "identity"}:
            self._state.violation = "response_encoding"
            response.close()
            raise _TransportFault("response_encoding")
        content_length = _parse_non_negative_int(response.headers.get("content-length"))
        if content_length is not None and content_length > self._state.max_response_bytes:
            self._state.violation = "response_size"
            response.close()
            raise _TransportFault("response_size")
        if response.is_stream_consumed:
            content = response.content
            try:
                self._state._check_deadline()
                self._state.record_chunk(content)
                self._state.finish_response()
                self._state.response_complete = True
            except _TransportFault:
                response.close()
                raise
            response.close()
            content = _sdk_compatible_body(content, self._state)
            headers = httpx.Headers(response.headers)
            headers["content-length"] = str(len(content))
            return httpx.Response(
                response.status_code,
                headers=headers,
                content=content,
                extensions=response.extensions,
                request=request,
            )
        headers = response.headers
        if self._state.deadline is not None:
            response.extensions["timeout"] = request.extensions.get("timeout")
        if not self._state.streaming:
            headers = httpx.Headers(headers)
            headers.pop("content-length", None)
        return httpx.Response(
            response.status_code,
            headers=headers,
            stream=_BoundedSyncByteStream(response, self._state),
            extensions=response.extensions,
            request=request,
        )

    def close(self) -> None:
        self._inner.close()


@dataclass(frozen=True, slots=True)
class _CloudflareHTTPContext:
    profile: _ProviderProfile
    handler: Any


_cloudflare_http_context: contextvars.ContextVar[_CloudflareHTTPContext | None] = (
    contextvars.ContextVar("personal_ai_litellm_cloudflare_http", default=None)
)


class LiteLLMGenerationClient:
    """Provider-selected generation adapter using LiteLLM below neutral contracts."""

    requires_inference_context = True

    def __init__(
        self,
        settings: Settings,
        provider: Literal["gemini", "groq", "cloudflare_workers_ai"] | None = None,
        *,
        async_transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
        sync_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    ):
        self._settings = settings
        selected = provider or settings.ai_provider.lower()
        self._profile = _provider_profile(settings, selected)
        self._async_transport_factory = async_transport_factory
        self._sync_transport_factory = sync_transport_factory
        self.identity = ProviderIdentity(
            self._profile.provider_id, self._profile.model_id, self._profile.serializer_id
        )
        operations = {"streaming", "bounded_generation"}
        if self._profile.structured_enabled:
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
        duration = _bounded_timeout(max_output_tokens, timeout_seconds, self._settings)
        deadline = asyncio.get_running_loop().time() + duration
        state = _TransportState(
            self._profile, "generation", True, _MAX_STREAM_RESPONSE_BYTES
        )
        handler, client = await self._make_async_handler(state, duration)
        stream: Any | None = None
        context_token = self._set_cloudflare_context(handler)
        sdk_usage: UsageMetadata | None = None
        has_non_whitespace_text = False
        try:
            sdk = _load_litellm()
            arguments = self._completion_arguments(
                messages,
                max_output_tokens=max_output_tokens,
                timeout_seconds=duration,
                stream=True,
            )
            async with asyncio.timeout(_remaining(deadline)):
                stream = await sdk.acompletion(**arguments, client=handler)
            async for chunk in _iterate_sdk_stream(stream, deadline):
                usage = _usage_from_sdk(_field(chunk, "usage"))
                sdk_usage = usage or sdk_usage
                for delta in _sdk_text_deltas(chunk):
                    has_non_whitespace_text = has_non_whitespace_text or bool(delta.strip())
                    yield GenerationEvent.text_delta(delta)
            if state.async_stream is not None:
                await state.async_stream.drain(deadline)
            wire = _parse_generation_wire(
                self._profile,
                bytes(state.raw_body),
                streaming=True,
                require_completed=state.response_complete,
            )
            status = wire.status
            if status == "success" and not has_non_whitespace_text:
                status = "incomplete"
            metadata = GenerationMetadata(
                status=status,
                identity=ProviderIdentity(
                    self._profile.provider_id, wire.model_id, self._profile.serializer_id
                ),
                usage=wire.usage or _mark_estimated(sdk_usage),
                error_code=_terminal_error_code(status),
                rate_limits=_rate_limit_metadata(state.response_headers),
            )
            yield GenerationEvent.terminal(metadata)
        except asyncio.CancelledError:
            raise
        except LLMError:
            raise
        except Exception as error:  # noqa: BLE001 - LiteLLM exceptions can contain provider payloads.
            _raise_safe_error(error, state)
        finally:
            if stream is not None:
                await _close_sdk_stream(stream)
            if state.async_stream is not None:
                await state.async_stream.force_close()
            if context_token is not None:
                _cloudflare_http_context.reset(context_token)
            await _close_async_client(client)
            _reset_sdk_cache_callbacks()

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
        _validate_schema(response_schema)
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
        duration = _bounded_timeout(max_output_tokens, timeout_seconds, self._settings)
        deadline = monotonic() + duration
        state = _TransportState(
            self._profile,
            "generation",
            False,
            _MAX_COMPLETION_RESPONSE_BYTES,
            required_schema=response_schema,
            deadline=deadline,
        )
        handler, client = self._make_sync_handler(state, duration)
        context_token = self._set_cloudflare_context(handler)
        try:
            sdk = _load_litellm()
            arguments = self._completion_arguments(
                messages,
                max_output_tokens=max_output_tokens,
                timeout_seconds=_sync_remaining(deadline),
                stream=False,
                response_schema=response_schema,
            )
            _sync_remaining(deadline)
            response = sdk.completion(**arguments, client=handler)
            _sync_remaining(deadline)
            wire = _parse_generation_wire(
                self._profile,
                bytes(state.raw_body),
                streaming=False,
                require_completed=state.response_complete,
            )
            text = _sdk_completion_text(response)
            status = wire.status
            if status == "success" and not text.strip():
                status = "incomplete"
            refusal = _sdk_refusal(response) or wire.refused
            if refusal:
                status = "rejected"
            result = GenerationResult(
                text=text,
                metadata=GenerationMetadata(
                    status=status,
                    identity=ProviderIdentity(
                        self._profile.provider_id, wire.model_id, self._profile.serializer_id
                    ),
                    usage=(
                        wire.usage
                        or (
                            None
                            if state.sdk_usage_supplemented
                            else _mark_estimated(_usage_from_sdk(_field(response, "usage")))
                        )
                    ),
                    error_code=_terminal_error_code(status),
                    rate_limits=_rate_limit_metadata(state.response_headers),
                ),
            )
            _sync_remaining(deadline)
            return result
        except LLMError:
            raise
        except Exception as error:  # noqa: BLE001 - LiteLLM exceptions can contain provider payloads.
            _raise_safe_error(error, state)
        finally:
            if context_token is not None:
                _cloudflare_http_context.reset(context_token)
            _close_sync_client(client)
            _reset_sdk_cache_callbacks()

    def _completion_arguments(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_output_tokens: int,
        timeout_seconds: float,
        stream: bool,
        response_schema: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        token_parameter = self._profile.max_tokens_parameter
        arguments: dict[str, Any] = {
            "model": self._profile.sdk_model,
            "custom_llm_provider": self._profile.sdk_provider,
            "api_base": self._profile.api_base,
            "api_key": self._profile.api_key,
            "messages": _sdk_messages(self._profile, messages),
            token_parameter: max_output_tokens,
            "timeout": timeout_seconds,
            "stream": stream,
            "num_retries": 0,
            "max_retries": 0,
            "caching": False,
            "drop_params": False,
            "fallbacks": [],
            "model_list": None,
            "no-log": True,
        }
        if response_schema is not None:
            arguments["response_format"] = _response_format(
                response_schema, self._profile.provider
            )
        return arguments

    def _validate_request(
        self,
        messages: Sequence[ChatMessage],
        inference_context: InferenceContext | None,
    ) -> None:
        _validate_inference_context(inference_context)
        if not messages or any(not isinstance(message, ChatMessage) for message in messages):
            raise LLMInvalidRequestError("at least one valid chat message is required")
        for message in messages:
            role = _role_name(message.role)
            if (
                role not in {"system", "user", "assistant"}
                or not isinstance(message.content, str)
                or not message.content.strip()
            ):
                raise LLMInvalidRequestError("chat messages must not be empty")
        if self._profile.provider == "gemini":
            if self._settings.ai_provider.lower() != "gemini":
                raise LLMInvalidConfigurationError("AI_PROVIDER must be 'gemini'")
            if not self._profile.api_key:
                raise LLMInvalidConfigurationError("AI_API_KEY is not configured")
        else:
            _validate_external_provider(self._settings, self._profile, inference_context)
        _assert_litellm_runtime_safe()

    async def _make_async_handler(
        self, state: _TransportState, timeout_seconds: float
    ) -> tuple[Any, httpx.AsyncClient]:
        sdk = _load_litellm()
        handler_type = _sdk_http_handler_types(sdk)[0]
        handler = handler_type(timeout=timeout_seconds)
        placeholder = handler.client
        await placeholder.aclose()
        transport = (
            self._async_transport_factory()
            if self._async_transport_factory is not None
            else httpx.AsyncHTTPTransport(retries=0)
        )
        bounded_transport = _BoundedAsyncTransport(transport, state)
        client = httpx.AsyncClient(
            transport=bounded_transport,
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"accept-encoding": "identity"},
        )
        handler.client = client
        return handler, client

    def _make_sync_handler(
        self, state: _TransportState, timeout_seconds: float
    ) -> tuple[Any, httpx.Client]:
        sdk = _load_litellm()
        handler_type = _sdk_http_handler_types(sdk)[1]
        handler = handler_type(timeout=timeout_seconds)
        handler.client.close()
        transport = (
            self._sync_transport_factory()
            if self._sync_transport_factory is not None
            else httpx.HTTPTransport(retries=0)
        )
        bounded_transport = _BoundedSyncTransport(transport, state)
        client = httpx.Client(
            transport=bounded_transport,
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"accept-encoding": "identity"},
        )
        handler.client = client
        return handler, client

    def _set_cloudflare_context(self, handler: Any):
        if self._profile.provider != "cloudflare_workers_ai":
            return None
        _install_cloudflare_client_hook()
        return _cloudflare_http_context.set(_CloudflareHTTPContext(self._profile, handler))


class LiteLLMTokenCounter:
    """Gemini countTokens shim tied to LiteLLM's pinned generation transform."""

    requires_inference_context = True
    count_confidence = "authoritative"

    def __init__(
        self,
        settings: Settings,
        *,
        sync_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    ):
        self.settings = settings
        self._profile = _provider_profile(settings, "gemini")
        self._sync_transport_factory = sync_transport_factory
        self.identity = ProviderIdentity("gemini", settings.ai_model, "gemini-content-v1")
        self.capabilities = ProviderCapabilities(frozenset({"token_counting"}))

    def count(
        self,
        messages: Sequence[ChatMessage],
        *,
        response_schema: Mapping[str, object] | None = None,
        inference_context: InferenceContext | None = None,
    ) -> TokenCount:
        return self.count_with_timeout(
            messages,
            None,
            response_schema=response_schema,
            inference_context=inference_context,
        )

    def count_with_timeout(
        self,
        messages: Sequence[ChatMessage],
        timeout_seconds: float | None,
        *,
        response_schema: Mapping[str, object] | None = None,
        inference_context: InferenceContext | None = None,
    ) -> TokenCount:
        _validate_inference_context(inference_context)
        if self.settings.ai_provider.lower() != "gemini":
            raise LLMInvalidConfigurationError("AI_PROVIDER must be 'gemini'")
        if not self._profile.api_key:
            raise LLMInvalidConfigurationError("AI_API_KEY is not configured")
        if not messages or any(not isinstance(message, ChatMessage) for message in messages):
            raise LLMInvalidRequestError("at least one valid chat message is required")
        if any(
            _role_name(message.role) not in {"system", "user", "assistant"}
            or not isinstance(message.content, str)
            or not message.content.strip()
            for message in messages
        ):
            raise LLMInvalidRequestError("chat messages must not be empty")
        if response_schema is not None:
            _validate_schema(response_schema)
        _assert_litellm_runtime_safe()
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self.settings.request_timeout_seconds
        )
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise LLMInvalidRequestError("token count deadline is invalid")
        body = _gemini_generation_body(
            self._profile, messages, response_schema=response_schema
        )
        request_body = {
            "generateContentRequest": {
                "model": f"models/{self._profile.model_id.removeprefix('models/')}",
                **body,
            }
        }
        state = _TransportState(
            self._profile,
            "token_counting",
            False,
            _MAX_COUNT_RESPONSE_BYTES,
            required_schema=response_schema,
        )
        handler_type = _sdk_http_handler_types(_load_litellm())[1]
        handler = handler_type(timeout=timeout)
        handler.client.close()
        transport = (
            self._sync_transport_factory()
            if self._sync_transport_factory is not None
            else httpx.HTTPTransport(retries=0)
        )
        http_client = httpx.Client(
            transport=_BoundedSyncTransport(transport, state),
            timeout=timeout,
            follow_redirects=False,
            headers={"accept-encoding": "identity"},
        )
        handler.client = http_client
        url = (
            f"{self._profile.api_base}/models/"
            f"{quote(self._profile.model_id.removeprefix('models/'), safe='-_.~')}:countTokens"
        )
        try:
            response = handler.post(
                url,
                json=request_body,
                headers={"x-goog-api-key": self._profile.api_key},
                timeout=timeout,
            )
            status = state.response_status or response.status_code
            rate_limits = _rate_limit_metadata(state.response_headers)
            if _is_non_success_or_redirect(status):
                _raise_for_status(status, rate_limits)
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise LLMInvalidResponseError("provider token count was invalid")
            token_count = payload.get("totalTokens", payload.get("total_tokens"))
            if isinstance(token_count, bool) or not isinstance(token_count, int) or token_count < 0:
                raise LLMInvalidResponseError("provider token count was invalid")
            return TokenCount(
                token_count,
                "provider",
                provider_id="gemini",
                model_id=self.settings.ai_model,
                serializer_id="gemini-content-v1",
                confidence="authoritative",
            )
        except LLMError:
            raise
        except Exception as error:  # noqa: BLE001 - SDK errors may contain provider payloads.
            _raise_safe_error(error, state)
        finally:
            _close_sync_client(http_client)


class LiteLLMEmbeddingClient:
    """Gemini embedding adapter preserving the persisted Personal AI space."""

    requires_inference_context = True

    def __init__(
        self,
        settings: Settings,
        *,
        sync_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
    ):
        self.settings = settings
        self._profile = _provider_profile(settings, "gemini")
        self._sync_transport_factory = sync_transport_factory
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
        inference_context: InferenceContext | None = None,
    ) -> tuple[EmbeddingResult, ...]:
        self.capabilities.require("embeddings")
        _validate_inference_context(inference_context)
        if self.settings.ai_provider.lower() != "gemini":
            raise LLMInvalidConfigurationError("AI_PROVIDER must be 'gemini'")
        if not self._profile.api_key:
            raise LLMInvalidConfigurationError("AI_API_KEY is not configured")
        if not texts or any(
            not isinstance(text, str) or not text.strip() or len(text) > 20_000
            for text in texts
        ):
            raise LLMInvalidRequestError("embedding input invalid")
        duration = timeout if timeout is not None else self.settings.memory_timeout_seconds
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise LLMInvalidRequestError("embedding deadline expired")
        _assert_litellm_runtime_safe()
        deadline = monotonic() + duration
        state = _TransportState(
            self._profile,
            "embeddings",
            False,
            _MAX_EMBEDDING_RESPONSE_BYTES,
            request_model_id=self.settings.memory_embedding_model,
            deadline=deadline,
        )
        handler_type = _sdk_http_handler_types(_load_litellm())[1]
        handler = handler_type(timeout=duration)
        handler.client.close()
        transport = (
            self._sync_transport_factory()
            if self._sync_transport_factory is not None
            else httpx.HTTPTransport(retries=0)
        )
        client = httpx.Client(
            transport=_BoundedSyncTransport(transport, state),
            timeout=duration,
            follow_redirects=False,
            headers={"accept-encoding": "identity"},
        )
        handler.client = client
        task = "query" if query else "document"
        from personal_ai.memory.contracts import vector

        space = EmbeddingSpace(
            provider_id="google_genai",
            model_id=self.settings.memory_embedding_model,
            dimensions=self.settings.memory_embedding_dimensions,
            normalization="l2",
            document_task="RETRIEVAL_DOCUMENT",
            query_task="RETRIEVAL_QUERY",
            version="v1",
        )
        results: list[EmbeddingResult] = []
        try:
            sdk = _load_litellm()
            batch_size = self.settings.memory_embedding_batch_size
            for start in range(0, len(texts), batch_size):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise LLMTimeoutError("embedding request timed out")
                batch = list(texts[start : start + batch_size])
                state.embedding_texts = tuple(batch)
                response = sdk.embedding(
                    model=f"gemini/{self.settings.memory_embedding_model}",
                    custom_llm_provider="gemini",
                    api_base=self._profile.api_base,
                    api_key=self._profile.api_key,
                    input=[f"personal-ai-text-placeholder-{index}" for index in range(len(batch))],
                    dimensions=self.settings.memory_embedding_dimensions,
                    task_type=space.query_task if query else space.document_task,
                    timeout=remaining,
                    num_retries=0,
                    max_retries=0,
                    caching=False,
                    drop_params=False,
                    **{"no-log": True},
                    client=handler,
                )
                data = _field(response, "data")
                if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
                    raise LLMInvalidResponseError("embedding response invalid")
                if len(data) != len(batch):
                    raise LLMInvalidResponseError("embedding response invalid")
                for item in data:
                    values = _field(item, "embedding")
                    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                        raise LLMInvalidResponseError("embedding response invalid")
                    results.append(EmbeddingResult(
                        values=vector(values, space.dimensions),
                        space=space,
                        task=task,
                    ))
                if monotonic() >= deadline:
                    raise LLMTimeoutError("embedding request timed out")
            if monotonic() > deadline:
                raise LLMTimeoutError("embedding request timed out")
            return tuple(results)
        except LLMError:
            raise
        except Exception as error:  # noqa: BLE001 - SDK errors may contain provider payloads.
            _raise_safe_error(error, state)
        finally:
            _close_sync_client(client)
            _reset_sdk_cache_callbacks()


@dataclass(frozen=True, slots=True)
class _WireMetadata:
    model_id: str
    status: Literal["success", "incomplete", "rejected"]
    usage: UsageMetadata | None = None
    refused: bool = False


def _provider_profile(settings: Settings, provider: str) -> _ProviderProfile:
    if provider == "gemini":
        model = settings.ai_model
        return _ProviderProfile(
            "gemini",
            "gemini",
            "gemini",
            model,
            "gemini-content-v1",
            "https://generativelanguage.googleapis.com/v1beta",
            settings.ai_api_key.get_secret_value(),
            frozenset({model}),
            True,
        )
    if provider == "groq":
        model = settings.groq_model
        return _ProviderProfile(
            "groq",
            "groq",
            "groq",
            model or "unconfigured",
            "groq-chat-completions-v1",
            "https://api.groq.com/openai/v1",
            settings.groq_api_key.get_secret_value(),
            frozenset({model, *settings.groq_approved_model_aliases}),
            settings.groq_structured_output_verified,
            "max_completion_tokens",
        )
    if provider == "cloudflare_workers_ai":
        model = settings.cloudflare_model
        account = quote(settings.cloudflare_account_id, safe="")
        return _ProviderProfile(
            "cloudflare_workers_ai",
            "cloudflare",
            "cloudflare_workers_ai",
            model or "unconfigured",
            "cloudflare-workers-ai-chat-v1",
            f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1",
            settings.cloudflare_api_token.get_secret_value(),
            frozenset({model, *settings.cloudflare_approved_model_aliases}),
            settings.cloudflare_structured_output_verified,
        )
    raise LLMInvalidConfigurationError("configured language model provider is unsupported")


def _validate_external_provider(
    settings: Settings,
    profile: _ProviderProfile,
    inference_context: InferenceContext | None,
) -> None:
    if settings.external_providers_kill_switch_enabled:
        raise LLMUnavailableError("external provider calls are disabled")
    if profile.provider == "groq":
        enabled = settings.groq_adapter_enabled
        free = settings.groq_free_tier_verified
        privacy = settings.groq_privacy_approved
        maximum = settings.groq_privacy_max_sensitivity
        preflight = settings.groq_preflight_reference
    else:
        enabled = settings.cloudflare_adapter_enabled
        free = settings.cloudflare_free_tier_verified
        privacy = settings.cloudflare_privacy_approved
        maximum = settings.cloudflare_privacy_max_sensitivity
        preflight = settings.cloudflare_preflight_reference
        if not settings.cloudflare_account_id:
            raise LLMInvalidConfigurationError("provider account scope is not configured")
    if not enabled:
        raise LLMInvalidConfigurationError("provider adapter is disabled")
    if not free or not privacy or not preflight.strip():
        raise LLMInvalidConfigurationError("provider preflight is incomplete")
    if not profile.api_key or profile.model_id == "unconfigured":
        raise LLMInvalidConfigurationError("provider credentials or model are not configured")
    maximum_rank = _SENSITIVITY_RANK.get(maximum, -1)
    if maximum_rank < 0:
        raise LLMInvalidConfigurationError("provider privacy ceiling is invalid")
    effective_rank = _SENSITIVITY_RANK.get(
        inference_context.effective_sensitivity if inference_context else "unknown", 4
    )
    if effective_rank > maximum_rank:
        raise LLMInvalidRequestError(
            "provider privacy preflight does not allow this sensitivity"
        )


def _validate_inference_context(context: InferenceContext | None) -> None:
    if context is None:
        raise LLMInvalidRequestError("context disclosure policy is required")
    try:
        InferenceContext(
            effective_sensitivity=context.effective_sensitivity,
            maximum_sensitivity=context.maximum_sensitivity,
            policy_version=context.policy_version,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise LLMInvalidRequestError("context disclosure policy denied") from error


def _validate_schema(schema: Mapping[str, object] | None) -> None:
    if not isinstance(schema, Mapping) or not schema:
        raise LLMInvalidRequestError("structured response schema is required")
    try:
        json.dumps(schema, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise LLMInvalidRequestError("structured response schema is invalid") from error


def _role_name(role: Any) -> str:
    return str(getattr(role, "value", role))


def _sdk_messages(
    profile: _ProviderProfile, messages: Sequence[ChatMessage]
) -> list[dict[str, str]]:
    prepared = list(messages)
    if profile.provider == "gemini":
        system = "\n\n".join([
            SYSTEM_INSTRUCTION,
            *(message.content for message in prepared if _role_name(message.role) == "system"),
        ])
        output = [{"role": "system", "content": system}]
        output.extend(
            {
                "role": "assistant" if _role_name(message.role) == "assistant" else "user",
                "content": message.content,
            }
            for message in prepared
            if _role_name(message.role) != "system"
        )
        return output
    return [
        {"role": _role_name(message.role), "content": message.content}
        for message in prepared
    ]


def _response_format(
    schema: Mapping[str, object], provider: str
) -> dict[str, Any]:
    if provider == "cloudflare_workers_ai":
        return {"type": "json_schema", "json_schema": dict(schema)}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "personal_ai_response",
            "strict": False,
            "schema": dict(schema),
        },
    }


def _request_preserves_schema(
    request_body: Any, profile: _ProviderProfile, schema: Mapping[str, object]
) -> bool:
    if profile.provider == "cloudflare_workers_ai":
        response_format = _field(request_body, "response_format")
        return response_format == {
            "type": "json_schema",
            "json_schema": dict(schema),
        }
    if profile.provider == "groq":
        tools = _field(request_body, "tools")
        choice = _field(request_body, "tool_choice")
        expected_function = {
            "name": "json_tool_call",
            "parameters": dict(schema),
        }
        return (
            isinstance(tools, list)
            and any(
                _field(tool, "type") == "function"
                and _field(tool, "function") == expected_function
                for tool in tools
            )
            and choice == {
                "type": "function",
                "function": {"name": "json_tool_call"},
            }
        )
    return _contains_schema_value(request_body, schema)


def _sse_payload_has_text(payload: Mapping[str, Any], provider: str) -> bool:
    if provider == "gemini":
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            return False
        for candidate in candidates:
            content = _field(candidate, "content")
            parts = _field(content, "parts")
            if isinstance(parts, list) and any(
                isinstance(_field(part, "text"), str) and _field(part, "text")
                for part in parts
            ):
                return True
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, Mapping):
            continue
        for name in ("delta", "message"):
            content = _field(_field(choice, name), "content")
            if isinstance(content, str) and content:
                return True
    return False


def _sse_finish_reason(payload: Mapping[str, Any], provider: str) -> str | None:
    if provider == "gemini":
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            return None
        reason: str | None = None
        for candidate in candidates:
            raw_reason = _gemini_reason(_field(candidate, "finishReason"))
            if raw_reason is None:
                continue
            if reason is not None and reason != raw_reason:
                raise LLMInvalidResponseError(
                    "language model emitted conflicting terminal metadata"
                )
            reason = raw_reason
        return reason
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return None
    reason = None
    for choice in choices:
        if not isinstance(choice, Mapping):
            raise LLMInvalidResponseError("language model stream choice was invalid")
        raw_reason = choice.get("finish_reason")
        if raw_reason is None:
            continue
        if not isinstance(raw_reason, str) or not raw_reason:
            raise LLMInvalidResponseError("language model terminal metadata was invalid")
        if reason is not None and reason != raw_reason:
            raise LLMInvalidResponseError(
                "language model emitted conflicting terminal metadata"
            )
        reason = raw_reason
    return reason


def _sync_remaining(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("request deadline expired")
    return remaining


def _apply_deadline_to_response(response: httpx.Response, state: _TransportState) -> None:
    if state.deadline is None:
        return
    response.extensions["timeout"] = httpx.Timeout(
        _sync_remaining(state.deadline)
    ).as_dict()


def _bounded_timeout(
    max_output_tokens: int, timeout_seconds: float, settings: Settings
) -> float:
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
    return min(float(timeout_seconds), settings.request_timeout_seconds)


def _remaining(deadline: float) -> float:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError("generation deadline expired")
    return remaining


async def _iterate_sdk_stream(stream: Any, deadline: float):
    iterator = stream.__aiter__()
    while True:
        try:
            async with asyncio.timeout(_remaining(deadline)):
                chunk = await anext(iterator)
        except StopAsyncIteration:
            return
        yield chunk


def _sdk_text_deltas(chunk: Any) -> tuple[str, ...]:
    choices = _field(chunk, "choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)):
        return ()
    result: list[str] = []
    for choice in choices:
        delta = _field(choice, "delta")
        content = _field(delta, "content")
        if isinstance(content, str) and content:
            result.append(content)
    return tuple(result)


def _sdk_completion_text(response: Any) -> str:
    choices = _field(response, "choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise LLMInvalidResponseError("language model response had no completion choice")
    message = _field(choices[0], "message")
    content = _field(message, "content")
    if content is None:
        return ""
    if not isinstance(content, str):
        raise LLMInvalidResponseError("language model completion text was invalid")
    return content


def _sdk_refusal(response: Any) -> bool:
    choices = _field(response, "choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)):
        return False
    return any(bool(_field(_field(choice, "message"), "refusal")) for choice in choices)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _usage_from_sdk(raw: Any) -> UsageMetadata | None:
    if raw is None:
        return None
    input_tokens = _parse_non_negative_int(_field(raw, "prompt_tokens", _field(raw, "input_tokens")))
    output_tokens = _parse_non_negative_int(
        _field(raw, "completion_tokens", _field(raw, "output_tokens"))
    )
    total_tokens = _parse_non_negative_int(_field(raw, "total_tokens"))
    if input_tokens is output_tokens is total_tokens is None:
        return None
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        source="estimated",
        confidence="estimated",
    )


def _mark_estimated(usage: UsageMetadata | None) -> UsageMetadata | None:
    if usage is None:
        return None
    return UsageMetadata(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        source="estimated",
        confidence="estimated",
    )


def _sdk_compatible_body(raw: bytes, state: _TransportState) -> bytes:
    """Patch pinned response-parser requirements while retaining raw evidence.

    LiteLLM 1.102.1 rejects otherwise valid Gemini completions when the provider
    omits optional usageMetadata. Its Groq transform also unconditionally reads
    service_tier from a LiteLLM ModelResponse. The SDK sees an empty usage field
    or a default service tier for parsing, while Personal AI derives identity,
    terminal state, and usage only from state.raw_body.
    """
    if (
        state.streaming
        or state.profile.provider not in {"gemini", "groq", "cloudflare_workers_ai"}
        or state.operation != "generation"
    ):
        return raw
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw
    if not isinstance(payload, dict):
        return raw
    modified = False
    if state.profile.provider == "gemini" and "usageMetadata" not in payload:
        payload["usageMetadata"] = {}
        state.sdk_usage_supplemented = True
        modified = True
    if state.profile.provider == "groq" and "service_tier" not in payload:
        payload["service_tier"] = "default"
        modified = True
    if not modified:
        return raw
    compatible = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(compatible) > state.max_response_bytes:
        state.violation = "response_size"
        raise _TransportFault("response_size")
    return compatible


def _parse_generation_wire(
    profile: _ProviderProfile,
    raw: bytes,
    *,
    streaming: bool,
    require_completed: bool,
) -> _WireMetadata:
    if not require_completed or not raw:
        raise LLMInvalidResponseError("language model response was not fully received")
    if profile.provider == "gemini":
        payloads, _done = _parse_sse(raw) if streaming else (_json_payloads(raw), False)
        return _parse_gemini_payloads(profile, payloads)
    if streaming:
        payloads, done = _parse_sse(raw)
        return _parse_openai_payloads(profile, payloads, done=done)
    payloads = _json_payloads(raw)
    return _parse_openai_payloads(profile, payloads, done=True)


def _json_payloads(raw: bytes) -> list[Mapping[str, Any]]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LLMInvalidResponseError("language model response was invalid") from error
    if not isinstance(payload, Mapping):
        raise LLMInvalidResponseError("language model response was invalid")
    return [payload]


def _parse_sse(raw: bytes) -> tuple[list[Mapping[str, Any]], bool]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise LLMInvalidResponseError("language model stream was invalid") from error
    payloads: list[Mapping[str, Any]] = []
    data_lines: list[str] = []
    done = False
    for line in text.splitlines():
        if line == "":
            event, done = _consume_sse_event(data_lines, payloads, done)
            data_lines = []
            if event:
                continue
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
    _, done = _consume_sse_event(data_lines, payloads, done)
    for payload in payloads:
        if payload.get("error") is not None:
            raise LLMUnavailableError("language model stream failed")
    return payloads, done


def _consume_sse_event(
    data_lines: list[str],
    payloads: list[Mapping[str, Any]],
    done: bool,
) -> tuple[bool, bool]:
    if not data_lines:
        return False, done
    data = "\n".join(data_lines)
    if data.strip() == "[DONE]":
        return True, True
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LLMInvalidResponseError("language model emitted malformed stream data") from error
    if not isinstance(payload, Mapping):
        raise LLMInvalidResponseError("language model emitted an invalid stream event")
    if done:
        raise LLMInvalidResponseError("language model emitted data after stream completion")
    payloads.append(payload)
    return True, done


def _parse_gemini_payloads(
    profile: _ProviderProfile, payloads: Sequence[Mapping[str, Any]]
) -> _WireMetadata:
    model: str | None = None
    reason: str | None = None
    usage: UsageMetadata | None = None
    refused = False
    for payload in payloads:
        raw_model = payload.get("modelVersion", payload.get("model_version", payload.get("model")))
        if raw_model is not None:
            model = _merge_model_identity(profile, model, raw_model)
        feedback = payload.get("promptFeedback")
        if isinstance(feedback, Mapping):
            refused = refused or _gemini_reason(feedback.get("blockReason")) == "BLOCKED"
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                candidate_reason = _gemini_reason(candidate.get("finishReason"))
                if candidate_reason is not None:
                    if reason is not None and reason != candidate_reason:
                        raise LLMInvalidResponseError("language model emitted conflicting terminal metadata")
                    reason = candidate_reason
        usage = _gemini_usage(payload.get("usageMetadata")) or usage
    if model is None:
        raise LLMInvalidResponseError("language model response omitted its model identity")
    if refused:
        status: Literal["success", "incomplete", "rejected"] = "rejected"
    elif reason in {"STOP", "FINISH_REASON_STOP"}:
        status = "success"
    elif reason in {"SAFETY", "RECITATION", "BLOCKED", "PROHIBITED_CONTENT"}:
        status = "rejected"
    else:
        status = "incomplete"
    return _WireMetadata(model, status, usage, refused)


def _parse_openai_payloads(
    profile: _ProviderProfile,
    payloads: Sequence[Mapping[str, Any]],
    *,
    done: bool,
) -> _WireMetadata:
    model: str | None = None
    reason: str | None = None
    usage: UsageMetadata | None = None
    refused = False
    for payload in payloads:
        raw_model = payload.get("model")
        if raw_model is not None:
            model = _merge_model_identity(profile, model, raw_model)
        usage = _openai_usage(payload.get("usage")) or usage
        choices = payload.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, Mapping):
                raise LLMInvalidResponseError("language model stream choice was invalid")
            raw_reason = choice.get("finish_reason")
            if raw_reason is not None:
                if not isinstance(raw_reason, str) or not raw_reason:
                    raise LLMInvalidResponseError("language model terminal metadata was invalid")
                if reason is not None and reason != raw_reason:
                    raise LLMInvalidResponseError("language model emitted conflicting terminal metadata")
                reason = raw_reason
            message = choice.get("message")
            delta = choice.get("delta")
            refused = refused or bool(
                _field(message, "refusal") or _field(delta, "refusal")
            )
    if model is None:
        raise LLMInvalidResponseError("language model response omitted its model identity")
    if refused or reason in {"content_filter", "safety"}:
        status: Literal["success", "incomplete", "rejected"] = "rejected"
    elif reason in {"stop", "end_turn", "completed"} and (done or profile.provider != "gemini"):
        status = "success"
    else:
        status = "incomplete"
    if profile.provider in {"groq", "cloudflare_workers_ai"} and not done:
        status = "incomplete"
    return _WireMetadata(model, status, usage, refused)


def _merge_model_identity(
    profile: _ProviderProfile, existing: str | None, raw_model: Any
) -> str:
    if not isinstance(raw_model, str) or not raw_model.strip() or len(raw_model) > 200:
        raise LLMInvalidResponseError("language model response model identity was invalid")
    model = raw_model.strip()
    if model not in profile.approved_models:
        raise LLMInvalidResponseError("language model returned an unapproved model identity")
    if existing is not None and existing != model:
        raise LLMInvalidResponseError("language model emitted conflicting model identities")
    return model


def _gemini_reason(value: Any) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    normalized = str(name if name is not None else value).upper().split(".")[-1]
    return normalized if normalized not in {"", "NONE", "0"} else None


def _gemini_usage(raw: Any) -> UsageMetadata | None:
    if not isinstance(raw, Mapping):
        return None
    input_tokens = _parse_non_negative_int(raw.get("promptTokenCount"))
    output_tokens = _parse_non_negative_int(raw.get("candidatesTokenCount"))
    total_tokens = _parse_non_negative_int(raw.get("totalTokenCount"))
    if input_tokens is output_tokens is total_tokens is None:
        return None
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        source="provider",
        confidence="reported",
    )


def _openai_usage(raw: Any) -> UsageMetadata | None:
    if not isinstance(raw, Mapping):
        return None
    input_tokens = _parse_non_negative_int(raw.get("prompt_tokens", raw.get("input_tokens")))
    output_tokens = _parse_non_negative_int(raw.get("completion_tokens", raw.get("output_tokens")))
    total_tokens = _parse_non_negative_int(raw.get("total_tokens"))
    if input_tokens is output_tokens is total_tokens is None:
        return None
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        source="provider",
        confidence="reported",
    )


def _terminal_error_code(status: str) -> str | None:
    if status == "incomplete":
        return LLMIncompleteGenerationError.code
    if status == "rejected":
        return LLMRejectedError.code
    if status == "failure":
        return LLMUnavailableError.code
    return None


def _raise_for_status(
    status_code: int, rate_limits: ProviderRateLimitMetadata | None
) -> None:
    if 200 <= status_code < 300:
        return
    if status_code < 200 or 300 <= status_code < 400:
        raise LLMUnavailableError("provider redirect or interim response was rejected")
    if status_code == 429:
        raise LLMRateLimitedError(rate_limits=rate_limits)
    if status_code in {401, 403}:
        raise LLMInvalidConfigurationError("provider credentials or model access are invalid")
    if status_code in {408, 504}:
        raise LLMTimeoutError("language model request timed out")
    if status_code in {400, 404, 413, 422}:
        raise LLMInvalidRequestError("language model rejected the request")
    raise LLMUnavailableError("language model is unavailable")


def _raise_safe_error(error: BaseException, state: _TransportState) -> None:
    if state.stream_error is not None:
        raise state.stream_error from None
    if state.deadline is not None and monotonic() >= state.deadline:
        raise LLMTimeoutError("language model request timed out") from None
    if state.violation == "endpoint":
        raise LLMInvalidConfigurationError("provider endpoint was not approved") from None
    if state.violation == "required_parameter":
        raise LLMUnsupportedCapabilityError(
            "provider SDK did not preserve the required structured schema"
        ) from None
    if state.violation == "request_size":
        raise LLMInvalidRequestError("language model request exceeded the size limit") from None
    if state.violation == "response_size":
        raise LLMInvalidResponseError("language model response exceeded the size limit") from None
    if state.violation == "response_encoding":
        raise LLMInvalidResponseError("language model response encoding was invalid") from None
    if state.violation == "generation_replay":
        raise LLMUnavailableError("language model request could not be safely retried") from None
    if state.response_status is not None and _is_non_success_or_redirect(state.response_status):
        _raise_for_status(
            state.response_status, _rate_limit_metadata(state.response_headers)
        )
    if _exception_chain_contains_timeout(error):
        raise LLMTimeoutError("language model request timed out") from None
    if isinstance(error, (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError)):
        raise LLMInvalidResponseError("language model response was invalid") from None
    raise LLMUnavailableError("language model is unavailable") from None


def _exception_chain_contains_timeout(error: BaseException) -> bool:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (TimeoutError, httpx.TimeoutException)) or type(current).__name__ in {
            "Timeout", "APITimeoutError", "ReadTimeout", "ConnectTimeout"
        }:
            return True
        for name in ("__cause__", "__context__", "original_exception"):
            nested = getattr(current, name, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
        nested_errors = getattr(current, "exceptions", ())
        if isinstance(nested_errors, Sequence) and not isinstance(nested_errors, (str, bytes)):
            pending.extend(item for item in nested_errors if isinstance(item, BaseException))
    return False


def _request_is_approved(
    request: httpx.Request,
    profile: _ProviderProfile,
    operation: str,
    streaming: bool,
    request_model_id: str | None,
) -> bool:
    url = request.url
    base = urlsplit(profile.api_base)
    if (
        request.method != "POST"
        or url.scheme != "https"
        or url.host != base.hostname
        or url.port not in {None, base.port, 443}
        or bool(url.username)
        or bool(url.password)
    ):
        return False
    base_path = base.path.rstrip("/")
    if operation == "generation" and profile.provider == "gemini":
        model = quote(
            (request_model_id or profile.model_id).removeprefix("models/"),
            safe="-_.~",
        )
        suffix = ":streamGenerateContent" if streaming else ":generateContent"
        expected_path = f"{base_path}/models/{model}{suffix}"
        query = url.query.decode("ascii", errors="ignore")
        return url.path == expected_path and query == ("alt=sse" if streaming else "")
    if operation == "token_counting":
        model = quote(
            (request_model_id or profile.model_id).removeprefix("models/"),
            safe="-_.~",
        )
        return url.path == f"{base_path}/models/{model}:countTokens" and not url.query
    if operation == "embeddings":
        model = quote(
            (request_model_id or profile.model_id).removeprefix("models/"),
            safe="-_.~",
        )
        return url.path == f"{base_path}/models/{model}:batchEmbedContents" and not url.query
    if operation == "generation":
        return url.path == f"{base_path}/chat/completions" and not url.query
    return False


def _safe_rate_headers(headers: Mapping[str, str]) -> dict[str, str]:
    allowed = (
        "retry-after",
        "x-ratelimit-limit-requests",
        "x-ratelimit-remaining-requests",
        "x-ratelimit-reset-requests",
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-reset-tokens",
    )
    return {name: headers[name] for name in allowed if name in headers}


def _is_non_success_or_redirect(status_code: int) -> bool:
    return status_code < 200 or status_code >= 300


def _parse_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _rate_limit_metadata(
    headers: Mapping[str, str],
) -> ProviderRateLimitMetadata | None:
    values = {
        "requests_limit": _parse_non_negative_int(headers.get("x-ratelimit-limit-requests")),
        "requests_remaining": _parse_non_negative_int(headers.get("x-ratelimit-remaining-requests")),
        "requests_reset_seconds": _duration(headers.get("x-ratelimit-reset-requests")),
        "tokens_limit": _parse_non_negative_int(headers.get("x-ratelimit-limit-tokens")),
        "tokens_remaining": _parse_non_negative_int(headers.get("x-ratelimit-remaining-tokens")),
        "tokens_reset_seconds": _duration(headers.get("x-ratelimit-reset-tokens")),
        "retry_after_seconds": _duration(headers.get("retry-after")),
    }
    if not any(value is not None for value in values.values()):
        return None
    return ProviderRateLimitMetadata(**values)


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


def _gemini_generation_body(
    profile: _ProviderProfile,
    messages: Sequence[ChatMessage],
    *,
    response_schema: Mapping[str, object] | None,
) -> dict[str, Any]:
    _load_litellm()
    try:
        from litellm.llms.vertex_ai.gemini.transformation import _transform_request_body
        from litellm.utils import get_optional_params

        model = profile.model_id.removeprefix("models/")
        response_format = (
            _response_format(response_schema, "gemini")
            if response_schema is not None
            else None
        )
        optional_params = get_optional_params(
            model=model,
            custom_llm_provider="gemini",
            max_tokens=None,
            response_format=response_format,
            drop_params=False,
            messages=_sdk_messages(profile, messages),
        )
        transformed = _transform_request_body(
            messages=_sdk_messages(profile, messages),
            model=model,
            optional_params=optional_params,
            custom_llm_provider="gemini",
            litellm_params={
                "custom_llm_provider": "gemini",
                "api_base": profile.api_base,
                "api_key": profile.api_key,
            },
            cached_content=None,
        )
    except Exception as error:  # noqa: BLE001 - pinned SDK internals can raise varied types.
        raise LLMInvalidConfigurationError(
            f"pinned LiteLLM Gemini serializer is unavailable ({type(error).__name__})"
        ) from None
    if not isinstance(transformed, Mapping):
        raise LLMInvalidRequestError("Gemini request serialization was invalid")
    body = dict(transformed)
    if response_schema is not None and not _contains_schema(body, response_schema):
        raise LLMUnsupportedCapabilityError(
            "LiteLLM did not preserve the required Gemini response schema"
        )
    return body


def _contains_schema(body: Mapping[str, Any], schema: Mapping[str, object]) -> bool:
    generation = body.get("generationConfig")
    if not isinstance(generation, Mapping):
        return False
    return generation.get("response_json_schema") == schema or generation.get(
        "response_schema"
    ) is not None


def _contains_schema_value(value: Any, schema: Mapping[str, object]) -> bool:
    if isinstance(value, Mapping):
        if value == schema:
            return True
        return any(_contains_schema_value(item, schema) for item in value.values())
    if isinstance(value, list):
        return any(_contains_schema_value(item, schema) for item in value)
    return False


def _sdk_http_handler_types(sdk: Any) -> tuple[Any, Any]:
    module = importlib.import_module("litellm.llms.custom_httpx.http_handler")
    return module.AsyncHTTPHandler, module.HTTPHandler


def _load_litellm() -> Any:
    global _SDK
    if _SDK is None:
        with _SDK_LOCK:
            if _SDK is None:
                # Prevent the optional model-price map download during SDK import.
                os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
                os.environ["LITELLM_LOG"] = "CRITICAL"
                try:
                    sdk = importlib.import_module("litellm")
                except Exception as error:  # noqa: BLE001 - SDK import may fail in varied ways.
                    raise LLMInvalidConfigurationError(
                        f"LiteLLM SDK {LITELLM_VERSION} could not be loaded ({type(error).__name__})"
                    ) from None
                try:
                    version = importlib.metadata.version("litellm")
                except importlib.metadata.PackageNotFoundError:
                    version = None
                if version != LITELLM_VERSION:
                    raise LLMInvalidConfigurationError("LiteLLM SDK version does not match the lockfile")
                if getattr(sdk, "cache", None) is not None or any(
                    bool(getattr(sdk, name, None))
                    for name in (
                        "callbacks",
                        "input_callback",
                        "success_callback",
                        "failure_callback",
                        "_async_input_callback",
                        "_async_success_callback",
                        "_async_failure_callback",
                        "pre_call_rules",
                        "post_call_rules",
                    )
                ):
                    raise LLMInvalidConfigurationError(
                        "LiteLLM cache and content hooks must be disabled"
                    )
                sdk.disable_cache()
                sdk.disable_anthropic_gemini_context_caching_transform = True
                sdk.suppress_debug_info = True
                sdk.turn_off_message_logging = True
                sdk.log_raw_request_response = False
                sdk.set_verbose = False
                _suppress_litellm_logging()
                _SDK = sdk
    return _SDK


def _assert_litellm_runtime_safe() -> None:
    sdk = _load_litellm()
    _suppress_litellm_logging()
    hook_names = (
        "callbacks",
        "input_callback",
        "success_callback",
        "failure_callback",
        "_async_input_callback",
        "_async_success_callback",
        "_async_failure_callback",
        "pre_call_rules",
        "post_call_rules",
    )
    if any(bool(getattr(sdk, name, None)) for name in hook_names):
        raise LLMInvalidConfigurationError("LiteLLM content hooks must be disabled")
    if (
        getattr(sdk, "cache", None) is not None
        or bool(getattr(sdk, "model_fallbacks", None))
        or bool(getattr(sdk, "model_alias_map", None))
        or getattr(sdk, "global_disable_no_log_param", False)
        or getattr(sdk, "turn_off_message_logging", False) is not True
        or getattr(sdk, "log_raw_request_response", True)
        or getattr(sdk, "suppress_debug_info", False) is not True
        or getattr(sdk, "drop_params", False)
        or getattr(sdk, "modify_params", False)
        or getattr(sdk, "num_retries_per_request", None) not in {None, 0}
        or getattr(sdk, "num_retries", None) not in {None, 0}
    ):
        raise LLMInvalidConfigurationError("LiteLLM runtime settings are not safe")


def _suppress_litellm_logging() -> None:
    """Suppress the pinned SDK's content-bearing diagnostics at every call."""
    names = {
        "LiteLLM",
        "LiteLLM Proxy",
        "LiteLLM Router",
        *(
            name
            for name in logging.Logger.manager.loggerDict
            if name.startswith(("LiteLLM", "litellm"))
        ),
    }
    for name in names:
        sdk_logger = logging.getLogger(name)
        sdk_logger.setLevel(logging.CRITICAL)
        sdk_logger.propagate = False


def _reset_sdk_cache_callbacks() -> None:
    sdk = _load_litellm()
    sdk.disable_cache()


def _install_cloudflare_client_hook() -> None:
    global _CF_HOOK_INSTALLED, _CF_HOOKS
    if _CF_HOOK_INSTALLED:
        return
    with _SDK_LOCK:
        if _CF_HOOK_INSTALLED:
            return
        module = importlib.import_module("litellm.llms.custom_httpx.llm_http_handler")
        original_async = module.get_async_httpx_client
        original_sync = module._get_httpx_client

        def get_async_httpx_client(*args: Any, **kwargs: Any):
            context = _cloudflare_http_context.get()
            if context is not None:
                return context.handler
            return original_async(*args, **kwargs)

        def get_httpx_client(*args: Any, **kwargs: Any):
            context = _cloudflare_http_context.get()
            if context is not None:
                return context.handler
            return original_sync(*args, **kwargs)

        module.get_async_httpx_client = get_async_httpx_client
        module._get_httpx_client = get_httpx_client
        _CF_HOOKS = (get_async_httpx_client, get_httpx_client)
        _CF_HOOK_INSTALLED = True


async def _close_sdk_stream(stream: Any) -> None:
    close = getattr(stream, "aclose", None)
    if close is None:
        close = getattr(stream, "close", None)
    if close is None:
        return
    with anyio.CancelScope(shield=True):
        with anyio.move_on_after(1):
            try:
                result = close()
                if hasattr(result, "__await__"):
                    await result
            except (Exception, asyncio.CancelledError):  # noqa: BLE001 - best-effort cleanup.
                return


async def _close_async_client(client: httpx.AsyncClient) -> None:
    with anyio.CancelScope(shield=True):
        with anyio.move_on_after(1):
            try:
                await client.aclose()
            except (Exception, asyncio.CancelledError):  # noqa: BLE001 - best-effort cleanup.
                return


def _close_sync_client(client: httpx.Client) -> None:
    try:
        client.close()
    except Exception:  # noqa: BLE001 - request result is already determined.
        logger.debug("LiteLLM client cleanup failed")
