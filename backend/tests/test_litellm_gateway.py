"""Personal AI contracts exercised through the pinned LiteLLM SDK path."""

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import ValidationError

from personal_ai.llm import (
    ChatMessage,
    CloudflareWorkersAILLMClient,
    GeminiLLMClient,
    GroqLLMClient,
    InferenceContext,
    LLMIncompleteGenerationError,
    LLMInvalidConfigurationError,
    LLMInvalidRequestError,
    LLMInvalidResponseError,
    LLMRateLimitedError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMUnsupportedCapabilityError,
)
from personal_ai.llm.client import SYSTEM_INSTRUCTION
from personal_ai.llm.context import GeminiTokenCounter
from personal_ai.llm.litellm_gateway import LITELLM_VERSION, LiteLLMEmbeddingClient
from personal_ai.settings import Settings


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "ai_provider": "gemini",
        "ai_model": "gemini-2.5-flash",
        "ai_api_key": "fixture-gemini-key",
        "app_environment": "test",
    }
    values.update(overrides)
    return Settings(**values)


def _groq_settings(**overrides) -> Settings:
    values = {
        "groq_adapter_enabled": True,
        "groq_model": "fixture-model",
        "groq_api_key": "fixture-groq-key",
        "groq_free_tier_verified": True,
        "groq_privacy_approved": True,
        "groq_privacy_max_sensitivity": "personal",
        "groq_approved_model_aliases": ("fixture-model-rev2",),
        "groq_structured_output_verified": True,
        "groq_preflight_reference": "synthetic-fixture-only",
    }
    values.update(overrides)
    return _settings(**values)


def _cloudflare_settings(**overrides) -> Settings:
    values = {
        "cloudflare_adapter_enabled": True,
        "cloudflare_account_id": "a" * 32,
        "cloudflare_model": "@cf/meta/llama-fixture",
        "cloudflare_api_token": "fixture-cloudflare-token",
        "cloudflare_free_tier_verified": True,
        "cloudflare_privacy_approved": True,
        "cloudflare_privacy_max_sensitivity": "personal",
        "cloudflare_approved_model_aliases": ("@cf/meta/llama-fixture-v2",),
        "cloudflare_structured_output_verified": True,
        "cloudflare_preflight_reference": "synthetic-fixture-only",
    }
    values.update(overrides)
    return _settings(**values)


def _context(sensitivity="personal") -> InferenceContext:
    return InferenceContext(
        effective_sensitivity=sensitivity,
        maximum_sensitivity=sensitivity,
        policy_version="test-policy-v1",
    )


def _response(provider: str, *, text="answer", model=None, usage=True):
    if provider == "gemini":
        payload = {
            "modelVersion": model or "gemini-2.5-flash",
            "candidates": [{
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": "STOP",
            }],
        }
        if usage:
            payload["usageMetadata"] = {
                "promptTokenCount": 4,
                "candidatesTokenCount": 2,
                "totalTokenCount": 6,
            }
        return payload
    model_id = model or (
        "fixture-model" if provider == "groq" else "@cf/meta/llama-fixture"
    )
    payload = {
        "id": "fixture-response-id",
        "object": "chat.completion",
        "created": 1,
        "model": model_id,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
    }
    if usage:
        payload["usage"] = {
            "prompt_tokens": 4,
            "completion_tokens": 2,
            "total_tokens": 6,
        }
    return payload


def _adapter(provider, transport_factory, *, async_mode=False, settings=None):
    settings = settings or {
        "gemini": _settings,
        "groq": _groq_settings,
        "cloudflare_workers_ai": _cloudflare_settings,
    }[provider]()
    keyword = "async_transport_factory" if async_mode else "sync_transport_factory"
    options = {keyword: transport_factory}
    cls = {
        "gemini": GeminiLLMClient,
        "groq": GroqLLMClient,
        "cloudflare_workers_ai": CloudflareWorkersAILLMClient,
    }[provider]
    return cls(settings, **options)


def _model(provider):
    return {
        "gemini": "gemini-2.5-flash",
        "groq": "fixture-model",
        "cloudflare_workers_ai": "@cf/meta/llama-fixture",
    }[provider]


def test_dependency_is_exactly_pinned_and_sdk_version_is_checked():
    from importlib.metadata import version

    assert version("litellm") == LITELLM_VERSION == "1.102.1"


def test_gemini_count_and_structured_generation_share_pinned_transformation():
    captured = []
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    messages = [ChatMessage("system", "Return strict JSON."), ChatMessage("user", "hello")]

    def handle(request):
        body = json.loads(request.content)
        captured.append((request, body))
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 41})
        return httpx.Response(200, json=_response("gemini", text='{"ok":true}', usage=False))

    counter = GeminiTokenCounter(
        _settings(), sync_transport_factory=lambda: httpx.MockTransport(handle)
    )
    generator = GeminiLLMClient(
        _settings(), sync_transport_factory=lambda: httpx.MockTransport(handle)
    )
    count = counter.count(messages, response_schema=schema, inference_context=_context())
    result = generator.generate_structured(
        messages,
        response_schema=schema,
        max_output_tokens=20,
        timeout_seconds=3,
        inference_context=_context(),
    )

    count_request, count_body = captured[0]
    generation_request, generation_body = captured[1]
    counted = count_body["generateContentRequest"]
    assert count_request.url.path.endswith(":countTokens")
    assert generation_request.url.path.endswith(":generateContent")
    assert count_request.headers["x-goog-api-key"] == "fixture-gemini-key"
    assert generation_request.headers["x-goog-api-key"] == "fixture-gemini-key"
    assert count.provider_id == "gemini"
    assert count.model_id == "gemini-2.5-flash"
    assert count.serializer_id == "gemini-content-v1"
    assert count.confidence == "authoritative"
    assert counted["system_instruction"]["parts"][0]["text"] == (
        SYSTEM_INSTRUCTION + "\n\nReturn strict JSON."
    )
    assert counted["system_instruction"] == generation_body["system_instruction"]
    assert counted["contents"] == generation_body["contents"]
    assert counted["generationConfig"]["response_json_schema"] == schema
    assert generation_body["generationConfig"]["response_json_schema"] == schema
    assert generation_body["generationConfig"]["max_output_tokens"] == 20
    assert result.text == '{"ok":true}'
    assert result.metadata.usage is None


@pytest.mark.parametrize(
    ("provider", "url", "auth_header", "auth_value", "token_field"),
    [
        (
            "groq",
            "https://api.groq.com/openai/v1/chat/completions",
            "authorization",
            "Bearer fixture-groq-key",
            "max_tokens",
        ),
        (
            "cloudflare_workers_ai",
            "https://api.cloudflare.com/client/v4/accounts/"
            + "a" * 32
            + "/ai/v1/chat/completions",
            "authorization",
            "Bearer fixture-cloudflare-token",
            "max_tokens",
        ),
    ],
)
def test_openai_compatible_providers_use_explicit_sdk_endpoint_and_schema(
    provider, url, auth_header, auth_value, token_field
):
    requests = []
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=_response(provider, text='{"ok":true}'),
            headers={"x-ratelimit-remaining-tokens": "91"},
        )

    adapter = _adapter(
        provider, lambda: httpx.MockTransport(handle)
    )
    result = adapter.generate_structured(
        [ChatMessage("system", "Only return JSON."), ChatMessage("user", "hello")],
        response_schema=schema,
        max_output_tokens=19,
        timeout_seconds=4,
        inference_context=_context(),
    )

    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == url
    assert request.headers[auth_header] == auth_value
    assert body["model"] == _model(provider)
    assert body[token_field] == 19
    if provider == "cloudflare_workers_ai":
        assert body["response_format"] == {
            "type": "json_schema",
            "json_schema": schema,
        }
        assert "tools" not in body
    else:
        assert body["tools"] == [{
            "type": "function",
            "function": {
                "name": "json_tool_call",
                "parameters": schema,
            },
        }]
        assert body["tool_choice"] == {
            "type": "function",
            "function": {"name": "json_tool_call"},
        }
    serialized = json.dumps(body)
    assert "Only return JSON." in serialized
    assert "fixture-groq-key" not in serialized
    assert "fixture-cloudflare-token" not in serialized
    assert result.text == '{"ok":true}'
    assert result.metadata.identity.provider_id == provider
    assert result.metadata.usage.confidence == "reported"
    assert result.metadata.rate_limits.tokens_remaining == 91


def test_gemini_schema_dropped_by_unknown_model_is_rejected_before_send():
    calls = []
    adapter = GeminiLLMClient(
        _settings(ai_model="unknown-fixture-model"),
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda request: (calls.append(request), httpx.Response(200, json={}))[1]
        ),
    )

    with pytest.raises(LLMUnsupportedCapabilityError, match="required structured schema"):
        adapter.generate_structured(
            [ChatMessage("user", "hello")],
            response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            max_output_tokens=10,
            timeout_seconds=3,
            inference_context=_context(),
        )

    assert calls == []


@pytest.mark.parametrize("provider", ["gemini", "groq", "cloudflare_workers_ai"])
def test_missing_or_unapproved_returned_model_identity_fails_closed(provider):
    payload = _response(provider)
    if provider == "gemini":
        payload.pop("modelVersion")
    else:
        payload["model"] = "unapproved-model"
    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(LLMInvalidResponseError):
        adapter.complete(
            [ChatMessage("user", "hello")],
            max_output_tokens=20,
            timeout_seconds=3,
            inference_context=_context(),
        )


@pytest.mark.parametrize("provider", ["gemini", "groq", "cloudflare_workers_ai"])
def test_unreported_usage_stays_unknown(provider):
    payload = _response(provider, usage=False)
    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    result = adapter.complete(
        [ChatMessage("user", "hello")],
        max_output_tokens=20,
        timeout_seconds=3,
        inference_context=_context(),
    )

    if provider == "cloudflare_workers_ai":
        assert result.metadata.usage.source == "estimated"
        assert result.metadata.usage.confidence == "estimated"
    else:
        assert result.metadata.usage is None


def _stream_payload(provider, *, include_done=True):
    if provider == "gemini":
        events = [
            {
                "modelVersion": _model(provider),
                "candidates": [{
                    "content": {"role": "model", "parts": [{"text": "hello"}]},
                    "finishReason": "STOP",
                }],
                "usageMetadata": {
                    "promptTokenCount": 4,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 6,
                },
            }
        ]
        return b"".join(
            b"data: " + json.dumps(event).encode() + b"\n\n" for event in events
        )
    model = _model(provider)
    events = [
        {
            "id": "chunk-1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}],
        },
        {
            "id": "chunk-2",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]
    if not include_done:
        return b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)
    return (
        b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)
        + b"data: [DONE]\n\n"
    )


class _ChunkedAsyncByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, block_after=False):
        self.chunks = chunks
        self.block_after = block_after
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.block_after:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def _openai_stream_event(model, content=None, finish_reason=None):
    delta = {} if content is None else {"content": content}
    return {
        "id": "fixture-chunk",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _sse(payload):
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


@pytest.mark.parametrize("provider", ["gemini", "groq", "cloudflare_workers_ai"])
def test_streaming_uses_sdk_and_preserves_terminal_and_usage(provider):
    body = _stream_payload(provider)
    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
        ),
        async_mode=True,
    )

    async def collect():
        return [event async for event in adapter.stream_events(
            [ChatMessage("user", "hello")],
            max_output_tokens=20,
            timeout_seconds=3,
            inference_context=_context(),
        )]

    events = asyncio.run(collect())
    terminal = events[-1]
    assert terminal.kind == "terminal"
    assert terminal.metadata.status == "success"
    assert terminal.metadata.identity.provider_id == provider
    assert terminal.metadata.identity.model_id == _model(provider)
    if provider == "gemini":
        assert terminal.metadata.usage.confidence == "reported"
    else:
        assert terminal.metadata.usage is None
    assert any(event.kind == "delta" and event.delta == "hello" for event in events)


def test_openai_stream_without_done_is_incomplete():
    body = _stream_payload("groq", include_done=False)
    adapter = _adapter(
        "groq",
        lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})
        ),
        async_mode=True,
    )

    async def collect():
        return [event async for event in adapter.stream_events(
            [ChatMessage("user", "hello")],
            max_output_tokens=20,
            timeout_seconds=3,
            inference_context=_context(),
        )]

    events = asyncio.run(collect())
    assert events[-1].metadata.status == "incomplete"

    async def consume_text():
        return [delta async for delta in adapter.stream(
            [ChatMessage("user", "hello")], inference_context=_context()
        )]

    with pytest.raises(LLMIncompleteGenerationError):
        asyncio.run(consume_text())


def test_cancelling_sdk_stream_closes_the_underlying_response():
    closed = []

    class BlockingResponseStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            payload = {
                "modelVersion": "gemini-2.5-flash",
                "candidates": [{
                    "content": {"role": "model", "parts": [{"text": "partial"}]},
                    "finishReason": None,
                }],
            }
            yield b"data: " + json.dumps(payload).encode() + b"\n\n"
            await asyncio.Event().wait()

        async def aclose(self):
            closed.append(True)

    adapter = GeminiLLMClient(
        _settings(),
        async_transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                stream=BlockingResponseStream(),
                headers={"content-type": "text/event-stream"},
            )
        ),
    )

    async def scenario():
        events = adapter.stream_events(
            [ChatMessage("user", "hello")],
            max_output_tokens=10,
            timeout_seconds=3,
            inference_context=_context(),
        )
        first = await anext(events)
        await events.aclose()
        return first

    first = asyncio.run(scenario())
    assert first.kind == "delta" and first.delta == "partial"
    assert closed


@pytest.mark.parametrize("provider", ["gemini", "groq", "cloudflare_workers_ai"])
def test_429_timeout_and_known_failure_make_at_most_one_send(provider):
    for status, error_type in (
        (429, LLMRateLimitedError),
        (503, LLMUnavailableError),
        (302, LLMUnavailableError),
    ):
        calls = []

        def respond(request, status=status, calls=calls):
            calls.append(request)
            return httpx.Response(
                status,
                headers={"retry-after": "2"},
                json={"error": {"message": "private provider body"}},
            )

        adapter = _adapter(provider, lambda respond=respond: httpx.MockTransport(respond))
        with pytest.raises(error_type) as raised:
            adapter.complete(
                [ChatMessage("user", "prompt-secret")],
                max_output_tokens=10,
                timeout_seconds=2,
                inference_context=_context(),
            )
        assert len(calls) == 1
        assert "private provider body" not in str(raised.value)
        if status == 429:
            assert raised.value.rate_limits.retry_after_seconds == 2

    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret timeout detail")

    adapter = _adapter(provider, lambda: httpx.MockTransport(timeout))
    with pytest.raises(LLMTimeoutError) as raised:
        adapter.complete(
            [ChatMessage("user", "prompt-secret")],
            max_output_tokens=10,
            timeout_seconds=2,
            inference_context=_context(),
        )
    assert len(calls) == 1
    assert "secret timeout detail" not in str(raised.value)


def test_gemini_request_and_completion_bounds_precede_sdk_parsing(monkeypatch):
    import personal_ai.llm.litellm_gateway as gateway

    monkeypatch.setattr(gateway, "_MAX_COMPLETION_RESPONSE_BYTES", 256)
    response_secret = "response-secret-" * 200
    adapter = GeminiLLMClient(
        _settings(),
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, json=_response("gemini", text=response_secret))
        ),
    )
    with pytest.raises(LLMInvalidResponseError, match="size limit") as raised:
        adapter.complete(
            [ChatMessage("user", "hello")],
            max_output_tokens=20,
            timeout_seconds=3,
            inference_context=_context(),
        )
    assert response_secret not in str(raised.value)

    called = []
    request_adapter = GeminiLLMClient(
        _settings(),
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda request: (called.append(request), httpx.Response(200, json={}))[-1]
        ),
    )
    with pytest.raises(LLMInvalidRequestError, match="size limit"):
        request_adapter.complete(
            [ChatMessage("user", "x" * (2 * 1024 * 1024 + 1))],
            max_output_tokens=20,
            timeout_seconds=3,
            inference_context=_context(),
        )
    assert called == []


def test_stream_line_and_event_caps_stop_before_sdk_parsing(monkeypatch):
    import personal_ai.llm.litellm_gateway as gateway

    monkeypatch.setattr(gateway, "_MAX_STREAM_LINE_BYTES", 256)
    monkeypatch.setattr(gateway, "_MAX_STREAM_EVENT_BYTES", 256)
    long_event = (
        b"data: "
        + json.dumps({"model": "fixture-model", "choices": [], "padding": "x" * 500}).encode()
        + b"\n\n"
    )
    adapter = GroqLLMClient(
        _groq_settings(),
        async_transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, content=long_event)
        ),
    )

    async def consume():
        return [event async for event in adapter.stream_events(
            [ChatMessage("user", "hello")],
            max_output_tokens=10,
            timeout_seconds=3,
            inference_context=_context(),
        )]

    with pytest.raises(LLMInvalidResponseError, match="size limit"):
        asyncio.run(consume())


def test_total_stream_cap_stops_many_small_events_before_sdk_parsing(monkeypatch):
    import personal_ai.llm.litellm_gateway as gateway

    monkeypatch.setattr(gateway, "_MAX_STREAM_RESPONSE_BYTES", 256)
    event = {
        "model": "fixture-model",
        "choices": [{"index": 0, "delta": {"content": "x"}, "finish_reason": None}],
    }
    body = (b"data: " + json.dumps(event).encode() + b"\n\n") * 5
    adapter = GroqLLMClient(
        _groq_settings(),
        async_transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, content=body)
        ),
    )

    async def consume():
        return [event async for event in adapter.stream_events(
            [ChatMessage("user", "hello")], max_output_tokens=10,
            timeout_seconds=3, inference_context=_context(),
        )]

    with pytest.raises(LLMInvalidResponseError, match="size limit"):
        asyncio.run(consume())


def test_external_provider_preflight_blocks_dispatch_and_structured_capability():
    called = []
    transport = lambda: httpx.MockTransport(
        lambda request: (called.append(request), httpx.Response(200, json=_response("groq")))[-1]
    )
    disabled = GroqLLMClient(
        _groq_settings(groq_adapter_enabled=False), sync_transport_factory=transport
    )
    with pytest.raises(LLMInvalidConfigurationError, match="disabled"):
        disabled.complete(
            [ChatMessage("user", "hello")], max_output_tokens=5,
            timeout_seconds=2, inference_context=_context(),
        )
    assert called == []

    not_structured = GroqLLMClient(
        _groq_settings(groq_structured_output_verified=False), sync_transport_factory=transport
    )
    with pytest.raises(LLMUnsupportedCapabilityError):
        not_structured.generate_structured(
            [ChatMessage("user", "hello")], response_schema={"type": "object"},
            max_output_tokens=5, timeout_seconds=2, inference_context=_context(),
        )
    assert called == []


@pytest.mark.parametrize(
    "provider_fields",
    [{"groq_adapter_enabled": True}, {"cloudflare_adapter_enabled": True}],
)
def test_enabled_external_provider_requires_preflight_configuration(provider_fields):
    with pytest.raises(ValidationError, match="provider_preflight_required"):
        _settings(**provider_fields)


def test_groq_and_cloudflare_are_generation_only_for_authoritative_count_workflows():
    groq = GroqLLMClient(_groq_settings())
    cloudflare = CloudflareWorkersAILLMClient(_cloudflare_settings())
    assert not groq.capabilities.supports("token_counting")
    assert not cloudflare.capabilities.supports("token_counting")


def test_ambient_hooks_fail_closed_and_disabled_logging_and_cache_hold(caplog, monkeypatch):
    import personal_ai.llm.litellm_gateway as gateway

    sdk = gateway._load_litellm()
    monkeypatch.setattr(sdk, "callbacks", ["external_callback"])
    called = []
    adapter = GeminiLLMClient(
        _settings(),
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda request: (called.append(request), httpx.Response(200, json=_response("gemini")))[-1]
        ),
    )
    with pytest.raises(LLMInvalidConfigurationError, match="content hooks"):
        adapter.complete(
            [ChatMessage("user", "prompt-canary")], max_output_tokens=5,
            timeout_seconds=2, inference_context=_context(),
        )
    assert called == []

    monkeypatch.setattr(sdk, "callbacks", [])
    monkeypatch.setenv("GEMINI_API_KEY", "ambient-key-canary")
    response_secret = "response-canary"
    adapter = GeminiLLMClient(
        _settings(ai_api_key="explicit-key-canary"),
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, json=_response("gemini", text=response_secret))
        ),
    )
    with caplog.at_level(logging.DEBUG):
        result = adapter.complete(
            [ChatMessage("user", "prompt-canary")], max_output_tokens=5,
            timeout_seconds=2, inference_context=_context(),
        )
    assert result.text == response_secret
    assert sdk.callbacks == []
    assert sdk.cache is None
    for canary in ("prompt-canary", response_secret, "explicit-key-canary", "ambient-key-canary"):
        assert canary not in caplog.text


def test_concurrent_cloudflare_calls_keep_account_and_token_isolated():
    captured = []

    def call(pair):
        account, token = pair
        settings = _cloudflare_settings(
            cloudflare_account_id=account,
            cloudflare_api_token=token,
        )

        def handle(request):
            captured.append((str(request.url), request.headers.get("authorization")))
            return httpx.Response(200, json=_response("cloudflare_workers_ai"))

        adapter = CloudflareWorkersAILLMClient(
            settings, sync_transport_factory=lambda: httpx.MockTransport(handle)
        )
        return adapter.complete(
            [ChatMessage("user", "isolated")], max_output_tokens=5,
            timeout_seconds=2, inference_context=_context(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(call, [("1" * 32, "token-one"), ("2" * 32, "token-two")]))

    assert [result.metadata.status for result in results] == ["success", "success"]
    assert sorted(captured) == sorted([
        ("https://api.cloudflare.com/client/v4/accounts/" + "1" * 32 + "/ai/v1/chat/completions", "Bearer token-one"),
        ("https://api.cloudflare.com/client/v4/accounts/" + "2" * 32 + "/ai/v1/chat/completions", "Bearer token-two"),
    ])


def test_gemini_embeddings_use_litellm_and_preserve_persisted_space():
    requests = []

    def handle(request):
        requests.append((request, json.loads(request.content)))
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"embeddings": [{"values": [3, 0, 0]} for _ in body["requests"]]},
        )

    embedder = LiteLLMEmbeddingClient(
        _settings(memory_embedding_dimensions=3, memory_embedding_batch_size=2),
        sync_transport_factory=lambda: httpx.MockTransport(handle),
    )
    documents = embedder.embed(["one", "two", "three"], inference_context=_context())
    query = embedder.embed(["query"], query=True, inference_context=_context())

    assert [len(body["requests"]) for _, body in requests] == [2, 1, 1]
    assert requests[0][0].url.path.endswith(":batchEmbedContents")
    assert all(body["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT" for _, body in requests[:2])
    assert requests[-1][1]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    assert documents[0].values == (1.0, 0.0, 0.0)
    assert query[0].values == (1.0, 0.0, 0.0)
    assert documents[0].space.provider_id == "google_genai"
    assert documents[0].space.model_id == "gemini-embedding-001"
    assert documents[0].space.dimensions == 3
    assert documents[0].space.normalization == "l2"
    assert documents[0].space.version == "v1"
    assert documents[0].task == "document"
    assert query[0].task == "query"


@pytest.mark.parametrize("provider", ["gemini", "groq", "cloudflare_workers_ai"])
def test_chunked_streams_drain_to_eof_and_allow_split_done_and_usage(provider):
    import personal_ai.llm.litellm_gateway as gateway

    body = _stream_payload(provider)
    if provider != "gemini":
        done_marker = b"data: [DONE]\n\n"
        usage = _sse({
            "id": "usage",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": _model(provider),
            "choices": [],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        })
        body = body.replace(done_marker, usage + done_marker)
    if provider == "gemini":
        midpoint = len(body) // 2
        chunks = [body[:midpoint], body[midpoint:]]
    else:
        head, _ = body.rsplit(b"data: [DONE]\n\n", 1)
        chunks = [head, b"data: [DO", b"NE]\n\n"]
    source = _ChunkedAsyncByteStream(chunks)
    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200, stream=source, headers={"content-type": "text/event-stream"}
            )
        ),
        async_mode=True,
    )

    async def collect():
        return [event async for event in adapter.stream_events(
            [ChatMessage("user", "hello")], max_output_tokens=20,
            timeout_seconds=3, inference_context=_context(),
        )]

    events = asyncio.run(collect())
    terminal = events[-1]
    assert terminal.kind == "terminal"
    assert terminal.metadata.status == "success"
    assert terminal.metadata.identity.model_id == _model(provider)
    assert sum(event.kind == "terminal" for event in events) == 1
    assert source.closed
    if provider != "gemini":
        assert terminal.metadata.usage.confidence == "reported"
    assert gateway._MAX_STREAM_RESPONSE_BYTES > len(body)


@pytest.mark.parametrize("provider", ["groq", "cloudflare_workers_ai"])
def test_stream_deadline_closes_a_reader_blocked_after_done(provider):
    source = _ChunkedAsyncByteStream([_stream_payload(provider)], block_after=True)
    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                stream=source,
                headers={"content-type": "text/event-stream"},
            )
        ),
        async_mode=True,
    )

    async def collect():
        return [event async for event in adapter.stream_events(
            [ChatMessage("user", "hello")], max_output_tokens=20,
            timeout_seconds=0.1, inference_context=_context(),
        )]

    with pytest.raises(LLMTimeoutError):
        asyncio.run(collect())
    assert source.closed


@pytest.mark.parametrize("provider", ["groq", "cloudflare_workers_ai"])
@pytest.mark.parametrize("terminal_suffix", [b"data: [DONE]\n\ndata: [DONE]\n\n", b"data: [DONE]\n\ndata: {\"model\":\"fixture-model\",\"choices\":[]}\n\n"])
def test_chunked_openai_stream_rejects_duplicate_or_trailing_data(provider, terminal_suffix):
    body = _stream_payload(provider).replace(b"data: [DONE]\n\n", terminal_suffix)
    chunks = [body[index : index + 30] for index in range(0, len(body), 30)]
    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                stream=_ChunkedAsyncByteStream(chunks),
                headers={"content-type": "text/event-stream"},
            )
        ),
        async_mode=True,
    )

    async def collect():
        return [event async for event in adapter.stream_events(
            [ChatMessage("user", "hello")], max_output_tokens=20,
            timeout_seconds=3, inference_context=_context(),
        )]

    with pytest.raises(LLMInvalidResponseError):
        asyncio.run(collect())


@pytest.mark.parametrize("provider", ["gemini", "groq", "cloudflare_workers_ai"])
def test_unapproved_stream_identity_is_rejected_before_any_text(provider):
    if provider == "gemini":
        payload = {
            "modelVersion": "unapproved-model",
            "candidates": [{"content": {"parts": [{"text": "secret"}]}}],
        }
    else:
        payload = _openai_stream_event("unapproved-model", "secret")
    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                stream=_ChunkedAsyncByteStream([_sse(payload)]),
                headers={"content-type": "text/event-stream"},
            )
        ),
        async_mode=True,
    )
    deltas = []

    async def consume():
        async for event in adapter.stream_events(
            [ChatMessage("user", "hello")], max_output_tokens=20,
            timeout_seconds=3, inference_context=_context(),
        ):
            if event.kind == "delta":
                deltas.append(event.delta)

    with pytest.raises(LLMInvalidResponseError):
        asyncio.run(consume())
    assert deltas == []


@pytest.mark.parametrize("provider", ["groq", "cloudflare_workers_ai"])
def test_conflicting_stream_identity_withholds_that_events_text(provider):
    alias = "fixture-model-rev2" if provider == "groq" else "@cf/meta/llama-fixture-v2"
    body = (
        _sse(_openai_stream_event(_model(provider), "hello"))
        + _sse(_openai_stream_event(alias, "secret"))
        + b"data: [DONE]\n\n"
    )
    # The approved alias is still a conflicting identity within this response.
    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                stream=_ChunkedAsyncByteStream([body[: len(_sse(_openai_stream_event(_model(provider), "hello")))], body[len(_sse(_openai_stream_event(_model(provider), "hello"))) :]]),
                headers={"content-type": "text/event-stream"},
            )
        ),
        async_mode=True,
    )
    deltas = []

    async def consume():
        async for event in adapter.stream_events(
            [ChatMessage("user", "hello")], max_output_tokens=20,
            timeout_seconds=3, inference_context=_context(),
        ):
            if event.kind == "delta":
                deltas.append(event.delta)

    with pytest.raises(LLMInvalidResponseError):
        asyncio.run(consume())
    assert deltas == ["hello"]


@pytest.mark.parametrize("cache_loaded", [False, True])
def test_ambient_litellm_retries_fail_closed_before_dispatch(cache_loaded, monkeypatch):
    import personal_ai.llm.litellm_gateway as gateway

    sdk = gateway._load_litellm()
    monkeypatch.setattr(sdk, "num_retries", 1)
    monkeypatch.setattr(gateway, "_SDK", sdk if cache_loaded else None)
    calls = []
    adapter = GeminiLLMClient(
        _settings(),
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda request: (calls.append(request), httpx.Response(503, json={}))[-1]
        ),
    )
    with pytest.raises(LLMInvalidConfigurationError, match="runtime settings"):
        adapter.complete(
            [ChatMessage("user", "hello")], max_output_tokens=10,
            timeout_seconds=2, inference_context=_context(),
        )
    assert calls == []


def test_generation_transport_fences_sdk_replay_even_if_global_changes_mid_call(monkeypatch):
    import personal_ai.llm.litellm_gateway as gateway

    sdk = gateway._load_litellm()
    monkeypatch.setattr(sdk, "num_retries", 1)
    monkeypatch.setattr(gateway, "_assert_litellm_runtime_safe", lambda: None)
    calls = []

    def unavailable(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "private"}})

    adapter = GeminiLLMClient(
        _settings(), sync_transport_factory=lambda: httpx.MockTransport(unavailable)
    )
    with pytest.raises(LLMUnavailableError):
        adapter.complete(
            [ChatMessage("user", "hello")], max_output_tokens=10,
            timeout_seconds=2, inference_context=_context(),
        )
    assert len(calls) == 1


def test_async_generation_transport_fences_sdk_replay(monkeypatch):
    import personal_ai.llm.litellm_gateway as gateway

    sdk = gateway._load_litellm()
    monkeypatch.setattr(sdk, "num_retries", 1)
    monkeypatch.setattr(gateway, "_assert_litellm_runtime_safe", lambda: None)
    calls = []

    def unavailable(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "private"}})

    adapter = GeminiLLMClient(
        _settings(),
        async_transport_factory=lambda: httpx.MockTransport(unavailable),
    )

    async def consume():
        return [event async for event in adapter.stream_events(
            [ChatMessage("user", "hello")], max_output_tokens=10,
            timeout_seconds=2, inference_context=_context(),
        )]

    with pytest.raises(LLMUnavailableError):
        asyncio.run(consume())
    assert len(calls) == 1


@pytest.mark.parametrize("provider", ["gemini", "groq", "cloudflare_workers_ai"])
@pytest.mark.parametrize(
    ("status", "error_type"),
    [(429, LLMRateLimitedError), (503, LLMUnavailableError)],
)
def test_async_generation_status_failures_make_one_physical_send(provider, status, error_type):
    calls = []

    def fail(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"retry-after": "2"},
            json={"error": {"message": "private provider detail"}},
        )

    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(fail),
        async_mode=True,
    )

    async def consume():
        return [event async for event in adapter.stream_events(
            [ChatMessage("user", "hello")], max_output_tokens=10,
            timeout_seconds=2, inference_context=_context(),
        )]

    with pytest.raises(error_type) as raised:
        asyncio.run(consume())
    assert len(calls) == 1
    assert "private provider detail" not in str(raised.value)


@pytest.mark.parametrize("provider", ["gemini", "groq", "cloudflare_workers_ai"])
@pytest.mark.parametrize("exception_type", [httpx.ReadTimeout, httpx.ConnectError])
def test_async_transport_failures_make_one_physical_send(provider, exception_type):
    calls = []

    def fail(request):
        calls.append(request)
        raise exception_type("private transport detail", request=request)

    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(fail),
        async_mode=True,
    )

    async def consume():
        return [event async for event in adapter.stream_events(
            [ChatMessage("user", "hello")], max_output_tokens=10,
            timeout_seconds=2, inference_context=_context(),
        )]

    expected = LLMTimeoutError if exception_type is httpx.ReadTimeout else LLMUnavailableError
    with pytest.raises(expected) as raised:
        asyncio.run(consume())
    assert len(calls) == 1
    assert "private transport detail" not in str(raised.value)


@pytest.mark.parametrize("provider", ["gemini", "groq", "cloudflare_workers_ai"])
def test_sync_generation_deadline_rejects_slow_success(provider):
    def slow_success(request):
        time.sleep(0.08)
        return httpx.Response(200, json=_response(provider))

    adapter = _adapter(
        provider,
        lambda: httpx.MockTransport(slow_success),
    )
    with pytest.raises(LLMTimeoutError):
        adapter.complete(
            [ChatMessage("user", "hello")], max_output_tokens=10,
            timeout_seconds=0.05, inference_context=_context(),
        )
    with pytest.raises(LLMTimeoutError):
        adapter.generate_structured(
            [ChatMessage("user", "hello")],
            response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            max_output_tokens=10,
            timeout_seconds=0.05,
            inference_context=_context(),
        )


def test_sync_generation_deadline_bounds_trickle_reads_and_parsing(monkeypatch):
    import personal_ai.llm.litellm_gateway as gateway

    class TrickleStream(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in (b'{"modelVersion":', b'"gemini-2.5-flash",', b'"candidates":[]}'):
                time.sleep(0.01)
                yield chunk

        def close(self):
            pass

    adapter = GeminiLLMClient(
        _settings(),
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, stream=TrickleStream())
        ),
    )
    with pytest.raises(LLMTimeoutError):
        adapter.complete(
            [ChatMessage("user", "hello")], max_output_tokens=10,
            timeout_seconds=0.02, inference_context=_context(),
        )

    sent = []
    adapter = GeminiLLMClient(
        _settings(),
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda request: (sent.append(request), httpx.Response(200, json=_response("gemini")))[-1]
        ),
    )
    original_arguments = gateway.LiteLLMGenerationClient._completion_arguments

    def slow_setup(self, *args, **kwargs):
        time.sleep(0.03)
        return original_arguments(self, *args, **kwargs)

    monkeypatch.setattr(gateway.LiteLLMGenerationClient, "_completion_arguments", slow_setup)
    with pytest.raises(LLMTimeoutError):
        adapter.complete(
            [ChatMessage("user", "hello")], max_output_tokens=10,
            timeout_seconds=0.02, inference_context=_context(),
        )
    assert sent == []

    adapter = GeminiLLMClient(
        _settings(),
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, json=_response("gemini"))
        ),
    )
    original_parse = gateway._parse_generation_wire

    def slow_parse(*args, **kwargs):
        time.sleep(0.03)
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(gateway, "_parse_generation_wire", slow_parse)
    with pytest.raises(LLMTimeoutError):
        adapter.complete(
            [ChatMessage("user", "hello")], max_output_tokens=10,
            timeout_seconds=0.02, inference_context=_context(),
        )


def test_embedding_text_prefixes_remain_literal_and_never_trigger_file_reads():
    texts = [
        "gs://bucket/example.pdf",
        "files/example-id",
        "data:image/png;base64,aaaa",
        "data:not-a-valid-media-uri",
        "ordinary prose",
    ]
    requests = []

    def handle(request):
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"embeddings": [{"values": [3, 0, 0]} for _ in body["requests"]]},
        )

    embedder = LiteLLMEmbeddingClient(
        _settings(memory_embedding_dimensions=3, memory_embedding_batch_size=5),
        sync_transport_factory=lambda: httpx.MockTransport(handle),
    )
    embedder.embed(texts, inference_context=_context())
    embedder.embed(texts, query=True, inference_context=_context())

    assert len(requests) == 2
    assert all(request.method == "POST" for request in requests)
    for request in requests:
        body = json.loads(request.content)
        assert [item["content"]["parts"] for item in body["requests"]] == [
            [{"text": text}] for text in texts
        ]
    document_body, query_body = [json.loads(request.content) for request in requests]
    assert document_body["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert query_body["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


def test_embedding_batch_response_limits_are_per_response_and_reset(monkeypatch):
    import personal_ai.llm.litellm_gateway as gateway

    monkeypatch.setattr(gateway, "_MAX_EMBEDDING_RESPONSE_BYTES", 64)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"embeddings": [{"values": [1, 0, 0]}]})

    embedder = LiteLLMEmbeddingClient(
        _settings(memory_embedding_dimensions=3, memory_embedding_batch_size=1),
        sync_transport_factory=lambda: httpx.MockTransport(handle),
    )
    results = embedder.embed(["one", "two", "three"], inference_context=_context())
    assert len(results) == len(requests) == 3
    assert len(json.dumps({"embeddings": [{"values": [1, 0, 0]}]}).encode()) < 64
    assert 3 * len(json.dumps({"embeddings": [{"values": [1, 0, 0]}]}).encode()) > 64

    calls = []

    def oversized_second(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"embeddings": [{"values": [1, 0, 0]}]})
        return httpx.Response(
            200,
            json={"embeddings": [{"values": [1, 0, 0], "padding": "x" * 128}]},
        )

    failing_embedder = LiteLLMEmbeddingClient(
        _settings(memory_embedding_dimensions=3, memory_embedding_batch_size=1),
        sync_transport_factory=lambda: httpx.MockTransport(oversized_second),
    )
    with pytest.raises(LLMInvalidResponseError, match="size limit"):
        failing_embedder.embed(["one", "two", "three"], inference_context=_context())
    assert len(calls) == 2


def test_embedding_deadline_is_forwarded_to_each_batch_and_stops_late_work():
    captured_timeouts = []
    calls = []

    def delayed(request):
        calls.append(request)
        captured_timeouts.append(request.extensions["timeout"]["read"])
        if len(calls) == 1:
            time.sleep(0.04)
        return httpx.Response(200, json={"embeddings": [{"values": [1, 0, 0]}]})

    embedder = LiteLLMEmbeddingClient(
        _settings(memory_embedding_dimensions=3, memory_embedding_batch_size=1),
        sync_transport_factory=lambda: httpx.MockTransport(delayed),
    )
    embedder.embed(["one", "two"], timeout=0.5, inference_context=_context())
    assert len(captured_timeouts) == 2
    assert captured_timeouts[1] < captured_timeouts[0]
    assert captured_timeouts[0] <= 0.5

    calls.clear()

    def exhaust_deadline(request):
        calls.append(request)
        if len(calls) == 1:
            time.sleep(0.22)
        return httpx.Response(200, json={"embeddings": [{"values": [1, 0, 0]}]})

    late_embedder = LiteLLMEmbeddingClient(
        _settings(memory_embedding_dimensions=3, memory_embedding_batch_size=1),
        sync_transport_factory=lambda: httpx.MockTransport(exhaust_deadline),
    )
    with pytest.raises(LLMTimeoutError):
        late_embedder.embed(
            ["one", "two", "three"], timeout=0.2, inference_context=_context()
        )
    assert len(calls) == 1

    class StalledBatch(httpx.SyncByteStream):
        def __iter__(self):
            time.sleep(0.2)
            yield b'{"embeddings":[{"values":[1,0,0]}]}'

        def close(self):
            pass

    calls.clear()
    second_batch_timeouts = []

    def stall_later_batch(request):
        calls.append(request)
        second_batch_timeouts.append(request.extensions["timeout"]["read"])
        if len(calls) == 1:
            return httpx.Response(200, json={"embeddings": [{"values": [1, 0, 0]}]})
        return httpx.Response(200, stream=StalledBatch())

    stalled_embedder = LiteLLMEmbeddingClient(
        _settings(memory_embedding_dimensions=3, memory_embedding_batch_size=1),
        sync_transport_factory=lambda: httpx.MockTransport(stall_later_batch),
    )
    with pytest.raises(LLMTimeoutError):
        stalled_embedder.embed(
            ["one", "two", "three"], timeout=0.15, inference_context=_context()
        )
    assert len(calls) == 2
    assert second_batch_timeouts[1] < second_batch_timeouts[0]


def test_cloudflare_schema_guard_rejects_openai_wrapped_shape():
    import personal_ai.llm.litellm_gateway as gateway

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    profile = gateway._provider_profile(_cloudflare_settings(), "cloudflare_workers_ai")
    assert gateway._request_preserves_schema(
        {"response_format": {"type": "json_schema", "json_schema": schema}},
        profile,
        schema,
    )
    assert not gateway._request_preserves_schema(
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "personal_ai_response",
                    "strict": False,
                    "schema": schema,
                },
            }
        },
        profile,
        schema,
    )
