import asyncio
import json
from datetime import timedelta
from uuid import uuid4

import pytest

from personal_ai.agents.research.contracts import ResearchError, evolve
from personal_ai.evaluation.research import NOW, build_fixture, load_fixtures, run_fixture
from personal_ai.llm.fake import FakeLLMClient
from personal_ai.search.providers.brave import SearchError


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("fixture", load_fixtures(), ids=lambda f: f["name"])
async def test_full_pipeline_fixtures(fixture):
    assert (await run_fixture(fixture))["passed"]


async def complete(service, request):
    session = await service.create(request)
    events = [e async for e in service.stream(await service.prepare_run(session.id))]
    return await service.detail(session.id), events


@pytest.mark.anyio
async def test_progress_replay_expiry_and_memory_separation():
    service, request = build_fixture(load_fixtures()[0])
    result, events = await complete(service, request)
    assert [e.splitlines()[0] for e in events] == [
        "event: research.started",
        "event: research.planned",
        "event: research.attempt",
        "event: research.evidence",
        "event: research.selected",
        "event: research.terminal",
    ]
    assert result.answer.endswith("The synthetic star is blue. [1]")
    assert request.question not in "".join(events)
    assert "blue" not in "".join(events)
    assert len(service.adapter.calls) == 1
    assert len([e async for e in service.stream(await service.prepare_run(result.id))]) == 1
    assert len(service.adapter.calls) == 1
    service.clock = lambda: NOW + timedelta(days=2)
    expired = await service.detail(result.id)
    assert expired.state == "expired" and expired.answer is None and not expired.citations
    assert len(expired.evidence) == 1
    assert (await service.create(request)).state == "expired"


@pytest.mark.anyio
async def test_budget_overflow_does_not_call_model_or_drop_question():
    service, request = build_fixture(load_fixtures()[1], research_max_evidence_context_tokens=1)
    result, _ = await complete(service, request)
    assert result.state == "insufficient" and result.selection.excluded
    assert not result.citations


@pytest.mark.anyio
async def test_retry_cap_and_quota_failure():
    service, request = build_fixture(load_fixtures()[0])
    service.adapter.error = SearchError("search_timeout", retryable=True)
    result, _ = await complete(service, request)
    assert result.state == "failed" and len(result.attempts) == 4
    assert len(service.adapter.calls) == 2
    assert result.queries[0].state == "failed"
    service.clock = lambda: NOW + timedelta(days=2)
    assert (await service.detail(result.id)).state == "expired"


@pytest.mark.anyio
async def test_disconnect_and_abandoned_execution():
    service, request = build_fixture(load_fixtures()[0])
    session = await service.create(request)
    claimed = await service.prepare_run(session.id)
    stream = service.stream(claimed)
    await anext(stream)
    await stream.aclose()
    assert (await service.detail(session.id)).failure_code == "research_cancelled"
    second = await service.create(request.model_copy(update={"idempotency_key": uuid4()}))
    await service.prepare_run(second.id)
    service.clock = lambda: NOW + timedelta(seconds=31)
    assert (await service.detail(second.id)).failure_code == "execution_abandoned"
    assert not service.adapter.calls


@pytest.mark.anyio
async def test_deadline_and_provider_failure_safe():
    service, request = build_fixture(load_fixtures()[0], research_timeout_seconds=0.01)

    async def slow(query, limit):
        await asyncio.sleep(1)

    service.adapter.search = slow
    result, _ = await complete(service, request)
    assert result.state == "failed" and result.failure_code == "research_timeout"

    class BadLLM:
        async def stream(self, messages):
            raise RuntimeError("secret provider message")
            yield ""

    service, request = build_fixture(load_fixtures()[0])
    service.llm = BadLLM()
    result, events = await complete(service, request)
    assert result.state == "failed" and "secret" not in "".join(events)


@pytest.mark.anyio
async def test_reranker_failure_falls_back_without_conflict_loss():
    class Reranker:
        def rank(self, question, evidence):
            return evidence[:1]

    service, request = build_fixture(load_fixtures()[1])
    service.reranker = Reranker()
    result, _ = await complete(service, request)
    assert len(result.citations) == 2
    assert "blue" in result.answer and "red" in result.answer


@pytest.mark.anyio
async def test_synthesis_rejects_unknown_and_changed_quotes():
    service, request = build_fixture(load_fixtures()[0])
    service.llm = FakeLLMClient(
        (json.dumps({"excerpts": [{"evidence_id": str(uuid4()), "quote": "invented"}]}),)
    )
    result, _ = await complete(service, request)
    assert result.failure_code == "invalid_citations"
    with pytest.raises(ResearchError):
        service.repository.save(evolve(result, revision=result.revision + 1, state="running"))


@pytest.mark.anyio
async def test_native_cancellation_waits_for_inflight_storage_before_terminal_cleanup():
    from threading import Event

    service, request = build_fixture(load_fixtures()[0])
    saved = await service.create(request)
    claimed = await service.prepare_run(saved.id)
    original = service.repository.save
    entered, release = Event(), Event()
    first = True

    def blocking_save(session):
        nonlocal first
        if first:
            first = False
            entered.set()
            release.wait(timeout=2)
        return original(session)

    service.repository.save = blocking_save
    stream = service.stream(claimed)
    await anext(stream)
    pull = asyncio.create_task(anext(stream))
    await asyncio.to_thread(entered.wait, 1)
    pull.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pull
    result = await service.detail(saved.id)
    assert result.state == "failed" and result.failure_code == "research_cancelled"
    assert result.queries  # The in-flight planning write finished before cleanup.


@pytest.mark.anyio
async def test_literal_synthesis_rejects_altered_quotes_even_with_a_valid_id():
    from personal_ai.evidence.pipeline import validate_synthesis

    service, request = build_fixture(load_fixtures()[0])
    result, _ = await complete(service, request)
    output = json.dumps(
        {
            "excerpts": [
                {
                    "evidence_id": str(result.evidence[0].id),
                    "quote": "The synthetic star is purple.",
                }
            ]
        }
    )
    with pytest.raises(ResearchError, match="invalid_citations"):
        validate_synthesis(result, output)
