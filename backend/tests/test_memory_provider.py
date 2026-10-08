"""Memory counting, generation, and embeddings use the pinned SDK gateway."""

import json

import httpx
import pytest

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


def _settings(**overrides):
    return fixture_settings(
        ai_api_key="offline-fake", ai_model="gemini-2.5-flash", **overrides
    )


def _gemini_response(settings, text):
    return {
        "modelVersion": settings.ai_model,
        "candidates": [{
            "content": {"role": "model", "parts": [{"text": text}]},
            "finishReason": "STOP",
        }],
        "usageMetadata": {
            "promptTokenCount": 200,
            "candidatesTokenCount": 30,
            "totalTokenCount": 230,
        },
    }


def test_litellm_embedding_batches_task_types_and_preserves_logical_space():
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append((request, body))
        assert all(item["outputDimensionality"] == 3 for item in body["requests"])
        return httpx.Response(
            200, json={"embeddings": [{"values": [3, 0, 0]} for _ in body["requests"]]}
        )

    settings = _settings(memory_embedding_dimensions=3, memory_embedding_batch_size=2)
    adapter = GeminiMemoryAdapter(
        settings, sync_transport_factory=lambda: httpx.MockTransport(handler)
    )
    embedded = adapter.embed(["a", "b", "c"], inference_context=_inference_context())
    query = adapter.embed(["query"], query=True, inference_context=_inference_context())

    assert tuple(item.values for item in embedded) == ((1.0, 0.0, 0.0),) * 3
    assert [len(body["requests"]) for _, body in requests] == [2, 1, 1]
    assert all(item["taskType"] == "RETRIEVAL_DOCUMENT" for item in requests[0][1]["requests"])
    assert requests[-1][1]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    assert all(item.space.provider_id == "google_genai" for item in embedded)
    assert all(item.space.version == "v1" for item in embedded)
    assert embedded[0].space.model_id == settings.memory_embedding_model
    assert embedded[0].space.dimensions == 3
    assert embedded[0].space.normalization == "l2"
    assert all(item.task == "document" for item in embedded)
    assert query[0].task == "query"
    assert requests[0][0].url.path.endswith(":batchEmbedContents")


def test_counter_and_embedding_require_authorization_envelope():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"totalTokens": 1})

    adapter = GeminiMemoryAdapter(
        _settings(), sync_transport_factory=lambda: httpx.MockTransport(handler)
    )
    with pytest.raises(LLMInvalidRequestError, match="disclosure policy"):
        adapter.counter.count([ChatMessage("user", "synthetic")])
    with pytest.raises(LLMInvalidRequestError, match="disclosure policy"):
        adapter.embed(["synthetic"])
    assert calls == []


def test_memory_extraction_counts_and_serializes_the_same_structured_schema():
    _, _, _, _, turns, candidates, _, _ = build_fixture(load_fixtures()[0])
    settings = _settings()
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 200})
        text = json.dumps({"candidates": [candidates[0].model_dump(mode="json")]})
        return httpx.Response(200, json=_gemini_response(settings, text))

    adapter = GeminiMemoryAdapter(
        settings, sync_transport_factory=lambda: httpx.MockTransport(handler)
    )
    result = adapter.extract(
        turns[0], timeout=2, inference_context=_inference_context()
    )

    assert result.candidates == tuple(candidates)
    assert result.attribution.identity.provider_id == "gemini"
    assert result.attribution.identity.model_id == settings.ai_model
    assert [path.endswith(":countTokens") for path, _ in requests] == [True, False]
    counted = requests[0][1]["generateContentRequest"]
    generated = requests[1][1]
    assert counted["generationConfig"]["response_json_schema"]
    assert counted["generationConfig"]["response_json_schema"] == (
        generated["generationConfig"]["response_json_schema"]
    )
    assert counted["system_instruction"] == generated["system_instruction"]
    assert generated["generationConfig"]["max_output_tokens"] == 2048
    instruction = generated["system_instruction"]["parts"][0]["text"]
    assert "exact contiguous excerpts" in instruction and "sensitive" in instruction
    source = json.loads(generated["contents"][0]["parts"][0]["text"])
    assert [item["id"] for item in source] == [str(turns[0][0].id)]


@pytest.mark.parametrize(
    "payload",
    [
        {"embeddings": []},
        {"embeddings": [{"values": [1, 0]}]},
        {"embeddings": [{"values": [0, 0, 0]}]},
    ],
)
def test_invalid_embedding_responses_fail_closed(payload):
    adapter = GeminiMemoryAdapter(
        _settings(memory_embedding_dimensions=3),
        sync_transport_factory=lambda: httpx.MockTransport(
            lambda _: httpx.Response(200, json=payload)
        ),
    )
    with pytest.raises(LLMInvalidResponseError):
        adapter.embed(["synthetic"], inference_context=_inference_context())


@pytest.mark.parametrize("kind", ["unavailable", "timeout", "invalid_json"])
def test_memory_provider_errors_are_normalized_without_body_disclosure(kind):
    settings = _settings()
    _, _, _, _, turns, candidates, _, _ = build_fixture(load_fixtures()[0])

    def handler(request):
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 200})
        if kind == "timeout":
            raise httpx.ReadTimeout("private provider body")
        if kind == "unavailable":
            return httpx.Response(503, json={"error": {"message": "private provider body"}})
        return httpx.Response(200, json=_gemini_response(settings, "not-json"))

    adapter = GeminiMemoryAdapter(
        settings, sync_transport_factory=lambda: httpx.MockTransport(handler)
    )
    expected = {
        "unavailable": LLMUnavailableError,
        "timeout": LLMTimeoutError,
        "invalid_json": LLMInvalidResponseError,
    }[kind]
    with pytest.raises(expected) as caught:
        adapter.extract(
            turns[0], timeout=2, inference_context=_inference_context()
        )
    assert "private provider body" not in str(caught.value)
    assert candidates


def test_memory_extraction_rejects_over_budget_input_before_generation():
    _, _, _, _, turns, _, _, _ = build_fixture(load_fixtures()[0])
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith(":countTokens"):
            return httpx.Response(200, json={"totalTokens": 513})
        return httpx.Response(200, json={"candidates": []})

    adapter = GeminiMemoryAdapter(
        _settings(), sync_transport_factory=lambda: httpx.MockTransport(handle)
    )
    with pytest.raises(LLMInvalidRequestError, match="token budget"):
        adapter.extract(turns[0], timeout=2, inference_context=_inference_context())
    assert len(paths) == 1
    assert paths[0].endswith(":countTokens")


def test_schema_near_ceiling_is_rejected_using_authoritative_schema_count():
    _, _, _, _, turns, _, _, _ = build_fixture(load_fixtures()[0])
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path.endswith(":countTokens"):
            schema = body["generateContentRequest"].get("generationConfig", {}).get(
                "response_json_schema"
            )
            return httpx.Response(200, json={"totalTokens": 513 if schema else 512})
        return httpx.Response(200, json={"candidates": []})

    adapter = GeminiMemoryAdapter(
        _settings(), sync_transport_factory=lambda: httpx.MockTransport(handler)
    )
    with pytest.raises(LLMInvalidRequestError, match="token budget"):
        adapter.extract(turns[0], timeout=2, inference_context=_inference_context())

    assert len(requests) == 1
    counted = requests[0][1]["generateContentRequest"]
    assert counted["generationConfig"]["response_json_schema"]
