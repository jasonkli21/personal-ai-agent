"""Offline contract, provider, evidence, replay, and HTTP tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import ServiceUnavailable
from pydantic import ValidationError
from starlette.requests import Request

from personal_ai.api.dependencies import get_settings
from personal_ai.auth.account_data import EXPORT_COLLECTIONS
from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.evaluation.research import build_fixture, load_fixtures
from personal_ai.itinerary_proposals.contracts import (
    ItineraryProposalRequest,
    ItineraryProposalResult,
    ModelProposal,
    ProposalError,
)
from personal_ai.itinerary_proposals.fakes import FakeItineraryProposalLLMClient
from personal_ai.itinerary_proposals.repositories import (
    FirestoreItineraryProposalRepository,
    InMemoryItineraryProposalRepository,
    proposal_id_for,
)
from personal_ai.itinerary_proposals.service import ItineraryProposalService
from personal_ai.main import app
from personal_ai.settings import Settings
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "itinerary-proposal-example.json"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def settings(**updates) -> Settings:
    values = {
        "_env_file": None,
        "ai_provider": "fake",
        "ai_model": "synthetic",
        "app_environment": "test",
        "itinerary_proposals_enabled": True,
        "itinerary_proposal_storage": "memory",
    }
    values.update(updates)
    return Settings(**values)


def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text())


def fixture_request() -> ItineraryProposalRequest:
    return ItineraryProposalRequest.model_validate_json(json.dumps(fixture_payload()["request"]))


def build_service(
    *,
    llm=None,
    repository=None,
    research_repository_factory=None,
    clock=None,
    settings_overrides=None,
    **overrides,
):
    configured = settings(**(settings_overrides or {}), **overrides)
    return ItineraryProposalService(
        configured,
        repository or InMemoryItineraryProposalRepository(),
        ContextAssembler(configured, EstimatedTokenCounter()),
        llm or FakeItineraryProposalLLMClient(),
        owner_id="local",
        research_repository_factory=research_repository_factory,
        clock=clock or (lambda: NOW),
    )


def firestore_proposal_repository():
    records, refs, ref_ids = {}, {}, {}
    client = MagicMock()
    client._firestore_api.begin_transaction.return_value = SimpleNamespace(transaction=b"offline")
    tx = client.transaction.return_value
    tx.id, tx._write_pbs = b"offline", []

    def collection(name):
        result = MagicMock()

        def document(identifier):
            ref = refs.setdefault((name, identifier), MagicMock())
            ref_ids[id(ref)] = (name, identifier)
            ref.get.side_effect = lambda **kwargs: SimpleNamespace(
                exists=(name, identifier) in records,
                to_dict=lambda: records[(name, identifier)],
            )
            return ref

        result.document.side_effect = document
        return result

    def transaction_set(ref, data):
        records[ref_ids[id(ref)]] = data

    tx.set.side_effect = transaction_set
    client.collection.side_effect = collection
    return FirestoreItineraryProposalRepository(client), records, refs, client, tx


@pytest.mark.anyio
async def test_exact_consumer_fixture_replays_immutable_result_and_rejects_changed_content():
    service = build_service()
    request = fixture_request()

    first = await service.create(request)
    replay = await service.create(request)

    assert first.state == "proposed"
    assert first.proposal_id == proposal_id_for("local", request.idempotency_key)
    assert [item.model_dump(mode="json") for item in first.operations] == fixture_payload()[
        "model_output"
    ]["operations"]
    assert replay == first
    assert len(service.llm.requests) == 1
    with pytest.raises(ProposalError, match="idempotency_conflict"):
        await service.create(request.model_copy(update={"instruction": "Different request."}))


def test_firestore_owner_scoped_transaction_replay_and_bounded_result_storage():
    repo, records, refs, client, tx = firestore_proposal_repository()
    request = fixture_request()
    fingerprint = request.fingerprint()
    first, created = repo.begin(
        owner_id="local",
        request=request,
        request_fingerprint=fingerprint,
        now=NOW,
        execution_deadline=NOW + timedelta(seconds=35),
    )
    assert created and first.state == "running"
    stored = records[("itinerary_proposals", str(first.proposal_id))]
    assert isinstance(stored["retained_until"], datetime)
    assert first.proposal_id == proposal_id_for("local", request.idempotency_key)
    assert "itinerary_proposals" in EXPORT_COLLECTIONS

    replay, created = repo.begin(
        owner_id="local",
        request=request,
        request_fingerprint=fingerprint,
        now=NOW + timedelta(seconds=1),
        execution_deadline=NOW + timedelta(seconds=36),
    )
    assert not created and replay == first
    with pytest.raises(ProposalError, match="idempotency_conflict"):
        repo.begin(
            owner_id="local",
            request=request,
            request_fingerprint="0" * 64,
            now=NOW + timedelta(seconds=1),
            execution_deadline=NOW + timedelta(seconds=36),
        )

    terminal = ItineraryProposalResult(
        proposal_id=first.proposal_id,
        state="insufficient",
        trip_handle=request.context.trip_handle,
        operations=(),
        operation_support=(),
        citations=(),
        failure_code="no_safe_operations",
        created_at=first.created_at,
        expires_at=first.proposal_expires_at,
    )
    completed = repo.complete(first, terminal)
    assert completed.result == terminal
    assert repo.get("local", first.proposal_id) == completed
    with pytest.raises(ResourceNotFoundError):
        repo.get("another-owner", first.proposal_id)

    for method in (client._firestore_api.begin_transaction, client._firestore_api.commit):
        assert method.call_args.kwargs["retry"] is None
        assert 0 < method.call_args.kwargs["timeout"] <= 5
    assert (
        refs[("itinerary_proposals", str(first.proposal_id))].get.call_args.kwargs["retry"] is None
    )
    assert tx.set.call_count == 2


def test_firestore_repository_maps_uncertain_commit_to_safe_storage_error():
    repo, _, _, client, _ = firestore_proposal_repository()
    client._firestore_api.commit.side_effect = ServiceUnavailable("private provider detail")
    with pytest.raises(StorageUnavailableError, match="proposal storage unavailable"):
        repo.begin(
            owner_id="local",
            request=fixture_request(),
            request_fingerprint=fixture_request().fingerprint(),
            now=NOW,
            execution_deadline=NOW + timedelta(seconds=35),
        )


@pytest.mark.anyio
async def test_unknown_evidence_handles_are_rejected_as_invalid_model_output():
    output = fixture_payload()["model_output"]
    output["operation_support"] = [{"operation_index": 0, "evidence_handles": ["e_unknown0001"]}]
    result = await build_service(llm=FakeItineraryProposalLLMClient((json.dumps(output),))).create(
        fixture_request()
    )
    assert result.state == "failed"
    assert result.failure_code == "invalid_model_output"
    assert result.operations == ()


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            (
                '{"schema_version":"itinerary-proposal-v1","trip_handle":"h_trip00001",'
                '"status":"proposed","failure_code":null,"operations":[],"operation_support":[]}'
            ),
            "invalid_model_output",
        ),
        (
            (
                '{"schema_version":"itinerary-proposal-v1","schema_version":"other",'
                '"trip_handle":"h_trip00001","status":"insufficient",'
                '"failure_code":"no_safe_operations","operations":[],"operation_support":[]}'
            ),
            "invalid_model_output",
        ),
    ],
)
@pytest.mark.anyio
async def test_empty_or_duplicate_key_model_json_fails_closed(raw, expected):
    service = build_service(llm=FakeItineraryProposalLLMClient((raw,)))
    result = await service.create(fixture_request())
    assert result.state == "failed"
    assert result.failure_code == expected
    assert result.operations == ()


@pytest.mark.parametrize(
    "operation, context_update, failure",
    [
        (
            {
                "kind": "add_item",
                "day_handle": "h_trip00001",
                "candidate_handle": "h_cand00001",
                "item_type": "activity",
                "position": 0,
                "start_time": None,
                "end_time": None,
            },
            {},
            "invalid_model_output",
        ),
        (
            {
                "kind": "move_item",
                "item_handle": "h_item0001",
                "day_handle": "h_day00001",
                "position": 0,
            },
            {"item": {"protected": True}},
            "invalid_model_output",
        ),
        (
            {"kind": "remove_item", "item_handle": "h_item0001"},
            {},
            "invalid_model_output",
        ),
        (
            {
                "kind": "add_item",
                "day_handle": "h_day00001",
                "candidate_handle": "h_item0001",
                "item_type": "activity",
                "position": 0,
                "start_time": None,
                "end_time": None,
            },
            {},
            "invalid_model_output",
        ),
    ],
)
@pytest.mark.anyio
async def test_unknown_cross_kind_protected_and_unallowlisted_handles_are_rejected(
    operation, context_update, failure
):
    payload = fixture_payload()
    if "item" in context_update:
        payload["request"]["context"]["days"][0]["items"][0].update(context_update["item"])
    request = ItineraryProposalRequest.model_validate_json(json.dumps(payload["request"]))
    model_value = payload["model_output"].copy()
    model_value["operations"] = [operation]
    raw = json.dumps(model_value)
    result = await build_service(llm=FakeItineraryProposalLLMClient((raw,))).create(request)
    assert result.state == "failed"
    assert result.failure_code == failure


def test_context_rejects_unknown_fields_duplicates_and_false_removal_flags():
    payload = fixture_payload()["request"]
    payload["context"]["days"][0]["items"][0]["owner_id"] = "private-owner"
    with pytest.raises(ValidationError):
        ItineraryProposalRequest.model_validate_json(json.dumps(payload))

    payload = fixture_payload()["request"]
    payload["context"]["removable_item_handles"] = ["h_item0001"]
    with pytest.raises(ValidationError):
        ItineraryProposalRequest.model_validate_json(json.dumps(payload))


@pytest.mark.anyio
async def test_shared_context_keeps_ids_urls_and_private_fields_out_of_model_input():
    research, research_request = build_fixture(load_fixtures()[0], itinerary_proposals_enabled=True)
    session = await research.create(research_request)
    claimed = await research.prepare_run(session.id)
    _ = [event async for event in research.stream(claimed)]
    completed = await research.detail(session.id)
    request = fixture_request().model_copy(update={"research_session_ids": (completed.id,)})
    configured = research.settings.model_copy(
        update={"itinerary_proposals_enabled": True, "itinerary_proposal_storage": "memory"}
    )
    proposal_llm = FakeItineraryProposalLLMClient()
    service = ItineraryProposalService(
        configured,
        InMemoryItineraryProposalRepository(),
        ContextAssembler(configured, EstimatedTokenCounter()),
        proposal_llm,
        owner_id="local",
        research_repository_factory=lambda: research.repository,
        clock=lambda: datetime(2026, 10, 2, 0, 0, 1, tzinfo=UTC),
    )
    result = await service.create(request)

    assert result.state == "proposed"
    assert result.citations
    assert result.citations[0].url.startswith("https://example.org/")
    assert result.operation_support[0].evidence_handles == (result.citations[0].evidence_handle,)
    combined = "\n".join(message.content for message in proposal_llm.requests[0])
    assert str(completed.id) not in combined
    assert "https://example.org/" not in combined
    assert "owner_id" not in combined
    assert "PRIVATE" not in combined


@pytest.mark.anyio
async def test_research_session_expiry_caps_proposal_evidence_lifetime():
    research, research_request = build_fixture(load_fixtures()[0], itinerary_proposals_enabled=True)
    session = await research.create(research_request)
    claimed = await research.prepare_run(session.id)
    _ = [event async for event in research.stream(claimed)]
    completed = await research.detail(session.id)
    proposal_now = datetime(2026, 10, 2, 0, 0, 1, tzinfo=UTC)
    short_session = completed.model_copy(update={"expires_at": proposal_now + timedelta(minutes=5)})

    class ShortLivedResearchRepository:
        def get(self, owner_id, session_id):
            assert owner_id == short_session.owner_id
            assert session_id == short_session.id
            return short_session

    request = fixture_request().model_copy(update={"research_session_ids": (completed.id,)})
    configured = research.settings.model_copy(
        update={"itinerary_proposals_enabled": True, "itinerary_proposal_storage": "memory"}
    )
    service = ItineraryProposalService(
        configured,
        InMemoryItineraryProposalRepository(),
        ContextAssembler(configured, EstimatedTokenCounter()),
        FakeItineraryProposalLLMClient(),
        owner_id="local",
        research_repository_factory=ShortLivedResearchRepository,
        clock=lambda: proposal_now,
    )
    result = await service.create(request)
    assert result.state == "proposed"
    assert result.expires_at == short_session.expires_at


@pytest.mark.anyio
async def test_cross_owner_research_observation_is_rejected_before_generation():
    research, research_request = build_fixture(load_fixtures()[0], itinerary_proposals_enabled=True)
    session = await research.create(research_request)
    claimed = await research.prepare_run(session.id)
    _ = [event async for event in research.stream(claimed)]
    completed = await research.detail(session.id)
    foreign = completed.model_copy(
        update={
            "observations": tuple(
                item.model_copy(update={"owner_id": "another-owner"})
                for item in completed.observations
            )
        }
    )

    class ForeignObservationRepository:
        def get(self, owner_id, session_id):
            assert owner_id == "local"
            assert session_id == completed.id
            return foreign

    request = fixture_request().model_copy(update={"research_session_ids": (completed.id,)})
    configured = research.settings.model_copy(
        update={"itinerary_proposals_enabled": True, "itinerary_proposal_storage": "memory"}
    )
    llm = FakeItineraryProposalLLMClient()
    service = ItineraryProposalService(
        configured,
        InMemoryItineraryProposalRepository(),
        ContextAssembler(configured, EstimatedTokenCounter()),
        llm,
        owner_id="local",
        research_repository_factory=ForeignObservationRepository,
        clock=lambda: datetime(2026, 10, 2, 0, 0, 1, tzinfo=UTC),
    )

    result = await service.create(request)
    assert result.state == "insufficient"
    assert result.failure_code == "insufficient_evidence"
    assert not llm.requests


@pytest.mark.anyio
async def test_result_expiry_withholds_operations_and_does_not_extend_on_replay():
    clock = [NOW]
    service = build_service(clock=lambda: clock[0])
    request = fixture_request()
    first = await service.create(request)
    clock[0] = first.expires_at + timedelta(seconds=1)

    expired = await service.detail(first.proposal_id)
    replay = await service.create(request)

    assert expired.state == "expired"
    assert expired.operations == ()
    assert replay.state == "expired"
    assert len(service.llm.requests) == 1


@pytest.mark.anyio
async def test_concurrent_replay_is_fenced_and_dispatches_only_one_model_call():
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingLLM(FakeItineraryProposalLLMClient):
        async def stream(self, messages):
            self.requests.append(tuple(messages))
            started.set()
            await release.wait()
            async for delta in FakeItineraryProposalLLMClient().stream(messages):
                yield delta

    llm = BlockingLLM()
    service = build_service(llm=llm)
    request = fixture_request()
    task = asyncio.create_task(service.create(request))
    await started.wait()

    with pytest.raises(ProposalError, match="proposal_busy"):
        await service.create(request)

    release.set()
    result = await task
    assert result.state == "proposed"
    assert len(llm.requests) == 1


@pytest.mark.anyio
async def test_timeout_and_oversized_output_are_terminal_for_the_same_key():
    class SlowLLM(FakeItineraryProposalLLMClient):
        async def stream(self, messages):
            self.requests.append(tuple(messages))
            await asyncio.sleep(0.03)
            yield "{}"

    llm = SlowLLM()
    service = build_service(llm=llm, itinerary_proposal_timeout_seconds=0.01)
    request = fixture_request()
    timed_out = await service.create(request)
    replay = await service.create(request)
    assert timed_out.failure_code == "generation_outcome_unknown"
    assert replay == timed_out
    assert len(llm.requests) == 1

    oversized = build_service(
        llm=FakeItineraryProposalLLMClient((" " * 2048,)),
        itinerary_proposal_max_response_bytes=1024,
    )
    failed = await oversized.create(fixture_request())
    assert failed.state == "failed"
    assert failed.failure_code == "invalid_model_output"


@pytest.mark.anyio
async def test_external_evidence_requires_citations_for_every_operation():
    research, research_request = build_fixture(load_fixtures()[0], itinerary_proposals_enabled=True)
    session = await research.create(research_request)
    claimed = await research.prepare_run(session.id)
    _ = [event async for event in research.stream(claimed)]
    completed = await research.detail(session.id)
    request = fixture_request().model_copy(update={"research_session_ids": (completed.id,)})
    output = fixture_payload()["model_output"]
    uncited_llm = FakeItineraryProposalLLMClient((json.dumps(output),))
    configured = research.settings.model_copy(
        update={"itinerary_proposals_enabled": True, "itinerary_proposal_storage": "memory"}
    )
    service = ItineraryProposalService(
        configured,
        InMemoryItineraryProposalRepository(),
        ContextAssembler(configured, EstimatedTokenCounter()),
        uncited_llm,
        owner_id="local",
        research_repository_factory=lambda: research.repository,
        clock=lambda: datetime(2026, 10, 2, 0, 0, 1, tzinfo=UTC),
    )

    result = await service.create(request)
    assert result.state == "uncited"
    assert result.failure_code == "uncited_evidence"
    assert result.operations == ()


@pytest.mark.anyio
async def test_expired_research_evidence_stops_before_model_call():
    research, research_request = build_fixture(load_fixtures()[0], itinerary_proposals_enabled=True)
    session = await research.create(research_request)
    claimed = await research.prepare_run(session.id)
    _ = [event async for event in research.stream(claimed)]
    completed = await research.detail(session.id)
    request = fixture_request().model_copy(update={"research_session_ids": (completed.id,)})
    configured = research.settings.model_copy(
        update={"itinerary_proposals_enabled": True, "itinerary_proposal_storage": "memory"}
    )
    llm = FakeItineraryProposalLLMClient()
    service = ItineraryProposalService(
        configured,
        InMemoryItineraryProposalRepository(),
        ContextAssembler(configured, EstimatedTokenCounter()),
        llm,
        owner_id="local",
        research_repository_factory=lambda: research.repository,
        clock=lambda: completed.expires_at + timedelta(seconds=1),
    )

    result = await service.create(request)
    assert result.state == "expired"
    assert result.failure_code == "evidence_expired"
    assert not llm.requests


def test_proposal_request_is_counted_by_existing_provider_safeguards():
    from personal_ai.auth.middleware import _provider_reservation, _provider_switch_is_on

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": "/v1/travel/itinerary-proposals",
            "raw_path": b"/v1/travel/itinerary-proposals",
            "query_string": b"",
            "headers": [],
            "server": ("example.test", 443),
            "client": ("test", 1),
            "root_path": "",
        }
    )
    configured = settings(
        ai_provider="gemini",
        itinerary_proposal_generator="gemini",
        itinerary_proposal_provider_enabled=True,
        itinerary_proposal_storage="firestore",
        ai_api_key="synthetic-key",
        external_providers_kill_switch_enabled=True,
    )
    calls, tokens = _provider_reservation(request, configured)
    assert calls == 1
    assert tokens == configured.itinerary_proposal_max_input_tokens
    assert _provider_switch_is_on(request, configured)


def test_disabled_route_does_not_construct_proposal_storage():
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = lambda: settings(itinerary_proposals_enabled=False)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/travel/itinerary-proposals",
                json=fixture_payload()["request"],
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides = previous


def test_fake_backed_http_endpoint_returns_and_reopens_typed_result():
    previous = app.dependency_overrides.copy()
    configured = settings(
        itinerary_proposals_enabled=True,
        itinerary_proposal_storage="memory",
        itinerary_proposal_generator="fake",
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/travel/itinerary-proposals",
                json=fixture_payload()["request"],
            )
            assert response.status_code == 201
            result = response.json()
            detail = client.get(f"/v1/travel/itinerary-proposals/{result['proposal_id']}")
            by_key = client.get(
                "/v1/travel/itinerary-proposals/by-key/"
                + fixture_payload()["request"]["idempotency_key"]
            )
        assert detail.status_code == 200
        assert detail.json() == result
        assert by_key.status_code == 200
        assert by_key.json() == result
        assert result["state"] == "proposed"
        assert result["operations"][0]["candidate_handle"] == "h_cand00001"
    finally:
        app.dependency_overrides = previous


def test_fake_backed_route_rejects_body_over_limit_before_parsing():
    previous = app.dependency_overrides.copy()
    configured = settings(itinerary_proposals_enabled=True)
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/travel/itinerary-proposals",
                content=b" " * (262_144 + 1),
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "proposal_request_too_large"
    finally:
        app.dependency_overrides = previous


def test_model_contract_rejects_wrong_wire_version_and_extra_fields():
    payload = fixture_payload()["model_output"]
    payload["extra"] = "not allowed"
    with pytest.raises(ValidationError):
        ModelProposal.model_validate_json(json.dumps(payload))
