"""Restricted persistence for verified principal-to-owner mappings."""

from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime
from typing import Protocol

from personal_ai.auth.contracts import AuthenticatedPrincipal

MIGRATION_VERSION = "phase9-owner-v1"


class IdentityMappingConflict(RuntimeError):
    """A verified identity mapping is inactive or conflicts with its stable owner."""


class IdentityDirectoryUnavailable(RuntimeError):
    """The owner mapping could not be checked or initialized safely."""


class PrincipalDirectory(Protocol):
    def ensure_active(self, principal: AuthenticatedPrincipal, *, correlation_id: str) -> None: ...


class InMemoryPrincipalDirectory:
    """Thread-safe identity registry for tests only."""

    def __init__(self) -> None:
        self._mappings: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def ensure_active(self, principal: AuthenticatedPrincipal, *, correlation_id: str) -> None:
        del correlation_id
        with self._lock:
            current = self._mappings.get(principal.owner_id)
            if current is None:
                self._mappings[principal.owner_id] = {
                    "subject": principal.subject,
                    "issuer": principal.issuer,
                    "status": "active",
                }
                return
            if (
                current["subject"] != principal.subject
                or current["issuer"] != principal.issuer
                or current["status"] != "active"
            ):
                raise IdentityMappingConflict

    def deactivate(self, owner_id: str) -> None:
        with self._lock:
            if owner_id in self._mappings:
                self._mappings[owner_id]["status"] = "disabled"


class FirestorePrincipalDirectory:
    """Create/check owner mappings with an immutable bootstrap audit event."""

    def __init__(self, *, project_id: str | None, emulator_host: str | None) -> None:
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import firestore

        self._firestore = firestore
        if emulator_host is None:
            self._db = firestore.Client(project=project_id)
        else:
            host = emulator_host.strip()
            if not host or "://" in host or "/" in host:
                raise ValueError("firestore_emulator_host must be a host and optional port")
            self._db = firestore.Client(project=project_id, credentials=AnonymousCredentials())
            self._db._emulator_host = host

    def ensure_active(self, principal: AuthenticatedPrincipal, *, correlation_id: str) -> None:
        mapping_ref = self._db.collection("identity_mappings").document(principal.owner_id)
        audit_id = hashlib.sha256(
            f"{principal.issuer}\0{principal.subject}\0principal.bootstrap".encode()
        ).hexdigest()
        audit_ref = self._db.collection("audit_events").document(audit_id)
        transaction = self._db.transaction()

        @self._firestore.transactional
        def apply(tx):
            existing = mapping_ref.get(transaction=tx)
            if existing.exists:
                values = existing.to_dict() or {}
                if (
                    values.get("subject") != principal.subject
                    or values.get("issuer") != principal.issuer
                    or values.get("owner_id") != principal.owner_id
                    or values.get("status") != "active"
                ):
                    raise IdentityMappingConflict
                return

            now = datetime.now(UTC)
            tx.create(
                mapping_ref,
                {
                    "subject": principal.subject,
                    "owner_id": principal.owner_id,
                    "issuer": principal.issuer,
                    "created_at": now,
                    "status": "active",
                    "migration_version": MIGRATION_VERSION,
                },
            )
            tx.create(
                audit_ref,
                {
                    "id": audit_id,
                    "actor_subject": principal.subject,
                    "owner_id": principal.owner_id,
                    "action": "principal.bootstrap",
                    "target_type": "identity_mapping",
                    "target_id": principal.owner_id,
                    "result": "created",
                    "correlation_id": correlation_id,
                    "occurred_at": now,
                },
            )

        try:
            apply(transaction)
        except IdentityMappingConflict:
            raise
        except Exception as error:
            raise IdentityDirectoryUnavailable from error

    def active_owner_ids(self, *, limit: int = 2) -> tuple[str, ...]:
        """Return a bounded set for single-owner maintenance authorization."""
        try:
            snapshots = (
                self._db.collection("identity_mappings")
                .where(filter=self._firestore.FieldFilter("status", "==", "active"))
                .limit(limit)
                .stream()
            )
            return tuple(
                str((snapshot.to_dict() or {}).get("owner_id", snapshot.id))
                for snapshot in snapshots
            )
        except Exception as error:
            raise IdentityDirectoryUnavailable from error
