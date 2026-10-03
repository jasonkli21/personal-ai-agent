"""Firestore transaction contract checks with an offline SDK-shaped fake."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from personal_ai.agents.research.contracts import ResearchRequest, ResearchSession, evolve
from personal_ai.agents.research.iterative_contracts import (
    ResearchRun,
    RunEvent,
    RunState,
    SafeEventPayload,
    StopReason,
)
from personal_ai.agents.research.iterative_repositories import (
    FirestoreIterativeResearchRepository,
)
from personal_ai.storage.errors import ResourceNotFoundError
from tests.test_iterative_research_contracts import NOW, initial_run


def environment():
    records, refs = {}, {}
    client = MagicMock()
    client._firestore_api.begin_transaction.return_value = SimpleNamespace(transaction=b"offline")
    transaction = client.transaction.return_value
    transaction.id, transaction._write_pbs = b"offline", []

    def collection(name):
        result = MagicMock()

        def document(identifier):
            ref = refs.setdefault((name, identifier), MagicMock())
            key = (name, identifier)
            ref.get.side_effect = lambda **kwargs: SimpleNamespace(
                exists=key in records,
                to_dict=lambda: records[key],
            )
            return ref

        result.document.side_effect = document
        return result

    def write(ref, value):
        key = next(key for key, candidate in refs.items() if candidate is ref)
        records[key] = value

    transaction.create.side_effect = write
    transaction.set.side_effect = write
    client.collection.side_effect = collection
    return FirestoreIterativeResearchRepository(client), records, client, transaction


def pending_session(run):
    request = ResearchRequest(
        question="Synthetic research question?",
        idempotency_key=uuid4(),
    )
    return ResearchSession(
        id=run.session_id,
        owner_id=run.owner_id,
        request=request,
        request_fingerprint=request.fingerprint(),
        state="pending",
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        iterative_run_id=run.id,
    )


def test_firestore_run_create_claim_commit_and_owner_fencing():
    repository, records, client, transaction = environment()
    run = initial_run()
    session = pending_session(run)
    records[("research_sessions", str(session.id))] = repository._data(session)

    assert repository.create(run) == run
    assert transaction.create.call_count == 2
    assert repository.get("local", run.id) == run
    assert repository.get_by_key("local", run.idempotency_key) == run
    with pytest.raises(ResourceNotFoundError):
        repository.get("another-owner", run.id)

    token = uuid4()
    claimed, running_session = repository.claim(
        "local", run.id, token, NOW, NOW + timedelta(seconds=30), NOW + timedelta(minutes=1)
    )
    assert claimed.state == RunState.ASSESSING
    assert running_session.state == "running" and running_session.run_token == token
    assert repository.get("local", run.id) == claimed

    now = NOW + timedelta(seconds=1)
    event = RunEvent(
        id=uuid4(),
        run_id=run.id,
        sequence=len(claimed.events),
        event_type="cancelled",
        idempotency_key=f"transition:{claimed.revision + 1}:cancelled",
        safe_payload=SafeEventPayload(state=RunState.CANCELLED, stop_reason=StopReason.CANCELLED),
        occurred_at=now,
    )
    cancelled = ResearchRun.model_validate({
        **claimed.model_dump(),
        "state": RunState.CANCELLED,
        "terminal_reason": StopReason.CANCELLED,
        "lease_owner": None,
        "lease_expires_at": None,
        "updated_at": now,
        "revision": claimed.revision + 1,
        "events": (*claimed.events, event),
    })
    stopped_session = evolve(
        running_session,
        state="insufficient",
        failure_code=StopReason.CANCELLED.value,
        updated_at=now,
        revision=running_session.revision + 1,
    )
    assert repository.commit("local", cancelled, stopped_session) == cancelled
    assert repository.get("local", run.id).terminal_reason == StopReason.CANCELLED
    assert repository.session("local", session.id).state == "insufficient"
    assert transaction.set.call_count == 4
    for method in (client._firestore_api.begin_transaction, client._firestore_api.commit):
        assert method.call_args.kwargs["retry"] is None
        assert 0 < method.call_args.kwargs["timeout"] <= 5
