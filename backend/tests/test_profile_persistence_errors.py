from contextlib import contextmanager

import pytest

from personal_ai.context.profile import GlobalProfileFieldUpdate, GlobalProfileUpdate
from personal_ai.persistence import postgres_context
from personal_ai.persistence.postgres import PersistenceConflict
from personal_ai.persistence.postgres_context import PostgresGlobalProfileRepository


def test_profile_repository_maps_exhausted_initial_insert_retries(monkeypatch):
    class UniqueViolation(Exception):
        pass

    class Database:
        @contextmanager
        def transaction(self):
            yield object()

    attempts = []

    def ensure_namespace(_connection, _owner_id, _scope):
        attempts.append(True)
        raise UniqueViolation("private database details")

    monkeypatch.setattr(postgres_context, "_ensure_namespace", ensure_namespace)
    monkeypatch.setattr(
        postgres_context,
        "_is_unique_violation",
        lambda error: isinstance(error, UniqueViolation),
    )
    repository = PostgresGlobalProfileRepository(Database())
    update = GlobalProfileUpdate(
        fields=(GlobalProfileFieldUpdate(field="locale", value="en-GB"),)
    )

    with pytest.raises(PersistenceConflict, match="profile update contention") as error:
        repository.update("owner-1", update)

    assert len(attempts) == 3
    assert "private database details" not in str(error.value)
