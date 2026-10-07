"""Postgres identity bootstrap and standalone account lifecycle records."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

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
    correlation_id, result, scope=_ACCOUNT_SCOPE,
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
        "actor_subject": owner_id,
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

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    @staticmethod
    def _require_standalone():
        scope = current_application_scope()
        if scope.application_id != "personal_ai" or scope.workspace_id is not None:
            raise AccountRequestNotFound

    def close(self):
        return None

    def export_owner(self, owner_id: str, *, max_records: int, max_bytes: int):
        del owner_id, max_records, max_bytes
        raise AccountDataUnavailable("portable export awaits the P/D revision snapshot adapter")

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
