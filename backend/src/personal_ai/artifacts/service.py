"""Bounded compression, authorization and recoverable cross-store operations."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.artifacts.contracts import (
    MAX_COMPRESSED_BYTES,
    MAX_RAW_BYTES,
    ArtifactConflict,
    ArtifactRef,
    ArtifactUnavailable,
)
from personal_ai.artifacts.observations import validate_observation


def encode(value, *, jsonl=False):
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    raw = bytearray()

    def row(item):
        for chunk in encoder.iterencode(item):
            raw.extend(chunk.encode())
            if len(raw) > MAX_RAW_BYTES:
                raise ArtifactUnavailable("artifact_uncompressed_size")

    if jsonl:
        if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 10000:
            raise ArtifactUnavailable("artifact_jsonl_rows_invalid")
        for item in value:
            row(item)
            raw.extend(b"\n")
    else:
        row(value)
    if not 0 < len(raw) <= MAX_RAW_BYTES:
        raise ArtifactUnavailable("artifact_uncompressed_size")
    compressed = gzip.compress(raw, mtime=0)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise ArtifactUnavailable("artifact_compressed_size")
    return bytes(raw), compressed


def decode(ref, body):
    if (
        len(body) != ref.compressed_bytes
        or hashlib.sha256(body).hexdigest() != ref.compressed_sha256
    ):
        raise ArtifactUnavailable("artifact_compressed_integrity")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            raw = stream.read(ref.uncompressed_bytes + 1)
        if len(raw) != ref.uncompressed_bytes or hashlib.sha256(raw).hexdigest() != ref.sha256:
            raise ArtifactUnavailable("artifact_uncompressed_integrity")
        if ref.content_type == "application/x-ndjson":
            return [json.loads(row) for row in raw.splitlines()]
        return json.loads(raw)
    except (OSError, EOFError, ValueError) as error:
        raise ArtifactUnavailable("artifact_corrupt") from error


class ArtifactService:
    """Internal authorized-service API; no arbitrary client keys or public URLs.

    Authorize is a trusted, current owner/app/workspace and grant-dependency check.
    Dependencies fail closed without a supplied resolver. Optional callers receive
    None on storage failure; required export callers always receive an exception.
    """

    def __init__(self, metadata, store, *, authorize=None, clock=None, writes_enabled=True):
        self.metadata, self.store = metadata, store
        self.authorize = authorize or (lambda ref: not ref.grant_dependencies)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.writes_enabled = writes_enabled

    def _authorized(self, ref):
        if ref.store_id != self.store.store_id:
            raise ArtifactUnavailable("artifact_store_identity_mismatch")
        if not self.metadata.active(ref.owner_id) or not self.authorize(ref):
            raise ArtifactUnavailable("artifact_authorization_denied")
        if self.clock() >= ref.expires_at:
            raise ArtifactUnavailable("artifact_expired")

    def write(
        self,
        value,
        *,
        owner_id,
        scope,
        kind,
        identity,
        schema_version,
        sensitivity="personal",
        grant_dependencies=(),
        retention_days=7,
        source_rights_until=None,
        source_rights_verified=False,
        jsonl=False,
        summary=None,
        required=False,
        **links,
    ):
        try:
            return self._write(
                value,
                owner_id=owner_id,
                scope=scope,
                kind=kind,
                identity=identity,
                schema_version=schema_version,
                sensitivity=sensitivity,
                grant_dependencies=grant_dependencies,
                retention_days=retention_days,
                source_rights_until=source_rights_until,
                source_rights_verified=source_rights_verified,
                jsonl=jsonl,
                summary=summary,
                **links,
            )
        except Exception as error:
            if required:
                raise ArtifactUnavailable("required_artifact_not_ready") from error
            return None

    def _write(
        self,
        value,
        *,
        owner_id,
        scope,
        kind,
        identity,
        schema_version,
        sensitivity,
        grant_dependencies,
        retention_days,
        source_rights_until,
        source_rights_verified,
        jsonl,
        summary,
        **links,
    ):
        if not self.writes_enabled:
            raise ArtifactUnavailable("artifact_writes_disabled")
        if kind != "export":
            if sensitivity in {"sensitive", "restricted"} or scope.application_id in {
                "health",
                "finance",
            }:
                raise ArtifactUnavailable("artifact_sensitive_verbose_disabled")
            value = validate_observation(kind, value, jsonl=jsonl)
        if kind == "routing_trace":
            if not isinstance(value, dict) or len(value.get("candidates", [])) > 32:
                raise ArtifactUnavailable("routing_artifact_candidate_limit")
            if len(json.dumps(value).encode()) > 65536:
                raise ArtifactUnavailable("routing_artifact_size")
        if source_rights_until is not None and not source_rights_verified:
            raise ArtifactUnavailable("artifact_source_rights_required")
        now = self.clock()
        expires = now + timedelta(days=retention_days)
        if source_rights_until is not None:
            expires = min(expires, source_rights_until)
        raw, body = encode(value, jsonl=jsonl)
        namespace = hashlib.sha256(
            json.dumps(
                [owner_id, scope.application_id, scope.workspace_id], separators=(",", ":")
            ).encode()
        ).hexdigest()
        artifact_id = uuid5(NAMESPACE_URL, f"artifact:v1:{namespace}:{kind}:{identity}")
        extension = "jsonl" if jsonl else "json"
        ref = ArtifactRef(
            artifact_id=artifact_id,
            store_id=self.store.store_id,
            owner_id=owner_id,
            scope=scope,
            kind=kind,
            identity=identity,
            key=f"artifacts/v1/{namespace}/{artifact_id}.{extension}.gz",
            sha256=hashlib.sha256(raw).hexdigest(),
            compressed_sha256=hashlib.sha256(body).hexdigest(),
            compressed_bytes=len(body),
            uncompressed_bytes=len(raw),
            content_type="application/x-ndjson" if jsonl else "application/json",
            schema_version=schema_version,
            sensitivity=sensitivity,
            grant_dependencies=grant_dependencies,
            created_at=now,
            expires_at=expires,
            source_rights_until=source_rights_until,
            summary=summary or {},
            **links,
        )
        try:
            previous = self.metadata.get(artifact_id, owner_id=owner_id, scope=scope)
        except ArtifactUnavailable:
            previous = None
        if previous is not None:
            stable = (
                "sha256",
                "kind",
                "schema_version",
                "sensitivity",
                "grant_dependencies",
                "scope",
                "source_rights_until",
                "routing_decision_id",
                "invocation_id",
                "evaluation_run_id",
                "cascade_run_id",
                "content_type",
                "store_id",
            )
            if any(getattr(previous, key) != getattr(ref, key) for key in stable):
                raise ArtifactConflict("artifact_identity_conflict")
            ref = previous
        self._authorized(ref)
        if ref.status == "pending" and self.clock() - ref.created_at > timedelta(minutes=1):
            raise ArtifactUnavailable("artifact_upload_window_expired")
        ref = self.metadata.begin_reserved(
            ref,
            operations=3,
            byte_count=len(body),
            objects=1,
            read_bytes=len(body),
        )
        if ref.status == "ready":
            # Never claim a required export ready without checking its generation/body.
            self.read(ref.artifact_id, owner_id=owner_id, scope=scope)
            return ref
        if ref.status != "pending":
            raise ArtifactUnavailable("artifact_not_pending")
        generation = self.store.put(ref.key, body)
        try:
            self._authorized(ref)  # deletion or revocation during upload denies publication
            return self._state(ref, "ready", generation=generation)
        except Exception:
            try:
                current = self.metadata.get(ref.artifact_id, owner_id=owner_id, scope=scope)
                if current.status == "ready" and current.generation == generation:
                    self._authorized(current)
                    return current  # concurrent identical publication is idempotent
                if (
                    current.status in {"deleting", "deleted"}
                    or not self.metadata.active(owner_id)
                    or not self.authorize(ref)
                ):
                    self.metadata.reserve(operations=1, byte_count=0)
                    self.store.delete(ref.key, generation)
            except Exception:  # noqa: BLE001, S110 - tracked pending/tombstone recovery owns retry
                pass
            raise

    def _state(self, ref, status, *, generation=None):
        updated = ArtifactRef.model_validate(
            {**ref.model_dump(), "status": status, "generation": generation or ref.generation}
        )
        return self.metadata.update(updated, expected_revision=ref.revision)

    def read(self, artifact_id: UUID, *, owner_id, scope):
        ref = self.metadata.get(artifact_id, owner_id=owner_id, scope=scope)
        self._authorized(ref)
        if not ref.available_at(self.clock()):
            raise ArtifactUnavailable("artifact_not_ready")
        self.metadata.reserve(operations=1, byte_count=0, read_bytes=ref.compressed_bytes)
        try:
            body = self.store.read(ref.key, ref.generation, max_bytes=ref.compressed_bytes)
            value = decode(ref, body)
        except Exception:
            self._state(ref, "missing")
            raise
        self._authorized(ref)  # do not return content revoked during IO
        return value

    def delete(self, ref, *, owner_deletion=False):
        current = self.metadata.get(ref.artifact_id, owner_id=ref.owner_id, scope=ref.scope)
        if current.store_id != self.store.store_id:
            raise ArtifactUnavailable("artifact_store_identity_mismatch")
        if current.status == "deleted":
            return current
        if current.status != "deleting":
            current = (
                self.metadata.claim_owner_deletion(current)
                if owner_deletion
                else self._state(current, "deleting")
            )
        self.metadata.reserve(operations=2, byte_count=0)
        generation = current.generation or self.store.generation(current.key)
        if generation is not None:
            self.store.delete(current.key, generation)
        return self._state(current, "deleted", generation=generation)

    def reconcile(self, *, limit=100, owner_id=None):
        results = {"checked": 0, "ready": 0, "deleted": 0, "missing": 0, "failed": 0}
        for ref in self.metadata.batch(limit=limit, owner_id=owner_id):
            results["checked"] += 1
            try:
                if ref.store_id != self.store.store_id:
                    raise ArtifactUnavailable("artifact_store_identity_mismatch")
                if ref.status == "deleted":
                    # Uploads start only in the first minute and GCS calls have a ten-second
                    # timeout. Recent tombstones cover an upload/delete race without listing
                    # arbitrary bucket keys or trusting an unrelated replacement generation.
                    self.metadata.reserve(
                        operations=3, byte_count=0, read_bytes=ref.compressed_bytes
                    )
                    generation = self.store.generation(ref.key)
                    if generation is not None:
                        decode(
                            ref,
                            self.store.read(ref.key, generation, max_bytes=ref.compressed_bytes),
                        )
                        self.store.delete(ref.key, generation)
                    continue
                owner_fenced = not self.metadata.active(ref.owner_id)
                if owner_fenced:
                    self.delete(ref, owner_deletion=True)
                    results["deleted"] += 1
                elif (
                    ref.status == "deleting"
                    or self.clock() >= ref.expires_at
                    or not self.authorize(ref)
                ):
                    self.delete(ref)
                    results["deleted"] += 1
                elif ref.status in {"pending", "missing"}:
                    self.metadata.reserve(
                        operations=2, byte_count=0, read_bytes=ref.compressed_bytes
                    )
                    generation = ref.generation or self.store.generation(ref.key)
                    if generation is None:
                        if self.clock() - ref.created_at >= timedelta(minutes=10):
                            self._state(ref, "missing")
                            results["missing"] += 1
                        continue
                    try:
                        decode(
                            ref,
                            self.store.read(ref.key, generation, max_bytes=ref.compressed_bytes),
                        )
                    except ArtifactUnavailable:
                        # Known generation is retained for safe corrupt-object cleanup.
                        bad = self._state(ref, "missing", generation=generation)
                        self.delete(bad)
                        results["deleted"] += 1
                        continue
                    self._authorized(ref)
                    self._state(ref, "ready", generation=generation)
                    results["ready"] += 1
                elif ref.status == "ready":
                    # Immutable ready bodies are validated on read/export. Repeated
                    # maintenance does not consume the same transfer budget to reread them.
                    results["ready"] += 1
            except Exception:  # noqa: BLE001 - bounded recovery continues across independent objects
                results["failed"] += 1
        return results

    def freeze_export(self, exported, *, owner_id, scope, identity, max_records, max_bytes):
        """Freeze exact generations from the declared DB snapshot; no partial success."""
        namespace = hashlib.sha256(
            json.dumps(
                [owner_id, scope.application_id, scope.workspace_id], separators=(",", ":")
            ).encode()
        ).hexdigest()
        artifact_id = uuid5(NAMESPACE_URL, f"artifact:v1:{namespace}:export:{identity}")
        try:
            cached = self.metadata.get(artifact_id, owner_id=owner_id, scope=scope)
        except ArtifactUnavailable:
            cached = None
        if cached is not None and cached.status == "ready":
            self.read(artifact_id, owner_id=owner_id, scope=scope)
            return cached
        rows = exported.get("collections", {}).get("artifact_metadata", [])
        if len(rows) > max_records:
            raise ArtifactUnavailable("export_artifact_limit")
        if sum(len(records) for records in exported.get("collections", {}).values()) > max_records:
            raise ArtifactUnavailable("export_record_limit")
        snapshot_bytes = len(encode(exported)[0])
        estimated_bytes = snapshot_bytes + 4096
        manifest, bodies, dependencies, expiries = [], [], set(), []
        for row in rows:
            ref = ArtifactRef.model_validate(row["data"])
            if ref.kind == "export" or ref.status == "deleted" or ref.expires_at <= self.clock():
                continue
            current = self.metadata.get(ref.artifact_id, owner_id=owner_id, scope=scope)
            if current != ref or not ref.available_at(self.clock()):
                raise ArtifactUnavailable("export_artifact_snapshot_incomplete")
            estimated_bytes += ref.uncompressed_bytes + len(ref.model_dump_json().encode()) + 128
            if estimated_bytes > min(max_bytes, MAX_RAW_BYTES):
                raise ArtifactUnavailable("export_artifact_size")
            bodies.append(
                {
                    "artifact_id": str(ref.artifact_id),
                    "body": self.read(ref.artifact_id, owner_id=owner_id, scope=scope),
                }
            )
            manifest.append(ref.model_dump(mode="json"))
            dependencies.update(ref.grant_dependencies)
            expiries.append(ref.expires_at)
        envelope = {
            "schema_version": "account-artifact-export-v1",
            "snapshot": exported,
            "artifact_manifest": manifest,
            "artifact_bodies": bodies,
            "consistency": "declared_database_snapshot_plus_exact_object_generations",
            "body_coverage": "live_non_export_artifacts_only; expired/deleted/prior_exports_excluded",
        }
        raw, _ = encode(envelope)
        if len(raw) > max_bytes:
            raise ArtifactUnavailable("export_artifact_size")
        return self.write(
            envelope,
            owner_id=owner_id,
            scope=scope,
            kind="export",
            identity=identity,
            schema_version="account-artifact-export-v1",
            retention_days=1,
            required=True,
            sensitivity="restricted",
            grant_dependencies=tuple(sorted(dependencies)),
            source_rights_until=min(expiries) if expiries else None,
            source_rights_verified=True,
        )
