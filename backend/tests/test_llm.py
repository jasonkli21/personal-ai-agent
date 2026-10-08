"""Offline contract tests for replaceable streamed LLM clients."""

import asyncio
import logging
from collections.abc import AsyncIterator

import httpx
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


def test_gemini_invalid_configuration_and_empty_chat_fail_before_transport():
    calls = []
    transport = lambda: httpx.MockTransport(
        lambda request: (calls.append(request), httpx.Response(200, json={}))[1]
    )
    missing_key = GeminiLLMClient(_settings(ai_api_key=""), async_transport_factory=transport)
    with pytest.raises(LLMInvalidConfigurationError):
        asyncio.run(_collect(missing_key.stream(
            _messages(), inference_context=_inference_context()
        )))

    configured = GeminiLLMClient(_settings(), async_transport_factory=transport)
    with pytest.raises(LLMInvalidRequestError):
        asyncio.run(_collect(configured.stream([], inference_context=_inference_context())))
    assert calls == []


def test_gemini_stream_requires_disclosure_policy_before_transport():
    calls = []
    client = GeminiLLMClient(
        _settings(),
        async_transport_factory=lambda: httpx.MockTransport(
            lambda request: (calls.append(request), httpx.Response(200, content=b""))[1]
        ),
    )
    with pytest.raises(LLMInvalidRequestError, match="context disclosure policy is required"):
        asyncio.run(_collect(client.stream(_messages())))
    assert calls == []


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
