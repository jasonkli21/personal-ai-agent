"""Memory auxiliary calls inherit server-owned application disclosure policy."""

import json
from uuid import uuid4

import httpx
import pytest
from google import genai

from personal_ai.applications.contracts import ApplicationContextRequest
from personal_ai.applications.registry import default_application_registry
from personal_ai.auth.scope import RequestScope
from personal_ai.context.providers import ContextPreparationError
from personal_ai.evaluation.memory import build_fixture, fixture_settings, load_fixtures
from personal_ai.llm.memory import GeminiMemoryAdapter
from personal_ai.memory.lifecycle import MemoryJob
from personal_ai.memory.lifecycle_jobs import MemoryLifecycleWorker
from personal_ai.memory.services import MemoryExtractionService, MemoryRetriever


def _context(completed, *, deny_disclosure=False, maximum="sensitive", version="test-memory-policy"):
    registry = default_application_registry()
    registration = registry.registration(completed.application_id)
    base_policy = registration.definition.context_policy
    providers = list(base_policy.provider_policies)
    memory_index = next(index for index, item in enumerate(providers) if item.provider_id == "ai_memory")
    memory_policy = providers[memory_index]
    if deny_disclosure:
        operations = tuple(
            operation.model_copy(update={"model_disclosure": False})
            if operation.operation == "search"
            else operation
            for operation in memory_policy.operations
        )
        providers[memory_index] = memory_policy.model_copy(update={"operations": operations})
    policy = base_policy.model_copy(update={
        "version": version,
        "provider_policies": tuple(providers),
        "maximum_model_sensitivity": maximum,
    })
    definition = registration.definition.model_copy(update={"context_policy": policy})
    return ApplicationContextRequest(
        definition=definition,
        scope=RequestScope(
            owner_id=completed.owner_id,
            request_id="memory-policy-test",
            application_id=completed.application_id,
            workspace_id=completed.workspace_id,
        ),
        context_provider_capabilities=registration.context_providers,
        tool_capabilities=registration.tools,
    )


def _fixture():
    fixture = next(item for item in load_fixtures() if item["name"] == "later-preference")
    return build_fixture(fixture)


class _RemoteSpy:
    requires_inference_context = True

    def __init__(self):
        self.calls = []

    def extract(self, *args, **kwargs):
        self.calls.append(("extract", args, kwargs))
        return ()

    def embed(self, *args, **kwargs):
        self.calls.append(("embed", args, kwargs))
        return ()


@pytest.mark.parametrize(
    "context_options",
    [
        {"deny_disclosure": True},
        {"maximum": "personal"},
    ],
)
def test_denied_memory_policy_blocks_extraction_count_generation_and_embedding(context_options):
    settings, _, messages, memories, turns, _, _, _ = _fixture()
    settings.memory_enabled = settings.memory_extraction_enabled = True
    remote = _RemoteSpy()
    context = _context(turns[0][1], **context_options)
    extraction = MemoryExtractionService(settings, memories, messages, remote, remote)

    result = extraction.run(turns[0][1], application_context=context)

    assert result.reasons == ("policy_denied",)
    assert remote.calls == []


def test_denied_memory_policy_blocks_query_embedding_before_retrieval():
    settings, _, messages, memories, turns, _, pending, _ = _fixture()
    settings.memory_enabled = True
    remote = _RemoteSpy()

    result = MemoryRetriever(settings, memories, messages, remote).retrieve(
        "local",
        pending.content,
        [pending],
        application_context=_context(turns[0][1], deny_disclosure=True),
    )

    assert result.diagnostics == ("policy_denied",)
    assert remote.calls == []


def test_allowed_policy_reaches_count_structured_generation_and_embedding_with_attribution():
    settings, _, messages, memories, turns, candidates, _, _ = _fixture()
    settings.memory_enabled = settings.memory_extraction_enabled = True
    requests = []

    def handler(request):
        if request.url.path.endswith(":countTokens"):
            requests.append(("count", json.loads(request.content)))
            return httpx.Response(200, json={"totalTokens": 200})
        if request.url.path.endswith(":batchEmbedContents"):
            requests.append(("embedding", json.loads(request.content)))
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={"embeddings": [{"values": [1, 0, 0]} for _ in body["requests"]]},
            )
        requests.append(("generation", json.loads(request.content)))
        text = json.dumps({"candidates": [candidates[0].model_dump(mode="json")]})
        return httpx.Response(200, json={
            "candidates": [{
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": "STOP",
            }],
            "usageMetadata": {
                "promptTokenCount": 200,
                "candidatesTokenCount": 30,
                "totalTokenCount": 230,
            },
        })

    client = genai.Client(
        api_key="offline-fake",
        http_options={"client_args": {"transport": httpx.MockTransport(handler)}},
    )
    adapter = GeminiMemoryAdapter(settings, client)
    used_contexts = []
    original_extract, original_embed = adapter.extract, adapter.embed

    def record_extract(*args, **kwargs):
        used_contexts.append(kwargs["inference_context"])
        return original_extract(*args, **kwargs)

    def record_embed(*args, **kwargs):
        used_contexts.append(kwargs["inference_context"])
        return original_embed(*args, **kwargs)

    adapter.extract = record_extract
    adapter.embed = record_embed
    context = _context(turns[0][1], version="allowed-memory-policy-v4")
    try:
        result = MemoryExtractionService(
            settings, memories, messages, adapter, adapter
        ).run(turns[0][1], application_context=context)
    finally:
        client.close()

    assert result.created
    assert {context.policy_version for context in used_contexts} == {"allowed-memory-policy-v4"}
    assert all(context.effective_sensitivity == "sensitive" for context in used_contexts)
    assert [kind for kind, _ in requests] == ["count", "generation", "embedding"]
    assert result.attributions[0].status == "success"
    assert result.attributions[0].usage.total_tokens == 230


def test_background_consolidation_reresolves_scope_policy_before_remote_embedding():
    settings = fixture_settings(memory_enabled=True, memory_lifecycle_worker_enabled=True,
                                memory_consolidation_enabled=True)
    _, _, _, _, turns, _, _, _ = _fixture()
    denied_context = _context(turns[0][1], deny_disclosure=True)
    resolved = []
    remote = _RemoteSpy()

    class Consolidator:
        called = False

        def plan(self, **kwargs):
            self.called = True

    consolidator = Consolidator()
    worker = MemoryLifecycleWorker(
        settings, lifecycle=object(), memories=object(), messages=object(), embedder=remote,
        consolidator=consolidator,
        application_context_resolver=lambda **kwargs: (resolved.append(kwargs) or denied_context),
    )
    job = MemoryJob(
        id=uuid4(), owner_id=turns[0][1].owner_id,
        application_id=turns[0][1].application_id,
        workspace_id=turns[0][1].workspace_id, scope_version=2,
        job_type="consolidation", candidate_memory_ids=(uuid4(), uuid4()),
        policy_version="score-v1", policy_snapshot={"version": "score-v1"},
        idempotency_key="worker-policy-test",
        created_at=turns[0][1].created_at, updated_at=turns[0][1].created_at,
    )

    context = worker._resolve_application_context(job)
    with pytest.raises(ContextPreparationError):
        worker._consolidate(job, uuid4(), 1e30, application_context=context)

    assert resolved[0]["application_id"] == job.application_id
    assert resolved[0]["workspace_id"] == job.workspace_id
    assert not consolidator.called
    assert remote.calls == []
