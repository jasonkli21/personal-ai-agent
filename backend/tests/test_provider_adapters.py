"""Offline contract coverage for the Phase 17 reference provider adapters."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from personal_ai.llm import (
    ChatMessage,
    CloudflareWorkersAILLMClient,
    GenerationEvent,
    GroqLLMClient,
    InferenceContext,
    LLMInvalidConfigurationError,
    LLMInvalidRequestError,
    LLMRateLimitedError,
    LLMUnavailableError,
    LLMUnsupportedCapabilityError,
)
from personal_ai.settings import Settings


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "ai_provider": "gemini",
        "ai_model": "gemini-2.5-flash",
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
        "groq_structured_output_verified": True,
        "groq_preflight_reference": "offline-provider-fixture",
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
        "cloudflare_structured_output_verified": True,
        "cloudflare_preflight_reference": "offline-provider-fixture",
    }
    values.update(overrides)
    return _settings(**values)


def _inference_context() -> InferenceContext:
    return InferenceContext(
        effective_sensitivity="personal",
        maximum_sensitivity="personal",
        policy_version="test-policy-v1",
    )


def test_new_provider_live_gates_are_off_in_the_example_settings() -> None:
    settings = _settings()

    assert not settings.groq_adapter_enabled
    assert not settings.cloudflare_adapter_enabled
    assert not settings.groq_free_tier_verified
    assert not settings.cloudflare_free_tier_verified


@pytest.mark.parametrize("provider_fields", [
    {"groq_adapter_enabled": True},
    {"cloudflare_adapter_enabled": True},
])
def test_enabled_live_provider_requires_account_model_privacy_and_preflight(
    provider_fields,
) -> None:
    with pytest.raises(ValidationError, match="provider_preflight_required"):
        _settings(**provider_fields)


def test_disabled_groq_adapter_fails_before_transport_call() -> None:
    called = False

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    adapter = GroqLLMClient(_settings(), client=client)
    try:
        with pytest.raises(LLMInvalidConfigurationError, match="disabled"):
            adapter.complete(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )
        assert not called
    finally:
        client.close()


def test_groq_completion_captures_usage_rate_headers_and_structured_schema() -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((str(request.url), body, request.headers.get("authorization")))
        return httpx.Response(
            200,
            headers={
                "x-ratelimit-limit-requests": "100",
                "x-ratelimit-remaining-requests": "97",
                "x-ratelimit-limit-tokens": "18000",
                "x-ratelimit-remaining-tokens": "17500",
                "x-ratelimit-reset-tokens": "2m59.5s",
            },
            json={
                "model": "fixture-model-rev2",
                "choices": [{
                    "message": {"role": "assistant", "content": "{\"ok\":true}"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handle))
    adapter = GroqLLMClient(_groq_settings(), client=client)
    try:
        result = adapter.generate_structured(
            [ChatMessage("system", "Return JSON."), ChatMessage("user", "hello")],
            response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            max_output_tokens=12,
            timeout_seconds=4,
            inference_context=_inference_context(),
        )
    finally:
        client.close()

    url, body, authorization = requests[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert authorization == "Bearer fixture-groq-key"
    assert body["model"] == "fixture-model"
    assert body["max_completion_tokens"] == 12
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is False
    assert result.text == '{"ok":true}'
    assert result.metadata.identity.model_id == "fixture-model-rev2"
    assert result.metadata.usage.total_tokens == 7
    assert result.metadata.rate_limits.requests_remaining == 97
    assert result.metadata.rate_limits.tokens_remaining == 17500
    assert result.metadata.rate_limits.tokens_reset_seconds == 179.5


def test_groq_429_preserves_only_normalized_rate_limit_metadata() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        429,
        headers={"retry-after": "2", "x-ratelimit-remaining-tokens": "0"},
        json={"error": {"message": "secret provider detail"}},
    )))
    adapter = GroqLLMClient(_groq_settings(), client=client)
    try:
        with pytest.raises(LLMRateLimitedError) as raised:
            adapter.complete(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )
    finally:
        client.close()

    assert raised.value.rate_limits.retry_after_seconds == 2
    assert raised.value.rate_limits.tokens_remaining == 0
    assert "secret provider detail" not in str(raised.value)


@pytest.mark.parametrize(("status_code", "expected_error"), [
    (400, LLMInvalidRequestError),
    (503, LLMUnavailableError),
])
def test_groq_provider_failures_are_normalized_without_body_disclosure(
    status_code, expected_error,
) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        status_code,
        json={"error": {"message": "secret provider detail"}},
    )))
    adapter = GroqLLMClient(_groq_settings(), client=client)
    try:
        with pytest.raises(expected_error) as raised:
            adapter.complete(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )
    finally:
        client.close()

    assert "secret provider detail" not in str(raised.value)


def test_groq_rejects_non_json_schemas_before_dispatch() -> None:
    called = False

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    adapter = GroqLLMClient(_groq_settings(), client=client)
    try:
        with pytest.raises(LLMInvalidRequestError, match="schema is invalid"):
            adapter.generate_structured(
                [ChatMessage("user", "hello")],
                response_schema={"value": object()},
                max_output_tokens=10,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )
        assert not called
    finally:
        client.close()


def test_groq_stream_requires_done_and_captures_terminal_usage() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["max_completion_tokens"] == 16
        return httpx.Response(
            200,
            headers={"x-ratelimit-remaining-requests": "42"},
            content=(
                'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
                '"usage":{"prompt_tokens":5,"completion_tokens":1,"total_tokens":6}}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    async def run() -> list[GenerationEvent]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = GroqLLMClient(_groq_settings(), async_client=client)
        try:
            return [event async for event in adapter.stream_events(
                [ChatMessage("user", "hello")],
                max_output_tokens=16,
                timeout_seconds=3,
                inference_context=_inference_context(),
            )]
        finally:
            await client.aclose()

    events = asyncio.run(run())
    assert [event.delta for event in events if event.kind == "delta"] == ["Hi"]
    terminal = events[-1].metadata
    assert terminal.status == "success"
    assert terminal.usage.total_tokens == 6
    assert terminal.rate_limits.requests_remaining == 42


def test_groq_stream_without_done_is_incomplete_even_with_stop_reason() -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                'data: {"choices":[{"delta":{"content":"partial"},'
                '"finish_reason":"stop"}]}\n\n'
            ),
        )

    async def run() -> list[GenerationEvent]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = GroqLLMClient(_groq_settings(), async_client=client)
        try:
            return [event async for event in adapter.stream_events(
                [ChatMessage("user", "hello")],
                max_output_tokens=16,
                timeout_seconds=3,
                inference_context=_inference_context(),
            )]
        finally:
            await client.aclose()

    events = asyncio.run(run())
    assert events[-1].kind == "terminal"
    assert events[-1].metadata.status == "incomplete"


def test_groq_stream_closes_response_when_consumer_cancels() -> None:
    class RecordingStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            self.closed = True

    response_stream = RecordingStream()

    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=response_stream)

    async def run() -> tuple[str, bool, bool]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = GroqLLMClient(_groq_settings(), async_client=client)
        events = adapter.stream_events(
            [ChatMessage("user", "hello")],
            max_output_tokens=16,
            timeout_seconds=3,
            inference_context=_inference_context(),
        )
        first = await anext(events)
        await events.aclose()
        closed = response_stream.closed
        client_open = not client.is_closed
        await client.aclose()
        return first.delta, closed, client_open

    assert asyncio.run(run()) == ("Hi", True, True)


def test_cloudflare_uses_account_scoped_endpoint_and_direct_schema_shape() -> None:
    captured = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={
            "model": "@cf/meta/llama-fixture",
            "choices": [{
                "message": {"role": "assistant", "content": "{}"},
                "finish_reason": "stop",
            }],
        })

    client = httpx.Client(transport=httpx.MockTransport(handle))
    adapter = CloudflareWorkersAILLMClient(_cloudflare_settings(), client=client)
    try:
        result = adapter.generate_structured(
            [ChatMessage("user", "extract")],
            response_schema={"type": "object", "properties": {}},
            max_output_tokens=50,
            timeout_seconds=3,
            inference_context=_inference_context(),
        )
    finally:
        client.close()

    url, body = captured[0]
    assert url == (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{'a' * 32}/ai/v1/chat/completions"
    )
    assert body["model"] == "@cf/meta/llama-fixture"
    assert body["max_tokens"] == 50
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"type": "object", "properties": {}},
    }
    assert result.metadata.status == "success"


def test_structured_generation_is_not_declared_without_model_preflight() -> None:
    adapter = GroqLLMClient(_groq_settings(groq_structured_output_verified=False))

    assert not adapter.capabilities.supports("structured_generation")
    with pytest.raises(LLMUnsupportedCapabilityError):
        adapter.generate_structured(
            [ChatMessage("user", "hello")],
            response_schema={"type": "object"},
            max_output_tokens=10,
            timeout_seconds=2,
            inference_context=_inference_context(),
        )
