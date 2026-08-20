"""Offline contract tests for replaceable streamed LLM clients."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from personal_ai.entities.conversation import MessageRole
from personal_ai.llm import (
    ChatMessage,
    FakeLLMClient,
    GeminiLLMClient,
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
        asyncio.run(_collect(client.stream(_messages())))


def test_invalid_configuration_is_safe_error() -> None:
    client = GeminiLLMClient(_settings(ai_api_key=""))

    with pytest.raises(LLMInvalidConfigurationError):
        asyncio.run(_collect(client.stream(_messages())))


def test_history_limit_is_an_invalid_request() -> None:
    client = GeminiLLMClient(_settings(max_phase_1_history_messages=1))

    with pytest.raises(LLMInvalidRequestError):
        asyncio.run(_collect(client.stream(_messages() * 2)))
