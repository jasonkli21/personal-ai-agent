"""Offline contract tests for replaceable streamed LLM clients."""

import asyncio
import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from personal_ai.entities.conversation import MessageRole
from personal_ai.llm import (
    ChatMessage,
    FakeLLMClient,
    GeminiLLMClient,
    InferenceContext,
    LLMIncompleteGenerationError,
    LLMInvalidConfigurationError,
    LLMInvalidRequestError,
    LLMRejectedError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMUnsupportedCapabilityError,
    ProviderIdentity,
    TokenCount,
)
from personal_ai.llm.attribution import log_generation_attribution
from personal_ai.llm.client import GenerationMetadata, UsageMetadata
from personal_ai.llm.preparation import prepare_bounded_input
from personal_ai.settings import Settings


async def _collect(stream: AsyncIterator[str]) -> list[str]:
    return [delta async for delta in stream]


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ai_provider": "gemini",
        "ai_model": "test-model",
        "ai_api_key": "test-key",
    }
    values.update(overrides)
    return Settings(**values)


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role=MessageRole.USER, content="Hello")]


def _inference_context() -> InferenceContext:
    return InferenceContext(
        effective_sensitivity="personal",
        maximum_sensitivity="sensitive",
        policy_version="test-policy-v1",
    )


def test_fake_client_preserves_delta_and_request_order() -> None:
    client = FakeLLMClient(["one", " two", " three"])

    deltas = asyncio.run(_collect(client.stream(_messages())))

    assert deltas == ["one", " two", " three"]
    assert client.requests == [tuple(_messages())]


def test_synthetic_provider_uses_distinct_neutral_identity_and_reports_terminal_usage():
    client = FakeLLMClient(
        ["answer"], provider_id="synthetic-provider", model_id="synthetic-model-v9"
    )

    events = asyncio.run(_collect(client.stream_events(
        _messages(), max_output_tokens=10, timeout_seconds=2
    )))

    assert events[0].delta == "answer"
    terminal = events[-1].metadata
    assert terminal.status == "success"
    assert terminal.identity.provider_id == "synthetic-provider"
    assert terminal.identity.model_id == "synthetic-model-v9"
    assert terminal.usage.source == "estimated"
    assert terminal.usage.confidence == "estimated"
    assert client.capabilities.supports("structured_generation")
    with pytest.raises(LLMUnsupportedCapabilityError):
        client.capabilities.require("token_counting")
    with pytest.raises(LLMUnsupportedCapabilityError):
        FakeLLMClient(supports_structured=False).capabilities.require("structured_generation")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("incomplete", LLMIncompleteGenerationError),
        ("failure", LLMUnavailableError),
        ("rejected", LLMRejectedError),
    ],
)
def test_fake_text_compatibility_facade_rejects_non_success_terminal(status, expected):
    client = FakeLLMClient(["partial"], terminal_status=status)
    with pytest.raises(expected):
        asyncio.run(_collect(client.stream(_messages())))


def test_fake_stream_requires_terminal_and_enforces_output_bound():
    missing = FakeLLMClient(["partial"], include_terminal=False)
    with pytest.raises(LLMIncompleteGenerationError):
        asyncio.run(_collect(missing.stream(_messages())))

    bounded = FakeLLMClient(["abcdefgh"])
    events = asyncio.run(_collect(bounded.stream_events(
        _messages(), max_output_tokens=1, timeout_seconds=2
    )))
    assert events[0].delta == "abcd"
    assert events[-1].metadata.status == "incomplete"


def test_fake_structured_generation_returns_terminal_attribution_and_checks_capability():
    client = FakeLLMClient(complete_text='{"ok":true}')
    result = client.generate_structured(
        _messages(), response_schema={"type": "object"},
        max_output_tokens=10, timeout_seconds=2,
    )
    assert result.text == '{"ok":true}'
    assert result.metadata.status == "success"
    assert result.metadata.identity.provider_id == "fake"

    unsupported = FakeLLMClient(supports_structured=False)
    with pytest.raises(LLMUnsupportedCapabilityError):
        unsupported.generate_structured(
            _messages(), response_schema={"type": "object"},
            max_output_tokens=10, timeout_seconds=2,
        )


class _ProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError(), LLMTimeoutError),
        (_ProviderError(400), LLMInvalidRequestError),
        (_ProviderError(503), LLMUnavailableError),
    ],
)
def test_provider_failures_map_to_stable_errors(
    error: BaseException, expected: type[Exception]
) -> None:
    class Models:
        async def generate_content_stream(self, **_: object) -> AsyncIterator[object]:
            raise error

    class Client:
        class aio:
            models = Models()

    client = GeminiLLMClient(_settings(), client=Client())

    with pytest.raises(expected):
        asyncio.run(_collect(client.stream(_messages(), inference_context=_inference_context())))


def test_invalid_configuration_is_safe_error() -> None:
    client = GeminiLLMClient(_settings(ai_api_key=""))

    with pytest.raises(LLMInvalidConfigurationError):
        asyncio.run(_collect(client.stream(_messages(), inference_context=_inference_context())))


def test_empty_chat_is_an_invalid_request_without_provider_call() -> None:
    client = GeminiLLMClient(_settings())
    with pytest.raises(LLMInvalidRequestError):
        asyncio.run(_collect(client.stream([], inference_context=_inference_context())))


def test_gemini_stream_requires_policy_before_provider_dispatch() -> None:
    calls = []

    class Models:
        async def generate_content_stream(self, **_: object) -> AsyncIterator[object]:
            calls.append(True)

            async def chunks():
                yield SimpleNamespace(text="answer")

            return chunks()

    class Client:
        class aio:
            models = Models()

    client = GeminiLLMClient(_settings(), client=Client())
    with pytest.raises(LLMInvalidRequestError, match="context disclosure policy is required"):
        asyncio.run(_collect(client.stream(_messages())))

    assert calls == []


def test_closing_gemini_stream_closes_provider_iterator_but_not_injected_client() -> None:
    class ProviderStream:
        def __init__(self) -> None:
            self.finalized = False

        async def __aiter__(self):
            try:
                yield SimpleNamespace(text="first")
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                self.finalized = True

    class Client:
        def __init__(self, stream: ProviderStream) -> None:
            self.stream = stream
            self.closed = False

        class _Models:
            def __init__(self, stream: ProviderStream) -> None:
                self.stream = stream

            async def generate_content_stream(self, **_: object) -> ProviderStream:
                return self.stream

        class _Aio:
            def __init__(self, models: object) -> None:
                self.models = models

        @property
        def aio(self):
            return self._Aio(self._Models(self.stream))

        def close(self) -> None:
            self.closed = True

    async def scenario() -> tuple[ProviderStream, Client]:
        provider_stream = ProviderStream()
        injected_client = Client(provider_stream)
        iterator = GeminiLLMClient(_settings(), client=injected_client).stream(
            _messages(), inference_context=_inference_context()
        )
        assert await anext(iterator) == "first"
        await iterator.aclose()
        assert provider_stream.finalized
        assert not injected_client.closed
        return provider_stream, injected_client

    provider_stream, injected_client = asyncio.run(scenario())

    assert provider_stream.finalized
    assert not injected_client.closed


def test_closing_gemini_bounded_facade_closes_provider_inside_running_loop():
    class ProviderStream:
        def __init__(self):
            self.finalized = False

        async def __aiter__(self):
            try:
                yield SimpleNamespace(text="first")
                await asyncio.Event().wait()
            finally:
                self.finalized = True

    provider = ProviderStream()

    class Models:
        async def generate_content_stream(self, **_):
            return provider

    client = GeminiLLMClient(
        _settings(), client=SimpleNamespace(aio=SimpleNamespace(models=Models()))
    )

    async def scenario():
        iterator = client.stream_bounded(
            _messages(), max_output_tokens=10, timeout_seconds=2,
            inference_context=_inference_context(),
        )
        assert await anext(iterator) == "first"
        await iterator.aclose()
        assert provider.finalized

    asyncio.run(scenario())


def test_gemini_stream_events_return_provider_finish_and_usage_metadata():
    class Models:
        async def generate_content_stream(self, **_: object) -> AsyncIterator[object]:
            async def chunks():
                yield SimpleNamespace(
                    text="partial",
                    candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
                    usage_metadata=SimpleNamespace(
                        prompt_token_count=31,
                        candidates_token_count=5,
                        total_token_count=36,
                    ),
                )

            return chunks()

    class Client:
        class aio:
            models = Models()

    client = GeminiLLMClient(_settings(), client=Client())
    events = asyncio.run(_collect(client.stream_events(
        _messages(),
        max_output_tokens=1,
        timeout_seconds=2,
        inference_context=_inference_context(),
    )))
    metadata = events[-1].metadata
    assert metadata.status == "incomplete"
    assert metadata.identity.provider_id == "gemini"
    assert metadata.identity.model_id == "test-model"
    assert metadata.usage.input_tokens == 31
    assert metadata.usage.output_tokens == 5
    assert metadata.usage.confidence == "reported"


@pytest.mark.parametrize(
    "reason",
    [None, "", "NONE", "STOP", "MAX_TOKENS", "SAFETY"],
)
def test_gemini_text_without_explicit_stop_never_becomes_success(reason):
    finish = [] if reason is None else [SimpleNamespace(finish_reason=reason)]

    class Models:
        async def generate_content_stream(self, **_: object) -> AsyncIterator[object]:
            async def chunks():
                yield SimpleNamespace(text="partial", candidates=finish)

            return chunks()

        def generate_content(self, **_: object):
            return SimpleNamespace(
                text="partial", candidates=[] if reason is None else finish
            )

    class Client:
        class aio:
            models = Models()

        models = Models()

    client = GeminiLLMClient(_settings(), client=Client())
    events = asyncio.run(_collect(client.stream_events(
        _messages(), max_output_tokens=10, timeout_seconds=2,
        inference_context=_inference_context(),
    )))
    assert events[0].delta == "partial"
    assert events[-1].metadata.status == (
        "success" if reason == "STOP" else "rejected" if reason == "SAFETY" else "incomplete"
    )
    if reason != "STOP":
        with pytest.raises((LLMIncompleteGenerationError, LLMRejectedError)):
            client.complete(
                _messages(), max_output_tokens=10, timeout_seconds=2,
                inference_context=_inference_context(),
            ).require_success()


def test_gemini_generation_timeout_caps_config_and_discards_late_result(monkeypatch):
    from personal_ai.llm import gemini

    configurations = []

    class Models:
        def generate_content(self, *, config, **kwargs):
            del kwargs
            configurations.append(config)
            return SimpleNamespace(
                text='{"ok":true}',
                candidates=[SimpleNamespace(finish_reason="STOP")],
            )

    client = GeminiLLMClient(
        _settings(request_timeout_seconds=1),
        client=SimpleNamespace(models=Models()),
    )
    for generate in (
        lambda timeout: client.complete(
            _messages(), max_output_tokens=5, timeout_seconds=timeout,
            inference_context=_inference_context(),
        ),
        lambda timeout: client.generate_structured(
            _messages(), response_schema={"type": "object"}, max_output_tokens=5,
            timeout_seconds=timeout, inference_context=_inference_context(),
        ),
    ):
        generate(90)
        generate(0.25)
    assert [item["http_options"]["timeout"] for item in configurations] == [1000, 250, 1000, 250]

    ticks = iter((10.0, 12.0))
    monkeypatch.setattr(gemini, "monotonic", lambda: next(ticks))
    with pytest.raises(LLMTimeoutError):
        client.complete(
            _messages(), max_output_tokens=5, timeout_seconds=1,
            inference_context=_inference_context(),
        )


@pytest.mark.parametrize(
    "mismatch",
    ["provider_id", "model_id", "serializer_id", "missing_identity"],
)
def test_bounded_preparation_rejects_a_counter_from_another_endpoint_before_call(mismatch):
    endpoint = ProviderIdentity("gemini", "model-a", "serializer-a")
    fields = {
        "provider_id": "other",
        "model_id": "model-b",
        "serializer_id": "serializer-b",
    }
    counter_identity = None if mismatch == "missing_identity" else endpoint
    if mismatch in fields:
        values = {
            "provider_id": endpoint.provider_id,
            "model_id": endpoint.model_id,
            "serializer_id": endpoint.serializer_id,
        }
        values[mismatch] = fields[mismatch]
        counter_identity = ProviderIdentity(**values)

    class Generator:
        identity = endpoint

    class Counter:
        identity = counter_identity

        def __init__(self):
            self.calls = 0

        def count(self, *_args, **_kwargs):
            self.calls += 1
            return TokenCount(1, "provider", confidence="authoritative")

    counter = Counter()
    with pytest.raises(LLMInvalidRequestError, match="endpoint"):
        prepare_bounded_input(
            _messages(), counter, generator=Generator(), input_limit=10
        )
    assert counter.calls == 0


@pytest.mark.parametrize("confidence", ["reported", "estimated", "authoritative"])
def test_bounded_preparation_requires_authoritative_matching_count(confidence):
    endpoint = ProviderIdentity("gemini", "model-a", "serializer-a")

    class Generator:
        identity = endpoint

    class Counter:
        identity = endpoint

        def count(self, messages, *, response_schema=None, inference_context=None):
            del messages, response_schema, inference_context
            if confidence == "estimated":
                return TokenCount(1, "estimated", confidence="estimated")
            return TokenCount(
                1,
                "provider",
                provider_id=endpoint.provider_id,
                model_id=endpoint.model_id,
                serializer_id=endpoint.serializer_id,
                confidence=confidence,
            )

    if confidence == "authoritative":
        result = prepare_bounded_input(
            _messages(), Counter(), generator=Generator(), input_limit=10
        )
        assert result.token_count.tokens == 1
    else:
        with pytest.raises(LLMInvalidRequestError, match="authoritative"):
            prepare_bounded_input(
                _messages(), Counter(), generator=Generator(), input_limit=10
            )


def test_invocation_attribution_logs_safe_identity_usage_and_unavailable_values(caplog):
    logger = logging.getLogger("test.invocation_attribution")
    identity = ProviderIdentity("synthetic-provider", "synthetic-model", "serializer-v1")
    with caplog.at_level(logging.INFO, logger=logger.name):
        log_generation_attribution(
            logger,
            "synthetic_path",
            GenerationMetadata(
                status="success",
                identity=identity,
                usage=UsageMetadata(
                    input_tokens=11,
                    output_tokens=7,
                    total_tokens=18,
                    source="provider",
                    confidence="reported",
                ),
            ),
        )
        log_generation_attribution(
            logger,
            "synthetic_path",
            GenerationMetadata(
                status="incomplete", identity=identity, usage=None, error_code="incomplete"
            ),
        )

    assert "provider=synthetic-provider model=synthetic-model status=success" in caplog.text
    assert "input_tokens=11 output_tokens=7 total_tokens=18" in caplog.text
    assert "usage_source=provider usage_confidence=reported" in caplog.text
    assert "usage_source=unavailable usage_confidence=unavailable" in caplog.text
    assert "incomplete" in caplog.text
    assert "prompt" not in caplog.text and "private" not in caplog.text


def test_closing_gemini_stream_closes_per_request_owned_client(monkeypatch) -> None:
    class ProviderStream:
        async def __aiter__(self):
            try:
                yield SimpleNamespace(text="first")
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                self.finalized = True

    class AsyncClient:
        def __init__(self, models: object) -> None:
            self.models = models
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    class Client:
        def __init__(self) -> None:
            self.models = Models()
            self.aio = AsyncClient(self.models)
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class Models:
        def __init__(self) -> None:
            self.stream = ProviderStream()

        async def generate_content_stream(self, **_: object) -> ProviderStream:
            return self.stream

    owned_client = Client()
    monkeypatch.setattr(GeminiLLMClient, "_build_client", lambda _: owned_client)

    async def scenario() -> None:
        iterator = GeminiLLMClient(_settings()).stream(
            _messages(), inference_context=_inference_context()
        )
        assert await anext(iterator) == "first"
        await iterator.aclose()

    asyncio.run(scenario())

    assert owned_client.models.stream.finalized
    assert owned_client.aio.closed
    assert owned_client.closed
