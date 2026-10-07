from __future__ import annotations

import hashlib
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_ai.persistence.firestore_migration import (
    DELETE_ORDER,
    DYNAMODB_FAMILIES,
    FIRESTORE_FAMILIES,
    MIGRATION_ORDER,
    MigrationRejected,
    SourceRecord,
    digest,
    map_source_record,
    run_migration,
)


class FakeSource:
    project_id = "unit-test-project"

    def __init__(self, families):
        self.families = {family: dict(rows) for family, rows in families.items()}

    def scan_page(self, family, after, limit):
        rows = self.families.get(family, {})
        ids = sorted(key for key in rows if after is None or key > after)[:limit]
        return [rows[key] for key in ids]

    def get(self, family, document_id):
        return self.families.get(family, {}).get(document_id)


class FakeControl:
    def __init__(self):
        self.rows = {}
        self.checkpoints = {}

    def epoch_lock(self, _epoch):
        return nullcontext()

    def begin_epoch(self, **_kwargs):
        pass

    def start_family(self, epoch, family):
        key = (epoch, family)
        generation, cursor, state = self.checkpoints.get(key, (0, None, "pending"))
        if state == "running":
            return generation, cursor
        generation += 1
        self.checkpoints[key] = (generation, None, "running")
        return generation, None

    def checkpoint_page(self, *, epoch_id, family, generation, last_source_document_id, **_kwargs):
        self.checkpoints[(epoch_id, family)] = (generation, last_source_document_id, "running")

    def finish_family(self, epoch, family, generation):
        self.checkpoints[(epoch, family)] = (generation, None, "complete")

    def prior_record(self, epoch, family, source_id):
        return self.rows.get((epoch, family, source_id))

    def acknowledge(self, *, epoch_id, record, target_hash, generation, **_kwargs):
        self.rows[(epoch_id, record.family, record.source_document_id)] = (
            record.logical_id, record.target_store, record.source_version, record.source_hash,
            target_hash, "applied", None, generation, record.owner_id,
            record.scope.application_id, record.scope.workspace_id, {},
        )

    def reject(self, *, epoch_id, family, source_id, logical_id, source_version, source_hash,
               generation, code):
        self.rows[(epoch_id, family, source_id)] = (
            logical_id, "dynamodb" if family in DYNAMODB_FAMILIES else "postgres",
            source_version, source_hash, "0" * 64, "rejected", code, generation,
            None, None, None, {},
        )

    def dispose(self, **kwargs):
        raise AssertionError("test source has no expired counters")

    def missing(self, epoch, family, generation):
        return [
            (source_id, *row[:5], *row[8:12])
            for (row_epoch, row_family, source_id), row in self.rows.items()
            if row_epoch == epoch and row_family == family
            and row[5] in {"applied", "rejected"} and row[7] != generation
        ]

    def missing_page(self, epoch, family, generation, after, limit):
        rows = [
            row for row in self.missing(epoch, family, generation)
            if after is None or row[0] > after
        ]
        return rows[:limit]

    def generation_scanned_count(self, epoch, family, generation):
        return sum(
            1 for (row_epoch, row_family, _source_id), row in self.rows.items()
            if row_epoch == epoch and row_family == family and row[7] == generation
            and row[5] in {"applied", "rejected", "disposed"}
        )

    def generation_disposition_count(self, epoch, family, generation):
        return sum(
            1 for (row_epoch, row_family, _source_id), row in self.rows.items()
            if row_epoch == epoch and row_family == family and row[7] == generation
            and row[5] in {"applied", "rejected", "disposed"}
        )

    def applied_records_page(self, epoch, family, generation, after, limit):
        rows = []
        for (row_epoch, row_family, source_id), row in sorted(self.rows.items()):
            if row_epoch != epoch or row_family != family or row[7] != generation or row[5] != "applied":
                continue
            if after is not None and source_id <= after:
                continue
            rows.append((source_id, row[0], row[1], row[2], row[4], row[4], *row[8:12]))
        return rows[:limit]

    def mark_conflict(self, epoch, family, source_id, generation, code):
        key = (epoch, family, source_id)
        row = self.rows[key]
        self.rows[key] = (*row[:5], "rejected", code, generation, *row[8:])

    def mark_deleted(self, epoch, family, source_id):
        key = (epoch, family, source_id)
        row = self.rows[key]
        self.rows[key] = (*row[:5], "source-deleted", None, row[7], *row[8:])

    def counts(self, epoch):
        return {}

    def finalize(self, _epoch, *, final_delta, conflict_count=0):
        return bool(final_delta and not conflict_count and all(
            self.checkpoints.get((_epoch, family), (0, None, "pending"))[2] == "complete"
            for family in FIRESTORE_FAMILIES
        ))

    def source_digest(self, epoch, generations):
        hasher = hashlib.sha256()
        for family in FIRESTORE_FAMILIES:
            rows = sorted(
                (source_id, row)
                for (row_epoch, row_family, source_id), row in self.rows.items()
                if row_epoch == epoch and row_family == family and row[7] == generations[family]
            )
            for source_id, row in rows:
                hasher.update(f"{family}\0{source_id}\0{row[2]}\0{row[3]}\n".encode())
        return hasher.hexdigest()


class FakePostgresTarget:
    def __init__(self, control):
        self.control = control
        self.rows = {}

    def logical_hash(self, family, logical_id, owner_id, scope, payload=None, **_kwargs):
        return self.rows.get((family, logical_id, owner_id, scope.application_id, scope.workspace_id))

    def import_record(self, record, *, epoch_id, generation, expected_existing_hash=None):
        key = (record.family, record.logical_id, record.owner_id,
               record.scope.application_id, record.scope.workspace_id)
        current = self.rows.get(key)
        from personal_ai.persistence.firestore_migration import _check_target_version

        _check_target_version(current, expected_existing_hash, record.logical_hash)
        self.rows[key] = record.logical_hash
        self.control.acknowledge(
            epoch_id=epoch_id, record=record, target_hash=record.logical_hash, generation=generation
        )
        return record.logical_hash

    def delete_record(self, family, logical_id, owner_id, scope, **_kwargs):
        self.rows.pop((family, logical_id, owner_id, scope.application_id, scope.workspace_id), None)


class FakeDynamoTarget:
    def __init__(self):
        self.rows = {}

    @staticmethod
    def _key(record):
        return (record.family, record.logical_id, record.owner_id,
                record.scope.application_id, record.scope.workspace_id)

    def logical_hash(self, family, logical_id, owner_id, scope, payload=None, **_kwargs):
        return self.rows.get((family, logical_id, owner_id, scope.application_id, scope.workspace_id))

    def import_record(self, record, *, expected_existing_hash=None):
        from personal_ai.persistence.firestore_migration import _check_target_version

        _check_target_version(self.rows.get(self._key(record)), expected_existing_hash, record.logical_hash)
        self.rows[self._key(record)] = record.logical_hash
        return record.logical_hash

    def delete_record(self, family, logical_id, owner_id, scope, **_kwargs):
        self.rows.pop((family, logical_id, owner_id, scope.application_id, scope.workspace_id), None)


def test_family_inventory_is_complete_and_has_no_duplicates():
    assert len(FIRESTORE_FAMILIES) == 34
    assert len(set(FIRESTORE_FAMILIES)) == len(FIRESTORE_FAMILIES)
    assert len(MIGRATION_ORDER) == len(FIRESTORE_FAMILIES)
    assert set(MIGRATION_ORDER) == set(FIRESTORE_FAMILIES)
    assert len(DELETE_ORDER) == len(FIRESTORE_FAMILIES)
    assert set(DELETE_ORDER) == set(FIRESTORE_FAMILIES)


def test_shared_ownerless_child_inherits_parent_namespace():
    parent = SourceRecord("entity-1", datetime.now(UTC), {
        "owner_id": "*", "owner_scope": "shared", "application_id": "personal_ai",
        "workspace_id": None, "id": "entity-1",
    })
    alias = SourceRecord("alias-1", datetime.now(UTC), {"entity_id": "entity-1", "alias": "sample"})
    source = FakeSource({"canonical_entities": {parent.document_id: parent}})
    record = map_source_record(source, "entity_aliases", alias, known_owners=set())
    assert record.owner_id == "*"
    assert record.scope_kind == "shared"
    assert record.scope.application_id == "personal_ai"


def test_usage_budget_resolves_opaque_owner_and_stable_day_identity():
    owner_id = "owner-opaque-test"
    day = "2026-10-06"
    opaque_owner = hashlib.sha256(owner_id.encode()).hexdigest()
    document_id = hashlib.sha256(f"{opaque_owner}\0{day}".encode()).hexdigest()
    snapshot = SourceRecord(document_id, datetime.now(UTC), {
        "scope": f"owner:{opaque_owner}",
        "period_start": datetime(2026, 10, 6, tzinfo=UTC),
        "period_end": datetime(2026, 10, 7, tzinfo=UTC),
        "limit": {"provider_calls": 20, "input_tokens": 2000},
        "reserved": {"provider_calls": 3, "input_tokens": 300},
        "settled": {"provider_calls": 0, "input_tokens": 0},
        "state": "reserved",
        "policy_version": "usage-budget-v1",
        "expires_at": datetime(2027, 1, 5, tzinfo=UTC),
    })
    record = map_source_record(
        FakeSource({}), "usage_budgets", snapshot, known_owners={owner_id}
    )
    assert record.owner_id == owner_id
    assert record.logical_id == "usage:2026-10-06"
    assert record.scope.application_id == "personal_ai"
    assert record.payload["reserved"]["provider_calls"] == 3


def test_backfill_rerun_is_idempotent_and_final_delta_removes_source_deletion():
    conversation_id, message_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    conversation = SourceRecord(str(conversation_id), now, {
        "id": str(conversation_id), "owner_id": "owner-1", "title": "One",
        "created_at": now, "updated_at": now,
    })
    message = SourceRecord(str(message_id), now, {
        "id": str(message_id), "conversation_id": str(conversation_id), "owner_id": "owner-1",
        "role": "user", "content": "hello", "status": "completed", "created_at": now,
    })
    from personal_ai.memory.contracts import Memory, normalize

    memory_model = Memory(
        id=uuid4(), owner_id="owner-1", memory_type="preference", content="likes tea",
        confidence=0.9, source_message_ids=(uuid4(),), rationale_code="user_preference",
        normalized_content=normalize("likes tea"), source_conversation_id=conversation_id,
        source_turn_id=message_id, source_fingerprint="a" * 64, observed_at=now,
        effective_at=now, created_at=now, embedding=(0.1, 0.2),
        embedding_model="test-vector-v1", embedding_dimensions=2,
    )
    memory = SourceRecord(str(memory_model.id), now, memory_model.model_dump(mode="json"))
    source = FakeSource({
        "conversations": {conversation.document_id: conversation},
        "messages": {message.document_id: message},
        "memories": {memory.document_id: memory},
    })
    control = FakeControl()
    postgres = FakePostgresTarget(control)
    dynamodb = FakeDynamoTarget()

    first = run_migration(
        source=source, control=control, postgres_target=postgres, dynamodb_target=dynamodb,
        epoch_id="epoch-test", batch_size=1,
    )
    second = run_migration(
        source=source, control=control, postgres_target=postgres, dynamodb_target=dynamodb,
        epoch_id="epoch-test", batch_size=1,
    )
    assert first.rejected == second.rejected == ()
    assert second.counts["messages"]["unchanged"] == 1
    assert len(dynamodb.rows) == 2
    assert second.reconciliation["messages"]["reconciled_count"] == 1
    assert second.reconciliation["messages"]["mapped_hash_digest"] == (
        second.reconciliation["messages"]["target_hash_digest"]
    )

    source.families["messages"].clear()
    source.families["memories"].clear()
    final = run_migration(
        source=source, control=control, postgres_target=postgres, dynamodb_target=dynamodb,
        epoch_id="epoch-test", batch_size=1, final_delta=True, writers_frozen=True,
    )
    assert final.final_delta_ready
    assert final.counts["messages"]["source_deleted"] == 1
    assert final.counts["memories"]["source_deleted"] == 1
    assert len(dynamodb.rows) == 1
    assert next(iter(dynamodb.rows))[0] == "conversations"
    assert postgres.rows == {}


def test_checkpoint_loss_after_target_commit_resumes_without_duplicate_records():
    conversation_ids = sorted((str(uuid4()), str(uuid4())))
    now = datetime.now(UTC)
    conversations = {
        identifier: SourceRecord(identifier, now, {
            "id": identifier, "owner_id": "owner-resume", "title": "resume",
            "created_at": now, "updated_at": now,
        })
        for identifier in conversation_ids
    }
    source = FakeSource({"conversations": conversations})

    class LostCheckpointControl(FakeControl):
        failed = False

        def checkpoint_page(self, **kwargs):
            if not self.failed:
                self.failed = True
                raise OSError("simulated checkpoint interruption")
            super().checkpoint_page(**kwargs)

    control = LostCheckpointControl()
    postgres = FakePostgresTarget(control)
    dynamodb = FakeDynamoTarget()
    try:
        run_migration(
            source=source, control=control, postgres_target=postgres, dynamodb_target=dynamodb,
            epoch_id="epoch-resume", batch_size=1,
        )
    except OSError as error:
        assert str(error) == "simulated checkpoint interruption"
    else:
        raise AssertionError("the injected checkpoint interruption must escape the first run")
    resumed = run_migration(
        source=source, control=control, postgres_target=postgres, dynamodb_target=dynamodb,
        epoch_id="epoch-resume", batch_size=1,
    )
    assert resumed.rejected == resumed.conflicts == ()
    assert len(dynamodb.rows) == 2
    assert resumed.reconciliation["conversations"]["source_count"] == 2
    assert resumed.reconciliation["conversations"]["reconciled_count"] == 2


def test_source_update_replaces_only_the_previously_migration_owned_target():
    conversation_id = uuid4()
    now = datetime.now(UTC)
    conversation = SourceRecord(str(conversation_id), now, {
        "id": str(conversation_id), "owner_id": "owner-update", "title": "Before",
        "created_at": now, "updated_at": now,
    })
    source = FakeSource({"conversations": {conversation.document_id: conversation}})
    control = FakeControl()
    postgres = FakePostgresTarget(control)
    dynamodb = FakeDynamoTarget()
    first = run_migration(
        source=source, control=control, postgres_target=postgres, dynamodb_target=dynamodb,
        epoch_id="epoch-update", batch_size=1,
    )
    updated_at = now + timedelta(microseconds=1)
    source.families["conversations"][conversation.document_id] = SourceRecord(
        conversation.document_id, updated_at,
        {**conversation.data, "title": "After", "updated_at": updated_at},
    )
    second = run_migration(
        source=source, control=control, postgres_target=postgres, dynamodb_target=dynamodb,
        epoch_id="epoch-update", batch_size=1,
    )
    assert first.source_digest != second.source_digest
    assert second.rejected == second.conflicts == ()
    assert len(dynamodb.rows) == 1
    assert second.reconciliation["conversations"]["reconciled_count"] == 1


def test_final_delta_refuses_to_delete_a_target_that_diverged_after_backfill():
    conversation_id = uuid4()
    now = datetime.now(UTC)
    conversation = SourceRecord(str(conversation_id), now, {
        "id": str(conversation_id), "owner_id": "owner-delete", "title": "One",
        "created_at": now, "updated_at": now,
    })
    source = FakeSource({"conversations": {conversation.document_id: conversation}})
    control = FakeControl()
    postgres = FakePostgresTarget(control)
    dynamodb = FakeDynamoTarget()
    run_migration(
        source=source, control=control, postgres_target=postgres, dynamodb_target=dynamodb,
        epoch_id="epoch-delete", batch_size=1,
    )
    key = next(iter(dynamodb.rows))
    dynamodb.rows[key] = "f" * 64
    source.families["conversations"].clear()
    final = run_migration(
        source=source, control=control, postgres_target=postgres, dynamodb_target=dynamodb,
        epoch_id="epoch-delete", batch_size=1, final_delta=True, writers_frozen=True,
    )
    assert not final.final_delta_ready
    assert final.conflicts[0]["code"] == "target_conflict"
    assert dynamodb.rows[key] == "f" * 64


def test_global_provider_throttle_hash_covers_complete_source_envelope():
    now = datetime.now(UTC)
    payload = {
        "provider_id": "shared-provider", "next_request_at": now,
        "revision": 7, "updated_at": now, "policy_version": "provider-v2",
    }
    record = map_source_record(
        FakeSource({}), "domain_provider_rate_limits",
        SourceRecord("shared-provider", now, payload), known_owners=set(),
    )
    from personal_ai.persistence.firestore_migration import digest

    assert record.scope_kind == "global"
    assert record.logical_hash == digest(payload)


def test_rate_counter_rejects_unmapped_source_fields():
    owner_id = "rate-owner"
    now = datetime.now(UTC)
    epoch = int(now.timestamp() // 60)
    document_id = hashlib.sha256(f"{owner_id}\0{epoch}".encode()).hexdigest()
    payload = {
        "request_count": 1,
        "window_start": datetime.fromtimestamp(epoch * 60, UTC),
        "expires_at": datetime.fromtimestamp((epoch + 2) * 60, UTC),
        "policy_version": "request-rate-v1",
        "new_unmapped_field": "must not disappear",
    }
    with pytest.raises(MigrationRejected, match="counter_payload_unmapped_fields"):
        map_source_record(
            FakeSource({}), "rate_limit_windows",
            SourceRecord(document_id, now, payload), known_owners={owner_id}, now=now,
        )


def test_lifecycle_job_rejects_candidate_with_missing_parent_memory():
    now = datetime.now(UTC)
    payload = {
        "id": str(uuid4()), "owner_id": "owner-lifecycle",
        "candidate_memory_ids": ["missing-memory"], "created_at": now,
    }
    with pytest.raises(MigrationRejected, match="referenced_parent_missing"):
        map_source_record(
            FakeSource({}), "memory_lifecycle_jobs",
            SourceRecord(payload["id"], now, payload), known_owners=set(),
        )


def test_small_postgres_envelope_rejects_rows_over_target_column_limit():
    now = datetime.now(UTC)
    payload = {
        "domain_id": "example", "field_schema_version": "1",
        "feature_policy_version": "1", "source_policy_version": "1",
        "large_metadata": "x" * 33_000,
    }
    with pytest.raises(MigrationRejected, match="postgres_envelope_bound_exceeded"):
        map_source_record(
            FakeSource({}), "domain_registrations",
            SourceRecord("module-doc", now, payload), known_owners=set(),
        )


def test_memory_embedding_is_bounded_in_its_vector_column_not_json_envelope():
    from personal_ai.memory.contracts import Memory, normalize

    owner_id = "large-vector-owner"
    now = datetime.now(UTC)
    memory = Memory(
        id=uuid4(), owner_id=owner_id, memory_type="preference", content="likes tea",
        confidence=0.9, source_message_ids=(uuid4(),), rationale_code="user_preference",
        normalized_content=normalize("likes tea"), source_conversation_id=uuid4(),
        source_turn_id=uuid4(), source_fingerprint="a" * 64, observed_at=now,
        effective_at=now, created_at=now, embedding=(0.123456789012345,) * 2048,
        embedding_model="memory-vector-v1", embedding_dimensions=2048,
        application_id="personal_ai", workspace_id=None, scope_version=2,
    )
    payload = memory.model_dump(mode="json")
    record = map_source_record(
        FakeSource({}), "memories", SourceRecord(str(memory.id), now, payload), known_owners=set(),
    )
    assert record.estimated_bytes > 32_768
    assert record.logical_hash == digest(payload)


def test_final_delta_requires_explicit_writer_freeze():
    source = FakeSource({})
    try:
        run_migration(
            source=source, control=FakeControl(), postgres_target=FakePostgresTarget(FakeControl()),
            dynamodb_target=FakeDynamoTarget(), epoch_id="epoch-test", final_delta=True,
        )
    except ValueError as error:
        assert str(error) == "final_delta_requires_writer_freeze_assertion"
    else:
        raise AssertionError("final delta without writer freeze must be rejected")
