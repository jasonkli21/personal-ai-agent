"""Deterministic fake adapters with the same immutable/CAS/budget boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import RLock

from personal_ai.artifacts.contracts import (
    MAX_COMPRESSED_BYTES,
    ArtifactBudgetExceeded,
    ArtifactConflict,
    ArtifactRef,
    ArtifactUnavailable,
    validate_transition,
)


class InMemoryArtifactStore:
    store_id = "memory:local"

    def __init__(self):
        self.objects = {}
        self.next_generation = 1
        self.lock = RLock()

    def put(self, key, body):
        from personal_ai.artifacts.gcs import _KEY

        if not _KEY.fullmatch(key) or not 0 < len(body) <= MAX_COMPRESSED_BYTES:
            raise ArtifactUnavailable("artifact_object_invalid")
        with self.lock:
            if key in self.objects:
                generation, existing = self.objects[key]
                if existing != body:
                    raise ArtifactConflict("artifact_object_conflict")
                return generation
            generation = str(self.next_generation)
            self.next_generation += 1
            self.objects[key] = (generation, body)
            return generation

    def generation(self, key):
        return self.objects.get(key, (None,))[0]

    def read(self, key, generation, *, max_bytes):
        if key not in self.objects or self.objects[key][0] != generation:
            raise ArtifactUnavailable("artifact_object_missing")
        body = self.objects[key][1]
        if len(body) > max_bytes:
            raise ArtifactUnavailable("artifact_object_oversized")
        return body

    def delete(self, key, generation):
        with self.lock:
            if key not in self.objects:
                return
            if self.objects[key][0] != generation:
                raise ArtifactConflict("artifact_generation_conflict")
            del self.objects[key]


class InMemoryArtifactMetadataRepository:
    def __init__(
        self,
        *,
        max_operations=1000,
        max_daily_bytes=16 * 1024 * 1024,
        max_objects=10000,
        max_live_bytes=64 * 1024 * 1024,
        clock=None,
    ):
        self.records = {}
        self.fences = set()
        self.lock = RLock()
        self.max_operations = max_operations
        self.max_daily_bytes = max_daily_bytes
        self.max_objects = max_objects
        self.max_live_bytes = max_live_bytes
        self.clock = clock or (lambda: datetime.now(UTC))
        self.day = None
        self.checked = {}
        self.operations = self.bytes_reserved = self.objects_reserved = self.read_bytes = 0
        self.months = {}

    def active(self, owner_id):
        return owner_id not in self.fences

    def fence(self, owner_id):
        with self.lock:
            self.fences.add(owner_id)

    def begin(self, ref):
        with self.lock:
            if not self.active(ref.owner_id):
                raise ArtifactUnavailable("artifact_owner_fenced")
            existing = self.records.get(ref.artifact_id)
            if existing is not None:
                expected = ref.model_dump(exclude={"revision", "status", "generation"})
                actual = existing.model_dump(exclude={"revision", "status", "generation"})
                if expected != actual:
                    raise ArtifactConflict("artifact_identity_conflict")
                return existing
            if ref.status != "pending" or ref.generation is not None or ref.revision != 1:
                raise ArtifactConflict("artifact_initial_state")
            live = [r for r in self.records.values() if r.status != "deleted"]
            if (
                len(live) >= self.max_objects
                or sum(r.compressed_bytes for r in live) + ref.compressed_bytes
                > self.max_live_bytes
            ):
                raise ArtifactBudgetExceeded("artifact_stock_budget")
            self.records[ref.artifact_id] = ref
            return ref

    def get(self, artifact_id, *, owner_id, scope):
        ref = self.records.get(artifact_id)
        if ref is None or ref.owner_id != owner_id or ref.scope != scope:
            raise ArtifactUnavailable("artifact_not_found")
        return ref

    def update(self, ref, *, expected_revision):
        with self.lock:
            previous = self.records.get(ref.artifact_id)
            if previous is None or previous.revision != expected_revision:
                raise ArtifactConflict("artifact_revision_conflict")
            validate_transition(previous, ref)
            if ref.status == "ready" and not self.active(ref.owner_id):
                raise ArtifactUnavailable("artifact_owner_fenced")
            updated = ArtifactRef.model_validate(
                {**ref.model_dump(), "revision": expected_revision + 1}
            )
            self.records[ref.artifact_id] = updated
            return updated

    def batch(self, *, limit, owner_id=None):
        if not 1 <= limit <= 100:
            raise ValueError("artifact_batch_limit")
        refs = tuple(
            sorted(
                (
                    r
                    for r in self.records.values()
                    if (
                        r.status != "deleted"
                        or self.clock() - r.created_at <= timedelta(minutes=10)
                    )
                    and (owner_id is None or r.owner_id == owner_id)
                ),
                key=lambda r: (
                    not (
                        r.expires_at <= self.clock()
                        or r.status == "deleting"
                        or not self.active(r.owner_id)
                    ),
                    self.checked.get(r.artifact_id, datetime.min.replace(tzinfo=UTC)),
                    r.expires_at,
                    str(r.artifact_id),
                ),
            )[:limit]
        )
        for ref in refs:
            self.checked[ref.artifact_id] = self.clock()
        return refs

    def reserve(self, *, operations, byte_count, objects=0, read_bytes=0):
        with self.lock:
            if min(operations, byte_count, objects, read_bytes) < 0:
                raise ValueError("artifact_reservation_invalid")
            today = self.clock().date()
            if today != self.day:
                self.day = today
                self.operations = self.bytes_reserved = self.objects_reserved = self.read_bytes = 0
            month = (today.year, today.month)
            monthly_ops, monthly_io = self.months.get(month, (0, 0))
            if monthly_ops + operations > 4000 or monthly_io + byte_count + read_bytes > 67108864:
                raise ArtifactBudgetExceeded("artifact_monthly_budget")
            if (
                self.operations + operations > self.max_operations
                or self.bytes_reserved + self.read_bytes + byte_count + read_bytes
                > self.max_daily_bytes
            ):
                raise ArtifactBudgetExceeded("artifact_daily_budget")
            self.months[month] = (monthly_ops + operations, monthly_io + byte_count + read_bytes)
            self.operations += operations
            self.read_bytes += read_bytes
            self.bytes_reserved += byte_count
            self.objects_reserved += objects

    def observations(self):
        refs = tuple(self.records.values())
        return {
            "postgres": {
                "references": len(refs),
                "metadata_bytes": sum(len(r.model_dump_json().encode()) for r in refs),
            },
            "dynamodb": {"artifact_body_bytes": 0, "metadata_mirror": False},
            "gcs": {
                "reserved_operations": self.operations,
                "reserved_write_bytes": self.bytes_reserved,
                "reserved_read_bytes": self.read_bytes,
                "live_body_bytes": sum(r.compressed_bytes for r in refs if r.status != "deleted"),
                "states": {
                    s: sum(r.status == s for r in refs)
                    for s in ("pending", "ready", "missing", "deleting", "deleted")
                },
            },
        }
