from time import monotonic

import pytest

from personal_ai.persistence import postgres


def test_database_rejects_an_expired_caller_budget_before_acquiring_connection(monkeypatch):
    database = postgres.PostgresDatabase(
        "postgresql://personal_ai@127.0.0.1:5432/personal_ai_test",
        environment="test",
    )
    opened = []
    monkeypatch.setattr(database, "open", lambda: opened.append(True))
    with pytest.raises(TimeoutError, match="deadline"), database.transaction(
        deadline=monotonic() - 1
    ):
        pytest.fail("expired operation must not enter a transaction")
    assert opened == []


def test_statement_budget_is_recomputed_before_every_sequential_write(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(postgres, "monotonic", lambda: clock[0])
    executed = []

    class Connection:
        def execute(self, query, params=None, **kwargs):
            if query.startswith("SELECT set_config"):
                clock[0] += 0.2
                return
            executed.append(query)
            clock[0] += 0.2

    connection = postgres._DeadlineConnection(
        Connection(), deadline=0.5, statement_timeout_ms=5_000, lock_timeout_ms=2_000
    )
    connection.execute("INSERT INTO first_table VALUES (1)")
    with pytest.raises(TimeoutError, match="deadline"):
        connection.execute("INSERT INTO second_table VALUES (2)")
    assert executed == ["INSERT INTO first_table VALUES (1)"]
