from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime

from personal_ai.auth.scope import ApplicationScope, application_scope_context
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
