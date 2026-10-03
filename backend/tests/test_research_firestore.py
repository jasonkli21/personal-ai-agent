"""Installed SDK transaction boundary tests; never contact Firestore."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from google.api_core.exceptions import ServiceUnavailable

from personal_ai.agents.research.contracts import ResearchError, evolve
from personal_ai.agents.research.repositories import FirestoreResearchRepository, key_id
from personal_ai.storage.errors import ResourceNotFoundError, StorageUnavailableError
from tests.test_research_contracts import NOW, session


def environment():
    records, refs = {}, {}
    client = MagicMock()
    client._firestore_api.begin_transaction.return_value = SimpleNamespace(transaction=b"offline")
    tx = client.transaction.return_value
    tx.id, tx._write_pbs = b"offline", []

    def collection(name):
        result = MagicMock()

        def document(identifier):
            ref = refs.setdefault((name, identifier), MagicMock())
            ref.get.side_effect = lambda **kw: SimpleNamespace(
                exists=(name, identifier) in records,
                to_dict=lambda: records[(name, identifier)],
            )
            return ref

        result.document.side_effect = document
        return result

    client.collection.side_effect = collection
    return FirestoreResearchRepository(client), records, refs, client, tx


def test_create_replay_claim_fencing_and_safe_storage_errors():
    repo, records, refs, client, tx = environment()
    value = session()
    assert repo.create(value) == value
    assert tx.create.call_count == 2
    records[("research_sessions", str(value.id))] = repo._data(value)
    records[("research_request_keys", key_id(value))] = {
        "session_id": str(value.id),
        "owner_id": value.owner_id,
    }
    assert repo.create(session(request=value.request)) == value
    with pytest.raises(ResourceNotFoundError):
        repo.get("other", value.id)
    claimed = repo.claim("local", value.id, uuid4(), NOW, NOW + timedelta(seconds=30))
    records[("research_sessions", str(value.id))] = repo._data(claimed)
    with pytest.raises(ResearchError, match="research_conflict"):
        repo.save(evolve(claimed, revision=claimed.revision + 1, run_token=uuid4()))
    saved = repo.save(evolve(claimed, revision=claimed.revision + 1, state="failed"))
    assert saved.state == "failed"
    for method in (client._firestore_api.begin_transaction, client._firestore_api.commit):
        assert method.call_args.kwargs["retry"] is None
        assert 0 < method.call_args.kwargs["timeout"] <= 5
    for ref in refs.values():
        assert ref.get.call_args.kwargs["retry"] is None
        assert 0 < ref.get.call_args.kwargs["timeout"] <= 5
    client._firestore_api.commit.side_effect = ServiceUnavailable("private provider text")
    with pytest.raises(StorageUnavailableError):
        repo.save(evolve(claimed, revision=claimed.revision + 1, state="failed"))


def test_expiry_query_uses_the_persisted_utc_timestamp_type_and_bounded_rpcs():
    repo, _, _, client, _ = environment()
    value = session()
    collection = repo.sessions
    query = MagicMock()
    collection.where.return_value = query
    query.where.return_value = query
    query.order_by.return_value = query
    query.limit.return_value = query
    snapshot = SimpleNamespace(
        id=str(value.id), exists=True, reference=MagicMock(), update_time=NOW,
        to_dict=lambda: repo._data(value),
    )
    query.stream.return_value = (snapshot,)
    due = value.expires_at + timedelta(microseconds=1)

    assert repo.expire_due_for_owner("local", now=due, correlation_id="synthetic") == 1
    expiry_filter = next(
        call.kwargs["filter"] for call in query.where.call_args_list
        if call.kwargs["filter"].field_path == "expires_at"
    )
    assert isinstance(repo._data(value)["expires_at"], str)
    assert expiry_filter.value == (value.expires_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    assert expiry_filter.op_string == "<"
    update = client.batch.return_value.update.call_args.args[1]
    assert update["state"] == "expired" and update["answer"] is None
    assert update["updated_at"] == due.isoformat().replace("+00:00", "Z")
    query.stream.assert_called_once_with(retry=None, timeout=5)
    client.batch.return_value.commit.assert_called_once_with(retry=None, timeout=5)

    # The query includes future instants in this same second only so that
    # variable-precision stored timestamps cannot hide already expired ones.
    query.stream.return_value = (SimpleNamespace(
        id=str(value.id), exists=True, reference=MagicMock(), update_time=NOW,
        to_dict=lambda: repo._data(evolve(value, expires_at=due + timedelta(microseconds=1))),
    ),)
    client.batch.return_value.commit.reset_mock()
    assert repo.expire_due_for_owner("local", now=due, correlation_id="synthetic") == 0
    client.batch.return_value.commit.assert_not_called()
