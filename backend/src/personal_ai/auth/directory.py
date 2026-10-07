"""Restricted persistence for verified principal-to-owner mappings."""

from __future__ import annotations

import threading
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
