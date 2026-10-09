"""Canonical artifact metadata, global conservative budgets and owner fences."""

from __future__ import annotations

from datetime import UTC, datetime

from personal_ai.artifacts.contracts import (
    ArtifactBudgetExceeded,
    ArtifactConflict,
    ArtifactRef,
    ArtifactUnavailable,
    same_publication_identity,
    validate_transition,
)


def assert_owner_unfenced(connection, owner_id):
    # Serializes begin/reservation/confirmation; external IO still rechecks before return.
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"artifact-owner:{owner_id}",)
    )
    if connection.execute(
        "SELECT 1 FROM artifact_owner_fences WHERE owner_id=%s", (owner_id,)
    ).fetchone():
        raise ArtifactUnavailable("artifact_owner_fenced")


class PostgresArtifactMetadataRepository:
    def __init__(
        self,
        database,
        *,
        max_operations=1000,
        max_daily_bytes=16 * 1024 * 1024,
        max_objects=10000,
        max_live_bytes=64 * 1024 * 1024,
    ):
        self.database = database
        self.max_operations = max_operations
        self.max_daily_bytes = max_daily_bytes
        self.max_objects = max_objects
        self.max_live_bytes = max_live_bytes

    def active(self, owner_id):
        with self.database.connection() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM artifact_owner_fences WHERE owner_id=%s", (owner_id,)
                ).fetchone()
                is None
            )

    def fence(self, owner_id):
        with self.database.transaction() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"artifact-owner:{owner_id}",),
            )
            connection.execute(
                "INSERT INTO artifact_owner_fences(owner_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (owner_id,),
            )

    def begin(self, ref):
        with self.database.transaction() as connection:
            assert_owner_unfenced(connection, ref.owner_id)
            connection.execute("SELECT pg_advisory_xact_lock(%s,%s)", (0x504149, 20))
            _assert_store_compatible_in_connection(connection, ref.store_id)
            row = connection.execute(
                "SELECT payload FROM artifact_metadata WHERE artifact_id=%s FOR UPDATE",
                (ref.artifact_id,),
            ).fetchone()
            if row:
                existing = ArtifactRef.model_validate(row[0])
                if not same_publication_identity(existing, ref):
                    raise ArtifactConflict("artifact_identity_conflict")
                return existing
            if ref.status != "pending" or ref.generation is not None or ref.revision != 1:
                raise ArtifactConflict("artifact_initial_state")
            count, live_bytes = connection.execute(
                "SELECT count(*),COALESCE(sum(compressed_bytes),0) FROM artifact_metadata "
                "WHERE status <> 'deleted'"
            ).fetchone()
            if count >= self.max_objects or live_bytes + ref.compressed_bytes > self.max_live_bytes:
                raise ArtifactBudgetExceeded("artifact_stock_budget")
            connection.execute(
                "INSERT INTO artifact_metadata(artifact_id,owner_id,application_id,workspace_id,"
                "kind,identity,routing_decision_id,invocation_id,evaluation_run_id,cascade_run_id,"
                "status,revision,compressed_bytes,created_at,expires_at,payload) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (
                    ref.artifact_id,
                    ref.owner_id,
                    ref.scope.application_id,
                    ref.scope.workspace_id,
                    ref.kind,
                    ref.identity,
                    ref.routing_decision_id,
                    ref.invocation_id,
                    ref.evaluation_run_id,
                    ref.cascade_run_id,
                    ref.status,
                    ref.revision,
                    ref.compressed_bytes,
                    ref.created_at,
                    ref.expires_at,
                    ref.model_dump_json(),
                ),
            )
            return ref

    def begin_reserved(
        self, ref, *, operations, byte_count, objects=0, read_bytes=0
    ):
        """Admit the flow budget and create pending metadata in one transaction."""
        with self.database.transaction() as connection:
            assert_owner_unfenced(connection, ref.owner_id)
            connection.execute("SELECT pg_advisory_xact_lock(%s,%s)", (0x504149, 20))
            _assert_store_compatible_in_connection(connection, ref.store_id)
            row = connection.execute(
                "SELECT payload FROM artifact_metadata WHERE artifact_id=%s FOR UPDATE",
                (ref.artifact_id,),
            ).fetchone()
            if row:
                existing = ArtifactRef.model_validate(row[0])
                if not same_publication_identity(existing, ref):
                    raise ArtifactConflict("artifact_identity_conflict")
                if existing.status == "pending":
                    _reserve_in_connection(
                        connection,
                        operations=operations,
                        byte_count=byte_count,
                        objects=objects,
                        read_bytes=read_bytes,
                        max_operations=self.max_operations,
                        max_daily_bytes=self.max_daily_bytes,
                    )
                return existing
            if ref.status != "pending" or ref.generation is not None or ref.revision != 1:
                raise ArtifactConflict("artifact_initial_state")
            count, live_bytes = connection.execute(
                "SELECT count(*),COALESCE(sum(compressed_bytes),0) FROM artifact_metadata "
                "WHERE status <> 'deleted'"
            ).fetchone()
            if count >= self.max_objects or live_bytes + ref.compressed_bytes > self.max_live_bytes:
                raise ArtifactBudgetExceeded("artifact_stock_budget")
            _reserve_in_connection(
                connection,
                operations=operations,
                byte_count=byte_count,
                objects=objects,
                read_bytes=read_bytes,
                max_operations=self.max_operations,
                max_daily_bytes=self.max_daily_bytes,
            )
            connection.execute(
                "INSERT INTO artifact_metadata(artifact_id,owner_id,application_id,workspace_id,"
                "kind,identity,routing_decision_id,invocation_id,evaluation_run_id,cascade_run_id,"
                "status,revision,compressed_bytes,created_at,expires_at,payload) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                _metadata_values(ref),
            )
            return ref

    def get(self, artifact_id, *, owner_id, scope):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM artifact_metadata WHERE artifact_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
                (artifact_id, owner_id, scope.application_id, scope.workspace_id),
            ).fetchone()
        if row is None:
            raise ArtifactUnavailable("artifact_not_found")
        return ArtifactRef.model_validate(row[0])

    def update(self, ref, *, expected_revision):
        updated = ArtifactRef.model_validate(
            {**ref.model_dump(), "revision": expected_revision + 1}
        )
        with self.database.transaction() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"artifact-owner:{ref.owner_id}",),
            )
            if ref.status == "ready":
                assert_owner_unfenced(connection, ref.owner_id)
            previous = connection.execute(
                "SELECT payload FROM artifact_metadata WHERE artifact_id=%s FOR UPDATE",
                (ref.artifact_id,),
            ).fetchone()
            if previous is None:
                raise ArtifactConflict("artifact_revision_conflict")
            validate_transition(ArtifactRef.model_validate(previous[0]), ref)
            row = connection.execute(
                "UPDATE artifact_metadata SET status=%s,revision=%s,payload=%s::jsonb,last_checked_at=now() "
                "WHERE artifact_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND revision=%s RETURNING artifact_id",
                (
                    updated.status,
                    updated.revision,
                    updated.model_dump_json(),
                    updated.artifact_id,
                    updated.owner_id,
                    updated.scope.application_id,
                    updated.scope.workspace_id,
                    expected_revision,
                ),
            ).fetchone()
            if row is None:
                raise ArtifactConflict("artifact_revision_conflict")
        return updated

    def claim_owner_deletion(self, ref):
        """Atomically order fenced cleanup against deletion-request cancellation."""
        with self.database.transaction() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"artifact-owner:{ref.owner_id}",),
            )
            if connection.execute(
                "SELECT 1 FROM artifact_owner_fences WHERE owner_id=%s", (ref.owner_id,)
            ).fetchone() is None:
                raise ArtifactUnavailable("artifact_owner_deletion_fence_missing")
            previous = connection.execute(
                "SELECT payload FROM artifact_metadata WHERE artifact_id=%s FOR UPDATE",
                (ref.artifact_id,),
            ).fetchone()
            if previous is None:
                raise ArtifactConflict("artifact_revision_conflict")
            current = ArtifactRef.model_validate(previous[0])
            if current.revision != ref.revision:
                raise ArtifactConflict("artifact_revision_conflict")
            if current.status == "deleting":
                return current
            updated = ArtifactRef.model_validate(
                {**current.model_dump(), "status": "deleting", "revision": current.revision + 1}
            )
            validate_transition(current, updated)
            row = connection.execute(
                "UPDATE artifact_metadata SET status='deleting',revision=%s,payload=%s::jsonb,"
                "last_checked_at=now() WHERE artifact_id=%s AND revision=%s RETURNING artifact_id",
                (updated.revision, updated.model_dump_json(), updated.artifact_id, current.revision),
            ).fetchone()
            if row is None:
                raise ArtifactConflict("artifact_revision_conflict")
            return updated

    def batch(self, *, limit, owner_id=None):
        if not 1 <= limit <= 100:
            raise ValueError("artifact_batch_limit")
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT a.payload FROM artifact_metadata a WHERE (a.status <> 'deleted' "
                "OR a.created_at >= now() - interval '10 minutes') "
                "AND (%s::text IS NULL OR a.owner_id=%s) "
                "ORDER BY CASE WHEN a.expires_at<=now() OR a.status='deleting' OR EXISTS "
                "(SELECT 1 FROM artifact_owner_fences f WHERE f.owner_id=a.owner_id) "
                "THEN 0 ELSE 1 END,a.last_checked_at,a.expires_at,a.artifact_id "
                "LIMIT %s FOR UPDATE SKIP LOCKED",
                (owner_id, owner_id, limit),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE artifact_metadata SET last_checked_at=now() WHERE artifact_id=%s",
                    (row[0]["artifact_id"],),
                )
        return tuple(ArtifactRef.model_validate(row[0]) for row in rows)

    def reserve(self, *, operations, byte_count, objects=0, read_bytes=0):
        if min(operations, byte_count, objects, read_bytes) < 0:
            raise ValueError("artifact_reservation_invalid")
        with self.database.transaction() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s,%s)", (0x504149, 20))
            _reserve_in_connection(
                connection,
                operations=operations,
                byte_count=byte_count,
                objects=objects,
                read_bytes=read_bytes,
                max_operations=self.max_operations,
                max_daily_bytes=self.max_daily_bytes,
            )

    def assert_store_compatible(self, store_id):
        with self.database.connection() as connection:
            _assert_store_compatible_in_connection(connection, store_id)

    def observations(self):
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT status,count(*),COALESCE(sum(compressed_bytes),0),"
                "COALESCE(sum(octet_length(payload::text)),0) FROM artifact_metadata GROUP BY status"
            ).fetchall()
            budget = connection.execute(
                "SELECT operations,write_bytes,read_bytes FROM artifact_storage_budgets WHERE budget_day=%s",
                (datetime.now(UTC).date(),),
            ).fetchone() or (0, 0, 0)
        return {
            "postgres": {
                "references": sum(r[1] for r in rows),
                "metadata_bytes": sum(r[3] for r in rows),
            },
            "dynamodb": {"artifact_body_bytes": 0, "metadata_mirror": False},
            "gcs": {
                "states": {r[0]: r[1] for r in rows},
                "live_body_bytes": sum(r[2] for r in rows if r[0] != "deleted"),
                "reserved_operations": budget[0],
                "reserved_write_bytes": budget[1],
                "reserved_read_bytes": budget[2],
            },
        }


def _reserve_in_connection(
    connection,
    *,
    operations,
    byte_count,
    objects,
    read_bytes,
    max_operations,
    max_daily_bytes,
):
    if min(operations, byte_count, objects, read_bytes) < 0:
        raise ValueError("artifact_reservation_invalid")
    today = datetime.now(UTC).date()
    month = today.replace(day=1)
    monthly_ops, monthly_io = connection.execute(
        "SELECT COALESCE(sum(operations),0),COALESCE(sum(write_bytes+read_bytes),0) "
        "FROM artifact_storage_budgets WHERE budget_day >= %s",
        (month,),
    ).fetchone()
    if monthly_ops + operations > 4000 or monthly_io + byte_count + read_bytes > 67108864:
        raise ArtifactBudgetExceeded("artifact_monthly_budget")
    connection.execute(
        "INSERT INTO artifact_storage_budgets VALUES (%s,0,0,0,0) ON CONFLICT DO NOTHING",
        (today,),
    )
    row = connection.execute(
        "UPDATE artifact_storage_budgets SET operations=operations+%s,"
        "write_bytes=write_bytes+%s,read_bytes=read_bytes+%s,objects=objects+%s WHERE budget_day=%s "
        "AND operations+%s<=%s AND write_bytes+read_bytes+%s<=%s RETURNING budget_day",
        (
            operations,
            byte_count,
            read_bytes,
            objects,
            today,
            operations,
            max_operations,
            byte_count + read_bytes,
            max_daily_bytes,
        ),
    ).fetchone()
    if row is None:
        raise ArtifactBudgetExceeded("artifact_daily_budget")
    connection.execute(
        "DELETE FROM artifact_storage_budgets WHERE budget_day < %s - 90", (today,)
    )


def _metadata_values(ref):
    return (
        ref.artifact_id,
        ref.owner_id,
        ref.scope.application_id,
        ref.scope.workspace_id,
        ref.kind,
        ref.identity,
        ref.routing_decision_id,
        ref.invocation_id,
        ref.evaluation_run_id,
        ref.cascade_run_id,
        ref.status,
        ref.revision,
        ref.compressed_bytes,
        ref.created_at,
        ref.expires_at,
        ref.model_dump_json(),
    )


def _assert_store_compatible_in_connection(connection, store_id):
    mismatch = connection.execute(
        "SELECT 1 FROM artifact_metadata WHERE payload->>'store_id'<>%s "
        "AND (status<>'deleted' OR created_at >= now()-interval '10 minutes') LIMIT 1",
        (store_id,),
    ).fetchone()
    if mismatch:
        raise ArtifactUnavailable("artifact_store_rotation_has_live_references")
