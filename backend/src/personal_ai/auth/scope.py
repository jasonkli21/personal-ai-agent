"""Validated application/workspace scope for owner-scoped Personal AI data."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_ai.auth.contracts import AuthenticatedPrincipal

STANDALONE_APPLICATION_ID = "personal_ai"
CANONICAL_APPLICATION_IDS = frozenset(
    {"personal_ai", "travel", "shopping", "finance", "health"}
)
ApplicationId = Literal["personal_ai", "travel", "shopping", "finance", "health"]
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
_CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")


class ApplicationScope(BaseModel):
    """The namespace of a request; this never grants owner or workspace access."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    application_id: ApplicationId = STANDALONE_APPLICATION_ID
    workspace_id: str | None = None

    @field_validator("workspace_id")
    @classmethod
    def valid_workspace_id(cls, value: str | None) -> str | None:
        if value is not None and not _ID_PATTERN.fullmatch(value):
            raise ValueError("workspace_id_invalid")
        return value


class RequestScope(ApplicationScope):
    """A validated request envelope with server-derived owner identity."""

    owner_id: str = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=1, max_length=100)
    capabilities: tuple[str, ...] = Field(default=(), max_length=16)
    client_context: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, max_length=32
    )

    @field_validator("capabilities")
    @classmethod
    def valid_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(
            not _CAPABILITY_PATTERN.fullmatch(value) for value in values
        ):
            raise ValueError("capabilities_invalid")
        return values

    @field_validator("client_context")
    @classmethod
    def valid_client_context(cls, values):
        if any(not _ID_PATTERN.fullmatch(key) for key in values):
            raise ValueError("client_context_invalid")
        return values

    @model_validator(mode="after")
    def validate_payload_size(self):
        if len(json.dumps(self.client_context, separators=(",", ":"))) > 4096:
            raise ValueError("client_context_too_large")
        return self


class ApplicationScopedRecord(BaseModel):
    """Persisted scope envelope.

    Records written before application scoping omitted these fields and are
    decoded as v1 standalone records. New repository writes use v2 and always
    serialize both application and nullable workspace IDs.
    """

    model_config = ConfigDict(extra="forbid")

    application_id: ApplicationId = STANDALONE_APPLICATION_ID
    workspace_id: str | None = None
    scope_version: Literal[1, 2] = 1

    @field_validator("workspace_id")
    @classmethod
    def valid_workspace_id(cls, value: str | None) -> str | None:
        if value is not None and not _ID_PATTERN.fullmatch(value):
            raise ValueError("workspace_id_invalid")
        return value


class WorkspaceAuthorizer(Protocol):
    """Server-side workspace membership check; client context is never authority."""

    def is_member(
        self, principal: AuthenticatedPrincipal, application_id: str, workspace_id: str
    ) -> bool: ...


class DenyWorkspaceAuthorizer:
    """Fail-closed default until an application supplies membership authority."""

    def is_member(self, principal: AuthenticatedPrincipal, application_id: str, workspace_id: str) -> bool:
        del principal, application_id, workspace_id
        return False


_request_scope: ContextVar[RequestScope | None] = ContextVar("personal_ai_request_scope", default=None)
_application_scope: ContextVar[ApplicationScope | None] = ContextVar(
    "personal_ai_application_scope", default=None
)
_DEFAULT_APPLICATION_SCOPE = ApplicationScope()


def current_request_scope() -> RequestScope | None:
    return _request_scope.get()


def current_application_scope() -> ApplicationScope:
    return _application_scope.get() or _DEFAULT_APPLICATION_SCOPE


def scope_key(scope: ApplicationScope | None = None) -> tuple[str, str | None]:
    scope = scope or current_application_scope()
    return scope.application_id, scope.workspace_id


def scoped_identifier(identifier, scope: ApplicationScope | None = None) -> str:
    """Stable document-key partition that preserves legacy standalone IDs."""
    scope = scope or current_application_scope()
    if scope.application_id == STANDALONE_APPLICATION_ID and scope.workspace_id is None:
        return str(identifier)
    return f"{scope.application_id}__{scope.workspace_id or 'no-workspace'}__{identifier}"


def bind_request_scope(scope: RequestScope):
    """Bind scope for repositories and model builders during one ASGI request."""
    return (_request_scope.set(scope), _application_scope.set(scope))


def bind_application_scope(scope: ApplicationScope):
    """Bind only the durable namespace while a worker resolves a scoped job."""
    return _application_scope.set(scope)


def reset_request_scope(token) -> None:
    request_token, application_token = token
    _request_scope.reset(request_token)
    _application_scope.reset(application_token)


def reset_application_scope(token) -> None:
    _application_scope.reset(token)


@contextmanager
def application_scope_context(scope: ApplicationScope):
    token = bind_application_scope(scope)
    try:
        yield
    finally:
        reset_application_scope(token)


def scope_matches(record, scope: ApplicationScope | None = None) -> bool:
    """Treat records without scope fields as legacy standalone/null records."""
    scope = scope or current_application_scope()
    return (
        getattr(record, "application_id", STANDALONE_APPLICATION_ID) == scope.application_id
        and getattr(record, "workspace_id", None) == scope.workspace_id
    )


def data_scope_matches(data: dict, scope: ApplicationScope | None = None) -> bool:
    """Scope check for raw Firestore dictionaries before model hydration."""
    scope = scope or current_application_scope()
    return (
        data.get("application_id", STANDALONE_APPLICATION_ID) == scope.application_id
        and data.get("workspace_id") == scope.workspace_id
    )


def scoped_record(record, scope: ApplicationScope | None = None):
    """Apply current scope recursively before a newly created aggregate is stored."""
    scope = scope or current_application_scope()

    def apply(value):
        if isinstance(value, BaseModel):
            updates = {}
            for name in type(value).model_fields:
                child = getattr(value, name)
                mapped = apply(child)
                if mapped is not child:
                    updates[name] = mapped
            if isinstance(value, ApplicationScopedRecord):
                updates.update(
                    application_id=scope.application_id,
                    workspace_id=scope.workspace_id,
                    scope_version=2,
                )
            return value.model_copy(update=updates) if updates else value
        if isinstance(value, tuple):
            mapped = tuple(apply(item) for item in value)
            return mapped if any(a is not b for a, b in zip(value, mapped, strict=True)) else value
        if isinstance(value, list):
            mapped = [apply(item) for item in value]
            return mapped if any(a is not b for a, b in zip(value, mapped, strict=True)) else value
        if isinstance(value, dict):
            mapped = {key: apply(item) for key, item in value.items()}
            return mapped if any(mapped[key] is not value[key] for key in value) else value
        return value

    return apply(record)


def preserve_legacy_child_scope(current, candidate):
    """Keep v1 child envelopes intact when rewriting a v2 aggregate.

    The aggregate root may advance to the active scope. Historical embedded
    records keep their original absent/v1 envelope and payload.
    """
    def preserve(old, new, *, include_self: bool):
        if isinstance(old, BaseModel) and isinstance(new, type(old)):
            updates = {}
            if include_self and isinstance(old, ApplicationScopedRecord) and old.scope_version == 1:
                updates.update(
                    application_id=old.application_id,
                    workspace_id=old.workspace_id,
                    scope_version=old.scope_version,
                )
            for name in type(old).model_fields:
                old_value = getattr(old, name)
                new_value = getattr(new, name)
                preserved = preserve(old_value, new_value, include_self=True)
                if preserved is not new_value:
                    updates[name] = preserved
            return new.model_copy(update=updates) if updates else new
        if isinstance(old, (tuple, list)) and isinstance(new, type(old)):
            values = [
                preserve(old[index], item, include_self=True)
                if index < len(old) else item
                for index, item in enumerate(new)
            ]
            return type(new)(values) if any(a is not b for a, b in zip(values, new, strict=True)) else new
        if isinstance(old, dict) and isinstance(new, dict):
            values = {key: preserve(old[key], value, include_self=True)
                      if key in old else value for key, value in new.items()}
            return values if any(values[key] is not new[key] for key in values) else new
        return new

    return preserve(current, candidate, include_self=False)


def scope_normalized_dump(value):
    """Serialize substantive record content without scope envelope fields."""
    if isinstance(value, BaseModel):
        return {
            key: scope_normalized_dump(item)
            for key, item in value.model_dump(mode="python").items()
            if key not in {"application_id", "workspace_id", "scope_version"}
        }
    if isinstance(value, dict):
        return {
            key: scope_normalized_dump(item)
            for key, item in value.items()
            if key not in {"application_id", "workspace_id", "scope_version"}
        }
    if isinstance(value, (tuple, list)):
        return [scope_normalized_dump(item) for item in value]
    return value


def scope_query(query, scope: ApplicationScope | None = None):
    """Add Firestore prefilters for non-legacy namespaces.

    Standalone compatibility queries intentionally retain their existing
    owner-prefilter so absent-field v1 records remain readable; callers must
    apply ``scope_matches`` to each result before returning it.
    """
    scope = scope or current_application_scope()
    if scope.application_id == STANDALONE_APPLICATION_ID and scope.workspace_id is None:
        return query
    from google.cloud import firestore

    return (
        query.where(filter=firestore.FieldFilter("scope_version", "==", 2))
        .where(filter=firestore.FieldFilter("application_id", "==", scope.application_id))
        .where(filter=firestore.FieldFilter("workspace_id", "==", scope.workspace_id))
    )


def scope_filtered_snapshots(
    query,
    *,
    limit: int,
    scope: ApplicationScope | None = None,
    scan_limit: int = 5_000,
    timeout: float = 5,
    page_size: int = 100,
    order_field: str = "__name__",
    direction=None,
):
    """Read a bounded number of scope-eligible snapshots before applying limit.

    Legacy standalone reads cannot filter absent scope fields in Firestore. This
    helper pages the owner-filtered query, checks each stored envelope before
    adding it to the result window, and fails closed when its scan budget is
    exhausted. Callers must apply their remaining record-specific validation.
    """
    if limit < 1:
        return ()
    if scan_limit < 1 or page_size < 1 or timeout <= 0:
        raise ValueError("scope_scan_bounds_invalid")
    active_scope = scope or current_application_scope()
    ordered = (
        query.order_by(order_field)
        if direction is None else query.order_by(order_field, direction=direction)
    )
    deadline = monotonic() + timeout
    snapshots = []
    cursor = None
    scanned = 0
    while len(snapshots) < limit:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("scope compatibility scan deadline exceeded")
        if scanned >= scan_limit:
            probe = ordered.start_after(cursor).limit(1).stream(
                retry=None, timeout=remaining
            )
            if next(iter(probe), None) is not None:
                raise TimeoutError("scope compatibility scan exceeded its record bound")
            break
        page_limit = min(page_size, scan_limit - scanned)
        page_query = ordered.limit(page_limit)
        if cursor is not None:
            page_query = page_query.start_after(cursor)
        page = list(page_query.stream(retry=None, timeout=remaining))
        if not page:
            break
        scanned += len(page)
        cursor = page[-1]
        for snapshot in page:
            if data_scope_matches(snapshot.to_dict() or {}, active_scope):
                snapshots.append(snapshot)
                if len(snapshots) == limit:
                    break
        if len(page) < page_limit:
            break
    return tuple(snapshots)
