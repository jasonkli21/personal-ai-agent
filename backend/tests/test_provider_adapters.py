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
    LLMIncompleteGenerationError,
    LLMInvalidConfigurationError,
    LLMInvalidRequestError,
    LLMInvalidResponseError,
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
        "groq_privacy_max_sensitivity": "personal",
        "groq_approved_model_aliases": ("fixture-model-rev2",),
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
        "cloudflare_privacy_max_sensitivity": "personal",
        "cloudflare_approved_model_aliases": ("@cf/meta/llama-fixture-v2",),
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


def _configured_adapter(provider: str, *, client=None, async_client=None, **overrides):
    if provider == "groq":
        settings = _groq_settings(**overrides)
        return GroqLLMClient(settings, client=client, async_client=async_client)
    if provider == "cloudflare":
        settings = _cloudflare_settings(**overrides)
        return CloudflareWorkersAILLMClient(settings, client=client, async_client=async_client)
    raise AssertionError(f"unknown provider fixture: {provider}")


def _configured_model(provider: str) -> str:
    return "fixture-model" if provider == "groq" else "@cf/meta/llama-fixture"


def _approved_model_alias(provider: str) -> str:
    return "fixture-model-rev2" if provider == "groq" else "@cf/meta/llama-fixture-v2"


def _completion_payload(provider: str, *, text: str = "answer", model: str | None = None):
    return {
        "model": model or _configured_model(provider),
        "choices": [{
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
    }


def _stream_payload(provider: str, *, text: str = "answer", model: str | None = None) -> bytes:
    model_id = model or _configured_model(provider)
    return (
        f"data: {json.dumps({'model': model_id, 'choices': [{'delta': {'content': text}, 'finish_reason': None}]})}\n\n"
        f"data: {json.dumps({'model': model_id, 'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        "data: [DONE]\n\n"
    ).encode()


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
                'data: {"model":"fixture-model","choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
                'data: {"model":"fixture-model","choices":[{"delta":{},"finish_reason":"stop"}],'
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
                'data: {"model":"fixture-model","choices":[{"delta":{"content":"partial"},'
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
            yield b'data: {"model":"fixture-model","choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
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


@pytest.mark.parametrize("provider", ["groq", "cloudflare"])
@pytest.mark.parametrize("sensitivity", ["public", "personal", "sensitive", "restricted"])
def test_provider_privacy_preflight_covers_each_sensitivity_for_both_adapters(
    provider, sensitivity
) -> None:
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_completion_payload(provider))

    client = httpx.Client(transport=httpx.MockTransport(handle))
    adapter = _configured_adapter(
        provider,
        client=client,
        **{f"{provider}_privacy_max_sensitivity": sensitivity},
    )
    context = InferenceContext(
        effective_sensitivity=sensitivity,
        maximum_sensitivity=sensitivity,
        policy_version="test-policy-v1",
    )
    try:
        result = adapter.complete(
            [ChatMessage("user", "hello")],
            max_output_tokens=20,
            timeout_seconds=2,
            inference_context=context,
        )
    finally:
        client.close()

    assert result.metadata.status == "success"
    assert calls == 1


@pytest.mark.parametrize("provider", ["groq", "cloudflare"])
def test_provider_denies_sensitivity_above_preflight_ceiling_before_transport(provider) -> None:
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_completion_payload(provider))

    client = httpx.Client(transport=httpx.MockTransport(handle))
    adapter = _configured_adapter(
        provider,
        client=client,
        **{f"{provider}_privacy_max_sensitivity": "personal"},
    )
    try:
        with pytest.raises(LLMInvalidRequestError, match="privacy preflight"):
            adapter.complete(
                [ChatMessage("user", "restricted source")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=InferenceContext(
                    effective_sensitivity="restricted",
                    maximum_sensitivity="restricted",
                    policy_version="test-policy-v1",
                ),
            )
    finally:
        client.close()

    assert calls == 0


@pytest.mark.parametrize("provider", ["groq", "cloudflare"])
def test_oversized_completion_body_is_rejected_before_json_parsing(provider, monkeypatch) -> None:
    from personal_ai.llm import openai_compatible

    monkeypatch.setattr(openai_compatible, "_MAX_COMPLETION_RESPONSE_BYTES", 128)
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        200,
        json=_completion_payload(provider, text="x" * 512),
    )))
    adapter = _configured_adapter(provider, client=client)
    try:
        with pytest.raises(LLMInvalidResponseError, match="size limit"):
            adapter.complete(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )
    finally:
        client.close()


@pytest.mark.parametrize("provider", ["groq", "cloudflare"])
def test_oversized_single_sse_event_is_rejected(provider, monkeypatch) -> None:
    from personal_ai.llm import openai_compatible

    monkeypatch.setattr(openai_compatible, "_MAX_SSE_EVENT_BYTES", 64)
    monkeypatch.setattr(openai_compatible, "_MAX_SSE_LINE_BYTES", 256)
    oversized_event = (
        "data: " + json.dumps({
            "model": _configured_model(provider),
            "choices": [{"delta": {"content": "x" * 100}, "finish_reason": None}],
        }) + "\n\n"
    ).encode()

    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=oversized_event)

    async def run() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = _configured_adapter(provider, async_client=client)
        try:
            async for _ in adapter.stream_events(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            ):
                pass
        finally:
            await client.aclose()

    with pytest.raises(LLMInvalidResponseError, match="event exceeded"):
        asyncio.run(run())


@pytest.mark.parametrize("provider", ["groq", "cloudflare"])
@pytest.mark.parametrize("text", ["", " \t\n"])
@pytest.mark.parametrize("operation", ["completion", "stream"])
def test_empty_or_whitespace_output_is_incomplete_for_both_adapters(
    provider, text, operation
) -> None:
    if operation == "completion":
        client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, json=_completion_payload(provider, text=text)
        )))
        adapter = _configured_adapter(provider, client=client)
        try:
            result = adapter.complete(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )
        finally:
            client.close()
        assert result.metadata.status == "incomplete"
        assert result.metadata.error_code == LLMIncompleteGenerationError.code
        return

    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_stream_payload(provider, text=text))

    async def run() -> list[GenerationEvent]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = _configured_adapter(provider, async_client=client)
        try:
            return [event async for event in adapter.stream_events(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )]
        finally:
            await client.aclose()

    events = asyncio.run(run())
    assert events[-1].metadata.status == "incomplete"
    assert events[-1].metadata.error_code == LLMIncompleteGenerationError.code


@pytest.mark.parametrize("provider", ["groq", "cloudflare"])
@pytest.mark.parametrize("operation", ["completion", "stream"])
def test_missing_provider_usage_remains_unknown(provider, operation) -> None:
    if operation == "completion":
        client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, json=_completion_payload(provider)
        )))
        adapter = _configured_adapter(provider, client=client)
        try:
            result = adapter.complete(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )
        finally:
            client.close()
        assert result.metadata.usage is None
        return

    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_stream_payload(provider))

    async def run() -> list[GenerationEvent]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = _configured_adapter(provider, async_client=client)
        try:
            return [event async for event in adapter.stream_events(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )]
        finally:
            await client.aclose()

    events = asyncio.run(run())
    assert events[-1].metadata.usage is None


@pytest.mark.parametrize("provider", ["groq", "cloudflare"])
@pytest.mark.parametrize("operation", ["completion", "stream"])
@pytest.mark.parametrize("model_case", ["matching", "alias", "mismatch"])
def test_response_model_identity_must_match_or_be_preflight_approved(
    provider, operation, model_case
) -> None:
    requested = _configured_model(provider)
    returned = {
        "matching": requested,
        "alias": _approved_model_alias(provider),
        "mismatch": "unapproved-model",
    }[model_case]

    if operation == "completion":
        client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, json=_completion_payload(provider, model=returned)
        )))
        adapter = _configured_adapter(provider, client=client)
        try:
            if model_case == "mismatch":
                with pytest.raises(LLMInvalidResponseError, match="unapproved model"):
                    adapter.complete(
                        [ChatMessage("user", "hello")],
                        max_output_tokens=20,
                        timeout_seconds=2,
                        inference_context=_inference_context(),
                    )
                return
            result = adapter.complete(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )
        finally:
            client.close()
        assert result.metadata.identity.model_id == returned
        return

    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_stream_payload(provider, model=returned))

    async def run() -> list[GenerationEvent]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = _configured_adapter(provider, async_client=client)
        try:
            return [event async for event in adapter.stream_events(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )]
        finally:
            await client.aclose()

    if model_case == "mismatch":
        with pytest.raises(LLMInvalidResponseError, match="unapproved model"):
            asyncio.run(run())
        return
    events = asyncio.run(run())
    assert events[-1].metadata.identity.model_id == returned


def test_cloudflare_streaming_success_reports_verified_identity_and_terminal_usage() -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-ratelimit-remaining-requests": "8"},
            content=_stream_payload("cloudflare"),
        )

    async def run() -> list[GenerationEvent]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = _configured_adapter("cloudflare", async_client=client)
        try:
            return [event async for event in adapter.stream_events(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )]
        finally:
            await client.aclose()

    events = asyncio.run(run())
    assert events[-1].metadata.status == "success"
    assert events[-1].metadata.identity.model_id == _configured_model("cloudflare")
    assert events[-1].metadata.usage is None
    assert events[-1].metadata.rate_limits.requests_remaining == 8


def test_cloudflare_interrupted_stream_is_incomplete() -> None:
    body = (
        "data: " + json.dumps({
            "model": _configured_model("cloudflare"),
            "choices": [{"delta": {"content": "partial"}, "finish_reason": "stop"}],
        }) + "\n\n"
    )

    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async def run() -> list[GenerationEvent]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = _configured_adapter("cloudflare", async_client=client)
        try:
            return [event async for event in adapter.stream_events(
                [ChatMessage("user", "hello")],
                max_output_tokens=20,
                timeout_seconds=2,
                inference_context=_inference_context(),
            )]
        finally:
            await client.aclose()

    events = asyncio.run(run())
    assert events[-1].metadata.status == "incomplete"
    assert events[-1].metadata.usage is None


@pytest.mark.parametrize(("status_code", "expected_error"), [
    (429, LLMRateLimitedError),
    (503, LLMUnavailableError),
])
def test_cloudflare_provider_failures_are_safe_and_normalized(status_code, expected_error) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        status_code,
        headers={"retry-after": "3"},
        json={"error": {"message": "secret Cloudflare detail"}},
    )))
    adapter = _configured_adapter("cloudflare", client=client)
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

    assert "secret Cloudflare detail" not in str(raised.value)
    if status_code == 429:
        assert raised.value.rate_limits.retry_after_seconds == 3


def test_cloudflare_stream_closes_response_when_consumer_cancels() -> None:
    class RecordingStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield (
                "data: " + json.dumps({
                    "model": _configured_model("cloudflare"),
                    "choices": [{"delta": {"content": "Hi"}, "finish_reason": None}],
                }) + "\n\n"
            ).encode()
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            self.closed = True

    response_stream = RecordingStream()

    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=response_stream)

    async def run() -> tuple[str, bool, bool]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        adapter = _configured_adapter("cloudflare", async_client=client)
        events = adapter.stream_events(
            [ChatMessage("user", "hello")],
            max_output_tokens=20,
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
