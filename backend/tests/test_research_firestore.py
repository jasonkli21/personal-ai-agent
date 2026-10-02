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
