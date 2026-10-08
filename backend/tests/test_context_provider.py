"""Exercise the locked SDK transport with offline HTTP responses."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from google import genai

from personal_ai.context.assembler import SUMMARY_INSTRUCTION, summary_request
from personal_ai.evaluation.context import build_fixture, fixture_settings, load_fixtures
from personal_ai.llm import (
    ChatMessage,
    GeminiLLMClient,
    InferenceContext,
    LLMInvalidRequestError,
    LLMUnavailableError,
)
from personal_ai.llm.client import SYSTEM_INSTRUCTION
from personal_ai.llm.context import GeminiConversationSummarizer, GeminiTokenCounter


def test_authoritative_counter_counts_exact_system_and_summary_request_shape_via_sdk_transport():
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"totalTokens": 123})

    client = genai.Client(
        api_key="offline-fake",
        http_options={"client_args": {"transport": httpx.MockTransport(handler)}},
    )
    try:
        messages = (
            ChatMessage("system", "Historical working summary: synthetic fact"),
            ChatMessage("user", "newest"),
        )
        count = GeminiTokenCounter(fixture_settings(), client).count(messages)
        assert count.tokens == 123 and count.kind == "provider"
        assert count.provider_id == "gemini"
        assert count.model_id == "fixture-model"
        assert count.serializer_id == "gemini-content-v1"
        assert count.confidence == "authoritative"
        request = captured[0]
        assert request.url.path.endswith("/models/fixture-model:countTokens")
        body = json.loads(request.content)["generateContentRequest"]
        assert (
            body["systemInstruction"]["parts"][0]["text"]
            == SYSTEM_INSTRUCTION + "\n\n" + messages[0].content
        )
        assert body["contents"] == [{"role": "user", "parts": [{"text": "newest"}]}]
    finally:
        client.close()


def test_summary_generation_adapter_sets_output_ceiling_and_preserves_prompt_instructions():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"role": "model", "parts": [{"text": "Launch color is amber."}]}}
                ]
            },
        )

    client = genai.Client(
        api_key="offline-fake",
        http_options={"client_args": {"transport": httpx.MockTransport(handler)}},
    )
    active, _, _ = build_fixture(load_fixtures()[2])
    try:
        settings = fixture_settings()
        draft = GeminiConversationSummarizer(settings, client).summarize(
            active[:2],
            None,
            inference_context=InferenceContext(
                effective_sensitivity="personal",
                maximum_sensitivity="sensitive",
                policy_version="test-policy-v1",
            ),
        )
        assert draft.content == "Launch color is amber."
        assert draft.attribution.identity.provider_id == "gemini"
        assert draft.attribution.identity.model_id == settings.ai_model
        assert draft.attribution.status == "success"
        assert captured[0]["generationConfig"]["maxOutputTokens"] == settings.max_summary_tokens
        system = captured[0]["systemInstruction"]["parts"][0]["text"]
        assert SUMMARY_INSTRUCTION in system
        assert "uncertainty" in system and "corrections" in system
        assert (
            captured[0]["contents"][0]["parts"][0]["text"]
            == summary_request(active[:2], None)[1].content
        )
    finally:
        client.close()


def test_gemini_summary_requires_policy_before_provider_dispatch():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"candidates": []})

    client = genai.Client(
        api_key="offline-fake",
        http_options={"client_args": {"transport": httpx.MockTransport(handler)}},
    )
    active, _, _ = build_fixture(load_fixtures()[2])
    settings = fixture_settings(ai_api_key="offline-fake")

    with pytest.raises(LLMInvalidRequestError, match="context disclosure policy is required"):
        GeminiConversationSummarizer(settings, client).summarize(active[:2], None)

    assert calls == []
    client.close()


def test_provider_count_failure_is_translated_without_leaking_response():
    client = genai.Client(
        api_key="offline-fake",
        http_options={
            "client_args": {
                "transport": httpx.MockTransport(
                    lambda _: httpx.Response(503, json={"error": {"message": "private"}})
                )
            },
            "retry_options": {"attempts": 1},
        },
    )
    try:
        with pytest.raises(LLMUnavailableError) as error:
            GeminiTokenCounter(fixture_settings(), client).count([ChatMessage("user", "test")])
        assert "private" not in str(error.value)
    finally:
        client.close()


def test_stream_adapter_keeps_summary_in_system_context_and_enforces_response_reserve():
    captured = []

    class Models:
        async def generate_content_stream(self, **kwargs):
            captured.append(kwargs)

            async def chunks():
                yield SimpleNamespace(text="answer")

            return chunks()

    settings = fixture_settings(ai_api_key="offline-fake")
    client = GeminiLLMClient(settings, client=SimpleNamespace(aio=SimpleNamespace(models=Models())))

    async def scenario():
        return [
            chunk
            async for chunk in client.stream(
                [ChatMessage("system", "Historical summary"), ChatMessage("user", "newest")],
                inference_context=InferenceContext(
                    effective_sensitivity="personal",
                    maximum_sensitivity="sensitive",
                    policy_version="test-policy-v1",
                ),
            )
        ]

    assert asyncio.run(scenario()) == ["answer"]
    assert captured[0]["config"]["max_output_tokens"] == settings.max_response_tokens
    assert captured[0]["contents"] == [{"role": "user", "parts": [{"text": "newest"}]}]
    assert "Historical summary" in captured[0]["config"]["system_instruction"]


def test_counting_reuses_owned_client_limits_calls_and_closes_at_assembly_end(monkeypatch):
    from personal_ai.context import ContextAssembler
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={'totalTokens': 20})
    client = genai.Client(api_key='offline-fake', http_options={
        'client_args': {'transport': httpx.MockTransport(handler)},
    })
    builds = []
    closes = []
    def build(self):
        builds.append(True)
        return client
    monkeypatch.setattr(GeminiLLMClient, '_build_client', build)
    close = client.close
    monkeypatch.setattr(client, 'close', lambda: (closes.append(True), close()))
    settings = fixture_settings(ai_api_key='offline-fake')
    active, pending, _ = build_fixture({**load_fixtures()[0], 'turns': 100, 'words_per_message': 1})
    result = ContextAssembler(settings, GeminiTokenCounter(settings)).assemble(active, pending)
    assert len(result.selected_message_ids) == 201
    assert len(captured) == 2
    assert len(builds) == len(closes) == 1


def test_count_deadline_is_forwarded_to_transport_without_sdk_retries():
    calls = []
    class Api:
        def request(self, *args, **kwargs):
            calls.append(kwargs['http_options'])
            return SimpleNamespace(body=json.dumps({'totalTokens': 20}))
    counter = GeminiTokenCounter(fixture_settings(), client=SimpleNamespace(_api_client=Api()))
    counter.count_with_timeout([ChatMessage('user', 'synthetic')], 0.25)
    assert calls == [{'timeout': 250, 'retry_options': {'attempts': 1}}]
