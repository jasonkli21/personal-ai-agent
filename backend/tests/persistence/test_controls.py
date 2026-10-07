from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from personal_ai.persistence.controls import (
    DynamoDBSafeguardStore,
    PostgresDailyBudgetRepository,
)


class _DynamoClient:
    def update_item(self, **kwargs):
        self.call = kwargs


class _DynamoTable:
    def __init__(self):
        self.client = _DynamoClient()
        self.table_name = "runtime"


class _Result:
    def fetchall(self):
        return [("old-1",), ("old-2",)]


class _Connection:
    def __init__(self):
        self.query = None
        self.params = None

    def execute(self, query, params):
        self.query = query
        self.params = params
        return _Result()


class _Database:
    def __init__(self):
        self.connection = _Connection()

    def transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def transaction_context():
            yield self.connection

        return transaction_context()


def test_dynamodb_request_window_expiration_is_numeric_epoch_seconds():
    table = _DynamoTable()
    safeguards = DynamoDBSafeguardStore(table, daily_budgets=object())

    safeguards.consume_request("owner", limit=10)

    values = table.client.call["ExpressionAttributeValues"]
    window_minute = int(table.client.call["Key"]["SK"]["S"].removeprefix("RATE#"))
    assert "N" in values[":expires"]
    assert int(values[":expires"]["N"]) == (window_minute + 2) * 60


def test_expired_usage_budget_cleanup_is_bounded_and_skip_locked():
    database = _Database()
    repository = PostgresDailyBudgetRepository(database)
    now = datetime.now(UTC)

    assert repository.purge_expired(now, limit=3) == 2

    assert "expires_at<=%s" in database.connection.query
    assert "LIMIT %s FOR UPDATE SKIP LOCKED" in database.connection.query
    assert database.connection.params == (now, 3)


def test_usage_budget_cleanup_migration_adds_expiry_order_index():
    migration = (
        Path(__file__).resolve().parents[2]
        / "src/personal_ai/persistence/migrations/014_usage_budget_expiry_cleanup.sql"
    ).read_text()

    assert "ON usage_budgets(expires_at, scope_id, record_id)" in migration
    assert "WHERE expires_at IS NOT NULL" in migration
