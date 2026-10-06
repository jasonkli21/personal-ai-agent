"""Exercise account persistence and migration contracts without a cloud client."""

from copy import deepcopy
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector

from personal_ai.auth.account_data import (
    AccountRequestConflict,
    AccountRequestNotFound,
    ExportTooLarge,
    FirestoreAccountDataRepository,
)
from personal_ai.entities import Conversation


class Reference:
    def __init__(self, client, collection, document_id):
        self.client, self.collection, self.id = client, collection, document_id

    def get(self, **_kwargs):
        value = self.client.data.get(self.collection, {}).get(self.id)
        return SimpleNamespace(
            exists=value is not None,
            id=self.id,
            reference=self,
            update_time=datetime(2026, 10, 3, tzinfo=UTC),
            to_dict=lambda: deepcopy(value),
        )


class Query:
    def __init__(self, client, name, owner=None, limit=None, after=None):
        self.client, self.name = client, name
        self.owner, self.count, self.after = owner, limit, after

    def document(self, document_id):
        return Reference(self.client, self.name, document_id)

    def where(self, *, filter):
        assert filter.field_path == "owner_id" and filter.op_string == "=="
        return Query(self.client, self.name, filter.value, self.count, self.after)

    def order_by(self, field):
        assert field == "__name__"
        return self

    def limit(self, count):
        return Query(self.client, self.name, self.owner, count, self.after)

    def start_after(self, snapshot):
        return Query(self.client, self.name, self.owner, self.count, snapshot.id)

    def stream(self):
        records = [
            self.document(key).get()
            for key, value in sorted(self.client.data.get(self.name, {}).items())
            if (self.owner is None or value.get("owner_id") == self.owner)
            and (self.after is None or key > self.after)
        ]
        return iter(records[: self.count])


class Transaction:
    def __init__(self, client):
        self.client = client

    def create(self, ref, data):
        collection = self.client.data.setdefault(ref.collection, {})
        assert ref.id not in collection
        collection[ref.id] = deepcopy(data)
        self.client.writes.append((ref.collection, "create", data))

    def update(self, ref, changes, option=None):
        if option is not None:
            assert isinstance(option, firestore.LastUpdateOption)
        self.client.data[ref.collection][ref.id].update(deepcopy(changes))
        self.client.writes.append((ref.collection, "update", changes))

    def commit(self):
        pass


class Client:
    def __init__(self, data=None):
        self.data = deepcopy(data or {})
        self.writes = []
        self.closed = False

    def collection(self, name):
        return Query(self, name)

    def transaction(self):
        return Transaction(self)

    batch = transaction

    def close(self):
        self.closed = True


@pytest.fixture
def repository(monkeypatch):
    client = Client()
    monkeypatch.setattr("personal_ai.storage.firestore._firestore_client", lambda *_: client)
    monkeypatch.setattr(firestore, "transactional", lambda function: function)
    result = FirestoreAccountDataRepository(project_id=None, emulator_host=None)
    return result, client


def test_export_serializes_vectors_and_binary_and_excludes_foreign_owner(repository):
    repo, client = repository
    client.data["memories"] = {
        "owned": {"owner_id": "owner", "embedding": Vector([0.1, 0.2]), "blob": b"abc"},
        "foreign": {"owner_id": "other", "content": "private foreign data"},
    }
    result = repo.export_owner("owner", max_records=2, max_bytes=2000)
    records = result["collections"]["memories"]
    assert len(records) == 1 and records[0]["document_id"] == "owned"
    assert records[0]["data"]["embedding"] == {"$type": "vector", "values": [0.1, 0.2]}
    assert records[0]["data"]["blob"] == {"$type": "base64", "value": "YWJj"}
    repo.close()
    assert client.closed


def test_export_enforces_record_and_complete_envelope_byte_limits(repository):
    repo, client = repository
    client.data["messages"] = {str(i): {"owner_id": "owner"} for i in range(2)}
    with pytest.raises(ExportTooLarge):
        repo.export_owner("owner", max_records=1, max_bytes=2000)
    with pytest.raises(ExportTooLarge):
        repo.export_owner("owner", max_records=2, max_bytes=50)


def test_standalone_export_scans_past_other_application_records(repository):
    repo, client = repository
    client.data["memories"] = {
        f"{index:04d}": {
            "owner_id": "owner",
            "application_id": "travel",
            "workspace_id": None,
            "scope_version": 2,
        }
        for index in range(260)
    }
    client.data["memories"]["zzzz-legacy"] = {"owner_id": "owner", "content": "legacy"}

    result = repo.export_owner("owner", max_records=1, max_bytes=2000)

    assert result["application_id"] == "personal_ai"
    assert [item["document_id"] for item in result["collections"]["memories"]] == [
        "zzzz-legacy"
    ]


def test_deletion_repository_replays_preserve_audit_and_enforce_owner_and_state(repository):
    repo, client = repository
    key = uuid4()
    request = repo.create_deletion(owner_id="owner", idempotency_key=key, correlation_id="request")
    replay = repo.create_deletion(owner_id="owner", idempotency_key=key, correlation_id="replay")
    assert request == replay and len(client.data["audit_events"]) == 1
    request_id = request["id"]
    with pytest.raises(AccountRequestNotFound):
        repo.get_deletion(owner_id="foreign", request_id=request_id)
    with pytest.raises(AccountRequestNotFound):
        repo.transition_deletion(
            owner_id="foreign", request_id=request_id, action="confirm", correlation_id="foreign"
        )
    confirmed = repo.transition_deletion(
        owner_id="owner", request_id=request_id, action="confirm", correlation_id="confirm"
    )
    again = repo.transition_deletion(
        owner_id="owner", request_id=request_id, action="confirm", correlation_id="retry"
    )
    assert confirmed == again and len(client.data["audit_events"]) == 2
    cancelled = repo.transition_deletion(
        owner_id="owner", request_id=request_id, action="cancel", correlation_id="cancel"
    )
    assert cancelled["state"] == "cancelled"
    with pytest.raises(AccountRequestConflict):
        repo.transition_deletion(
            owner_id="owner", request_id=request_id, action="confirm", correlation_id="late"
        )


def migration_module():
    spec = spec_from_file_location(
        "migrate_local_owner", Path(__file__).parents[1] / "scripts/migrate_local_owner.py"
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migration_client():
    owner = "usr_0123456789abcdef0123456789abcdef"
    conversation = Conversation(
        id=uuid4(),
        owner_id="local",
        title="Synthetic",
        created_at=datetime(2026, 10, 3, tzinfo=UTC),
        updated_at=datetime(2026, 10, 3, tzinfo=UTC),
    )
    client = Client(
        {
            "identity_mappings": {owner: {"owner_id": owner, "status": "active"}},
            "conversations": {str(conversation.id): conversation.model_dump(mode="python")},
        }
    )
    return client, owner, conversation.id


def test_owner_migration_preserves_strict_record_schema_and_audits_separately():
    module = migration_module()
    client, owner, conversation_id = migration_client()
    assert module.migrate(client, owner_id=owner, apply=True) == 0
    record = Conversation.model_validate(client.data["conversations"][str(conversation_id)])
    assert record.owner_id == owner
    assert len(client.data["audit_events"]) == 1
    writes = len(client.writes)
    assert module.migrate(client, owner_id=owner, apply=True) == 0
    assert len(client.writes) == writes


def test_owner_migration_refuses_unsupported_aggregates_before_any_writes(capsys):
    module = migration_module()
    client, owner, conversation_id = migration_client()
    client.data["research_sessions"] = {"session": {"owner_id": "local"}}
    assert module.migrate(client, owner_id=owner, apply=False) == 0
    assert module.migrate(client, owner_id=owner, apply=True) == 2
    assert not client.writes
    assert client.data["conversations"][str(conversation_id)]["owner_id"] == "local"
    assert "no records were changed" in capsys.readouterr().err
