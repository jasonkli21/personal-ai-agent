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
    LLMInvalidConfigurationError,
    LLMInvalidRequestError,
    LLMTimeoutError,
    LLMUnavailableError,
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
