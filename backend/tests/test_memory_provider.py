"""Locked SDK request contracts, batching, malformed output and safe errors."""

import json

import httpx
import pytest
from google import genai

from personal_ai.evaluation.memory import build_fixture, fixture_settings, load_fixtures
from personal_ai.llm import (
    ChatMessage,
    InferenceContext,
    LLMInvalidRequestError,
    LLMInvalidResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from personal_ai.llm.memory import GeminiMemoryAdapter


def _inference_context():
    return InferenceContext(
        effective_sensitivity="sensitive",
        maximum_sensitivity="sensitive",
        policy_version="test-memory-policy-v1",
    )


def test_sdk_embedding_batch_order_task_types_and_dimensions():
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert all(r["outputDimensionality"] == 3 for r in payload["requests"])
        return httpx.Response(
            200, json={"embeddings": [{"values": [3, 0, 0]} for _ in payload["requests"]]}
        )

    client = genai.Client(
        api_key="offline-fake",
        http_options={"client_args": {"transport": httpx.MockTransport(handler)}},
    )
    settings = fixture_settings(memory_embedding_batch_size=2)
    adapter = GeminiMemoryAdapter(settings, client)
    try:
        embedded = adapter.embed(["a", "b", "c"], inference_context=_inference_context())
        assert tuple(item.values for item in embedded) == ((1, 0, 0),) * 3
        assert all(item.space.provider_id == "google_genai" for item in embedded)
        assert all(item.space.version == "v1" for item in embedded)
        assert all(item.task == "document" for item in embedded)
        assert [len(r["requests"]) for r in requests] == [2, 1]
        assert requests[0]["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"
        adapter.embed(["query"], query=True, inference_context=_inference_context())
        assert requests[-1]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    finally:
        client.close()


def test_counter_and_embedding_capabilities_require_an_authorization_envelope():
    calls = []
    client = genai.Client(
        api_key="offline-fake",
        http_options={
            "client_args": {
                "transport": httpx.MockTransport(
                    lambda request: (calls.append(request), httpx.Response(200, json={"totalTokens": 1}))[1]
                )
            }
        },
    )
    adapter = GeminiMemoryAdapter(fixture_settings(), client)
    try:
        with pytest.raises(LLMInvalidRequestError, match="disclosure policy"):
            adapter.counter.count([ChatMessage("user", "synthetic")])
        with pytest.raises(LLMInvalidRequestError, match="disclosure policy"):
            adapter.embed(["synthetic"])
        assert calls == []
    finally:
        client.close()


def test_sdk_extraction_schema_limits_and_source_are_bounded():
    _, _, _, _, turns, candidates, _, _ = build_fixture(load_fixtures()[0])
    captured = []
    count_requests = []

    def handler(request):
        if request.url.path.endswith(":countTokens"):
            count_requests.append(json.loads(request.content))
            return httpx.Response(200, json={"totalTokens": 200})
        captured.append(json.loads(request.content))
        text = json.dumps({"candidates": [candidates[0].model_dump(mode="json")]})
        return httpx.Response(
            200,
            json={"candidates": [{
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": "STOP",
            }]},
        )

    client = genai.Client(
        api_key="offline-fake",
        http_options={"client_args": {"transport": httpx.MockTransport(handler)}},
    )
    try:
        result = GeminiMemoryAdapter(fixture_settings(), client).extract(
            turns[0], timeout=2, inference_context=_inference_context()
        )
        assert result.candidates == tuple(candidates)
        assert result.attribution.identity.provider_id == "gemini"
        assert result.attribution.identity.model_id == "fake-chat"
        config = captured[0]["generationConfig"]
        assert config["maxOutputTokens"] == 2048
        assert config["responseMimeType"] == "application/json"
        assert config["responseJsonSchema"]
        counted = count_requests[0]["generateContentRequest"]["generationConfig"]
        assert counted["responseMimeType"] == config["responseMimeType"]
        assert counted["responseJsonSchema"] == config["responseJsonSchema"]
        instruction = captured[0]["systemInstruction"]["parts"][0]["text"]
        assert "exact contiguous excerpts" in instruction and "sensitive" in instruction
        sources = json.loads(captured[0]["contents"][0]["parts"][0]["text"])
        assert [s["id"] for s in sources] == [str(turns[0][0].id)]
    finally:
        client.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"embeddings": []},
        {"embeddings": [{"values": [1, 0]}]},
        {"embeddings": [{"values": [0, 0, 0]}]},
    ],
)
def test_invalid_embedding_responses_fail_closed(payload):
    client = genai.Client(
        api_key="offline-fake",
        http_options={
            "client_args": {
                "transport": httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
            }
        },
    )
    try:
        with pytest.raises(LLMInvalidResponseError):
            GeminiMemoryAdapter(fixture_settings(), client).embed(
                ["synthetic"], inference_context=_inference_context()
            )
    finally:
        client.close()


@pytest.mark.parametrize("kind", ["unavailable", "timeout", "invalid_json"])
def test_safe_provider_failure_mapping(kind):
    def handler(request):
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 200})
        if kind == "timeout":
            raise httpx.ReadTimeout("private provider text")
        if kind == "unavailable":
            return httpx.Response(503, json={"error": {"message": "private provider text"}})
        return httpx.Response(
            200,
            json={"candidates": [{
                "content": {"role": "model", "parts": [{"text": "not-json"}]},
                "finishReason": "STOP",
            }]},
        )

    client = genai.Client(
        api_key="offline-fake",
        http_options={"client_args": {"transport": httpx.MockTransport(handler)}},
    )
    _, _, _, _, turns, _, _, _ = build_fixture(load_fixtures()[0])
    try:
        error_type = {
            "unavailable": LLMUnavailableError,
            "timeout": LLMTimeoutError,
            "invalid_json": LLMInvalidResponseError,
        }[kind]
        with pytest.raises(error_type) as caught:
            GeminiMemoryAdapter(fixture_settings(), client).extract(
                turns[0], timeout=1, inference_context=_inference_context()
            )
        assert "private" not in str(caught.value)
    finally:
        client.close()


def test_memory_extraction_rejects_an_over_budget_input_before_generation():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 513})
        return httpx.Response(200, json={"candidates": []})

    client = genai.Client(
        api_key="offline-fake",
        http_options={"client_args": {"transport": httpx.MockTransport(handler)}},
    )
    _, _, _, _, turns, _, _, _ = build_fixture(load_fixtures()[0])
    try:
        with pytest.raises(LLMInvalidRequestError, match="token budget"):
            GeminiMemoryAdapter(fixture_settings(), client).extract(
                turns[0], timeout=2, inference_context=_inference_context()
            )
        assert calls == ["/v1beta/models/fake-chat:countTokens"]
    finally:
        client.close()


def test_memory_extraction_schema_count_rejects_near_ceiling_before_generation():
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path.endswith(":countTokens"):
            generation = body["generateContentRequest"]
            schema_present = bool(
                generation.get("generationConfig", {}).get("responseJsonSchema")
            )
            # The text-only request is at the limit; its actual structured form is over it.
            return httpx.Response(
                200, json={"totalTokens": 513 if schema_present else 512}
            )
        return httpx.Response(200, json={"candidates": []})

    client = genai.Client(
        api_key="offline-fake",
        http_options={"client_args": {"transport": httpx.MockTransport(handler)}},
    )
    _, _, _, _, turns, _, _, _ = build_fixture(load_fixtures()[0])
    try:
        with pytest.raises(LLMInvalidRequestError, match="token budget"):
            GeminiMemoryAdapter(fixture_settings(), client).extract(
                turns[0], timeout=2, inference_context=_inference_context()
            )
        assert len(requests) == 1
        assert requests[0][0] == "/v1beta/models/fake-chat:countTokens"
        counted_request = requests[0][1]["generateContentRequest"]
        assert counted_request["generationConfig"]["responseMimeType"] == "application/json"
        assert counted_request["generationConfig"]["responseJsonSchema"]
    finally:
        client.close()
