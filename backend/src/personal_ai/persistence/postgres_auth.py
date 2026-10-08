"""Postgres identity bootstrap and standalone account lifecycle records."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.auth.account_data import (
    AccountDataUnavailable,
    AccountRequestConflict,
    AccountRequestNotFound,
)
from personal_ai.auth.contracts import AuthenticatedPrincipal
from personal_ai.auth.directory import (
    MIGRATION_VERSION,
    IdentityDirectoryUnavailable,
    IdentityMappingConflict,
)
from personal_ai.auth.scope import ApplicationScope, current_application_scope
from personal_ai.persistence.postgres import (
    PostgresDatabase,
    PostgresPayloadRepository,
    _ensure_namespace,
)

_ACCOUNT_SCOPE = ApplicationScope(application_id="personal_ai", workspace_id=None)


def _json(value):
    return PostgresPayloadRepository._json(value)


def _audit_id(owner_id, action, idempotency_key, application_id=None, workspace_id=None):
    namespace = "" if application_id in {None, "personal_ai"} and workspace_id is None else (
        f"\0{application_id or 'personal_ai'}\0{workspace_id or ''}"
    )
    return hashlib.sha256(
        f"{owner_id}\0{action}{namespace}\0{idempotency_key}".encode()
    ).hexdigest()


def _append_audit(
    connection, *, owner_id, audit_id, action, target_type, target_id,
    correlation_id, result, scope=_ACCOUNT_SCOPE, actor_subject=None,
):
    scope_id = _ensure_namespace(connection, owner_id, scope)
    existing = connection.execute(
        "SELECT payload FROM audit_events WHERE scope_id=%s AND record_id=%s FOR UPDATE",
        (scope_id, audit_id),
    ).fetchone()
    if existing is not None:
        return
    aggregate = f"account:{owner_id}"
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"audit:{scope_id}:{aggregate}",),
    )
    sequence = connection.execute(
        "SELECT COALESCE(MAX(event_sequence),0)+1 FROM audit_events "
        "WHERE scope_id=%s AND aggregate_id=%s",
        (scope_id, aggregate),
    ).fetchone()[0]
    now = datetime.now(UTC)
    value = {
        "id": audit_id,
        "actor_subject": actor_subject or owner_id,
        "owner_id": owner_id,
        "action": action,
        "target_type": target_type,
        "target_id": str(target_id),
        "result": result,
        "correlation_id": correlation_id,
        "occurred_at": now.isoformat(),
        "application_id": scope.application_id,
        "workspace_id": scope.workspace_id,
        "scope_version": 2,
    }
    connection.execute(
        "INSERT INTO audit_events(record_id,scope_id,owner_id,application_id,workspace_id,"
        "record_version,status,revision,event_sequence,aggregate_id,created_at,idempotency_key,payload) "
        "VALUES (%s,%s,%s,%s,%s,1,'active',1,%s,%s,%s,%s,%s::jsonb)",
        (
            audit_id, scope_id, owner_id, scope.application_id, scope.workspace_id,
            sequence, aggregate, now, audit_id, _json(value),
        ),
    )


class PostgresPrincipalDirectory:
    """Verified issuer/subject mapping with its bootstrap audit in one transaction."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def ensure_active(self, principal: AuthenticatedPrincipal, *, correlation_id: str) -> None:
        if not principal.authenticated:
            raise IdentityMappingConflict
        try:
            with self.database.transaction() as connection:
                scope_id = _ensure_namespace(connection, principal.owner_id, _ACCOUNT_SCOPE)
                row = connection.execute(
                    "SELECT payload FROM identity_mappings WHERE scope_id=%s AND record_id=%s "
                    "AND owner_id=%s FOR UPDATE",
                    (scope_id, principal.owner_id, principal.owner_id),
                ).fetchone()
                if row is not None:
                    current = row[0]
                    if (
                        current.get("subject") != principal.subject
                        or current.get("issuer") != principal.issuer
                        or current.get("owner_id") != principal.owner_id
                        or current.get("status") != "active"
                    ):
                        raise IdentityMappingConflict
                    return
                now = datetime.now(UTC)
                mapping = {
                    "subject": principal.subject,
                    "owner_id": principal.owner_id,
                    "issuer": principal.issuer,
                    "created_at": now.isoformat(),
                    "status": "active",
                    "migration_version": MIGRATION_VERSION,
                    "application_id": _ACCOUNT_SCOPE.application_id,
                    "workspace_id": None,
                    "scope_version": 2,
                }
                connection.execute(
                    "INSERT INTO identity_mappings(record_id,scope_id,owner_id,application_id,workspace_id,"
                    "record_version,status,revision,created_at,payload) "
                    "VALUES (%s,%s,%s,%s,NULL,1,'active',1,%s,%s::jsonb)",
                    (
                        principal.owner_id, scope_id, principal.owner_id,
                        _ACCOUNT_SCOPE.application_id, now, _json(mapping),
                    ),
                )
                audit_id = hashlib.sha256(
                    f"{principal.issuer}\0{principal.subject}\0principal.bootstrap".encode()
                ).hexdigest()
                _append_audit(
                    connection, owner_id=principal.owner_id, audit_id=audit_id,
                    action="principal.bootstrap", target_type="identity_mapping",
                    target_id=principal.owner_id, correlation_id=correlation_id, result="created",
                )
        except IdentityMappingConflict:
            raise
        except Exception as error:
            raise IdentityDirectoryUnavailable from error

    def active_owner_ids(self, *, limit: int = 2) -> tuple[str, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("owner_limit_invalid")
        try:
            with self.database.connection() as connection:
                rows = connection.execute(
                    "SELECT owner_id FROM identity_mappings WHERE application_id=%s "
                    "AND workspace_id IS NULL AND status='active' ORDER BY owner_id LIMIT %s",
                    (_ACCOUNT_SCOPE.application_id, limit),
                ).fetchall()
            return tuple(row[0] for row in rows)
        except Exception as error:
            raise IdentityDirectoryUnavailable from error


class PostgresAccountLifecycleRepository:
    """P-side deletion intent and audit operations; never performs deletion."""

    def __init__(self, database: PostgresDatabase, runtime_table=None) -> None:
        self.database = database
        self.runtime_table = runtime_table

    @staticmethod
    def _require_standalone():
        scope = current_application_scope()
        if scope.application_id != "personal_ai" or scope.workspace_id is not None:
            raise AccountRequestNotFound

    def close(self):
        return None

    def export_owner(self, owner_id: str, *, max_records: int, max_bytes: int):
        import json
        from time import monotonic

        from personal_ai.auth.account_data import (
            EXPORT_COLLECTIONS,
            MAX_EXPORT_SCAN_RECORDS,
            ExportTooLarge,
            _portable,
        )
        from personal_ai.context.traces import ContextTraceManifest
        from personal_ai.persistence.dynamodb import (
            MAX_CONTEXT_TRACE_RETENTION,
            MAX_CONVERSATION_MESSAGES,
            DynamoDBSummaryRepository,
            _authorized,
            _conversation_from_item,
            _namespace,
        )

        if self.runtime_table is None or max_records < 1 or max_bytes < 1:
            raise AccountDataUnavailable("portable export stores unavailable")
        scope = current_application_scope()
        started_at = datetime.now(UTC)
        collections = {}
        count = 0
        estimated_bytes = 0
        p_revision_max = 0
        p_count = 0
        p_revision_coverage = {}
        p_collection_counts = {}
        p_snapshot_id = None

        def add(collection, document_id, values):
            nonlocal count, estimated_bytes
            if collection not in EXPORT_COLLECTIONS:
                raise AccountDataUnavailable("export collection mapping invalid")
            record = {"document_id": str(document_id), "data": _portable(values)}
            encoded = _json(record).encode("utf-8")
            count += 1
            estimated_bytes += len(encoded) + len(collection.encode("utf-8")) + 4
            if count > max_records or count > MAX_EXPORT_SCAN_RECORDS or estimated_bytes > max_bytes:
                raise ExportTooLarge
            collections.setdefault(collection, []).append(record)

        p_families = (
            "research_sessions", "research_request_keys", "itinerary_proposals",
            "booking_document_extractions", "iterative_research_runs",
            "iterative_research_request_keys", "memory_lifecycle_states",
            "memory_lifecycle_events", "canonical_entities", "entity_aliases",
            "entity_claims", "entity_matches", "decision_snapshots",
            "decision_evidence_snapshots", "candidate_evaluations",
            "domain_claim_extensions", "provider_observations", "domain_comparison_views",
            "domain_lookup_idempotency", "account_lifecycle_requests", "audit_events",
            "identity_mappings", "global_profiles",
        )
        try:
            with self.database.connection(snapshot=True) as connection:
                p_snapshot_id = connection.execute(
                    "SELECT txid_current_snapshot()::text"
                ).fetchone()[0]
                for family in p_families:
                    rows = connection.execute(
                        f"SELECT record_id,payload,revision FROM {family} "
                        "WHERE owner_id=%s AND application_id=%s "
                        "AND workspace_id IS NOT DISTINCT FROM %s ORDER BY record_id LIMIT %s",
                        (owner_id, scope.application_id, scope.workspace_id,
                         MAX_EXPORT_SCAN_RECORDS + 1),
                    ).fetchall()
                    if len(rows) > MAX_EXPORT_SCAN_RECORDS:
                        raise ExportTooLarge
                    p_collection_counts[family] = len(rows)
                    p_revision_coverage[family] = max(
                        (int(row[2] or 0) for row in rows), default=0
                    )
                    for record_id, payload, revision in rows:
                        p_revision_max = max(p_revision_max, int(revision or 0))
                        add(family, record_id, payload)
                        p_count += 1
                budget_rows = connection.execute(
                    "SELECT record_id,owner_id,application_id,workspace_id,record_version,status,"
                    "revision,created_at,expires_at,budget_day,provider_calls,input_tokens "
                    "FROM usage_budgets WHERE owner_id=%s AND application_id=%s "
                    "AND workspace_id IS NOT DISTINCT FROM %s ORDER BY record_id LIMIT %s",
                    (owner_id, scope.application_id, scope.workspace_id,
                     MAX_EXPORT_SCAN_RECORDS + 1),
                ).fetchall()
                if len(budget_rows) > MAX_EXPORT_SCAN_RECORDS:
                    raise ExportTooLarge
                p_collection_counts["usage_budgets"] = len(budget_rows)
                p_revision_coverage["usage_budgets"] = max(
                    (int(row[6] or 0) for row in budget_rows), default=0
                )
                for (
                    record_id, record_owner, app_id, workspace_id, record_version,
                    status, revision, created_at, expires_at, budget_day, provider_calls,
                    input_tokens,
                ) in budget_rows:
                    add("usage_budgets", record_id, {
                        "owner_id": record_owner,
                        "application_id": app_id,
                        "workspace_id": workspace_id,
                        "scope_version": 2,
                        "record_version": record_version,
                        "status": status,
                        "revision": revision,
                        "created_at": created_at,
                        "expires_at": expires_at,
                        "budget_day": budget_day,
                        "provider_calls": provider_calls,
                        "input_tokens": input_tokens,
                    })
                    p_revision_max = max(p_revision_max, int(revision or 0))
                    p_count += 1
                for family in ("memories", "derived_memories"):
                    rows = connection.execute(
                        f"SELECT record_id,payload,embedding FROM {family} "
                        "WHERE owner_id=%s AND application_id=%s "
                        "AND workspace_id IS NOT DISTINCT FROM %s ORDER BY record_id LIMIT %s",
                        (owner_id, scope.application_id, scope.workspace_id,
                         MAX_EXPORT_SCAN_RECORDS + 1),
                    ).fetchall()
                    if len(rows) > MAX_EXPORT_SCAN_RECORDS:
                        raise ExportTooLarge
                    p_collection_counts[family] = len(rows)
                    p_revision_coverage[family] = "identity_set_in_repeatable_read_snapshot"
                    for record_id, payload, embedding in rows:
                        add(family, record_id, {**payload, "embedding": list(embedding)})
                        p_count += 1
                relation_rows = connection.execute(
                    "SELECT ds.derived_memory_id,ds.source_memory_id,d.owner_id,d.application_id,"
                    "d.workspace_id,d.created_at "
                    "FROM derived_memory_sources ds "
                    "JOIN derived_memories d ON d.scope_id=ds.scope_id "
                    "AND d.record_id=ds.derived_memory_id WHERE d.owner_id=%s "
                    "AND d.application_id=%s AND d.workspace_id IS NOT DISTINCT FROM %s "
                    "ORDER BY ds.derived_memory_id,ds.source_ordinal LIMIT %s",
                    (owner_id, scope.application_id, scope.workspace_id,
                     MAX_EXPORT_SCAN_RECORDS + 1),
                ).fetchall()
                if len(relation_rows) > MAX_EXPORT_SCAN_RECORDS:
                    raise ExportTooLarge
                p_collection_counts["derived_memory_sources"] = len(relation_rows)
                p_revision_coverage["derived_memory_sources"] = "parent_revision_in_repeatable_read_snapshot"
                for derived_id, source_id, relation_owner, app_id, workspace_id, created_at in relation_rows:
                    relation_id = hashlib.sha256(
                        f"{relation_owner}:{app_id}:{workspace_id or ''}:{source_id}:{derived_id}".encode()
                    ).hexdigest()
                    values = {
                        "owner_id": relation_owner, "application_id": app_id,
                        "workspace_id": workspace_id, "scope_version": 2,
                        "source_memory_id": source_id, "derived_memory_id": derived_id,
                        "created_at": created_at,
                    }
                    add("derived_memory_sources", relation_id, values)
                    p_count += 1
                receipts = connection.execute(
                    "SELECT operation_id,attempt_id,fingerprint,outcome,result_refs,"
                    "execution_deadline,created_at FROM memory_lifecycle_operations "
                    "WHERE owner_id=%s AND application_id=%s "
                    "AND workspace_id IS NOT DISTINCT FROM %s ORDER BY operation_id,attempt_id LIMIT %s",
                    (owner_id, scope.application_id, scope.workspace_id,
                     MAX_EXPORT_SCAN_RECORDS + 1),
                ).fetchall()
                if len(receipts) > MAX_EXPORT_SCAN_RECORDS:
                    raise ExportTooLarge
                if len(receipts) > MAX_EXPORT_SCAN_RECORDS:
                    raise ExportTooLarge
                p_collection_counts["memory_lifecycle_operations"] = len(receipts)
                p_revision_coverage["memory_lifecycle_operations"] = "receipt_identity_in_repeatable_read_snapshot"
                for operation_id, attempt_id, fp, outcome, refs, deadline, created_at in receipts:
                    document_id = hashlib.sha256((
                        f"{owner_id}\0{PostgresPayloadRepository.scope_id(owner_id, scope)}\0"
                        f"{operation_id}\0{attempt_id}"
                    ).encode()).hexdigest()
                    add("memory_lifecycle_operations", document_id, {
                        "owner_id": owner_id, "application_id": scope.application_id,
                        "workspace_id": scope.workspace_id, "scope_version": 2,
                        "operation_id": operation_id, "attempt_id": attempt_id,
                        "fingerprint": fp.strip(), "outcome": outcome,
                        "result_refs": refs, "execution_deadline": deadline,
                        "created_at": created_at,
                    })
                    p_count += 1
        except ExportTooLarge:
            raise
        except AccountDataUnavailable:
            raise
        except Exception as error:
            raise AccountDataUnavailable("Postgres export failed") from error

        postgres_finished_at = datetime.now(UTC)
        dynamo_started_at = postgres_finished_at
        dynamo_revisions = {}
        d_count = 0
        namespace = _namespace(scope, owner_id)
        catalog_partition = f"{namespace}#CATALOG"
        deadline = monotonic() + 60
        summary_repository = DynamoDBSummaryRepository(self.runtime_table)
        try:
            conversation_entries = self.runtime_table.query(
                partition=catalog_partition, sort_prefix="CONV#", consistent=True,
                deadline=deadline, limit=MAX_EXPORT_SCAN_RECORDS + 1,
            )
            job_entries = self.runtime_table.query(
                partition=catalog_partition, sort_prefix="JOB#", consistent=True,
                deadline=deadline, limit=MAX_EXPORT_SCAN_RECORDS + 1,
            )
            if len(conversation_entries) > MAX_EXPORT_SCAN_RECORDS or len(job_entries) > MAX_EXPORT_SCAN_RECORDS:
                raise ExportTooLarge
            conversation_keys = []
            summary_directory = {}
            trace_directory = {}
            for entry in conversation_entries:
                if not _authorized(entry, owner_id, scope):
                    raise AccountDataUnavailable("conversation directory scope mismatch")
                conversation_id = entry["conversation_id"]
                partition = f"{namespace}#CONV#{conversation_id}"
                meta_key = {"PK": partition, "SK": "META"}
                metadata = self.runtime_table.get(meta_key)
                if (
                    metadata is None or not _authorized(metadata, owner_id, scope)
                    or int(metadata["revision"]) != int(entry["revision"])
                    or metadata["updated_at"] != entry["updated_at"]
                ):
                    raise AccountDataUnavailable("conversation directory revision mismatch")
                conversation = _conversation_from_item(metadata)
                add("conversations", conversation.id, conversation.model_dump(mode="json"))
                d_count += 1
                dynamo_revisions[f"conversation:{conversation_id}"] = int(metadata["revision"])
                conversation_keys.append((entry["SK"], int(entry["revision"]), conversation_id, partition))

                message_items = self.runtime_table.query(
                    partition=partition, sort_prefix="MSG#", consistent=True,
                    deadline=deadline, limit=MAX_CONVERSATION_MESSAGES + 1,
                )
                if len(message_items) > MAX_CONVERSATION_MESSAGES:
                    raise ExportTooLarge
                for item in message_items:
                    if not _authorized(item, owner_id, scope):
                        raise AccountDataUnavailable("message scope mismatch")
                    add("messages", item["message_id"], json.loads(item["payload"]))
                    d_count += 1

                summary_items = self.runtime_table.query(
                    partition=partition, sort_prefix="SUM#", consistent=True,
                    deadline=deadline, limit=MAX_EXPORT_SCAN_RECORDS + 1,
                )
                if len(summary_items) > MAX_EXPORT_SCAN_RECORDS:
                    raise ExportTooLarge
                summary_directory[conversation_id] = [item["SK"] for item in summary_items]
                for item in summary_items:
                    if not item.get("published") or not _authorized(item, owner_id, scope):
                        raise AccountDataUnavailable("summary header unavailable")
                    summary = summary_repository._load(item, partition, deadline)
                    add("conversation_summaries", summary.id, summary.model_dump(mode="json"))
                    dynamo_revisions[f"summary:{summary.id}"] = {
                        "source_manifest_sha256": hashlib.sha256(
                            item["source_manifest"].encode()
                        ).hexdigest(),
                        "coverage_manifest_sha256": hashlib.sha256(
                            item["coverage_manifest"].encode()
                        ).hexdigest(),
                    }
                    d_count += 1

                trace_items = self.runtime_table.query(
                    partition=partition, sort_prefix="CTX#", consistent=True,
                    deadline=deadline, limit=MAX_CONTEXT_TRACE_RETENTION + 1,
                )
                if len(trace_items) > MAX_CONTEXT_TRACE_RETENTION:
                    raise AccountDataUnavailable("context trace retention bound exceeded")
                trace_directory[conversation_id] = [item["SK"] for item in trace_items]
                for item in trace_items:
                    if not _authorized(item, owner_id, scope):
                        raise AccountDataUnavailable("context trace scope mismatch")
                    trace = ContextTraceManifest.model_validate_json(item["payload"])
                    if (
                        trace.conversation_id != UUID(conversation_id)
                        or trace.assistant_message_id != UUID(item["assistant_message_id"])
                        or trace.user_message_id != UUID(item["user_message_id"])
                        or trace.request_id != item.get("request_id")
                        or trace.application_id != scope.application_id
                        or trace.workspace_id != scope.workspace_id
                    ):
                        raise AccountDataUnavailable("context trace identity mismatch")
                    add("context_traces", trace.assistant_message_id, trace.model_dump(mode="json"))
                    dynamo_revisions[f"context_trace:{trace.assistant_message_id}"] = item[
                        "recorded_at"
                    ]
                    d_count += 1

            job_keys = []
            for entry in job_entries:
                if not _authorized(entry, owner_id, scope):
                    raise AccountDataUnavailable("job directory scope mismatch")
                job_item = self.runtime_table.get({"PK": entry["record_pk"], "SK": entry["record_sk"]})
                if job_item is None or not _authorized(job_item, owner_id, scope):
                    raise AccountDataUnavailable("job record unavailable")
                if job_item.get("job_id") != entry.get("job_id"):
                    raise AccountDataUnavailable("job directory identity mismatch")
                job_id = job_item["job_id"]
                data = json.loads(job_item["payload"])
                if job_item.get("pending_effect") is not None:
                    data["pending_effect"] = job_item["pending_effect"]
                add("memory_lifecycle_jobs", job_id, data)
                d_count += 1
                dynamo_revisions[f"job:{job_id}"] = int(job_item["revision"])
                job_keys.append((entry["SK"], job_id, entry["record_pk"], entry["record_sk"], int(job_item["revision"])))

            for sort_key, revision, conversation_id, partition in conversation_keys:
                metadata = self.runtime_table.get({"PK": partition, "SK": "META"})
                if metadata is None or int(metadata["revision"]) != revision:
                    raise AccountDataUnavailable("conversation changed during export")
                message_items = self.runtime_table.query(
                    partition=partition, sort_prefix="MSG#", consistent=True,
                    deadline=deadline, limit=MAX_CONVERSATION_MESSAGES + 1,
                )
                if len(message_items) > MAX_CONVERSATION_MESSAGES:
                    raise ExportTooLarge
                current_summaries = self.runtime_table.query(
                    partition=partition, sort_prefix="SUM#", consistent=True,
                    deadline=deadline, limit=MAX_EXPORT_SCAN_RECORDS + 1,
                )
                if [item["SK"] for item in current_summaries] != summary_directory[conversation_id]:
                    raise AccountDataUnavailable("summary directory changed during export")
                current_traces = self.runtime_table.query(
                    partition=partition, sort_prefix="CTX#", consistent=True,
                    deadline=deadline, limit=MAX_CONTEXT_TRACE_RETENTION + 1,
                )
                if [item["SK"] for item in current_traces] != trace_directory[conversation_id]:
                    raise AccountDataUnavailable("conversation context traces changed during export")
            final_conversations = self.runtime_table.query(
                partition=catalog_partition, sort_prefix="CONV#", consistent=True,
                deadline=deadline, limit=MAX_EXPORT_SCAN_RECORDS + 1,
            )
            if [(item["SK"], int(item["revision"])) for item in final_conversations] != [
                (sk, revision) for sk, revision, _, _ in conversation_keys
            ]:
                raise AccountDataUnavailable("conversation directory changed during export")
            final_jobs = self.runtime_table.query(
                partition=catalog_partition, sort_prefix="JOB#", consistent=True,
                deadline=deadline, limit=MAX_EXPORT_SCAN_RECORDS + 1,
            )
            if [(item["SK"], item["job_id"]) for item in final_jobs] != [
                (sk, job_id) for sk, job_id, _, _, _ in job_keys
            ]:
                raise AccountDataUnavailable("job directory changed during export")
            for _, job_id, record_pk, record_sk, revision in job_keys:
                current = self.runtime_table.get({"PK": record_pk, "SK": record_sk})
                if current is None or int(current["revision"]) != revision:
                    raise AccountDataUnavailable("job changed during export")
        except ExportTooLarge:
            raise
        except AccountDataUnavailable:
            raise
        except Exception as error:
            raise AccountDataUnavailable("DynamoDB export failed") from error

        finished_at = datetime.now(UTC)
        result = {
            "schema_version": "personal-ai-export-v2",
            "generated_at": finished_at.isoformat(),
            "owner_id": owner_id,
            "application_id": scope.application_id,
            "workspace_id": scope.workspace_id,
            "collections": collections,
            "snapshot_coverage": {
                "cross_store_snapshot": False,
                "postgres": {
                    "isolation": "repeatable_read_read_only",
                    "snapshot_id": p_snapshot_id,
                    "started_at": started_at.isoformat(),
                    "finished_at": postgres_finished_at.isoformat(),
                    "record_count": p_count,
                    "max_revision": p_revision_max,
                    "collection_counts": p_collection_counts,
                    "revision_coverage": p_revision_coverage,
                },
                "dynamodb": {
                    "consistency": "strong_bounded_key_reads",
                    "started_at": dynamo_started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "record_count": d_count,
                    "revisions": dynamo_revisions,
                },
            },
        }
        try:
            byte_count = len(json.dumps(
                result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8"))
        except (TypeError, ValueError) as error:
            raise AccountDataUnavailable("export serialization failed") from error
        if byte_count > max_bytes:
            raise ExportTooLarge
        return result

    def record_export(self, *, owner_id, idempotency_key, correlation_id):
        scope = current_application_scope()
        audit_id = _audit_id(
            owner_id, "account.export", idempotency_key,
            scope.application_id, scope.workspace_id,
        )
        with self.database.transaction() as connection:
            _append_audit(
                connection, owner_id=owner_id, audit_id=audit_id,
                action="account.export", target_type="owner_data_export",
                target_id=owner_id, correlation_id=correlation_id, result="generated",
                scope=scope,
            )

    def create_deletion(self, *, owner_id, idempotency_key, correlation_id):
        self._require_standalone()
        request_id = uuid5(NAMESPACE_URL, f"account-lifecycle-v1:{owner_id}:{idempotency_key}")
        audit_id = _audit_id(owner_id, "account.deletion.request", idempotency_key)
        now = datetime.now(UTC)
        value = {
            "id": str(request_id), "owner_id": owner_id, "request_type": "deletion",
            "state": "pending_confirmation", "idempotency_key": str(idempotency_key),
            "confirmed_at": None, "irreversible_at": None, "completed_at": None,
            "audit_event_ids": [audit_id], "created_at": now.isoformat(),
            "updated_at": now.isoformat(), "application_id": "personal_ai",
            "workspace_id": None, "scope_version": 2,
        }
        scope_id = PostgresPayloadRepository.scope_id(owner_id, _ACCOUNT_SCOPE)
        try:
            with self.database.transaction() as connection:
                _ensure_namespace(connection, owner_id, _ACCOUNT_SCOPE)
                existing = connection.execute(
                    "SELECT payload FROM account_lifecycle_requests WHERE scope_id=%s AND record_id=%s FOR UPDATE",
                    (scope_id, str(request_id)),
                ).fetchone()
                if existing is not None:
                    current = existing[0]
                    if current.get("owner_id") != owner_id or current.get("request_type") != "deletion":
                        raise AccountRequestConflict
                    return current
                connection.execute(
                    "INSERT INTO account_lifecycle_requests(record_id,scope_id,owner_id,application_id,"
                    "workspace_id,record_version,status,revision,created_at,idempotency_key,payload) "
                    "VALUES (%s,%s,%s,'personal_ai',NULL,1,%s,1,%s,%s,%s::jsonb)",
                    (
                        str(request_id), scope_id, owner_id, value["state"], now,
                        str(idempotency_key), _json(value),
                    ),
                )
                _append_audit(
                    connection, owner_id=owner_id, audit_id=audit_id,
                    action="account.deletion.request", target_type="account_lifecycle_request",
                    target_id=request_id, correlation_id=correlation_id,
                    result="pending_confirmation",
                )
        except (AccountRequestConflict, AccountRequestNotFound):
            raise
        except Exception as error:
            raise AccountDataUnavailable from error
        return value

    def get_deletion(self, *, owner_id, request_id):
        self._require_standalone()
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM account_lifecycle_requests WHERE scope_id=%s AND record_id=%s "
                "AND owner_id=%s AND status IS NOT NULL",
                (PostgresPayloadRepository.scope_id(owner_id, _ACCOUNT_SCOPE), str(request_id), owner_id),
            ).fetchone()
        if row is None or row[0].get("request_type") != "deletion":
            raise AccountRequestNotFound
        return row[0]

    def transition_deletion(self, *, owner_id, request_id, action, correlation_id):
        self._require_standalone()
        if action not in {"confirm", "cancel"}:
            raise ValueError("unsupported_deletion_action")
        scope_id = PostgresPayloadRepository.scope_id(owner_id, _ACCOUNT_SCOPE)
        audit_id = hashlib.sha256(f"{request_id}\0{action}".encode()).hexdigest()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload,revision FROM account_lifecycle_requests WHERE scope_id=%s "
                "AND record_id=%s AND owner_id=%s FOR UPDATE",
                (scope_id, str(request_id), owner_id),
            ).fetchone()
            if row is None or row[0].get("request_type") != "deletion":
                raise AccountRequestNotFound
            current, revision = row
            state = current["state"]
            if action == "confirm" and state in {"confirmed_pending_operator", "completed"}:
                return current
            if action == "cancel" and state == "cancelled":
                return current
            if action == "confirm" and state != "pending_confirmation":
                raise AccountRequestConflict
            if action == "cancel" and (
                state not in {"pending_confirmation", "confirmed_pending_operator"}
                or current.get("irreversible_at") is not None
            ):
                raise AccountRequestConflict
            now = datetime.now(UTC)
            next_state = "confirmed_pending_operator" if action == "confirm" else "cancelled"
            updated = {**current, "state": next_state, "updated_at": now.isoformat()}
            if action == "confirm":
                updated["confirmed_at"] = now.isoformat()
            ids = list(updated.get("audit_event_ids", []))
            if audit_id not in ids:
                ids.append(audit_id)
            updated["audit_event_ids"] = ids
            connection.execute(
                "UPDATE account_lifecycle_requests SET payload=%s::jsonb,status=%s,revision=revision+1,updated_at=%s "
                "WHERE scope_id=%s AND record_id=%s AND revision=%s",
                (_json(updated), next_state, now, scope_id, str(request_id), revision),
            )
            _append_audit(
                connection, owner_id=owner_id, audit_id=audit_id,
                action=f"account.deletion.{action}", target_type="account_lifecycle_request",
                target_id=request_id, correlation_id=correlation_id, result=next_state,
            )
            return updated
