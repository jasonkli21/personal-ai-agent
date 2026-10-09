"""Versioned text-only SIWC Responses serializer and bounded, non-retrying IO."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import httpx

from personal_ai.llm.chatgpt.oauth import RESOURCE
from personal_ai.llm.chatgpt.wire import decode_json
from personal_ai.llm.client import (
    ChatMessage,
    ExecutionProvenance,
    GenerationEvent,
    GenerationMetadata,
    ProviderIdentity,
    UsageMetadata,
)
from personal_ai.llm.errors import LLMInvalidRequestError, LLMInvalidResponseError

PROVIDER = "openai_chatgpt_plan"
SERIALIZER = "siwc-responses-text-v1"
ERROR_CODES = {
    "subscription_sharing_user_not_eligible": "bridge_ineligible",
    "subscription_sharing_usage_limit_exceeded": "bridge_usage_limit",
    "subscription_sharing_usage_unavailable": "bridge_usage_unavailable",
    "subscription_sharing_unsupported_capability": "bridge_unsupported_request",
    "subscription_sharing_route_not_supported": "bridge_admission_denied",
    "subscription_sharing_invalid_user": "bridge_auth_required",
    "chatpass_v2_scope_not_authorized": "bridge_permission_denied",
    "chatpass_v2_invalid_authorization_context": "bridge_permission_denied",
    "subscription_sharing_user_unavailable": "bridge_unavailable",
}


@dataclass(frozen=True, slots=True)
class VisibleModel:
    slug: str
    display_name: str


class BridgeProviderFailure(RuntimeError):
    def __init__(self, code, *, status=None, shape="unknown"):
        super().__init__(code)
        self.code, self.status, self.shape = code, status, shape


def classify_error(data, status=None):
    error = data.get("error") if isinstance(data, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    shape = (
        "error"
        if isinstance(error, dict)
        else ("detail" if isinstance(data, dict) and "detail" in data else "unknown")
    )
    normalized = ERROR_CODES.get(code) if isinstance(code, str) else None
    if normalized is None:
        normalized = {
            401: "bridge_auth_required",
            403: "bridge_admission_denied",
            429: "bridge_usage_limit",
            400: "bridge_unsupported_request",
        }.get(status, "bridge_unavailable")
    return BridgeProviderFailure(normalized, status=status, shape=shape)


def serialize(messages: Sequence[ChatMessage], model: str) -> bytes:
    if not messages or len(messages) > 256:
        raise LLMInvalidRequestError("bridge_request_invalid")
    items = []
    for message in messages:
        role = getattr(message.role, "value", message.role)
        if role not in {"system", "developer", "user", "assistant"}:
            raise LLMInvalidRequestError("bridge_request_unsupported")
        if not isinstance(message.content, str) or not message.content:
            raise LLMInvalidRequestError("bridge_request_invalid")
        items.append(
            {"role": "developer" if role == "system" else role, "content": message.content}
        )
    # No arbitrary body fields, tools, API key, prior response ID or output-token parameter.
    body = json.dumps(
        {"model": model, "input": items, "store": False, "stream": True},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    if len(body) > 262144:
        raise LLMInvalidRequestError("bridge_request_too_large")
    return body


async def bounded_json(response, limit=262144):
    if response.headers.get("content-encoding", "identity") != "identity":
        raise LLMInvalidResponseError("bridge_response_encoding_unsupported")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise LLMInvalidResponseError("bridge_response_too_large")
    try:
        data = decode_json(body)
    except (ValueError, UnicodeError, RecursionError):
        raise LLMInvalidResponseError("bridge_response_invalid") from None
    if not isinstance(data, dict):
        raise LLMInvalidResponseError("bridge_response_invalid")
    return data


async def sse_objects(response) -> AsyncIterator[dict]:
    """Bound bytes before splitting lines; httpx's line iterator alone is unbounded."""
    pending = bytearray()
    event_lines = []
    event_size = 0
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > 2 * 1024 * 1024:
            raise LLMInvalidResponseError("bridge_stream_too_large")
        pending.extend(chunk)
        while b"\n" in pending:
            line, _, rest = pending.partition(b"\n")
            pending = bytearray(rest)
            line = line.rstrip(b"\r")
            if len(line) > 131072:
                raise LLMInvalidResponseError("bridge_event_too_large")
            if not line:
                if event_lines:
                    raw = b"\n".join(event_lines)
                    try:
                        data = decode_json(raw)
                    except (ValueError, UnicodeError, RecursionError):
                        raise LLMInvalidResponseError("bridge_event_invalid") from None
                    if not isinstance(data, dict):
                        raise LLMInvalidResponseError("bridge_event_invalid")
                    yield data
                event_lines, event_size = [], 0
            elif line.startswith(b"data:"):
                event_size += len(line)
                if event_size > 262144:
                    raise LLMInvalidResponseError("bridge_event_too_large")
                event_lines.append(line[5:].lstrip(b" "))
        if len(pending) > 131072:
            raise LLMInvalidResponseError("bridge_event_too_large")
    if pending or event_lines:
        raise LLMInvalidResponseError("bridge_stream_truncated")


class ChatGPTResponses:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    def _client(self):
        return httpx.AsyncClient(
            transport=self.transport,
            timeout=10,
            follow_redirects=False,
            trust_env=False,
            headers={"Accept-Encoding": "identity"},
        )

    async def discover(self, access_token: str) -> tuple[VisibleModel, ...]:
        try:
            async with (
                asyncio.timeout(10),
                self._client() as client,
                client.stream(
                    "GET",
                    RESOURCE + "/models",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                    },
                ) as response,
            ):
                data = await bounded_json(response)
                if response.status_code != 200:
                    raise classify_error(data, response.status_code)
            models = data["models"]
            if not isinstance(models, list) or len(models) > 256:
                raise ValueError()
            result = []
            seen = set()
            for model in models:
                if not isinstance(model, dict):
                    raise TypeError()
                if model.get("visibility") != "list":
                    continue
                slug, name = model["slug"], model["display_name"]
                if (
                    not isinstance(slug, str)
                    or not 1 <= len(slug) <= 200
                    or any(
                        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                        "0123456789._:/-"
                        for c in slug
                    )
                    or not isinstance(name, str)
                    or not 1 <= len(name) <= 200
                    or any(ord(c) < 32 for c in name)
                    or slug in seen
                ):
                    raise ValueError()
                seen.add(slug)
                result.append(VisibleModel(slug, name))
            return tuple(result)
        except (ValueError, KeyError, TypeError, LLMInvalidResponseError):
            raise BridgeProviderFailure("bridge_catalog_invalid") from None
        except (httpx.HTTPError, TimeoutError):
            raise BridgeProviderFailure("bridge_unavailable") from None

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        access_token: str,
        connection_id: str,
        invocation_id: str,
        max_output_bytes: int,
        timeout_seconds: float,
    ) -> AsyncIterator[GenerationEvent]:
        body = serialize(messages, model)
        identity = ProviderIdentity(PROVIDER, model, SERIALIZER)
        provenance = ExecutionProvenance(
            "connected_provider", "bridge_observed", PROVIDER, model, connection_id
        )

        def terminal(status, code=None, usage=None):
            return GenerationEvent.terminal(
                GenerationMetadata(
                    status,
                    identity,
                    usage=usage,
                    error_code=code,
                    invocation_id=invocation_id,
                    provenance=provenance,
                )
            )

        emitted_bytes = 0
        terminal_event = None
        response_id = None
        text_parts = []
        try:
            async with (
                asyncio.timeout(timeout_seconds),
                self._client() as client,
                client.stream(
                    "POST",
                    RESOURCE + "/responses",
                    content=body,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    data = await bounded_json(response)
                    error = classify_error(data, response.status_code)
                    # A generic server/gateway error does not establish that the
                    # provider rejected admission before doing work. Documented
                    # subscription admission errors remain explicit rejections.
                    raw_error = data.get("error")
                    documented = (
                        isinstance(raw_error, dict)
                        and isinstance(raw_error.get("code"), str)
                        and raw_error["code"] in ERROR_CODES
                    )
                    if response.status_code >= 500 and not documented:
                        yield terminal("incomplete", "bridge_transport_unknown")
                    else:
                        yield terminal("rejected", error.code)
                    return
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise LLMInvalidResponseError("bridge_stream_invalid")
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise LLMInvalidResponseError("bridge_stream_encoding_unsupported")
                async for data in sse_objects(response):
                    if terminal_event is not None:
                        raise LLMInvalidResponseError("bridge_event_after_terminal")
                    kind = data.get("type")
                    if kind == "response.created":
                        created = data.get("response", {})
                        if (
                            not isinstance(created, dict)
                            or response_id is not None
                            or not isinstance(created.get("id"), str)
                            or not 1 <= len(created["id"]) <= 200
                        ):
                            raise LLMInvalidResponseError("bridge_response_invalid")
                        response_id = created["id"]
                    elif kind == "response.output_text.delta":
                        delta = data.get("delta")
                        if response_id is None or not isinstance(delta, str) or not delta:
                            raise LLMInvalidResponseError("bridge_delta_invalid")
                        emitted_bytes += len(delta.encode())
                        if emitted_bytes > max_output_bytes:
                            yield terminal("incomplete", "bridge_output_bound")
                            return
                        text_parts.append(delta)
                        yield GenerationEvent.text_delta(delta)
                    elif kind in {"response.completed", "response.incomplete", "response.failed"}:
                        result = data.get("response")
                        if not isinstance(result, dict) or result.get("id") != response_id:
                            raise LLMInvalidResponseError("bridge_response_invalid")
                        if result.get("model") != model:
                            raise LLMInvalidResponseError("bridge_model_mismatch")
                        if kind == "response.completed":
                            if result.get("status") != "completed" or not emitted_bytes:
                                raise LLMInvalidResponseError("bridge_completion_invalid")
                            output = result.get("output")
                            if not isinstance(output, list) or len(output) > 256:
                                raise LLMInvalidResponseError("bridge_completion_invalid")
                            final_text = []
                            for item in output:
                                if not isinstance(item, dict):
                                    raise LLMInvalidResponseError("bridge_completion_invalid")
                                if item.get("type") == "reasoning":
                                    continue
                                if item.get("type") != "message" or item.get("role") != "assistant":
                                    raise LLMInvalidResponseError("bridge_output_unsupported")
                                content = item.get("content")
                                if not isinstance(content, list) or len(content) > 256:
                                    raise LLMInvalidResponseError("bridge_completion_invalid")
                                for part in content:
                                    if (
                                        not isinstance(part, dict)
                                        or part.get("type") != "output_text"
                                        or not isinstance(part.get("text"), str)
                                    ):
                                        raise LLMInvalidResponseError("bridge_output_unsupported")
                                    final_text.append(part["text"])
                            if "".join(final_text) != "".join(text_parts):
                                raise LLMInvalidResponseError("bridge_terminal_text_mismatch")
                            usage = result.get("usage")
                            normalized = None
                            if usage is not None:
                                if not isinstance(usage, dict) or any(
                                    type(usage.get(k)) is not int or not 0 <= usage[k] <= 10**9
                                    for k in ("input_tokens", "output_tokens", "total_tokens")
                                ):
                                    raise LLMInvalidResponseError("bridge_usage_invalid")
                                normalized = UsageMetadata(
                                    usage["input_tokens"],
                                    usage["output_tokens"],
                                    usage["total_tokens"],
                                )
                            terminal_event = terminal("success", usage=normalized)
                        elif kind == "response.incomplete":
                            if result.get("status") != "incomplete":
                                raise LLMInvalidResponseError("bridge_completion_invalid")
                            terminal_event = terminal("incomplete", "bridge_incomplete")
                        else:
                            if result.get("status") != "failed":
                                raise LLMInvalidResponseError("bridge_completion_invalid")
                            terminal_event = terminal("failure", classify_error(result).code)
                    elif kind == "error":
                        terminal_event = terminal(
                            "failure",
                            classify_error(
                                {
                                    "error": data,
                                }
                            ).code,
                        )
                    elif kind in {"response.output_item.added", "response.output_item.done"}:
                        item = data.get("item")
                        if not isinstance(item, dict) or item.get("type") not in {
                            "message",
                            "reasoning",
                        }:
                            raise LLMInvalidResponseError("bridge_tool_unsupported")
                    elif kind in {"response.content_part.added", "response.content_part.done"}:
                        part = data.get("part")
                        if not isinstance(part, dict) or part.get("type") != "output_text":
                            raise LLMInvalidResponseError("bridge_output_unsupported")
                    elif kind in {"response.refusal.delta", "response.refusal.done"}:
                        terminal_event = terminal("rejected", "bridge_rejected")
                    elif kind not in {
                        "response.in_progress",
                        "response.output_text.done",
                        "response.reasoning_summary_part.added",
                        "response.reasoning_summary_part.done",
                        "response.reasoning_summary_text.delta",
                        "response.reasoning_summary_text.done",
                        "response.reasoning_text.delta",
                        "response.reasoning_text.done",
                    }:
                        raise LLMInvalidResponseError("bridge_event_invalid")
                yield terminal_event or terminal("incomplete", "bridge_terminal_missing")
        except TimeoutError:
            yield terminal("incomplete", "bridge_timeout_unknown")
        except httpx.HTTPError:
            yield terminal("incomplete", "bridge_transport_unknown")
        except (LLMInvalidResponseError, UnicodeError, RecursionError, ValueError, TypeError):
            yield terminal("incomplete", "bridge_protocol_invalid")
