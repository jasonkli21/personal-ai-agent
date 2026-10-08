"""Context integrations use the Gemini LiteLLM gateway offline."""

import json

import httpx
import pytest

from personal_ai.context.assembler import SUMMARY_INSTRUCTION, summary_request
from personal_ai.evaluation.context import build_fixture, fixture_settings, load_fixtures
from personal_ai.llm import (
    ChatMessage,
    InferenceContext,
    LLMInvalidRequestError,
    LLMUnavailableError,
)
from personal_ai.llm.client import SYSTEM_INSTRUCTION
from personal_ai.llm.context import GeminiConversationSummarizer, GeminiTokenCounter


def _inference_context():
    return InferenceContext(
        effective_sensitivity="personal",
        maximum_sensitivity="sensitive",
        policy_version="test-policy-v1",
    )


def _settings():
    return fixture_settings(ai_api_key="offline-fake", ai_model="gemini-2.5-flash")


def _gemini_response(settings, text):
    return {
        "modelVersion": settings.ai_model,
        "candidates": [{
            "content": {"role": "model", "parts": [{"text": text}]},
            "finishReason": "STOP",
        }],
    }


def test_summary_generation_preserves_prompt_and_output_ceiling_through_litellm():
    captured = []
    settings = _settings()

    def handler(request):
        captured.append((request, json.loads(request.content)))
        return httpx.Response(
            200, json=_gemini_response(settings, "Launch color is amber.")
        )

    active, _, _ = build_fixture(load_fixtures()[2])
    draft = GeminiConversationSummarizer(
        settings, sync_transport_factory=lambda: httpx.MockTransport(handler)
    ).summarize(active[:2], None, inference_context=_inference_context())

    request, body = captured[0]
    prompt = summary_request(active[:2], None)
    assert request.url.path.endswith(":generateContent")
    assert body["generationConfig"]["max_output_tokens"] == settings.max_summary_tokens
    assert SUMMARY_INSTRUCTION in body["system_instruction"]["parts"][0]["text"]
    assert SYSTEM_INSTRUCTION in body["system_instruction"]["parts"][0]["text"]
    assert "uncertainty" in body["system_instruction"]["parts"][0]["text"]
    assert body["contents"][0]["parts"][0]["text"] == prompt[1].content
    assert draft.content == "Launch color is amber."
    assert draft.attribution.identity.provider_id == "gemini"
    assert draft.attribution.identity.model_id == settings.ai_model
    assert draft.attribution.status == "success"


def test_summary_requires_disclosure_policy_before_provider_dispatch():
    calls = []
    settings = _settings()
    active, _, _ = build_fixture(load_fixtures()[2])
    summarizer = GeminiConversationSummarizer(
        settings,
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda request: (calls.append(request), httpx.Response(200, json={}))[1]
        ),
    )

    with pytest.raises(LLMInvalidRequestError, match="context disclosure policy is required"):
        summarizer.summarize(active[:2], None)

    assert calls == []


def test_provider_count_failure_is_translated_without_response_disclosure():
    settings = _settings()
    counter = GeminiTokenCounter(
        settings,
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(503, json={"error": {"message": "private response"}})
        ),
    )

    with pytest.raises(LLMUnavailableError) as error:
        counter.count(
            [ChatMessage("user", "test")], inference_context=_inference_context()
        )

    assert "private response" not in str(error.value)


def test_context_assembler_counts_with_provider_gateway_and_bounded_batches():
    from personal_ai.applications.contracts import ApplicationContextRequest
    from personal_ai.applications.registry import default_application_registry
    from personal_ai.auth.scope import RequestScope
    from personal_ai.context import ContextAssembler

    requests = []
    settings = _settings()

    def handle(request):
        requests.append((request, json.loads(request.content)))
        return httpx.Response(200, json={"totalTokens": 20})

    active, pending, _ = build_fixture({
        **load_fixtures()[0], "turns": 100, "words_per_message": 1
    })
    registration = default_application_registry().registration("personal_ai")
    app_context = ApplicationContextRequest(
        definition=registration.definition,
        scope=RequestScope(owner_id="local", request_id="counter-test", application_id="personal_ai"),
        context_provider_capabilities=registration.context_providers,
        tool_capabilities=registration.tools,
    )
    result = ContextAssembler(
        settings,
        GeminiTokenCounter(
            settings, sync_transport_factory=lambda: httpx.MockTransport(handle)
        ),
    ).assemble(active, pending, application_context=app_context)

    assert len(result.selected_message_ids) == 201
    assert len(requests) >= 2
    assert all(request.url.path.endswith(":countTokens") for request, _ in requests)
    assert all(body["generateContentRequest"]["system_instruction"] for _, body in requests)


def test_count_deadline_is_forwarded_to_the_pinned_sdk_transport():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"totalTokens": 20})

    GeminiTokenCounter(
        _settings(),
        sync_transport_factory=lambda: httpx.MockTransport(handle),
    ).count_with_timeout(
        [ChatMessage("user", "synthetic")],
        0.25,
        inference_context=_inference_context(),
    )

    timeout = requests[0].extensions["timeout"]
    assert max(timeout.values()) <= 0.25
