from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime
from uuid import uuid4

from personal_ai.auth.scope import ApplicationScope, application_scope_context
from personal_ai.context.builder import ContextBuildManifest
from personal_ai.context.traces import ContextTraceManifest
from personal_ai.entities import Conversation
from personal_ai.persistence.dynamodb import (
    _catalog_item,
    _conversation_payload,
    _metadata_item,
    _namespace,
    _timestamp,
)
from personal_ai.persistence.postgres_auth import PostgresAccountLifecycleRepository


class _Result:
    def __init__(self, *, row=None, rows=()):
        self.row = row
        self.rows = list(rows)

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _Connection:
    def execute(self, query, params=None):
        if "txid_current_snapshot" in query:
            return _Result(row=("snapshot-1",))
        if "FROM global_profiles" in query:
            return _Result(rows=[(
                "owner-global-profile-v1",
                {
                    "schema_version": "global-profile-v1",
                    "owner_id": "owner",
                    "revision": 2,
                    "fields": [{
                        "field": "preferred_units",
                        "value": "metric",
                        "shared_with_applications": ["travel"],
                        "set_by": "user",
                        "set_at": datetime(2026, 10, 5, tzinfo=UTC),
                    }],
                    "updated_at": datetime(2026, 10, 5, tzinfo=UTC),
                },
                2,
            )])
        if "FROM usage_budgets" in query:
            return _Result(rows=[(
                "usage:2026-10-05", "owner", "personal_ai", None, 1, "active", 3,
                datetime(2026, 10, 5, tzinfo=UTC), datetime(2027, 1, 4, tzinfo=UTC),
                date(2026, 10, 5), 7, 321,
            )])
        return _Result()


class _Database:
    @contextmanager
    def connection(self, *, snapshot=False):
        assert snapshot
        yield _Connection()


class _RuntimeTable:
    def query(self, **_kwargs):
        return []


class _TraceRuntimeTable(_RuntimeTable):
    def __init__(self, owner, scope, conversation, trace):
        self.scope = scope
        partition = f"{_namespace(scope, owner)}#CONV#{conversation.id}"
        self.metadata = _metadata_item(
            conversation, _conversation_payload(conversation), revision=1
        )
        self.catalog = _catalog_item(conversation, revision=1)
        self.trace = {
            "PK": partition,
            "SK": f"CTX#{_timestamp(trace.recorded_at)}#{trace.assistant_message_id}",
            "kind": "context-trace",
            "owner_id": owner,
            "application_id": scope.application_id,
            "workspace_id_present": scope.workspace_id is not None,
            "workspace_id": scope.workspace_id or "",
            "conversation_id": str(conversation.id),
            "user_message_id": str(trace.user_message_id),
            "assistant_message_id": str(trace.assistant_message_id),
            "request_id": trace.request_id,
            "recorded_at": _timestamp(trace.recorded_at),
            "payload": trace.model_dump_json(),
        }

    def get(self, key, **_kwargs):
        return self.metadata if key["SK"] == "META" else None

    def query(self, *, sort_prefix, partition, **_kwargs):
        if sort_prefix == "CONV#":
            return [self.catalog]
        if sort_prefix == "CTX#":
            return [self.trace]
        return []


def test_account_export_includes_typed_daily_usage_budget_columns():
    repository = PostgresAccountLifecycleRepository(_Database(), _RuntimeTable())

    with application_scope_context(
        ApplicationScope(application_id="personal_ai", workspace_id=None)
    ):
        result = repository.export_owner("owner", max_records=100, max_bytes=1_000_000)

    record = result["collections"]["usage_budgets"][0]
    assert record["document_id"] == "usage:2026-10-05"
    assert record["data"]["budget_day"] == "2026-10-05"
    assert record["data"]["provider_calls"] == 7
    assert record["data"]["input_tokens"] == 321
    assert record["data"]["expires_at"] == "2027-01-04T00:00:00+00:00"


def test_account_export_includes_owner_wide_global_profile_and_user_provenance():
    repository = PostgresAccountLifecycleRepository(_Database(), _RuntimeTable())

    with application_scope_context(
        ApplicationScope(application_id="personal_ai", workspace_id=None)
    ):
        result = repository.export_owner("owner", max_records=100, max_bytes=1_000_000)

    record = result["collections"]["global_profiles"][0]
    assert record["document_id"] == "owner-global-profile-v1"
    assert record["data"]["fields"][0]["field"] == "preferred_units"
    assert record["data"]["fields"][0]["set_by"] == "user"
    assert record["data"]["fields"][0]["shared_with_applications"] == ["travel"]


def test_account_export_includes_context_traces_and_tracks_them_in_snapshot_coverage():
    owner = "owner"
    scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
    now = datetime(2026, 10, 7, tzinfo=UTC)
    conversation = Conversation(
        id=uuid4(), owner_id=owner, title="Export fixture", created_at=now, updated_at=now
    )
    context = ContextBuildManifest(
        counter_kind="estimated",
        counter_version="fixture-v1",
        global_input_tokens=400,
        actual_input_tokens=50,
        effective_sensitivity="personal",
    )
    trace = ContextTraceManifest.from_build(
        context,
        request_id="export-trace-request",
        conversation_id=conversation.id,
        user_message_id=uuid4(),
        assistant_message_id=uuid4(),
        scope=scope,
        recorded_at=now,
    )
    table = _TraceRuntimeTable(owner, scope, conversation, trace)
    repository = PostgresAccountLifecycleRepository(_Database(), table)

    with application_scope_context(scope):
        result = repository.export_owner(owner, max_records=100, max_bytes=1_000_000)

    record = result["collections"]["context_traces"][0]
    assert record["document_id"] == str(trace.assistant_message_id)
    assert record["data"]["request_id"] == "export-trace-request"
    assert f"context_trace:{trace.assistant_message_id}" in result["snapshot_coverage"]["dynamodb"]["revisions"]
