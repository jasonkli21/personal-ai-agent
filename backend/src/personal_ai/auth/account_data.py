"""Firestore boundaries for portable owner exports and deletion request records."""

from __future__ import annotations

import base64
import hashlib
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.auth.owner_data import OWNER_DATA_COLLECTIONS

EXPORT_COLLECTIONS = (*OWNER_DATA_COLLECTIONS, "account_lifecycle_requests")


class AccountDataUnavailable(RuntimeError):
    """Owner data could not be read or changed safely."""


class AccountRequestNotFound(LookupError):
    """The owner-scoped lifecycle request does not exist."""


class AccountRequestConflict(RuntimeError):
    """The idempotency key conflicts with a previous lifecycle action."""


class ExportTooLarge(RuntimeError):
    """The export exceeds its configured synchronous response limits."""


def _portable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"$type": "base64", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _portable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_portable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"$type": "float", "value": repr(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        return {"$type": "geopoint", "latitude": value.latitude, "longitude": value.longitude}
    if value.__class__.__name__ == "Vector":
        return {"$type": "vector", "values": [_portable(item) for item in value]}
    raise TypeError("unsupported_export_value")


class FirestoreAccountDataRepository:
    def __init__(self, *, project_id: str | None, emulator_host: str | None) -> None:
        from personal_ai.storage.firestore import _firestore_client

        self.client = _firestore_client(project_id, emulator_host)
        self.firestore = __import__("google.cloud.firestore", fromlist=["firestore"])
        self.requests = self.client.collection("account_lifecycle_requests")
        self.audit_events = self.client.collection("audit_events")

    def export_owner(self, owner_id: str, *, max_records: int, max_bytes: int) -> dict:
        generated_at = datetime.now(UTC)
        collections: dict[str, list[dict]] = {}
        count = 0
        estimated_bytes = 0
        try:
            for collection_name in EXPORT_COLLECTIONS:
                records = []
                remaining = max_records - count
                query = (
                    self.client.collection(collection_name)
                    .where(filter=self.firestore.FieldFilter("owner_id", "==", owner_id))
                    .order_by("__name__")
                    .limit(remaining + 1)
                )
                for snapshot in query.stream():
                    count += 1
                    if count > max_records:
                        raise ExportTooLarge
                    record = {"document_id": snapshot.id, "data": _portable(snapshot.to_dict() or {})}
                    estimated_bytes += len(
                        json.dumps(
                            record, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                        ).encode("utf-8")
                    ) + len(collection_name) + 4
                    if estimated_bytes > max_bytes:
                        raise ExportTooLarge
                    records.append(record)
                if records:
                    collections[collection_name] = records
        except ExportTooLarge:
            raise
        except Exception as error:
            raise AccountDataUnavailable from error
        result = {
            "schema_version": "personal-ai-export-v1",
            "generated_at": generated_at.isoformat(),
            "owner_id": owner_id,
            "collections": collections,
        }
        try:
            byte_count = len(
                json.dumps(
                    result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
            )
        except (TypeError, ValueError) as error:
            raise AccountDataUnavailable from error
        if byte_count > max_bytes:
            raise ExportTooLarge
        return result

    def record_export(self, *, owner_id: str, idempotency_key: UUID, correlation_id: str) -> None:
        self._write_audit(
            owner_id=owner_id,
            action="account.export",
            target_type="owner_data_export",
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            result="delivered",
        )

    def create_deletion(self, *, owner_id: str, idempotency_key: UUID, correlation_id: str) -> dict:
        request_id = uuid5(NAMESPACE_URL, f"account-lifecycle-v1:{owner_id}:{idempotency_key}")
        ref = self.requests.document(str(request_id))
        audit_id = self._audit_id(owner_id, "account.deletion.request", idempotency_key)
        audit_ref = self.audit_events.document(audit_id)
        transaction = self.client.transaction()

        @self.firestore.transactional
        def apply(tx):
            existing = ref.get(transaction=tx)
            if existing.exists:
                current = existing.to_dict() or {}
                if current.get("owner_id") != owner_id or current.get("request_type") != "deletion":
                    raise AccountRequestConflict
                return current
            now = datetime.now(UTC)
            data = {
                "id": str(request_id),
                "owner_id": owner_id,
                "request_type": "deletion",
                "state": "pending_confirmation",
                "idempotency_key": str(idempotency_key),
                "confirmed_at": None,
                "irreversible_at": None,
                "completed_at": None,
                "audit_event_ids": [audit_id],
                "created_at": now,
                "updated_at": now,
            }
            tx.create(ref, data)
            tx.create(
                audit_ref,
                self._audit_data(
                    audit_id,
                    owner_id,
                    "account.deletion.request",
                    "account_lifecycle_request",
                    str(request_id),
                    correlation_id,
                    "pending_confirmation",
                    now,
                ),
            )
            return data

        try:
            return apply(transaction)
        except AccountRequestConflict:
            raise
        except Exception as error:
            raise AccountDataUnavailable from error

    def get_deletion(self, *, owner_id: str, request_id: UUID) -> dict:
        try:
            snapshot = self.requests.document(str(request_id)).get()
            data = snapshot.to_dict() if snapshot.exists else None
            if (
                not data
                or data.get("owner_id") != owner_id
                or data.get("request_type") != "deletion"
            ):
                raise AccountRequestNotFound
            return data
        except AccountRequestNotFound:
            raise
        except Exception as error:
            raise AccountDataUnavailable from error

    def transition_deletion(
        self,
        *,
        owner_id: str,
        request_id: UUID,
        action: str,
        correlation_id: str,
    ) -> dict:
        if action not in {"confirm", "cancel"}:
            raise ValueError("unsupported_deletion_action")
        ref = self.requests.document(str(request_id))
        transaction = self.client.transaction()
        audit_id = hashlib.sha256(f"{request_id}\0{action}".encode()).hexdigest()
        audit_ref = self.audit_events.document(audit_id)

        @self.firestore.transactional
        def apply(tx):
            snapshot = ref.get(transaction=tx)
            current = snapshot.to_dict() if snapshot.exists else None
            if (
                not current
                or current.get("owner_id") != owner_id
                or current.get("request_type") != "deletion"
            ):
                raise AccountRequestNotFound
            state = current.get("state")
            audit_exists = audit_ref.get(transaction=tx).exists
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
            changes = {"state": next_state, "updated_at": now}
            if action == "confirm":
                changes["confirmed_at"] = now
            if not audit_exists:
                tx.create(
                    audit_ref,
                    self._audit_data(
                        audit_id,
                        owner_id,
                        f"account.deletion.{action}",
                        "account_lifecycle_request",
                        str(request_id),
                        correlation_id,
                        next_state,
                        now,
                    ),
                )
            audit_ids = list(current.get("audit_event_ids", []))
            if audit_id not in audit_ids:
                audit_ids.append(audit_id)
                changes["audit_event_ids"] = audit_ids
            tx.update(ref, changes)
            current.update(changes)
            return current

        try:
            return apply(transaction)
        except (AccountRequestConflict, AccountRequestNotFound):
            raise
        except Exception as error:
            raise AccountDataUnavailable from error

    @staticmethod
    def _audit_id(owner_id: str, action: str, idempotency_key: UUID) -> str:
        return hashlib.sha256(f"{owner_id}\0{action}\0{idempotency_key}".encode()).hexdigest()

    @staticmethod
    def _audit_data(
        audit_id, owner_id, action, target_type, target_id, correlation_id, result, now
    ):
        return {
            "id": audit_id,
            "actor_subject": owner_id,
            "owner_id": owner_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "result": result,
            "correlation_id": correlation_id,
            "occurred_at": now,
        }

    def _write_audit(
        self, *, owner_id, action, target_type, idempotency_key, correlation_id, result
    ):
        audit_id = self._audit_id(owner_id, action, idempotency_key)
        ref = self.audit_events.document(audit_id)
        transaction = self.client.transaction()

        @self.firestore.transactional
        def apply(tx):
            if ref.get(transaction=tx).exists:
                return
            tx.create(
                ref,
                self._audit_data(
                    audit_id,
                    owner_id,
                    action,
                    target_type,
                    audit_id,
                    correlation_id,
                    result,
                    datetime.now(UTC),
                ),
            )

        try:
            apply(transaction)
        except Exception as error:
            raise AccountDataUnavailable from error
