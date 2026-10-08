"""Offline contract tests for replaceable streamed LLM clients."""

import asyncio
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
)
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
        return provider_stream, injected_client

    provider_stream, injected_client = asyncio.run(scenario())

    assert provider_stream.finalized
    assert not injected_client.closed


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
