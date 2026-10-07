"""Bounded Firestore-to-polyglot migration and logical reconciliation.

The normal persistence factory does not import this module.  It is an operator
tool used while Firestore remains canonical; every scan is explicit and every
target write is keyed by the original Firestore document identity.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.postgres import (
    FAMILY_TABLES,
    PostgresDatabase,
    PostgresPayloadRepository,
)

MIGRATION_SCHEMA_VERSION = "phase10-target-v1"
DEFAULT_BATCH_SIZE = 100
MAX_BATCH_SIZE = 500
MAX_MIGRATION_RECORDS = 500_000

# Keep this list in lockstep with the literal source inventory documented in
# docs/personal-ai-chapter-2/phase-10-storage-ownership-and-access-patterns.md.
FIRESTORE_FAMILIES = (
    "conversations",
    "messages",
    "conversation_summaries",
    "research_sessions",
    "research_request_keys",
    "itinerary_proposals",
    "booking_document_extractions",
    "iterative_research_runs",
    "iterative_research_request_keys",
    "memories",
    "derived_memories",
    "derived_memory_sources",
    "memory_lifecycle_states",
    "memory_lifecycle_events",
    "memory_lifecycle_jobs",
    "memory_lifecycle_operations",
    "canonical_entities",
    "entity_aliases",
    "entity_claims",
    "entity_matches",
    "decision_snapshots",
    "decision_evidence_snapshots",
    "candidate_evaluations",
    "domain_registrations",
    "domain_claim_extensions",
    "provider_observations",
    "domain_comparison_views",
    "domain_lookup_idempotency",
    "identity_mappings",
    "account_lifecycle_requests",
    "audit_events",
    "usage_budgets",
    "domain_provider_rate_limits",
    "rate_limit_windows",
)

DYNAMODB_FAMILIES = frozenset(
    {
        "conversations",
        "messages",
        "conversation_summaries",
        "memory_lifecycle_jobs",
        "rate_limit_windows",
    }
)
POSTGRES_FAMILIES = frozenset(FIRESTORE_FAMILIES) - DYNAMODB_FAMILIES
GLOBAL_FAMILIES = frozenset({"domain_registrations", "domain_provider_rate_limits"})
LEGACY_OPERATION_FAMILY = "memory_lifecycle_operations"


class MigrationRejected(ValueError):
    """A source row cannot be mapped safely to its approved target family."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MigrationConflict(RuntimeError):
    """A target record diverged from the version last owned by this migration."""


class SourceSnapshot(Protocol):
    document_id: str
    update_time: datetime
    data: dict[str, Any]


class FirestoreMigrationSource(Protocol):
    project_id: str

    def scan_page(self, family: str, after: str | None, limit: int) -> list[SourceSnapshot]: ...
    def get(self, family: str, document_id: str) -> SourceSnapshot | None: ...


class MigrationTarget(Protocol):
    def logical_hash(
        self, family: str, logical_id: str, owner_id: str, scope: ApplicationScope,
        payload: dict[str, Any] | None = None, *, source_version: str | None = None,
    ): ...
    def import_record(self, record: MappedRecord, expected_existing_hash: str | None): ...
    def delete_record(self, family: str, logical_id: str, owner_id: str, scope: ApplicationScope): ...


@dataclass(frozen=True)
class SourceRecord:
    document_id: str
    update_time: datetime
    data: dict[str, Any]


@dataclass(frozen=True)
class MappedRecord:
    family: str
    source_document_id: str
    logical_id: str
    target_store: str
    owner_id: str
    scope: ApplicationScope
    scope_kind: str
    payload: dict[str, Any]
    source_version: str
    source_hash: str
    logical_hash: str
    estimated_bytes: int


@dataclass(frozen=True)
class MigrationResult:
    epoch_id: str
    mode: str
    counts: dict[str, dict[str, int]]
    rejected: tuple[dict[str, str], ...]
    conflicts: tuple[dict[str, str], ...]
    source_digest: str
    reconciliation: dict[str, dict[str, str | int]]
    final_delta_ready: bool


def portable(value: Any) -> Any:
    """Convert Firestore-native values to deterministic, loss-aware JSON."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise MigrationRejected("timestamp_without_timezone")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return {"$type": "date", "value": value.isoformat()}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise MigrationRejected("non_finite_decimal")
        return {"$type": "decimal", "value": str(value)}
    if isinstance(value, bytes):
        return {"$type": "base64", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): portable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [portable(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MigrationRejected("non_finite_number")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    # Firestore Vector and GeoPoint are optional SDK types; their values are
    # represented explicitly so an unknown custom object is never stringified.
    if value.__class__.__name__ == "Vector":
        return [portable(item) for item in value]
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        return {
            "$type": "geopoint",
            "latitude": portable(value.latitude),
            "longitude": portable(value.longitude),
        }
    raise MigrationRejected("unsupported_source_value")


def canonical_json(value: Any) -> str:
    return json.dumps(portable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _source_version(snapshot: SourceSnapshot) -> str:
    version = snapshot.update_time
    if not isinstance(version, datetime) or version.tzinfo is None or version.utcoffset() is None:
        raise MigrationRejected("source_update_time_missing")
    return version.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _id_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int)):
        return str(value)
    return None


def _explicit_scope(payload: dict[str, Any]) -> ApplicationScope:
    try:
        return ApplicationScope(
            application_id=payload.get("application_id", "personal_ai"),
            workspace_id=payload.get("workspace_id"),
        )
    except (TypeError, ValueError) as error:
        raise MigrationRejected("scope_invalid") from error


def _require_parent_scope(
    source: FirestoreMigrationSource,
    family: str,
    document_id: str,
    owner_id: str,
    scope: ApplicationScope,
) -> None:
    parent = source.get(family, document_id)
    if parent is None:
        raise MigrationRejected("referenced_parent_missing")
    parent_owner = _id_value(parent.data.get("owner_id"))
    if parent_owner != owner_id:
        raise MigrationRejected("referenced_parent_owner_conflict")
    if _explicit_scope(parent.data) != scope:
        raise MigrationRejected("referenced_parent_scope_conflict")


def _counter_owner(document_id: str, payload: dict[str, Any], owner_ids: set[str]) -> str | None:
    window = payload.get("window_start")
    if not isinstance(window, datetime) or window.tzinfo is None:
        return None
    epoch = int(window.astimezone(UTC).timestamp() // 60)
    for owner_id in owner_ids:
        expected = hashlib.sha256(f"{owner_id}\0{epoch}".encode()).hexdigest()
        if expected == document_id:
            return owner_id
    return None


def _budget_owner(document_id: str, payload: dict[str, Any], owner_ids: set[str]) -> tuple[str, str] | None:
    period = _timestamp(payload.get("period_start"))
    source_scope = payload.get("scope")
    if period is None or not isinstance(source_scope, str) or not source_scope.startswith("owner:"):
        return None
    day = period.date().isoformat()
    for owner_id in owner_ids:
        opaque_owner = hashlib.sha256(owner_id.encode()).hexdigest()
        expected_id = hashlib.sha256(f"{opaque_owner}\0{day}".encode()).hexdigest()
        if source_scope == f"owner:{opaque_owner}" and expected_id == document_id:
            return owner_id, day
    return None


def map_source_record(
    source: FirestoreMigrationSource,
    family: str,
    snapshot: SourceSnapshot,
    *,
    known_owners: set[str],
    now: datetime | None = None,
) -> MappedRecord:
    if family not in FIRESTORE_FAMILIES:
        raise MigrationRejected("source_family_unmapped")
    payload = snapshot.data
    source_hash = digest(payload)
    target_store = "dynamodb" if family in DYNAMODB_FAMILIES else "postgres"
    owner_id = _id_value(payload.get("owner_id"))
    scope = _explicit_scope(payload)
    scope_kind = "private"
    logical_id_override = None

    if family in {"candidate_evaluations", "domain_claim_extensions", "entity_aliases"}:
        parent_collection, parent_field = {
            "candidate_evaluations": ("decision_snapshots", "decision_id"),
            "domain_claim_extensions": ("entity_claims", "claim_id"),
            "entity_aliases": ("canonical_entities", "entity_id"),
        }[family]
        parent_id = _id_value(payload.get(parent_field))
        parent = None if parent_id is None else source.get(parent_collection, parent_id)
        parent_data = None if parent is None else parent.data
        if parent_data is None:
            raise MigrationRejected("ownerless_child_parent_missing")
        parent_scope = _explicit_scope(parent_data)
        if ("application_id" in payload or "workspace_id" in payload) and parent_scope != scope:
            raise MigrationRejected("ownerless_child_scope_conflict")
        if "application_id" not in payload and "workspace_id" not in payload:
            scope = parent_scope
        parent_owner = _id_value(parent_data.get("owner_id"))
        if owner_id is not None and parent_owner not in {owner_id, "*"}:
            raise MigrationRejected("child_parent_owner_conflict")
        if owner_id is None:
            owner_id = parent_owner
        if parent_collection == "canonical_entities" and (
            parent_data.get("owner_scope") == "shared" or parent_owner == "*"
        ):
            scope_kind = "shared"
    if family in {"entity_claims", "entity_matches"}:
        entity_id = _id_value(payload.get("entity_id"))
        entity = None if entity_id is None else source.get("canonical_entities", entity_id)
        if entity is None:
            raise MigrationRejected("entity_parent_missing")
        parent_owner = _id_value(entity.data.get("owner_id"))
        if owner_id is not None and parent_owner not in {owner_id, "*"}:
            raise MigrationRejected("child_parent_owner_conflict")
        if owner_id is None:
            owner_id = parent_owner
        parent_scope = _explicit_scope(entity.data)
        if ("application_id" in payload or "workspace_id" in payload) and parent_scope != scope:
            raise MigrationRejected("ownerless_child_scope_conflict")
        if "application_id" not in payload and "workspace_id" not in payload:
            scope = parent_scope
        if entity.data.get("owner_scope") == "shared" or parent_owner == "*":
            scope_kind = "shared"
    if family == "rate_limit_windows":
        # The current Firestore safeguard writer persists exactly this fixed
        # request-window envelope. Do not drop a newly introduced source field
        # while projecting onto the bounded DynamoDB item.
        if not {"request_count", "window_start", "expires_at"} <= set(payload):
            raise MigrationRejected("counter_payload_incomplete")
        if set(payload) - {"request_count", "window_start", "expires_at", "policy_version"}:
            raise MigrationRejected("counter_payload_unmapped_fields")
        owner_id = _counter_owner(snapshot.document_id, payload, known_owners)
        if owner_id is None:
            expires_at = payload.get("expires_at")
            current = now or datetime.now(UTC)
            if expires_at is None or not isinstance(expires_at, datetime) or expires_at > current:
                raise MigrationRejected("active_counter_owner_unresolved")
            owner_id = "__expired_unattributed__"
            scope_kind = "expired-disposition"
        window = payload.get("window_start")
        if not isinstance(window, datetime) or window.tzinfo is None:
            raise MigrationRejected("counter_window_invalid")
        logical_id_override = str(int(window.astimezone(UTC).timestamp() // 60))
        scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
    elif family == "usage_budgets":
        identity = _budget_owner(snapshot.document_id, payload, known_owners)
        if identity is None:
            raise MigrationRejected("usage_budget_owner_unresolved")
        owner_id, day = identity
        logical_id_override = f"usage:{day}"
        scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
    elif family in GLOBAL_FAMILIES:
        owner_id = "__global__"
        scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
        scope_kind = "global"
    elif family == "canonical_entities" and (
        payload.get("owner_scope") == "shared" or owner_id == "*"
    ) or owner_id == "*" or payload.get("owner_scope") == "shared":
        owner_id = "*"
        scope_kind = "shared"

    if owner_id is None or not owner_id:
        raise MigrationRejected("owner_missing")
    if family == "memory_lifecycle_states":
        memory_id = _id_value(payload.get("memory_id")) or snapshot.document_id
        _require_parent_scope(source, "memories", memory_id, owner_id, scope)
        last_event_id = _id_value(payload.get("last_event_id"))
        if last_event_id:
            _require_parent_scope(source, "memory_lifecycle_events", last_event_id, owner_id, scope)
    elif family == "memory_lifecycle_events":
        memory_id = _id_value(payload.get("memory_id"))
        if not memory_id:
            raise MigrationRejected("lifecycle_event_memory_missing")
        _require_parent_scope(source, "memories", memory_id, owner_id, scope)
        for related_id in payload.get("related_memory_ids", ()):
            normalized_id = _id_value(related_id)
            if not normalized_id:
                raise MigrationRejected("lifecycle_event_related_memory_invalid")
            _require_parent_scope(source, "memories", normalized_id, owner_id, scope)
        job_id = _id_value(payload.get("job_id"))
        if job_id:
            _require_parent_scope(source, "memory_lifecycle_jobs", job_id, owner_id, scope)
    elif family == "memory_lifecycle_jobs":
        for memory_id in payload.get("candidate_memory_ids", ()):
            normalized_id = _id_value(memory_id)
            if not normalized_id:
                raise MigrationRejected("lifecycle_job_candidate_memory_invalid")
            _require_parent_scope(source, "memories", normalized_id, owner_id, scope)
    elif family == "entity_matches":
        decision_id = _id_value(payload.get("decision_id"))
        if decision_id:
            _require_parent_scope(source, "decision_snapshots", decision_id, owner_id, scope)
    if family in GLOBAL_FAMILIES:
        # Global controls have no private owner namespace, but their stable
        # provider/module identity is still retained separately from the payload.
        logical_id = (
            (_id_value(payload.get("provider_id") or payload.get("provider")) or snapshot.document_id)
            if family == "domain_provider_rate_limits"
            else canonical_json([
                _id_value(payload.get(key)) for key in (
                    "domain_id", "field_schema_version", "feature_policy_version", "source_policy_version"
                )
            ])
        )
    elif family == LEGACY_OPERATION_FAMILY and _is_receipt_payload(payload):
        operation_id = _id_value(payload.get("operation_id"))
        attempt_id = _id_value(payload.get("attempt_id"))
        if not operation_id or not attempt_id:
            raise MigrationRejected("effect_receipt_identity_missing")
        logical_id = f"{operation_id}|{attempt_id}"
    else:
        logical_id = logical_id_override or _id_value(payload.get("id")) or (
            _id_value(payload.get("memory_id")) if family == "memory_lifecycle_states" else None
        ) or snapshot.document_id
    if not logical_id or len(logical_id) > 512 or len(snapshot.document_id) > 512:
        raise MigrationRejected("logical_id_invalid")

    # Legacy source envelopes stay byte/field compatible in `payload`; scope
    # normalization happens only in target namespace columns and physical keys.
    normalized = portable(payload)
    if target_store == "dynamodb" or family in {"memories", "derived_memories"}:
        logical_payload = _target_logical_payload(family, payload)
    elif family == "domain_provider_rate_limits":
        logical_payload = payload
    else:
        logical_payload = payload
    logical_hash = digest(logical_payload)
    estimated_bytes = len(canonical_json(normalized).encode("utf-8"))
    postgres_envelope = normalized
    if family in {"memories", "derived_memories"}:
        postgres_envelope = dict(normalized)
        postgres_envelope.pop("embedding", None)
    postgres_envelope_bytes = len(canonical_json(postgres_envelope).encode("utf-8"))
    if target_store == "dynamodb" and estimated_bytes > 350_000:
        raise MigrationRejected("dynamodb_payload_bound_exceeded")
    if estimated_bytes > 262_144 and target_store == "postgres":
        raise MigrationRejected("postgres_payload_bound_exceeded")
    if family in {"memories", "derived_memories", LEGACY_OPERATION_FAMILY} \
            and postgres_envelope_bytes > 32_768:
        raise MigrationRejected("memory_payload_bound_exceeded")
    if family in {"derived_memory_sources", "domain_registrations", "domain_provider_rate_limits"} \
            and estimated_bytes > 32_768:
        raise MigrationRejected("postgres_envelope_bound_exceeded")
    return MappedRecord(
        family=family,
        source_document_id=snapshot.document_id,
        logical_id=logical_id,
        target_store=target_store,
        owner_id=owner_id,
        scope=scope,
        scope_kind=scope_kind,
        payload=payload,
        source_version=_source_version(snapshot),
        source_hash=source_hash,
        logical_hash=logical_hash,
        estimated_bytes=estimated_bytes,
    )


def _target_logical_payload(family: str, payload: dict[str, Any]) -> Any:
    """Normalize DTO/vector-column records while raw P envelope families stay lossless."""
    if family == "conversations":
        from personal_ai.entities import Conversation

        return Conversation.model_validate(payload).model_dump(
            mode="json", exclude={"context_preparation_id", "context_preparation_started_at", "persistence_revision"}
        )
    if family == "messages":
        from personal_ai.entities import Message

        return Message.model_validate(payload).model_dump(mode="json")
    if family == "conversation_summaries":
        from personal_ai.context.contracts import ConversationSummary

        return ConversationSummary.model_validate(payload).model_dump(mode="json")
    if family == "memory_lifecycle_jobs":
        from personal_ai.memory.lifecycle import MemoryJob

        return MemoryJob.model_validate(payload).model_dump(mode="json")
    if family == "memories":
        from personal_ai.memory.contracts import Memory

        return Memory.model_validate(payload).model_dump(mode="json")
    if family == "derived_memories":
        from personal_ai.memory.contracts import DerivedMemory

        return DerivedMemory.model_validate(payload).model_dump(mode="json")
    if family == "rate_limit_windows":
        return {
            "request_count": int(payload.get("request_count", 0)),
            "window_start": payload.get("window_start"),
            "expires_at": payload.get("expires_at"),
            "policy_version": payload.get("policy_version", "request-rate-v1"),
        }
    return payload


class GoogleFirestoreMigrationSource:
    """Operator-only paginated reader; normal request paths never use it."""

    def __init__(self, project_id: str, *, database_id: str = "(default)", client=None):
        if not project_id:
            raise ValueError("firestore_migration_project_required")
        from google.cloud import firestore

        self.project_id = project_id
        self.database_id = database_id
        if client is None:
            self.client = firestore.Client(project=project_id, database=database_id)
        else:
            self.client = client
        self._field_path = firestore.FieldPath.document_id()

    def scan_page(self, family: str, after: str | None, limit: int) -> list[SourceRecord]:
        if family not in FIRESTORE_FAMILIES:
            raise ValueError("firestore_migration_family_invalid")
        query = self.client.collection(family).order_by(self._field_path).limit(limit)
        if after is not None:
            query = query.start_after({self._field_path: after})
        snapshots = list(query.stream(retry=None))
        return [
            SourceRecord(
                document_id=snapshot.id,
                update_time=snapshot.update_time,
                data=snapshot.to_dict() or {},
            )
            for snapshot in snapshots
        ]

    def get(self, family: str, document_id: str) -> SourceRecord | None:
        snapshot = self.client.collection(family).document(document_id).get(retry=None)
        if not snapshot.exists:
            return None
        return SourceRecord(snapshot.id, snapshot.update_time, snapshot.to_dict() or {})


class PostgresMigrationControl:
    """Durable migration checkpoints and source-version ownership metadata."""

    def __init__(self, database) -> None:
        self.database = database

    @contextmanager
    def epoch_lock(self, epoch_id: str):
        self.database.open()
        with self.database._pool.connection() as connection:
            # Lock the shared target, not just one operator-supplied epoch. Two
            # differently named runs must not interleave target ownership.
            key = "p10-storage-migration-target"
            connection.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (key,))
            try:
                yield
            finally:
                connection.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))

    def begin_epoch(self, *, epoch_id: str, project_id: str, database_id: str,
                    config_fingerprint: str, final_delta: bool) -> None:
        status = "final-delta" if final_delta else "backfill"
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT source_project_id,source_database_id,source_schema_version,"
                "target_schema_version,config_fingerprint FROM storage_migration_epochs "
                "WHERE epoch_id=%s FOR UPDATE", (epoch_id,)
            ).fetchone()
            identity = (
                project_id, database_id, "firestore-native-v1",
                MIGRATION_SCHEMA_VERSION, config_fingerprint,
            )
            if row is None:
                connection.execute(
                    "INSERT INTO storage_migration_epochs(epoch_id,source_project_id,source_database_id,"
                    "source_schema_version,target_schema_version,config_fingerprint,status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)", (epoch_id, *identity, status)
                )
            elif tuple(row) != identity:
                raise MigrationConflict("migration epoch source or target configuration changed")
            else:
                connection.execute(
                    "UPDATE storage_migration_epochs SET status=%s,updated_at=now() WHERE epoch_id=%s",
                    (status, epoch_id),
                )

    def start_family(self, epoch_id: str, family: str) -> tuple[int, str | None]:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT generation,last_source_document_id,scan_state FROM storage_migration_checkpoints "
                "WHERE epoch_id=%s AND family=%s FOR UPDATE", (epoch_id, family)
            ).fetchone()
            if row is None:
                generation, cursor = 1, None
                connection.execute(
                    "INSERT INTO storage_migration_checkpoints(epoch_id,family,generation,scan_state) "
                    "VALUES (%s,%s,%s,'running')", (epoch_id, family, generation)
                )
            elif row[2] == "running":
                generation, cursor = int(row[0]), row[1]
            else:
                generation, cursor = int(row[0]) + 1, None
                connection.execute(
                    "UPDATE storage_migration_checkpoints SET generation=%s,last_source_document_id=NULL,"
                    "scan_state='running',scanned_count=0,applied_count=0,rejected_count=0,updated_at=now() "
                    "WHERE epoch_id=%s AND family=%s", (generation, epoch_id, family)
                )
            return generation, cursor

    def checkpoint_page(self, *, epoch_id: str, family: str, generation: int,
                        last_source_document_id: str, scanned: int, applied: int, rejected: int) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE storage_migration_checkpoints SET last_source_document_id=%s,"
                "scanned_count=scanned_count+%s,applied_count=applied_count+%s,"
                "rejected_count=rejected_count+%s,updated_at=now() "
                "WHERE epoch_id=%s AND family=%s AND generation=%s",
                (last_source_document_id, scanned, applied, rejected, epoch_id, family, generation),
            )

    def finish_family(self, epoch_id: str, family: str, generation: int) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE storage_migration_checkpoints SET last_source_document_id=NULL,"
                "scan_state='complete',updated_at=now() WHERE epoch_id=%s AND family=%s AND generation=%s",
                (epoch_id, family, generation),
            )

    def prior_record(self, epoch_id: str, family: str, source_id: str):
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT logical_id,target_store,source_version,source_hash,target_hash,disposition,"
                "rejection_code,seen_generation FROM storage_migration_records "
                "WHERE epoch_id=%s AND family=%s AND source_document_id=%s",
                (epoch_id, family, source_id),
            ).fetchone()

    def acknowledge(self, *, epoch_id: str, record: MappedRecord, target_hash: str,
                    generation: int, connection=None) -> None:
        sql = (
            "INSERT INTO storage_migration_records(epoch_id,family,source_document_id,logical_id,"
            "target_store,source_version,source_hash,mapped_hash,target_hash,disposition,seen_generation,owner_id,"
            "application_id,workspace_id,target_locator) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'applied',%s,%s,%s,%s,%s::jsonb) "
            "ON CONFLICT(epoch_id,family,source_document_id) DO UPDATE SET logical_id=EXCLUDED.logical_id,"
            "target_store=EXCLUDED.target_store,source_version=EXCLUDED.source_version,"
            "source_hash=EXCLUDED.source_hash,mapped_hash=EXCLUDED.mapped_hash,target_hash=EXCLUDED.target_hash,"
            "disposition='applied',"
            "rejection_code=NULL,disposition_code=NULL,seen_generation=EXCLUDED.seen_generation,owner_id=EXCLUDED.owner_id,"
            "application_id=EXCLUDED.application_id,workspace_id=EXCLUDED.workspace_id,"
            "target_locator=EXCLUDED.target_locator,updated_at=now()"
        )
        params = (
            epoch_id, record.family, record.source_document_id, record.logical_id,
            record.target_store, record.source_version, record.source_hash, record.logical_hash,
            target_hash, generation,
            record.owner_id, record.scope.application_id, record.scope.workspace_id,
            canonical_json(_target_locator(record)),
        )
        if connection is not None:
            connection.execute(sql, params)
        else:
            with self.database.transaction() as tx:
                tx.execute(sql, params)

    def reject(self, *, epoch_id: str, family: str, source_id: str, logical_id: str,
               source_version: str, source_hash: str, generation: int, code: str) -> None:
        target_store = "dynamodb" if family in DYNAMODB_FAMILIES else "postgres"
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO storage_migration_records(epoch_id,family,source_document_id,logical_id,"
                "target_store,source_version,source_hash,target_hash,disposition,rejection_code,seen_generation) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'rejected',%s,%s) "
                "ON CONFLICT(epoch_id,family,source_document_id) DO UPDATE SET "
                "source_version=EXCLUDED.source_version,source_hash=EXCLUDED.source_hash,"
                "disposition='rejected',rejection_code=EXCLUDED.rejection_code,disposition_code=NULL,"
                "seen_generation=EXCLUDED.seen_generation,updated_at=now()",
                (epoch_id, family, source_id, logical_id, target_store, source_version,
                 source_hash, "0" * 64, code, generation),
            )

    def dispose(self, *, epoch_id: str, record: MappedRecord, generation: int, code: str) -> None:
        with self.database.transaction() as connection:
            self.acknowledge(
                epoch_id=epoch_id, record=record, target_hash="0" * 64,
                generation=generation, connection=connection,
            )
            connection.execute(
                "UPDATE storage_migration_records SET disposition='disposed',rejection_code=NULL,disposition_code=%s "
                "WHERE epoch_id=%s AND family=%s AND source_document_id=%s",
                (code, epoch_id, record.family, record.source_document_id),
            )

    def missing_page(self, epoch_id: str, family: str, generation: int,
                     after: str | None, limit: int):
        with self.database.connection() as connection:
            query = (
                "SELECT source_document_id,logical_id,target_store,source_version,source_hash,target_hash,"
                "owner_id,application_id,workspace_id,target_locator "
                "FROM storage_migration_records WHERE epoch_id=%s AND family=%s "
                "AND disposition IN ('applied','rejected') AND seen_generation<>%s "
            )
            params: tuple = (epoch_id, family, generation)
            if after is not None:
                query += "AND source_document_id>%s "
                params += (after,)
            return connection.execute(
                query + "ORDER BY source_document_id LIMIT %s", params + (limit,),
            ).fetchall()

    def applied_records_page(self, epoch_id: str, family: str, generation: int,
                             after: str | None, limit: int):
        with self.database.connection() as connection:
            query = (
                "SELECT source_document_id,logical_id,target_store,source_version,mapped_hash,target_hash,owner_id,"
                "application_id,workspace_id,target_locator FROM storage_migration_records "
                "WHERE epoch_id=%s AND family=%s AND seen_generation=%s AND disposition='applied' "
            )
            params: tuple = (epoch_id, family, generation)
            if after is not None:
                query += "AND source_document_id>%s "
                params += (after,)
            return connection.execute(
                query + "ORDER BY source_document_id LIMIT %s", params + (limit,),
            ).fetchall()

    def generation_disposition_count(self, epoch_id: str, family: str, generation: int) -> int:
        with self.database.connection() as connection:
            return int(connection.execute(
                "SELECT count(*) FROM storage_migration_records WHERE epoch_id=%s AND family=%s "
                "AND seen_generation=%s AND disposition IN ('applied','rejected','disposed')",
                (epoch_id, family, generation),
            ).fetchone()[0])

    def generation_scanned_count(self, epoch_id: str, family: str, generation: int) -> int:
        with self.database.connection() as connection:
            return int(connection.execute(
                "SELECT scanned_count FROM storage_migration_checkpoints "
                "WHERE epoch_id=%s AND family=%s AND generation=%s",
                (epoch_id, family, generation),
            ).fetchone()[0])

    def mark_conflict(self, epoch_id: str, family: str, source_id: str,
                      generation: int, code: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE storage_migration_records SET disposition='rejected',rejection_code=%s,"
                "disposition_code=NULL,seen_generation=%s,updated_at=now() "
                "WHERE epoch_id=%s AND family=%s AND source_document_id=%s",
                (code, generation, epoch_id, family, source_id),
            )

    def mark_deleted(self, epoch_id: str, family: str, source_id: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE storage_migration_records SET disposition='source-deleted',rejection_code=NULL,"
                "disposition_code=NULL,"
                "updated_at=now() WHERE epoch_id=%s AND family=%s AND source_document_id=%s",
                (epoch_id, family, source_id),
            )

    def counts(self, epoch_id: str) -> dict[str, dict[str, int]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT family,disposition,count(*) FROM storage_migration_records WHERE epoch_id=%s "
                "GROUP BY family,disposition ORDER BY family,disposition", (epoch_id,)
            ).fetchall()
        result: dict[str, dict[str, int]] = {}
        for family, disposition, amount in rows:
            result.setdefault(family, {})[disposition] = int(amount)
        return result

    def source_digest(self, epoch_id: str, generations: dict[str, int]) -> str:
        hasher = hashlib.sha256()
        with self.database.connection() as connection:
            for family in FIRESTORE_FAMILIES:
                cursor = None
                while True:
                    query = (
                        "SELECT source_document_id,source_version,source_hash FROM storage_migration_records "
                        "WHERE epoch_id=%s AND family=%s AND seen_generation=%s "
                    )
                    params: tuple = (epoch_id, family, generations[family])
                    if cursor is not None:
                        query += "AND source_document_id>%s "
                        params += (cursor,)
                    rows = connection.execute(
                        query + "ORDER BY source_document_id LIMIT %s", params + (MAX_BATCH_SIZE,),
                    ).fetchall()
                    if not rows:
                        break
                    for source_id, version, source_hash in rows:
                        hasher.update(f"{family}\0{source_id}\0{version}\0{source_hash}\n".encode())
                    cursor = rows[-1][0]
                    if len(rows) < MAX_BATCH_SIZE:
                        break
        return hasher.hexdigest()

    def finalize(self, epoch_id: str, *, final_delta: bool, conflict_count: int = 0) -> bool:
        with self.database.transaction() as connection:
            checkpoints = connection.execute(
                "SELECT count(*) FROM storage_migration_checkpoints WHERE epoch_id=%s "
                "AND scan_state='complete'", (epoch_id,),
            ).fetchone()[0]
            rejected = connection.execute(
                "SELECT count(*) FROM storage_migration_records WHERE epoch_id=%s "
                "AND disposition='rejected'", (epoch_id,),
            ).fetchone()[0]
            ready = (
                final_delta and int(checkpoints) == len(FIRESTORE_FAMILIES)
                and int(rejected) == 0 and conflict_count == 0
            )
            connection.execute(
                "UPDATE storage_migration_epochs SET status=%s,updated_at=now() WHERE epoch_id=%s",
                (("final-delta" if ready else "blocked") if final_delta else "backfill", epoch_id),
            )
        return ready


class PostgresMigrationTarget:
    """Imports P-owned families without routing historical effects through live guards."""

    def __init__(self, database: PostgresDatabase, control: PostgresMigrationControl) -> None:
        self.database = database
        self.control = control

    def logical_hash(
        self, family: str, logical_id: str, owner_id: str, scope: ApplicationScope,
        payload: dict[str, Any] | None = None, *, source_version: str | None = None,
    ) -> str | None:
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        if family == "domain_registrations":
            key = _domain_registration_key_from_logical(logical_id)
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT enabled,created_at,payload FROM domain_registrations WHERE module_id=%s AND module_version=%s "
                    "AND policy_version=%s", key,
                ).fetchone()
            if row is None:
                return None
            target_payload = row[2]
            if bool(row[0]) != bool(target_payload.get("enabled", False)):
                raise MigrationConflict("domain registration projection diverged")
            expected_created = _timestamp(target_payload.get("created_at"))
            if expected_created is not None and _timestamp(row[1]) != expected_created:
                raise MigrationConflict("domain registration timestamp projection diverged")
            return digest(target_payload)
        if family == "domain_provider_rate_limits":
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT next_available_at,revision,updated_at,payload FROM domain_provider_rate_limits "
                    "WHERE provider_id=%s", (logical_id,),
                ).fetchone()
            if row is None:
                return None
            if row[3] is not None:
                target_payload = row[3]
                if _timestamp(row[0]) != _timestamp(target_payload.get("next_request_at")):
                    raise MigrationConflict("provider throttle timestamp projection diverged")
                if int(row[1]) != int(target_payload.get("revision", 1)):
                    raise MigrationConflict("provider throttle revision projection diverged")
                expected_updated = _timestamp(target_payload.get("updated_at"))
                if expected_updated is not None and _timestamp(row[2]) != expected_updated:
                    raise MigrationConflict("provider throttle update projection diverged")
                return digest(target_payload)
            return digest({
                "provider": logical_id, "next_request_at": row[0],
            })
        if family == "memories":
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT payload,memory_type,status,source_conversation_id,source_turn_id,"
                    "source_message_ids,source_fingerprint,embedding_provider,embedding_model,"
                    "embedding_dimensions,embedding_normalization,document_task,query_task,embedding,"
                    "created_at,effective_at FROM memories WHERE scope_id=%s AND record_id=%s "
                    "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
                    (scope_id, logical_id, owner_id, scope.application_id, scope.workspace_id),
                ).fetchone()
            if row is None:
                return None
            from personal_ai.memory.contracts import Memory

            target_payload = row[0]
            item = Memory.model_validate({**target_payload, "embedding": row[13]})
            expected = (
                item.memory_type, str(getattr(item.status, "value", item.status)),
                str(item.source_conversation_id), str(item.source_turn_id),
                [str(value) for value in item.source_message_ids], item.source_fingerprint,
                item.embedding_provider, item.embedding_model, item.embedding_dimensions,
                item.embedding_normalization, item.embedding_document_task, item.embedding_query_task,
                tuple(float(value) for value in item.embedding), _timestamp(item.created_at),
                _timestamp(item.effective_at),
            )
            actual = (
                row[1], row[2], row[3], row[4], [str(value) for value in row[5]], str(row[6]).strip(),
                row[7], row[8], int(row[9]), row[10], row[11], row[12],
                tuple(float(value) for value in row[13]), _timestamp(row[14]), _timestamp(row[15]),
            )
            if actual != expected:
                raise MigrationConflict("memory vector or provenance projection diverged")
            return digest(item.model_dump(mode="json"))
        if family == "derived_memories":
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT payload,memory_type,status,source_set_identity,embedding_provider,embedding_model,"
                    "embedding_dimensions,embedding_normalization,document_task,query_task,embedding,"
                    "created_at,effective_at FROM derived_memories WHERE scope_id=%s AND record_id=%s "
                    "AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
                    (scope_id, logical_id, owner_id, scope.application_id, scope.workspace_id),
                ).fetchone()
            if row is None:
                return None
            from personal_ai.memory.contracts import DerivedMemory

            target_payload = row[0]
            item = DerivedMemory.model_validate({**target_payload, "embedding": row[10]})
            expected = (
                item.memory_type, "active", item.source_set_identity,
                item.embedding_provider, item.embedding_model, item.embedding_dimensions,
                item.embedding_normalization, item.embedding_document_task, item.embedding_query_task,
                tuple(float(value) for value in item.embedding), _timestamp(item.created_at),
                _timestamp(item.effective_at),
            )
            actual = (
                row[1], row[2], str(row[3]).strip(), row[4], row[5], int(row[6]), row[7], row[8], row[9],
                tuple(float(value) for value in row[10]), _timestamp(row[11]), _timestamp(row[12]),
            )
            if actual != expected:
                raise MigrationConflict("derived memory vector or source projection diverged")
            return digest(item.model_dump(mode="json"))
        is_receipt = bool(payload) and (
            payload.get("receipt") is True or _is_receipt_payload(payload)
        )
        if family == LEGACY_OPERATION_FAMILY and not is_receipt:
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT created_at,payload FROM legacy_memory_lifecycle_operations WHERE scope_id=%s "
                    "AND record_id=%s AND owner_id=%s AND application_id=%s "
                    "AND workspace_id IS NOT DISTINCT FROM %s",
                    (scope_id, logical_id, owner_id, scope.application_id, scope.workspace_id),
                ).fetchone()
            if row is None:
                return None
            target_payload = row[1]
            expected_created = _payload_created_at(target_payload)
            if expected_created is not None and _timestamp(row[0]) != expected_created:
                raise MigrationConflict("legacy lifecycle operation timestamp projection diverged")
            return digest(target_payload)
        if family == LEGACY_OPERATION_FAMILY and is_receipt:
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT fingerprint,outcome,result_refs,execution_deadline,created_at,payload "
                    "FROM memory_lifecycle_operations WHERE scope_id=%s "
                    "AND operation_id=%s AND attempt_id=%s",
                    (scope_id, payload["operation_id"], payload["attempt_id"]),
                ).fetchone()
            if row is None:
                return None
            if row[5] is not None:
                receipt = row[5]
                if (
                    str(row[0]).strip() != str(receipt.get("fingerprint", "")).strip()
                    or row[1] != receipt.get("outcome")
                    or row[2] != receipt.get("result_refs", {})
                    or _timestamp(row[3]) != _timestamp(receipt.get("execution_deadline"))
                ):
                    raise MigrationConflict("effect receipt projection diverged")
                return digest(receipt)
            return digest({
                "unowned_receipt": True,
                "fingerprint": str(row[0]).strip(), "outcome": row[1], "result_refs": row[2],
                "execution_deadline": row[3], "created_at": row[4],
            })
        if family == LEGACY_OPERATION_FAMILY:
            raise MigrationRejected("lifecycle_operation_locator_invalid")
        elif family in FAMILY_TABLES or family in {
            "memories", "derived_memories", "legacy_memory_lifecycle_operations",
        }:
            table = family
        elif family == "derived_memory_sources":
            with self.database.connection() as connection:
                row = connection.execute(
                    "SELECT ds.derived_memory_id,ds.source_memory_id,ds.source_ordinal,ds.source_fingerprint,"
                    "ds.source_conversation_id,ds.source_turn_id,ds.source_message_ids,ds.excerpt,ds.created_at,"
                    "ds.scope_version,ds.source_document_id,ds.source_payload,dm.payload "
                    "FROM derived_memory_sources ds JOIN derived_memories dm ON dm.scope_id=ds.scope_id "
                    "AND dm.record_id=ds.derived_memory_id WHERE ds.scope_id=%s AND ds.source_document_id=%s",
                    (scope_id, (payload or {}).get("source_document_id", logical_id)),
                ).fetchone()
            if row is None:
                return None
            target_payload = row[11]
            parent = row[12]
            source_id = str(row[1])
            provenance = next(
                (item for item in parent.get("sources", ()) if str(item.get("memory_id")) == source_id),
                None,
            )
            source_ids = tuple(str(item) for item in parent.get("source_memory_ids", ()))
            if provenance is None or source_id not in source_ids:
                raise MigrationConflict("derived source parent projection diverged")
            expected_projection = (
                str(row[0]), source_id, source_ids.index(source_id) + 1,
                str(provenance["source_fingerprint"]), str(provenance["source_conversation_id"]),
                str(provenance["source_turn_id"]), [str(item) for item in provenance["source_message_ids"]],
                str(provenance["excerpt"]), _timestamp(target_payload.get("created_at")),
                int(target_payload.get("scope_version", 1)),
            )
            actual_projection = (
                str(row[0]), str(row[1]), int(row[2]), str(row[3]).strip(), str(row[4]), str(row[5]),
                [str(item) for item in row[6]], str(row[7]), _timestamp(row[8]), int(row[9]),
            )
            if actual_projection != expected_projection:
                raise MigrationConflict("derived source relation projection diverged")
            return digest(target_payload)
        else:
            raise MigrationRejected("postgres_target_family_unmapped")
        with self.database.connection() as connection:
            row = connection.execute(
                f"SELECT payload,owner_id,application_id,workspace_id,created_at,updated_at,status,revision,"
                f"event_sequence,aggregate_id,expires_at,fingerprint,idempotency_key "
                f"FROM {table} WHERE scope_id=%s AND record_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
                (scope_id, logical_id, owner_id, scope.application_id, scope.workspace_id),
            ).fetchone()
            if row is not None:
                payload_value = row[0]
                expected_created = _payload_created_at(payload_value)
                expected_fingerprint = _valid_fingerprint(
                    payload_value.get("fingerprint") or payload_value.get("request_fingerprint")
                )
                expected_projection = (
                    owner_id, scope.application_id, scope.workspace_id,
                    expected_created, _timestamp(payload_value.get("updated_at")),
                    payload_value.get("status") or payload_value.get("state"),
                    int(payload_value.get("revision", 1)),
                    _payload_event_sequence(family, payload_value),
                    _payload_aggregate_id(family, payload_value, owner_id),
                    _timestamp(payload_value.get("expires_at")), expected_fingerprint,
                    _idempotency_key(payload_value),
                )
                actual_projection = (
                    row[1], row[2], row[3], _timestamp(row[4]), _timestamp(row[5]), row[6], int(row[7]),
                    row[8], row[9], _timestamp(row[10]),
                    None if row[11] is None else str(row[11]).strip(), row[12],
                )
                # `created_at` may be sourced from Firestore's update timestamp
                # only when the source envelope has no durable timestamp field.
                if not _has_durable_created_at(payload_value):
                    expected_projection = (expected_projection[0:3] + (actual_projection[3],)
                                           + expected_projection[4:])
                if actual_projection != expected_projection:
                    raise MigrationConflict("postgres indexed projection diverged")
                if family == "usage_budgets":
                    budget_day = _timestamp(payload_value.get("period_start"))
                    reserved = payload_value.get("reserved") or {}
                    budget_projection = connection.execute(
                        "SELECT budget_day,provider_calls,input_tokens FROM usage_budgets "
                        "WHERE scope_id=%s AND record_id=%s",
                        (scope_id, logical_id),
                    ).fetchone()
                    expected_budget = (
                        None if budget_day is None else budget_day.date(),
                        int(reserved.get("provider_calls", 0)), int(reserved.get("input_tokens", 0)),
                    )
                    if tuple(budget_projection) != expected_budget:
                        raise MigrationConflict("usage budget projection diverged")
            if row is not None and family == "entity_claims":
                payload_value = row[0]
                expected_evidence = {
                    (str(evidence_id), str(payload_value.get("entity_id", "")))
                    for evidence_id in payload_value.get("evidence_ids", ())
                }
                actual_evidence = set(connection.execute(
                    "SELECT evidence_id,entity_id FROM entity_claim_evidence "
                    "WHERE scope_id=%s AND claim_id=%s",
                    (scope_id, logical_id),
                ).fetchall())
                if actual_evidence != expected_evidence:
                    raise MigrationConflict("claim evidence projection diverged")
        return None if row is None else digest(row[0])

    def import_record(self, record: MappedRecord, *, epoch_id: str, generation: int,
                      expected_existing_hash: str | None = None) -> str:
        if record.target_store != "postgres":
            raise MigrationRejected("target_store_mismatch")
        if record.family in GLOBAL_FAMILIES:
            target_hash = self._import_global(
                record, expected_existing_hash, epoch_id=epoch_id, generation=generation
            )
            return target_hash
        family = record.family
        if family not in FAMILY_TABLES | {"memories", "derived_memories", "derived_memory_sources"}:
            raise MigrationRejected("postgres_target_family_unmapped")
        scope_id = PostgresPayloadRepository.scope_id(record.owner_id, record.scope)
        payload = portable(record.payload)
        serialized = PostgresPayloadRepository._json(payload)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO scope_namespaces(scope_id,owner_id,application_id,workspace_id,scope_kind,scope_version) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(scope_id) DO NOTHING",
                (scope_id, record.owner_id, record.scope.application_id, record.scope.workspace_id,
                 record.scope_kind if record.scope_kind in {"private", "shared"} else "private",
                 2),
            )
            namespace = connection.execute(
                "SELECT owner_id,application_id,workspace_id,scope_kind FROM scope_namespaces "
                "WHERE scope_id=%s FOR UPDATE", (scope_id,),
            ).fetchone()
            expected_scope_kind = record.scope_kind if record.scope_kind in {"private", "shared"} else "private"
            if namespace is None or tuple(namespace) != (
                record.owner_id, record.scope.application_id, record.scope.workspace_id,
                expected_scope_kind,
            ):
                raise MigrationConflict("target scope namespace ownership conflict")
            if family in {"memories", "derived_memories"}:
                self._import_memory(
                    connection, record, scope_id, serialized, expected_existing_hash
                )
            elif family == "derived_memory_sources":
                self._import_relation(connection, record, scope_id, serialized, expected_existing_hash)
            elif family == "usage_budgets":
                self._import_usage_budget(connection, record, scope_id, serialized, expected_existing_hash)
            elif family == LEGACY_OPERATION_FAMILY and not _is_receipt_payload(record.payload):
                self._import_legacy_operation(
                    connection, record, scope_id, serialized, expected_existing_hash
                )
            elif family == LEGACY_OPERATION_FAMILY:
                self._import_receipt(connection, record, scope_id, expected_existing_hash)
            else:
                self._import_payload_family(
                    connection, record, scope_id, serialized, expected_existing_hash
                )
                if family == "entity_claims":
                    self._import_claim_evidence(connection, record, scope_id)
            self.control.acknowledge(
                epoch_id=epoch_id, record=record, target_hash=record.logical_hash,
                generation=generation, connection=connection,
            )
        return record.logical_hash

    def _import_global(self, record: MappedRecord, expected_hash: str | None,
                       *, epoch_id: str, generation: int) -> str:
        payload = portable(record.payload)
        with self.database.transaction() as connection:
            if record.family == "domain_registrations":
                module_id, module_version, policy_version = _domain_registration_key(record.payload)
                row = connection.execute(
                    "SELECT payload FROM domain_registrations WHERE module_id=%s AND module_version=%s "
                    "AND policy_version=%s FOR UPDATE", (module_id, module_version, policy_version),
                ).fetchone()
                current = None if row is None else digest(row[0])
                _check_target_version(current, expected_hash, record.logical_hash)
                if current is None:
                    connection.execute(
                        "INSERT INTO domain_registrations(module_id,module_version,policy_version,enabled,payload,created_at) "
                        "VALUES (%s,%s,%s,%s,%s::jsonb,%s)",
                        (module_id, module_version, policy_version, bool(payload.get("enabled", False)),
                         canonical_json(payload), _timestamp(payload.get("created_at")) or datetime.now(UTC)),
                    )
                elif current != record.logical_hash:
                    connection.execute(
                        "UPDATE domain_registrations SET enabled=%s,payload=%s::jsonb "
                        "WHERE module_id=%s AND module_version=%s AND policy_version=%s",
                        (bool(payload.get("enabled", False)), canonical_json(payload),
                         module_id, module_version, policy_version),
                    )
                self.control.acknowledge(
                    epoch_id=epoch_id, record=record, target_hash=record.logical_hash,
                    generation=generation, connection=connection,
                )
                return record.logical_hash

            provider = record.logical_id
            next_available = _required_timestamp(payload.get("next_request_at"))
            updated_at = _timestamp(payload.get("updated_at")) or _version_timestamp(record.source_version)
            revision = int(payload.get("revision", 1))
            row = connection.execute(
                "SELECT next_available_at,revision,updated_at,payload FROM domain_provider_rate_limits "
                "WHERE provider_id=%s FOR UPDATE", (provider,),
            ).fetchone()
            current = None if row is None else (
                digest(row[3]) if row[3] is not None else digest({
                    "provider": provider, "next_request_at": row[0],
                })
            )
            _check_target_version(current, expected_hash, record.logical_hash)
            if row is None:
                connection.execute(
                    "INSERT INTO domain_provider_rate_limits(provider_id,next_available_at,revision,updated_at,payload) "
                    "VALUES (%s,%s,%s,%s,%s::jsonb)",
                    (provider, next_available, revision, updated_at, canonical_json(payload)),
                )
            elif current != record.logical_hash:
                connection.execute(
                    "UPDATE domain_provider_rate_limits SET next_available_at=%s,revision=%s,updated_at=%s,"
                    "payload=%s::jsonb WHERE provider_id=%s",
                    (next_available, revision, updated_at, canonical_json(payload), provider),
                )
            self.control.acknowledge(
                epoch_id=epoch_id, record=record, target_hash=record.logical_hash,
                generation=generation, connection=connection,
            )
            return record.logical_hash

    @staticmethod
    def _import_payload_family(connection, record: MappedRecord, scope_id: str,
                               serialized: str, expected_hash: str | None) -> None:
        family, payload = record.family, portable(record.payload)
        if family not in FAMILY_TABLES:
            raise MigrationRejected("postgres_payload_family_unmapped")
        row = connection.execute(
            f"SELECT payload FROM {family} WHERE scope_id=%s AND record_id=%s FOR UPDATE",
            (scope_id, record.logical_id),
        ).fetchone()
        current = None if row is None else digest(row[0])
        _check_target_version(current, expected_hash, record.logical_hash)
        revision = int(payload.get("revision", 1))
        if revision < 1:
            raise MigrationRejected("record_revision_invalid")
        created_at = _record_created_at(record)
        status = payload.get("status") or payload.get("state")
        expires_at = _timestamp(payload.get("expires_at"))
        fingerprint = _valid_fingerprint(payload.get("fingerprint") or payload.get("request_fingerprint"))
        idempotency_key = _idempotency_key(payload)
        event_sequence = _event_sequence(record)
        aggregate_id = _aggregate_id(record)
        if row is None:
            connection.execute(
                f"INSERT INTO {family}(record_id,scope_id,owner_id,application_id,workspace_id,record_version,"
                "status,revision,event_sequence,aggregate_id,created_at,updated_at,expires_at,fingerprint,"
                "idempotency_key,payload) VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (record.logical_id, scope_id, record.owner_id, record.scope.application_id,
                 record.scope.workspace_id, status, revision, event_sequence, aggregate_id, created_at,
                 _timestamp(payload.get("updated_at")), expires_at, fingerprint, idempotency_key, serialized),
            )
        elif current != record.logical_hash:
            connection.execute(
                f"UPDATE {family} SET status=%s,revision=%s,event_sequence=%s,aggregate_id=%s,created_at=%s,"
                "updated_at=%s,expires_at=%s,fingerprint=%s,idempotency_key=%s,payload=%s::jsonb "
                "WHERE scope_id=%s AND record_id=%s",
                (status, revision, event_sequence, aggregate_id, created_at,
                 _timestamp(payload.get("updated_at")), expires_at, fingerprint, idempotency_key,
                 serialized, scope_id, record.logical_id),
            )

    @staticmethod
    def _import_memory(connection, record: MappedRecord, scope_id: str,
                       serialized: str, expected_hash: str | None) -> None:
        from personal_ai.memory.contracts import DerivedMemory, Memory

        if record.family == "memories":
            item = Memory.model_validate(record.payload)
            stored_payload = item.model_dump(mode="json")
            stored_payload.pop("embedding", None)
            serialized = PostgresPayloadRepository._json(stored_payload)
            row = connection.execute(
                "SELECT payload,embedding FROM memories WHERE scope_id=%s AND record_id=%s FOR UPDATE",
                (scope_id, record.logical_id),
            ).fetchone()
            current = None if row is None else digest(Memory.model_validate({
                **row[0], "embedding": row[1],
            }).model_dump(mode="json"))
            _check_target_version(current, expected_hash, record.logical_hash)
            columns = (
                record.logical_id, scope_id, record.owner_id, record.scope.application_id,
                record.scope.workspace_id, item.memory_type, item.status,
                str(item.source_conversation_id), str(item.source_turn_id),
                [str(value) for value in item.source_message_ids], item.source_fingerprint,
                item.embedding_provider, item.embedding_model, item.embedding_dimensions,
                item.embedding_normalization, item.embedding_document_task,
                item.embedding_query_task, list(item.embedding), item.created_at,
                item.effective_at, serialized,
            )
            if row is None:
                connection.execute(
                    "INSERT INTO memories(record_id,scope_id,owner_id,application_id,workspace_id,memory_type,status,"
                    "source_conversation_id,source_turn_id,source_message_ids,source_fingerprint,embedding_provider,"
                    "embedding_model,embedding_dimensions,embedding_normalization,document_task,query_task,embedding,"
                    "created_at,effective_at,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                    columns,
                )
            elif current != record.logical_hash:
                connection.execute(
                    "UPDATE memories SET memory_type=%s,status=%s,source_conversation_id=%s,source_turn_id=%s,"
                    "source_message_ids=%s,source_fingerprint=%s,embedding_provider=%s,embedding_model=%s,"
                    "embedding_dimensions=%s,embedding_normalization=%s,document_task=%s,query_task=%s,embedding=%s,"
                    "created_at=%s,effective_at=%s,payload=%s::jsonb WHERE scope_id=%s AND record_id=%s",
                    columns[5:] + (scope_id, record.logical_id),
                )
            return

        item = DerivedMemory.model_validate(record.payload)
        stored_payload = item.model_dump(mode="json")
        stored_payload.pop("embedding", None)
        serialized = PostgresPayloadRepository._json(stored_payload)
        row = connection.execute(
            "SELECT payload,embedding FROM derived_memories WHERE scope_id=%s AND record_id=%s FOR UPDATE",
            (scope_id, record.logical_id),
        ).fetchone()
        current = None if row is None else digest(DerivedMemory.model_validate({
            **row[0], "embedding": row[1],
        }).model_dump(mode="json"))
        _check_target_version(current, expected_hash, record.logical_hash)
        values = (
            item.memory_type, item.source_set_identity, item.embedding_provider, item.embedding_model,
            item.embedding_dimensions, item.embedding_normalization, item.embedding_document_task,
            item.embedding_query_task, list(item.embedding), item.created_at, item.effective_at,
            serialized, scope_id, record.logical_id,
        )
        if row is None:
            connection.execute(
                "INSERT INTO derived_memories(record_id,scope_id,owner_id,application_id,workspace_id,memory_type,status,"
                "source_set_identity,embedding_provider,embedding_model,embedding_dimensions,embedding_normalization,"
                "document_task,query_task,embedding,created_at,effective_at,revision,payload) "
                "VALUES (%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s::jsonb)",
                (record.logical_id, scope_id, record.owner_id, record.scope.application_id,
                 record.scope.workspace_id, item.memory_type, item.source_set_identity,
                 item.embedding_provider, item.embedding_model, item.embedding_dimensions,
                 item.embedding_normalization, item.embedding_document_task, item.embedding_query_task,
                 list(item.embedding), item.created_at, item.effective_at, serialized),
            )
        elif current != record.logical_hash:
            connection.execute(
                "UPDATE derived_memories SET memory_type=%s,source_set_identity=%s,embedding_provider=%s,"
                "embedding_model=%s,embedding_dimensions=%s,embedding_normalization=%s,document_task=%s,"
                "query_task=%s,embedding=%s,created_at=%s,effective_at=%s,payload=%s::jsonb "
                "WHERE scope_id=%s AND record_id=%s", values,
            )

    @staticmethod
    def _import_usage_budget(connection, record: MappedRecord, scope_id: str,
                             serialized: str, expected_hash: str | None) -> None:
        payload = portable(record.payload)
        period_start = _required_timestamp(payload.get("period_start"))
        day = period_start.date()
        reserved = payload.get("reserved") or {}
        limits = payload.get("limit") or {}
        calls = int(reserved.get("provider_calls", 0))
        tokens = int(reserved.get("input_tokens", 0))
        call_limit = int(limits.get("provider_calls", calls))
        token_limit = int(limits.get("input_tokens", tokens))
        if min(calls, tokens, call_limit, token_limit) < 0 or calls > call_limit or tokens > token_limit:
            raise MigrationRejected("usage_budget_values_invalid")
        row = connection.execute(
            "SELECT payload FROM usage_budgets WHERE scope_id=%s AND record_id=%s FOR UPDATE",
            (scope_id, record.logical_id),
        ).fetchone()
        current = None if row is None else digest(row[0])
        _check_target_version(current, expected_hash, record.logical_hash)
        status = payload.get("state")
        revision = int(payload.get("revision", 1))
        if revision < 1:
            raise MigrationRejected("record_revision_invalid")
        created_at = datetime.combine(day, datetime.min.time(), UTC)
        expires_at = _timestamp(payload.get("expires_at"))
        if row is None:
            connection.execute(
                "INSERT INTO usage_budgets(record_id,scope_id,owner_id,application_id,workspace_id,"
                "record_version,status,revision,created_at,updated_at,expires_at,budget_day,provider_calls,"
                "input_tokens,payload) VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (record.logical_id, scope_id, record.owner_id, record.scope.application_id,
                 record.scope.workspace_id, status, revision, created_at,
                 _timestamp(payload.get("updated_at")), expires_at, day, calls, tokens, serialized),
            )
        elif current != record.logical_hash:
            connection.execute(
                "UPDATE usage_budgets SET status=%s,revision=%s,created_at=%s,updated_at=%s,expires_at=%s,"
                "budget_day=%s,provider_calls=%s,input_tokens=%s,payload=%s::jsonb "
                "WHERE scope_id=%s AND record_id=%s",
                (status, revision, created_at, _timestamp(payload.get("updated_at")), expires_at,
                 day, calls, tokens, serialized, scope_id, record.logical_id),
            )

    @staticmethod
    def _import_relation(connection, record: MappedRecord, scope_id: str,
                         serialized: str, expected_hash: str | None) -> None:
        payload = portable(record.payload)
        source_id = _id_value(payload.get("source_memory_id"))
        derived_id = _id_value(payload.get("derived_memory_id"))
        if not source_id or not derived_id:
            raise MigrationRejected("derived_source_identity_missing")
        parent = connection.execute(
            "SELECT payload FROM derived_memories WHERE scope_id=%s AND record_id=%s",
            (scope_id, derived_id),
        ).fetchone()
        if parent is None:
            raise MigrationRejected("derived_source_parent_missing")
        parent_payload = parent[0]
        provenance = next(
            (item for item in parent_payload.get("sources", ()) if str(item.get("memory_id")) == source_id),
            None,
        )
        sources = tuple(str(item) for item in parent_payload.get("source_memory_ids", ()))
        if provenance is None or source_id not in sources:
            raise MigrationRejected("derived_source_not_in_parent")
        ordinal = sources.index(source_id) + 1
        created_at = _timestamp(payload.get("created_at"))
        if created_at is None:
            raise MigrationRejected("relation_timestamp_missing")
        row = connection.execute(
            "SELECT source_ordinal,source_fingerprint,source_conversation_id,source_turn_id,"
            "source_message_ids,excerpt,created_at,scope_version,source_payload "
            "FROM derived_memory_sources WHERE scope_id=%s "
            "AND derived_memory_id=%s AND source_memory_id=%s FOR UPDATE",
            (scope_id, derived_id, source_id),
        ).fetchone()
        current = None if row is None else digest(row[8])
        _check_target_version(current, expected_hash, record.logical_hash)
        if row is None:
            connection.execute(
                "INSERT INTO derived_memory_sources(scope_id,derived_memory_id,source_memory_id,source_ordinal,"
                "source_fingerprint,source_conversation_id,source_turn_id,source_message_ids,excerpt,created_at,"
                "source_document_id,scope_version,source_payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (scope_id, derived_id, source_id, ordinal, provenance["source_fingerprint"],
                 str(provenance["source_conversation_id"]), str(provenance["source_turn_id"]),
                 [str(value) for value in provenance["source_message_ids"]], provenance["excerpt"],
                 created_at, record.source_document_id, int(payload.get("scope_version", 1)), serialized),
            )
        elif current != record.logical_hash:
            connection.execute(
                "UPDATE derived_memory_sources SET source_ordinal=%s,source_fingerprint=%s,"
                "source_conversation_id=%s,source_turn_id=%s,source_message_ids=%s,excerpt=%s,"
                "created_at=%s,source_document_id=%s,scope_version=%s,source_payload=%s::jsonb "
                "WHERE scope_id=%s AND derived_memory_id=%s AND source_memory_id=%s",
                (ordinal, provenance["source_fingerprint"],
                 str(provenance["source_conversation_id"]), str(provenance["source_turn_id"]),
                 [str(value) for value in provenance["source_message_ids"]], provenance["excerpt"],
                 created_at, record.source_document_id, int(payload.get("scope_version", 1)), serialized,
                 scope_id, derived_id, source_id),
            )

    @staticmethod
    def _import_legacy_operation(connection, record: MappedRecord, scope_id: str,
                                 serialized: str, expected_hash: str | None) -> None:
        row = connection.execute(
            "SELECT payload FROM legacy_memory_lifecycle_operations WHERE scope_id=%s AND record_id=%s FOR UPDATE",
            (scope_id, record.logical_id),
        ).fetchone()
        current = None if row is None else digest(row[0])
        _check_target_version(current, expected_hash, record.logical_hash)
        created = _record_created_at(record)
        if row is None:
            connection.execute(
                "INSERT INTO legacy_memory_lifecycle_operations(scope_id,record_id,owner_id,application_id,"
                "workspace_id,created_at,payload) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (scope_id, record.logical_id, record.owner_id, record.scope.application_id,
                 record.scope.workspace_id, created, serialized),
            )
        elif current != record.logical_hash:
            connection.execute(
                "UPDATE legacy_memory_lifecycle_operations SET created_at=%s,payload=%s::jsonb "
                "WHERE scope_id=%s AND record_id=%s",
                (created, serialized, scope_id, record.logical_id),
            )

    @staticmethod
    def _import_receipt(connection, record: MappedRecord, scope_id: str,
                        expected_hash: str | None) -> None:
        payload = portable(record.payload)
        serialized = canonical_json(payload)
        keys = ("operation_id", "attempt_id", "fingerprint", "outcome", "execution_deadline")
        if any(not payload.get(key) for key in keys):
            raise MigrationRejected("effect_receipt_incomplete")
        row = connection.execute(
                "SELECT fingerprint,outcome,result_refs,execution_deadline,created_at,payload "
                "FROM memory_lifecycle_operations WHERE scope_id=%s AND operation_id=%s AND attempt_id=%s FOR UPDATE",
                (scope_id, payload["operation_id"], payload["attempt_id"]),
            ).fetchone()
        current = None if row is None else (
            digest(row[5]) if row[5] is not None else digest({
                "unowned_receipt": True,
                "fingerprint": row[0].strip(),
                "outcome": row[1],
                "result_refs": row[2],
                "execution_deadline": row[3],
                "created_at": row[4],
            })
        )
        _check_target_version(current, expected_hash, record.logical_hash)
        if row is None:
            connection.execute(
                "INSERT INTO memory_lifecycle_operations(scope_id,owner_id,application_id,workspace_id,"
                "operation_id,attempt_id,fingerprint,outcome,result_refs,execution_deadline,created_at,payload) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb)",
                (scope_id, record.owner_id, record.scope.application_id, record.scope.workspace_id,
                 payload["operation_id"], payload["attempt_id"], payload["fingerprint"], payload["outcome"],
                 canonical_json(payload.get("result_refs", {})), _required_timestamp(payload["execution_deadline"]),
                 _timestamp(payload.get("created_at")) or _version_timestamp(record.source_version), serialized),
            )
        elif current != record.logical_hash:
            connection.execute(
                "UPDATE memory_lifecycle_operations SET fingerprint=%s,outcome=%s,result_refs=%s::jsonb,"
                "execution_deadline=%s,created_at=%s,payload=%s::jsonb WHERE scope_id=%s "
                "AND operation_id=%s AND attempt_id=%s",
                (payload["fingerprint"], payload["outcome"], canonical_json(payload.get("result_refs", {})),
                 _required_timestamp(payload["execution_deadline"]),
                 _timestamp(payload.get("created_at")) or _version_timestamp(record.source_version), serialized,
                 scope_id, payload["operation_id"], payload["attempt_id"]),
            )

    @staticmethod
    def _import_claim_evidence(connection, record: MappedRecord, scope_id: str) -> None:
        payload = portable(record.payload)
        connection.execute(
            "DELETE FROM entity_claim_evidence WHERE scope_id=%s AND claim_id=%s",
            (scope_id, record.logical_id),
        )
        for evidence_id in payload.get("evidence_ids", ()):
            connection.execute(
                "INSERT INTO entity_claim_evidence(scope_id,owner_id,application_id,workspace_id,"
                "evidence_id,entity_id,claim_id) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (scope_id, record.owner_id, record.scope.application_id, record.scope.workspace_id,
                 str(evidence_id), str(payload.get("entity_id", "")), record.logical_id),
            )

    def delete_record(self, family: str, logical_id: str, owner_id: str,
                      scope: ApplicationScope, *, source_document_id: str | None = None,
                      locator: dict[str, Any] | None = None) -> None:
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        if family == "domain_provider_rate_limits":
            with self.database.transaction() as connection:
                connection.execute("DELETE FROM domain_provider_rate_limits WHERE provider_id=%s", (logical_id,))
            return
        if family == "domain_registrations":
            key = _domain_registration_key_from_logical(logical_id)
            with self.database.transaction() as connection:
                connection.execute(
                    "DELETE FROM domain_registrations WHERE module_id=%s AND module_version=%s AND policy_version=%s",
                    key,
                )
            return
        if family == "derived_memory_sources":
            with self.database.transaction() as connection:
                connection.execute(
                    "DELETE FROM derived_memory_sources WHERE scope_id=%s AND source_document_id=%s",
                    (scope_id, source_document_id or logical_id),
                )
            return
        if family == LEGACY_OPERATION_FAMILY and locator and locator.get("operation_id"):
            with self.database.transaction() as connection:
                connection.execute(
                    "DELETE FROM memory_lifecycle_operations WHERE scope_id=%s AND owner_id=%s "
                    "AND operation_id=%s AND attempt_id=%s",
                    (scope_id, owner_id, locator["operation_id"], locator["attempt_id"]),
                )
            return
        if family == LEGACY_OPERATION_FAMILY:
            table = "legacy_memory_lifecycle_operations"
        else:
            table = family
        if family not in FAMILY_TABLES | {"memories", "derived_memories", "legacy_memory_lifecycle_operations"}:
            raise MigrationRejected("postgres_delete_family_unmapped")
        with self.database.transaction() as connection:
            if family == "entity_claims":
                connection.execute(
                    "DELETE FROM entity_claim_evidence WHERE scope_id=%s AND claim_id=%s",
                    (scope_id, logical_id),
                )
            connection.execute(
                f"DELETE FROM {table} WHERE scope_id=%s AND record_id=%s AND owner_id=%s "
                "AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s",
                (scope_id, logical_id, owner_id, scope.application_id, scope.workspace_id),
            )


class DynamoDBMigrationTarget:
    """Publishes canonical D records and required directories through P10.3 keys."""

    def __init__(self, table) -> None:
        self.table = table

    def logical_hash(
        self, family: str, logical_id: str, owner_id: str, scope: ApplicationScope,
        payload: dict[str, Any] | None = None, *, source_version: str | None = None,
    ) -> str | None:
        from personal_ai.auth.scope import application_scope_context
        from personal_ai.persistence.dynamodb import (
            DynamoDBSummaryRepository,
            _authorized,
            _catalog_key_for,
            _conversation_from_item,
            _conversation_keys_for,
            _job_key,
            _message_from_item,
            _message_key_for,
        )

        with application_scope_context(scope):
            if family == "conversations":
                item = self.table.get(_conversation_keys_for(owner_id, scope, _uuid(logical_id)).meta)
                if item is None:
                    return None
                if not _authorized(item, owner_id, scope):
                    raise MigrationConflict("conversation metadata scope conflict")
                conversation = _conversation_from_item(item)
                catalog_key = _catalog_key_for(
                    owner_id, scope, conversation.id, conversation.updated_at
                )
                catalog = self.table.get(catalog_key)
                if (
                    catalog is None or not _authorized(catalog, owner_id, scope)
                    or catalog.get("conversation_id") != str(conversation.id)
                    or int(catalog.get("revision", -1)) != int(item["revision"])
                    or catalog.get("updated_at") != item.get("updated_at")
                ):
                    raise MigrationConflict("conversation directory projection diverged")
                return digest(_target_logical_payload(family, conversation.model_dump(mode="json")))
            if family == "messages":
                if payload is None:
                    raise ValueError("message payload required for target hash")
                message_id = _id_value(payload.get("id"))
                conversation_id = _id_value(payload.get("conversation_id"))
                if not message_id or not conversation_id:
                    raise ValueError("message target locator required for target hash")
                keys = _conversation_keys_for(owner_id, scope, _uuid(conversation_id))
                locator = self.table.get({"PK": keys.partition, "SK": f"MID#{message_id}"})
                if locator is None:
                    return None
                if not _authorized(locator, owner_id, scope):
                    raise MigrationConflict("message locator scope conflict")
                item = self.table.get({
                    "PK": locator["message_pk"], "SK": locator["message_sk"],
                })
                if item is not None and (
                    item.get("message_id") != str(message_id)
                    or item.get("conversation_id") != str(conversation_id)
                ):
                    raise MigrationConflict("message locator identity conflict")
                if item is None:
                    return None
                if not _authorized(item, owner_id, scope):
                    raise MigrationConflict("message target scope conflict")
                message = _message_from_item(item)
                canonical_key = _message_key_for(
                    owner_id, scope, message.conversation_id, message.created_at, message.id
                )
                if (
                    item.get("PK") != canonical_key["PK"] or item.get("SK") != canonical_key["SK"]
                    or locator.get("message_pk") != canonical_key["PK"]
                    or locator.get("message_sk") != canonical_key["SK"]
                    or locator.get("message_id") != str(message.id)
                    or locator.get("conversation_id") != str(message.conversation_id)
                ):
                    raise MigrationConflict("message access-path projection diverged")
                return digest(_target_logical_payload(family, message.model_dump(mode="json")))
            if family == "conversation_summaries":
                if payload is None:
                    raise ValueError("summary target locator required for target hash")
                from personal_ai.persistence.dynamodb import _conversation_keys_for

                summary_id = _uuid(_id_value(payload.get("id")) or "")
                conversation_id = _uuid(_id_value(payload.get("conversation_id")) or "")
                created_at = _timestamp(payload.get("created_at"))
                if created_at is None:
                    raise ValueError("summary target locator timestamp invalid")
                keys = _conversation_keys_for(owner_id, scope, conversation_id)
                item = self.table.get({
                    "PK": keys.partition, "SK": f"SUM#{_ddb_timestamp(created_at)}#{summary_id}",
                })
                if item is None:
                    return None
                loaded = DynamoDBSummaryRepository(self.table)._load(
                    item, keys.partition, __import__("time").monotonic() + 5
                )
                return digest(_target_logical_payload(family, loaded.model_dump(mode="json")))
            if family == "memory_lifecycle_jobs":
                from personal_ai.memory.lifecycle import MemoryJob
                from personal_ai.persistence.dynamodb import (
                    _authorized,
                    _job_catalog_item,
                    _job_id_locator,
                    _job_item,
                    _namespace_puts,
                    _owner_job_catalog_item,
                )

                item = self.table.get(_job_key(scope, _uuid(logical_id), owner_id))
                if item is None:
                    return None
                current = MemoryJob.model_validate(json.loads(item["payload"]))
                directories = (
                    _job_id_locator(current, scope),
                    _job_catalog_item(current, scope),
                    _owner_job_catalog_item(current, scope),
                )
                if _namespace_puts(self.table, owner_id, scope):
                    raise MigrationConflict("job namespace directory missing")
                for expected in directories:
                    actual = self.table.get({"PK": expected["PK"], "SK": expected["SK"]})
                    if actual != expected:
                        raise MigrationConflict("job directory projection diverged")
                publication = _job_item(current, revision=int(item["revision"]))
                for field in ("PUBPK", "PUBSK", "record_pk", "record_sk", "publish_after"):
                    if item.get(field) != publication.get(field):
                        raise MigrationConflict("job publication projection diverged")
                return digest(_target_logical_payload(family, current.model_dump(mode="json")))
            if family == "rate_limit_windows":
                epoch = int(logical_id)
                item = self.table.get({
                    "PK": f"OWNER#{_ddb_b64(owner_id)}", "SK": f"RATE#{epoch}",
                })
                if item is None:
                    return None
                return digest({
                    "request_count": int(item["request_count"]),
                    "window_start": item["window_start"],
                    "expires_at": item["expires_at"],
                    "policy_version": item.get("policy_version"),
                })
        raise MigrationRejected("dynamodb_target_family_unmapped")

    def import_record(self, record: MappedRecord, expected_existing_hash: str | None = None) -> str:
        from personal_ai.auth.scope import application_scope_context

        with application_scope_context(record.scope):
            if record.family == "conversations":
                self._import_conversation(record, expected_existing_hash)
            elif record.family == "messages":
                self._import_message(record, expected_existing_hash)
            elif record.family == "conversation_summaries":
                self._import_summary(record, expected_existing_hash)
            elif record.family == "memory_lifecycle_jobs":
                self._import_job(record, expected_existing_hash)
            elif record.family == "rate_limit_windows":
                self._import_counter(record, expected_existing_hash)
            else:
                raise MigrationRejected("dynamodb_target_family_unmapped")
        return record.logical_hash

    def _import_conversation(self, record: MappedRecord, expected_hash: str | None) -> None:
        from personal_ai.entities import Conversation
        from personal_ai.persistence.dynamodb import (
            DynamoDBConversationRepository,
            _conversation_from_item,
        )

        if record.payload.get("context_preparation_id") or record.payload.get("context_preparation_started_at"):
            raise MigrationRejected("conversation_preparation_not_drained")
        value = Conversation.model_validate(record.payload)
        repo = DynamoDBConversationRepository(self.table)
        existing = repo._metadata_item_for(record.owner_id, value.id, record.scope)
        if existing is None:
            _check_target_version(None, expected_hash, record.logical_hash)
            repo.create(value)
            return
        current = _conversation_from_item(existing)
        current_hash = digest(_target_logical_payload("conversations", current.model_dump(mode="json")))
        _check_target_version(current_hash, expected_hash, record.logical_hash)
        if current_hash == record.logical_hash:
            return
        replacement = value.model_copy(update={"persistence_revision": int(existing["revision"])})
        repo.update(replacement)

    def _import_message(self, record: MappedRecord, expected_hash: str | None) -> None:
        from personal_ai.entities import Message
        from personal_ai.persistence.dynamodb import (
            DynamoDBConversationRepository,
            _authorized,
            _catalog_key_for,
            _conversation_keys_for,
            _message_from_item,
            _message_item,
            _message_key_for,
            _message_locator,
            _update,
        )

        value = Message.model_validate(record.payload)
        conversation_repo = DynamoDBConversationRepository(self.table)
        conversation = conversation_repo.get(owner_id=record.owner_id, conversation_id=value.conversation_id)
        canonical_key = _message_key_for(
            record.owner_id, record.scope, value.conversation_id, value.created_at, value.id
        )
        current = self.table.get(canonical_key)
        locator_key = _conversation_keys_for(
            record.owner_id, record.scope, value.conversation_id
        ).partition
        locator_key = {"PK": locator_key, "SK": f"MID#{value.id}"}
        existing_locator = self.table.get(locator_key)
        if current is None and existing_locator is not None:
            if not _authorized(existing_locator, record.owner_id, record.scope):
                raise MigrationConflict("message locator scope conflict")
            previous_key = {
                "PK": existing_locator["message_pk"], "SK": existing_locator["message_sk"],
            }
            previous = self.table.get(previous_key)
            if previous is None or not _authorized(previous, record.owner_id, record.scope):
                raise MigrationConflict("message locator target missing")
            if (
                previous.get("message_id") != str(value.id)
                or previous.get("conversation_id") != str(value.conversation_id)
            ):
                raise MigrationConflict("message locator identity conflict")
            previous_hash = digest(_target_logical_payload(
                "messages", _message_from_item(previous).model_dump(mode="json")
            ))
            _check_target_version(previous_hash, expected_hash, record.logical_hash)
            metadata_key = _conversation_keys_for(
                record.owner_id, record.scope, value.conversation_id
            ).meta
            metadata = self.table.get(metadata_key)
            revision = int(metadata["revision"])
            catalog_key = _catalog_key_for(
                record.owner_id, record.scope, value.conversation_id, conversation.updated_at
            )
            replacement_locator = _message_locator(value, record.scope)
            self.table.transact([
                {"Delete": {
                    "Key": _low_marshal(previous_key),
                    "ConditionExpression": "owner_id=:owner",
                    "ExpressionAttributeValues": _low_marshal({":owner": record.owner_id}),
                }},
                {"Put": {
                    "Item": _low_marshal(_message_item(value, record.scope)),
                    "ConditionExpression": "attribute_not_exists(PK)",
                }},
                {"Put": {
                    "Item": _low_marshal(replacement_locator),
                    "ConditionExpression": "message_pk=:old_pk AND message_sk=:old_sk",
                    "ExpressionAttributeValues": _low_marshal({
                        ":old_pk": previous_key["PK"], ":old_sk": previous_key["SK"],
                    }),
                }},
                _update(
                    metadata_key, "SET #revision=:next",
                    names={"#revision": "revision", "#owner": "owner_id"},
                    values={":next": revision + 1, ":old": revision, ":owner": record.owner_id},
                    condition="#owner=:owner AND revision=:old AND attribute_not_exists(effect_guard)",
                ),
                _update(
                    catalog_key, "SET #revision=:next",
                    names={"#revision": "revision", "#owner": "owner_id"},
                    values={":next": revision + 1, ":owner": record.owner_id},
                    condition="#owner=:owner",
                ),
            ])
            return
        if current is not None:
            current_message = _message_from_item(current)
            current_hash = digest(_target_logical_payload("messages", current_message.model_dump(mode="json")))
            _check_target_version(current_hash, expected_hash, record.logical_hash)
            if current_hash == record.logical_hash:
                return
            metadata_key = _conversation_keys_for(record.owner_id, record.scope, value.conversation_id).meta
            metadata = self.table.get(metadata_key)
            revision = int(metadata["revision"])
            catalog_key = _catalog_key_for(
                record.owner_id, record.scope, value.conversation_id, conversation.updated_at
            )
            operations = [
                {"Put": {"TableName": self.table.table_name, "Item": _low_marshal(_message_item(value, record.scope))}},
                {"Put": {"TableName": self.table.table_name, "Item": _low_marshal(_message_locator(value, record.scope))}},
                _update(
                    metadata_key, "SET #revision=:next",
                    names={"#revision": "revision", "#owner": "owner_id"},
                    values={":next": revision + 1, ":old": revision, ":owner": record.owner_id},
                    condition="#owner=:owner AND revision=:old AND attribute_not_exists(effect_guard)",
                ),
                _update(
                    catalog_key, "SET #revision=:next",
                    names={"#revision": "revision", "#owner": "owner_id"},
                    values={":next": revision + 1, ":owner": record.owner_id},
                    condition="#owner=:owner",
                ),
            ]
            self.table.transact(operations)
            return
        _check_target_version(None, expected_hash, record.logical_hash)
        metadata_key = _conversation_keys_for(record.owner_id, record.scope, value.conversation_id).meta
        metadata = self.table.get(metadata_key)
        if metadata is None:
            raise MigrationRejected("message_conversation_missing")
        revision = int(metadata["revision"])
        catalog_key = _catalog_key_for(
            record.owner_id, record.scope, value.conversation_id, conversation.updated_at
        )
        self.table.transact([
            {"Put": {"TableName": self.table.table_name,
                     "Item": _low_marshal(_message_item(value, record.scope)),
                     "ConditionExpression": "attribute_not_exists(PK)"}},
            {"Put": {"TableName": self.table.table_name,
                     "Item": _low_marshal(_message_locator(value, record.scope)),
                     "ConditionExpression": "attribute_not_exists(PK)"}},
            _update(
                metadata_key, "SET #revision=:next",
                names={"#revision": "revision", "#owner": "owner_id"},
                values={":next": revision + 1, ":old": revision, ":owner": record.owner_id},
                condition="#owner=:owner AND revision=:old AND attribute_not_exists(effect_guard) "
                          "AND attribute_not_exists(context_preparation_id)",
            ),
            _update(
                catalog_key, "SET #revision=:next",
                names={"#revision": "revision", "#owner": "owner_id"},
                values={":next": revision + 1, ":owner": record.owner_id},
                condition="#owner=:owner",
            ),
        ])

    def _import_summary(self, record: MappedRecord, expected_hash: str | None) -> None:
        from personal_ai.context.contracts import ConversationSummary
        from personal_ai.persistence.dynamodb import (
            DynamoDBSummaryRepository,
            _conversation_keys_for,
            _ddb_timestamp,
        )

        value = ConversationSummary.model_validate(record.payload)
        keys = _conversation_keys_for(record.owner_id, record.scope, value.conversation_id)
        summary_key = {"PK": keys.partition, "SK": f"SUM#{_ddb_timestamp(value.created_at)}#{value.id}"}
        existing = self.table.get(summary_key)
        repo = DynamoDBSummaryRepository(self.table)
        if existing is None:
            _check_target_version(None, expected_hash, record.logical_hash)
            repo.create(value)
            return
        loaded = repo._load(existing, keys.partition, __import__("time").monotonic() + 5)
        current_hash = digest(_target_logical_payload("conversation_summaries", loaded.model_dump(mode="json")))
        _check_target_version(current_hash, expected_hash, record.logical_hash)
        if current_hash == record.logical_hash:
            return
        raise MigrationConflict("append_only_summary_version_changed")

    def _import_job(self, record: MappedRecord, expected_hash: str | None) -> None:
        from personal_ai.memory.lifecycle import MemoryJob
        from personal_ai.persistence.dynamodb import DynamoDBMemoryJobRepository, _job_key

        job = MemoryJob.model_validate(record.payload)
        repo = DynamoDBMemoryJobRepository(self.table)
        key = _job_key(record.scope, job.id, record.owner_id)
        existing = self.table.get(key)
        if existing is None:
            _check_target_version(None, expected_hash, record.logical_hash)
            repo.create_job(job)
            return
        current = MemoryJob.model_validate(json.loads(existing["payload"]))
        current_hash = digest(_target_logical_payload("memory_lifecycle_jobs", current.model_dump(mode="json")))
        _check_target_version(current_hash, expected_hash, record.logical_hash)
        if current_hash == record.logical_hash:
            return
        repo._save_job(existing, job, int(existing["revision"]), remove_publication=True)

    def _import_counter(self, record: MappedRecord, expected_hash: str | None) -> None:
        from personal_ai.persistence.dynamodb import _b64, _timestamp

        if record.scope.application_id != "personal_ai" or record.scope.workspace_id is not None:
            raise MigrationRejected("counter_scope_invalid")
        epoch = int(record.logical_id)
        expires = record.payload.get("expires_at")
        window = record.payload.get("window_start")
        if not isinstance(expires, datetime) or not isinstance(window, datetime):
            raise MigrationRejected("counter_expiry_invalid")
        item = {
            "PK": f"OWNER#{_b64(record.owner_id)}",
            "SK": f"RATE#{epoch}",
            "kind": "request-window",
            "owner_id": record.owner_id,
            "request_count": int(record.payload.get("request_count", 0)),
            "window_start": _timestamp(window),
            "expires_at": _timestamp(expires),
            "policy_version": record.payload.get("policy_version", "request-rate-v1"),
        }
        if item["request_count"] < 0:
            raise MigrationRejected("counter_value_invalid")
        current = self.table.get({"PK": item["PK"], "SK": item["SK"]})
        current_hash = None if current is None else digest({
            "request_count": int(current["request_count"]),
            "window_start": current["window_start"],
            "expires_at": current["expires_at"],
            "policy_version": current.get("policy_version"),
        })
        _check_target_version(current_hash, expected_hash, record.logical_hash)
        if current_hash != record.logical_hash:
            self.table.client.put_item(
                TableName=self.table.table_name,
                Item=_low_marshal(item),
            )

    def delete_record(self, family: str, logical_id: str, owner_id: str, scope: ApplicationScope,
                      *, payload: dict[str, Any] | None = None) -> None:
        from personal_ai.persistence.dynamodb import (
            _b64,
            _conversation_from_item,
            _conversation_keys_for,
            _job_key,
            _message_key_for,
            _namespace,
            _timestamp,
        )

        if family == "rate_limit_windows":
            key = {"PK": f"OWNER#{_b64(owner_id)}", "SK": f"RATE#{int(logical_id)}"}
            self.table.client.delete_item(TableName=self.table.table_name, Key=_low_marshal(key))
            return
        if family == "messages":
            if payload is None:
                raise ValueError("message target locator required for deletion")
            conversation_id = _uuid(payload.get("conversation_id"))
            message_id = _uuid(logical_id)
            created_at = _required_timestamp(payload.get("created_at"))
            key = _message_key_for(owner_id, scope, conversation_id, created_at, message_id)
            self.table.client.delete_item(TableName=self.table.table_name, Key=_low_marshal(key))
            self.table.client.delete_item(
                TableName=self.table.table_name,
                Key=_low_marshal({"PK": key["PK"], "SK": f"MID#{message_id}"}),
            )
            meta_key = _conversation_keys_for(owner_id, scope, conversation_id).meta
            metadata = self.table.get(meta_key)
            if metadata is not None:
                revision = int(metadata["revision"])
                conversation = _conversation_from_item(metadata)
                catalog_key = {
                    "PK": f"{_namespace(scope, owner_id)}#CATALOG",
                    "SK": f"CONV#{_timestamp(conversation.updated_at)}#{conversation.id}",
                }
                from personal_ai.persistence.dynamodb import _update

                self.table.transact([
                    _update(
                        meta_key, "SET #revision=:next",
                        names={"#revision": "revision", "#owner": "owner_id"},
                        values={":next": revision + 1, ":old": revision, ":owner": owner_id},
                        condition="#owner=:owner AND revision=:old",
                    ),
                    _update(
                        catalog_key, "SET #revision=:next",
                        names={"#revision": "revision", "#owner": "owner_id"},
                        values={":next": revision + 1, ":owner": owner_id},
                        condition="#owner=:owner",
                    ),
                ])
            return
        if family == "memory_lifecycle_jobs":
            key = _job_key(scope, _uuid(logical_id), owner_id)
            self.table.client.delete_item(TableName=self.table.table_name, Key=_low_marshal(key))
            self.table.client.delete_item(
                TableName=self.table.table_name,
                Key=_low_marshal({"PK": f"JOBID#{logical_id}", "SK": "LOCATOR"}),
            )
            self.table.client.delete_item(
                TableName=self.table.table_name,
                Key=_low_marshal({"PK": f"{_namespace(scope, owner_id)}#CATALOG", "SK": f"JOB#{logical_id}"}),
            )
            self.table.client.delete_item(
                TableName=self.table.table_name,
                Key=_low_marshal({
                    "PK": f"OWNER#{_b64(owner_id)}",
                    "SK": f"JOB#{_b64([scope.application_id, scope.workspace_id])}#{logical_id}",
                }),
            )
            return
        if family == "conversation_summaries":
            if payload is None:
                raise ValueError("summary target locator required for deletion")
            summary_id = _uuid(logical_id)
            conversation_id = _uuid(payload.get("conversation_id"))
            created_at = _required_timestamp(payload.get("created_at"))
            keys = _conversation_keys_for(owner_id, scope, conversation_id)
            prefix = f"SC#{summary_id}#"
            chunks = self.table.query(
                partition=keys.partition, sort_prefix=prefix,
                deadline=__import__("time").monotonic() + 5,
            )
            for offset in range(0, len(chunks), 25):
                self.table.transact([
                    {"Delete": {"TableName": self.table.table_name,
                                "Key": _low_marshal({"PK": keys.partition, "SK": item["SK"]})}}
                    for item in chunks[offset:offset + 25]
                ])
            header = {"PK": keys.partition, "SK": f"SUM#{_ddb_timestamp(created_at)}#{summary_id}"}
            self.table.client.delete_item(TableName=self.table.table_name, Key=_low_marshal(header))
            return
        if family == "conversations":
            key = _conversation_keys_for(owner_id, scope, _uuid(logical_id)).meta
            current = self.table.get(key)
            if current is None:
                return
            conversation = _conversation_from_item(current)
            history = self.table.query(
                partition=key["PK"], sort_prefix="MSG#",
                deadline=__import__("time").monotonic() + 5, limit=1,
            )
            if history:
                raise MigrationConflict("conversation still has messages; delete dependents first")
            self.table.client.delete_item(TableName=self.table.table_name, Key=_low_marshal(key))
            self.table.client.delete_item(
                TableName=self.table.table_name,
                Key=_low_marshal({
                    "PK": f"{_b64([owner_id, scope.application_id, scope.workspace_id])}#CATALOG",
                    "SK": f"CONV#{_timestamp(conversation.updated_at)}#{conversation.id}",
                }),
            )
            return
        raise MigrationRejected("dynamodb_delete_family_unmapped")


MIGRATION_ORDER = (
    "conversations",
    "messages",
    "conversation_summaries",
    "memories",
    "derived_memories",
    "derived_memory_sources",
    "memory_lifecycle_states",
    "memory_lifecycle_events",
    "memory_lifecycle_operations",
    "research_sessions",
    "research_request_keys",
    "iterative_research_runs",
    "iterative_research_request_keys",
    "canonical_entities",
    "entity_aliases",
    "entity_claims",
    "entity_matches",
    "decision_snapshots",
    "decision_evidence_snapshots",
    "candidate_evaluations",
    "domain_registrations",
    "domain_claim_extensions",
    "provider_observations",
    "domain_comparison_views",
    "domain_lookup_idempotency",
    "itinerary_proposals",
    "booking_document_extractions",
    "identity_mappings",
    "account_lifecycle_requests",
    "audit_events",
    "usage_budgets",
    "domain_provider_rate_limits",
    "memory_lifecycle_jobs",
    "rate_limit_windows",
)
DELETE_ORDER = (
    "conversation_summaries",
    "messages",
    "memory_lifecycle_jobs",
    "rate_limit_windows",
    "conversations",
    "derived_memory_sources",
    "derived_memories",
    "memory_lifecycle_events",
    "memory_lifecycle_states",
    "memory_lifecycle_operations",
    "memories",
    "candidate_evaluations",
    "entity_matches",
    "decision_evidence_snapshots",
    "domain_claim_extensions",
    "provider_observations",
    "domain_comparison_views",
    "domain_lookup_idempotency",
    "decision_snapshots",
    "entity_aliases",
    "entity_claims",
    "canonical_entities",
    "research_request_keys",
    "iterative_research_request_keys",
    "iterative_research_runs",
    "research_sessions",
    "itinerary_proposals",
    "booking_document_extractions",
    "identity_mappings",
    "account_lifecycle_requests",
    "audit_events",
    "usage_budgets",
    "domain_registrations",
    "domain_provider_rate_limits",
)


def run_migration(
    *,
    source: FirestoreMigrationSource,
    control: PostgresMigrationControl,
    postgres_target: PostgresMigrationTarget,
    dynamodb_target: DynamoDBMigrationTarget,
    epoch_id: str,
    database_id: str = "(default)",
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_records: int = MAX_MIGRATION_RECORDS,
    dry_run: bool = False,
    final_delta: bool = False,
    writers_frozen: bool = False,
    review_expired_counters: bool = False,
) -> MigrationResult:
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError("migration_batch_size_invalid")
    if not 1 <= max_records <= MAX_MIGRATION_RECORDS:
        raise ValueError("migration_record_bound_invalid")
    if final_delta and not writers_frozen:
        raise ValueError("final_delta_requires_writer_freeze_assertion")

    families = MIGRATION_ORDER
    config_fingerprint = digest({
        "families": families,
        "dynamodb_families": sorted(DYNAMODB_FAMILIES),
        "schema": MIGRATION_SCHEMA_VERSION,
        "batch_size": batch_size,
    })
    per_family: dict[str, Counter] = {
        family: Counter() for family in families
    }
    rejected: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    reconciliation: dict[str, dict[str, str | int]] = {}
    owners: set[str] = set()
    manifest = hashlib.sha256()
    total_records = 0
    generations: dict[str, int] = {}

    def note_rejection(family: str, snapshot: SourceSnapshot, code: str, *, is_conflict=False,
                       generation: int | None = None) -> None:
        safe_doc_id = snapshot.document_id[:512]
        issue = {"family": family, "document_id": safe_doc_id, "code": code}
        (conflicts if is_conflict else rejected).append(issue)
        per_family[family]["rejected" if not is_conflict else "conflicts"] += 1
        if not dry_run and generation is not None:
            version = "unknown"
            try:
                version = _source_version(snapshot)
            except MigrationRejected:
                pass
            try:
                source_hash = digest(snapshot.data)
            except MigrationRejected:
                source_hash = digest({"document_id": safe_doc_id, "version": version, "rejection": code})
            control.reject(
                epoch_id=epoch_id, family=family, source_id=safe_doc_id,
                logical_id=_id_value(snapshot.data.get("id")) or safe_doc_id,
                source_version=version, source_hash=source_hash,
                generation=generation, code=code,
            )

    def target_for(record: MappedRecord):
        return dynamodb_target if record.target_store == "dynamodb" else postgres_target

    with (control.epoch_lock(epoch_id) if not dry_run else _null_context()):
        if not dry_run:
            control.begin_epoch(
                epoch_id=epoch_id,
                project_id=source.project_id,
                database_id=database_id,
                config_fingerprint=config_fingerprint,
                final_delta=final_delta,
            )
        for family in families:
            generation, cursor = (0, None) if dry_run else control.start_family(epoch_id, family)
            generations[family] = generation
            scanned_family = 0
            while True:
                page = source.scan_page(family, cursor, batch_size)
                if not page:
                    break
                page_applied = page_rejected = 0
                for snapshot in page:
                    total_records += 1
                    scanned_family += 1
                    per_family[family]["source"] += 1
                    if total_records > max_records:
                        raise MigrationRejected("migration_inventory_bound_exceeded")
                    try:
                        raw_version = _source_version(snapshot)
                    except MigrationRejected as error:
                        raw_version = "unknown"
                        source_hash = digest({
                            "document_id": snapshot.document_id,
                            "version": raw_version,
                            "rejection": error.code,
                        })
                        manifest.update(
                            f"{family}\0{snapshot.document_id}\0{raw_version}\0{source_hash}\n".encode()
                        )
                        note_rejection(
                            family, snapshot, error.code,
                            generation=None if dry_run else generation,
                        )
                        page_rejected += 1
                        continue
                    try:
                        source_hash = digest(snapshot.data)
                    except MigrationRejected:
                        source_hash = digest({
                            "document_id": snapshot.document_id,
                            "version": raw_version,
                            "rejection": "unsupported_source_value",
                        })
                    manifest.update(
                        f"{family}\0{snapshot.document_id}\0{raw_version}\0{source_hash}\n".encode()
                    )
                    source_owner = _id_value(snapshot.data.get("owner_id"))
                    if source_owner:
                        owners.add(source_owner)
                    try:
                        record = map_source_record(
                            source, family, snapshot, known_owners=owners
                        )
                        per_family[family]["mapped"] += 1
                        per_family[family]["bytes"] += record.estimated_bytes
                        if record.scope_kind == "expired-disposition":
                            if not review_expired_counters:
                                raise MigrationRejected("expired_counter_disposition_requires_review")
                            per_family[family]["disposed"] += 1
                            if not dry_run:
                                control.dispose(
                                    epoch_id=epoch_id, record=record, generation=generation,
                                    code="expired_unattributed_counter_operator_disposition",
                                )
                            page_applied += 1
                            continue
                        if dry_run:
                            continue

                        prior = control.prior_record(epoch_id, family, snapshot.document_id)
                        target = target_for(record)
                        old_hash = None if prior is None else prior[4]
                        old_status = None if prior is None else prior[5]
                        expected = old_hash if old_status == "applied" or (
                            old_status == "rejected" and old_hash and old_hash.strip("0")
                        ) else None
                        current_hash = _target_hash(target, record)
                        if old_status == "applied" and record.source_hash == prior[3]:
                            if current_hash != old_hash:
                                raise MigrationConflict("migration-owned target no longer matches prior hash")
                            control.acknowledge(
                                epoch_id=epoch_id, record=record, target_hash=old_hash,
                                generation=generation,
                            )
                            per_family[family]["unchanged"] += 1
                            page_applied += 1
                            continue
                        result_hash = target.import_record(
                            record,
                            expected_existing_hash=expected,
                        ) if record.target_store == "dynamodb" else target.import_record(
                            record, epoch_id=epoch_id, generation=generation,
                            expected_existing_hash=expected,
                        )
                        if result_hash != record.logical_hash:
                            raise MigrationConflict("target logical hash differs from source mapping")
                        if record.target_store == "dynamodb":
                            control.acknowledge(
                                epoch_id=epoch_id, record=record, target_hash=result_hash,
                                generation=generation,
                            )
                        per_family[family]["applied"] += 1
                        page_applied += 1
                    except MigrationConflict as error:
                        note_rejection(
                            family, snapshot, _safe_error_code(error), is_conflict=True,
                            generation=None if dry_run else generation,
                        )
                        page_rejected += 1
                    except MigrationRejected as error:
                        note_rejection(
                            family, snapshot, error.code, generation=None if dry_run else generation
                        )
                        page_rejected += 1
                    except (ValueError, TypeError, KeyError) as error:
                        # Reports carry a stable category, never source values or
                        # provider/database exception strings.
                        code = _safe_error_code(error)
                        note_rejection(
                            family, snapshot, code, generation=None if dry_run else generation
                        )
                        page_rejected += 1
                    except Exception as error:
                        sqlstate = getattr(error, "sqlstate", None)
                        if sqlstate == "23505":
                            note_rejection(
                                family, snapshot, "duplicate_target_logical_identity",
                                is_conflict=True, generation=None if dry_run else generation,
                            )
                            page_rejected += 1
                        elif sqlstate == "23503":
                            note_rejection(
                                family, snapshot, "target_reference_conflict",
                                generation=None if dry_run else generation,
                            )
                            page_rejected += 1
                        elif sqlstate == "23514":
                            note_rejection(
                                family, snapshot, "target_constraint_rejected",
                                generation=None if dry_run else generation,
                            )
                            page_rejected += 1
                        elif isinstance(sqlstate, str) and sqlstate.startswith("22"):
                            note_rejection(
                                family, snapshot, "target_data_rejected",
                                generation=None if dry_run else generation,
                            )
                            page_rejected += 1
                        else:
                            raise
                cursor = page[-1].document_id
                if not dry_run:
                    control.checkpoint_page(
                        epoch_id=epoch_id, family=family, generation=generation,
                        last_source_document_id=cursor, scanned=len(page),
                        applied=page_applied, rejected=page_rejected,
                    )
                if len(page) < batch_size:
                    break
            if not dry_run:
                control.finish_family(epoch_id, family, generation)
                per_family[family]["source"] = control.generation_disposition_count(
                    epoch_id, family, generation
                )

        if final_delta and not dry_run:
            for family in DELETE_ORDER:
                cursor = None
                while True:
                    missing_page = control.missing_page(
                        epoch_id, family, generations[family], cursor, batch_size
                    )
                    if not missing_page:
                        break
                    for missing in missing_page:
                        source_id, logical_id, target_store, source_version, _source_hash, _ledger_target_hash, owner, app, workspace, locator = missing
                        if _ledger_target_hash.strip("0") == "" or not owner:
                            control.mark_deleted(epoch_id, family, source_id)
                            per_family[family]["source_deleted"] += 1
                            continue
                        scope = ApplicationScope(application_id=app, workspace_id=workspace)
                        try:
                            target = dynamodb_target if target_store == "dynamodb" else postgres_target
                            current_hash = target.logical_hash(
                                family, logical_id, owner, scope, locator or {},
                                source_version=source_version,
                            )
                            if current_hash is not None and current_hash != _ledger_target_hash:
                                raise MigrationConflict("target diverged before source deletion")
                            if current_hash is not None:
                                target.delete_record(
                                    family, logical_id, owner, scope,
                                    **({"payload": locator} if target_store == "dynamodb" else {
                                        "source_document_id": source_id,
                                        "locator": locator,
                                    }),
                                )
                            control.mark_deleted(epoch_id, family, source_id)
                            per_family[family]["source_deleted"] += 1
                        except Exception as error:  # noqa: BLE001 - cloud deletion failures block parity
                            conflicts.append({
                                "family": family,
                                "document_id": source_id,
                                "code": _safe_error_code(error),
                            })
                            per_family[family]["conflicts"] += 1
                    cursor = missing_page[-1][0]
                    if len(missing_page) < batch_size:
                        break

        if not dry_run:
            for family in families:
                ledger_source_count = control.generation_disposition_count(
                    epoch_id, family, generations[family]
                )
                scan_attempt_count = control.generation_scanned_count(
                    epoch_id, family, generations[family]
                )
                mapped_hasher = hashlib.sha256()
                target_hasher = hashlib.sha256()
                reconciled_count = 0
                applied_count = 0
                if scan_attempt_count < ledger_source_count:
                    conflicts.append({
                        "family": family,
                        "document_id": "__family__",
                        "code": "source_disposition_count_mismatch",
                    })
                    per_family[family]["conflicts"] += 1
                cursor = None
                while True:
                    applied_page = control.applied_records_page(
                        epoch_id, family, generations[family], cursor, batch_size
                    )
                    if not applied_page:
                        break
                    for applied in applied_page:
                        (source_id, logical_id, target_store, source_version,
                         mapped_hash, target_hash, owner, app, workspace, locator) = applied
                        applied_count += 1
                        mapped_hasher.update(
                            f"{source_id}\0{logical_id}\0{mapped_hash}\n".encode()
                        )
                        scope = ApplicationScope(application_id=app, workspace_id=workspace)
                        target = dynamodb_target if target_store == "dynamodb" else postgres_target
                        current_hash = target.logical_hash(
                            family, logical_id, owner, scope, locator or {},
                            source_version=source_version,
                        )
                        target_hasher.update(
                            f"{source_id}\0{logical_id}\0{current_hash or '<missing>'}\n".encode()
                        )
                        if current_hash != mapped_hash or target_hash != mapped_hash:
                            control.mark_conflict(
                                epoch_id, family, source_id, generations[family],
                                "target_reconciliation_mismatch",
                            )
                            conflicts.append({
                                "family": family,
                                "document_id": source_id[:512],
                                "code": "target_reconciliation_mismatch",
                            })
                            per_family[family]["conflicts"] += 1
                        else:
                            reconciled_count += 1
                    cursor = applied_page[-1][0]
                    if len(applied_page) < batch_size:
                        break
                reconciliation[family] = {
                    "source_count": ledger_source_count,
                    "ledger_count": ledger_source_count,
                    "scan_attempt_count": scan_attempt_count,
                    "applied_count": applied_count,
                    "reconciled_count": reconciled_count,
                    "mapped_hash_digest": mapped_hasher.hexdigest(),
                    "target_hash_digest": target_hasher.hexdigest(),
                }

    if not dry_run:
        final_ready = control.finalize(
            epoch_id, final_delta=final_delta, conflict_count=len(conflicts)
        )
        source_digest = control.source_digest(epoch_id, generations)
        stored = control.counts(epoch_id)
        result_counts = {
            family: dict(per_family[family]) | {"ledger": stored.get(family, {})}
            for family in families
        }
    else:
        result_counts = {family: dict(counts) for family, counts in per_family.items()}
    return MigrationResult(
        epoch_id=epoch_id,
        mode="dry-run" if dry_run else ("final-delta" if final_delta else "backfill"),
        counts=result_counts,
        rejected=tuple(rejected),
        conflicts=tuple(conflicts),
        source_digest=source_digest if not dry_run else manifest.hexdigest(),
        reconciliation=reconciliation,
        final_delta_ready=(
            final_delta and not rejected and not conflicts and not dry_run and final_ready
        ),
    )


def _check_target_version(current_hash: str | None, expected_hash: str | None,
                          desired_hash: str) -> None:
    if current_hash == desired_hash:
        return
    if current_hash is None:
        if expected_hash is not None:
            raise MigrationConflict("migration-owned target record disappeared")
        return
    if expected_hash is None:
        raise MigrationConflict("target identity already exists outside this migration")
    if current_hash != expected_hash:
        raise MigrationConflict("target record diverged from last migration-owned version")


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise MigrationRejected("timestamp_without_timezone")
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise MigrationRejected("timestamp_invalid") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise MigrationRejected("timestamp_without_timezone")
        return parsed.astimezone(UTC)
    raise MigrationRejected("timestamp_invalid")


def _required_timestamp(value: Any) -> datetime:
    result = _timestamp(value)
    if result is None:
        raise MigrationRejected("timestamp_missing")
    return result


def _version_timestamp(value: str) -> datetime:
    return _required_timestamp(value)


def _record_created_at(record: MappedRecord) -> datetime:
    return _payload_created_at(record.payload) or _version_timestamp(record.source_version)


def _has_durable_created_at(payload: dict[str, Any]) -> bool:
    return any(payload.get(field) is not None for field in (
        "created_at", "occurred_at", "observed_at", "window_start", "period_start", "updated_at"
    ))


def _payload_created_at(payload: dict[str, Any]) -> datetime | None:
    for field in ("created_at", "occurred_at", "observed_at", "window_start", "period_start", "updated_at"):
        raw = payload.get(field)
        if isinstance(raw, date) and not isinstance(raw, datetime):
            return datetime.combine(raw, datetime.min.time(), UTC)
        value = _timestamp(raw)
        if value is not None:
            return value
    return None


def _valid_fingerprint(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value)
    if len(text_value) != 64 or any(char not in "0123456789abcdef" for char in text_value):
        raise MigrationRejected("fingerprint_invalid")
    return text_value


def _idempotency_key(payload: dict[str, Any]) -> str | None:
    value = payload.get("idempotency_key")
    if value is None:
        return None
    rendered = str(value)
    if not rendered or len(rendered) > 300:
        raise MigrationRejected("idempotency_key_invalid")
    return rendered


def _event_sequence(record: MappedRecord) -> int | None:
    return _payload_event_sequence(record.family, record.payload)


def _payload_event_sequence(family: str, payload: dict[str, Any]) -> int | None:
    value = payload.get("event_sequence", payload.get("sequence"))
    if value is None and family == "memory_lifecycle_events":
        value = int(payload.get("expected_state_version", 0)) + 1
    if value is None:
        return None
    try:
        sequence = int(value)
    except (TypeError, ValueError) as error:
        raise MigrationRejected("event_sequence_invalid") from error
    if sequence < 1:
        raise MigrationRejected("event_sequence_invalid")
    return sequence


def _aggregate_id(record: MappedRecord) -> str | None:
    return _payload_aggregate_id(record.family, record.payload, record.owner_id)


def _payload_aggregate_id(family: str, payload: dict[str, Any], owner_id: str) -> str | None:
    value = payload.get("aggregate_id")
    if value is None and family == "memory_lifecycle_events":
        value = payload.get("memory_id")
    if value is None and family == "audit_events":
        value = payload.get("aggregate_id") or f"account:{owner_id}"
    return None if value is None else str(value)


def _domain_registration_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    module_id = _id_value(payload.get("domain_id"))
    module_version = _id_value(payload.get("field_schema_version"))
    feature = _id_value(payload.get("feature_policy_version"))
    source = _id_value(payload.get("source_policy_version"))
    if not module_id or not module_version or not feature or not source:
        raise MigrationRejected("domain_registration_identity_invalid")
    return module_id, module_version, f"{feature}:{source}"


def _domain_registration_key_from_logical(logical_id: str) -> tuple[str, str, str]:
    try:
        parts = json.loads(logical_id)
    except json.JSONDecodeError as error:
        raise MigrationRejected("domain_registration_identity_invalid") from error
    if not isinstance(parts, list) or len(parts) != 4 or any(not part for part in parts):
        raise MigrationRejected("domain_registration_identity_invalid")
    return str(parts[0]), str(parts[1]), f"{parts[2]}:{parts[3]}"


def _is_receipt_payload(payload: dict[str, Any]) -> bool:
    return all(payload.get(key) is not None for key in (
        "operation_id", "attempt_id", "fingerprint", "outcome", "execution_deadline"
    ))


def _uuid(value: str):
    from uuid import UUID

    return value if isinstance(value, UUID) else UUID(str(value))


def _ddb_timestamp(value: datetime) -> str:
    return _version_timestamp(_timestamp(value).isoformat(timespec="microseconds").replace("+00:00", "Z")).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _ddb_b64(value: str) -> str:
    from personal_ai.persistence.dynamodb import _b64

    return _b64(value)


def _low_marshal(value: dict[str, Any]) -> dict[str, Any]:
    from personal_ai.persistence.dynamodb import _marshal

    return _marshal(value)


def _model(family: str, payload: dict[str, Any]):
    if family == "conversations":
        from personal_ai.entities import Conversation

        return Conversation.model_validate(payload)
    if family == "messages":
        from personal_ai.entities import Message

        return Message.model_validate(payload)
    if family == "conversation_summaries":
        from personal_ai.context.contracts import ConversationSummary

        return ConversationSummary.model_validate(payload)
    raise MigrationRejected("dynamodb_model_unmapped")


def _target_hash(target, record: MappedRecord) -> str | None:
    payload = record.payload
    if record.family in {"derived_memory_sources", LEGACY_OPERATION_FAMILY}:
        payload = _target_locator(record)
    return target.logical_hash(
        record.family, record.logical_id, record.owner_id, record.scope, payload,
        source_version=record.source_version,
    )


def _target_locator(record: MappedRecord) -> dict[str, Any]:
    if record.family == "messages":
        return {
            "conversation_id": str(record.payload.get("conversation_id", "")),
            "created_at": portable(record.payload.get("created_at")),
            "id": record.logical_id,
        }
    if record.family == "conversation_summaries":
        return {
            "conversation_id": str(record.payload.get("conversation_id", "")),
            "created_at": portable(record.payload.get("created_at")),
            "id": record.logical_id,
        }
    if record.family == "derived_memory_sources":
        return {"source_document_id": record.source_document_id}
    if record.family == LEGACY_OPERATION_FAMILY and _is_receipt_payload(record.payload):
        return {
            "receipt": True,
            "operation_id": str(record.payload["operation_id"]),
            "attempt_id": str(record.payload["attempt_id"]),
        }
    return {}


class _null_context:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


def _safe_error_code(error: Exception) -> str:
    if isinstance(error, MigrationRejected):
        return error.code
    if isinstance(error, MigrationConflict):
        return "target_conflict"
    name = error.__class__.__name__
    if name in {"ValidationError", "ValueError", "TypeError", "KeyError"}:
        return "source_record_invalid"
    if name in {"ForeignKeyViolation", "IntegrityError"}:
        return "target_reference_conflict"
    return "target_or_source_operation_failed"
