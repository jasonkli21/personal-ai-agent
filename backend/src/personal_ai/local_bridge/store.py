"""Protected POSIX local state, with cross-process serialization and crash fences."""

from __future__ import annotations

import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

try:
    import fcntl
except ImportError:  # Explicit unsupported-platform failure, no file fallback.
    fcntl = None


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str = Field(min_length=1, max_length=32768, repr=False)
    refresh_token: str | None = Field(default=None, max_length=32768, repr=False)
    id_token: str = Field(min_length=1, max_length=32768, repr=False)
    scopes: tuple[str, ...] = Field(max_length=32)
    expires_at: int = Field(ge=0, strict=True)
    earliest_refresh_at: int = Field(default=0, ge=0, strict=True)


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    client_id: str = Field(pattern=r"^oaiapp_[A-Za-z0-9_-]{1,193}$", repr=False)
    issuer: str | None = Field(default=None, repr=False)
    subject: str | None = Field(default=None, max_length=200, repr=False)
    credentials: Credentials | None = Field(default=None, repr=False)
    revision: int = Field(default=0, strict=True, ge=0)
    state: Literal["connected", "disconnected", "permission_required", "reauth", "unavailable"] = (
        "disconnected"
    )
    refresh_pending: bool = False
    remote_revocation: Literal["unknown", "confirmed", "unconfirmed"] = "unknown"


class LocalState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(default=1, strict=True)
    host_id: str
    runtime_id: str
    registrations: dict[str, Registration] = Field(default_factory=dict, max_length=32, repr=False)
    receipts: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=4096)


class LocalStoreError(RuntimeError):
    def __init__(self, code="local_store_unavailable"):
        super().__init__(code)
        self.code = code


class LocalTransaction:
    def __init__(self, store, state):
        self.store, self.state = store, state

    def save(self):
        self.store._write(self.state)


class ProtectedLocalStore:
    """Single directory, local files only. No managed repository implementation.

    Calls must run outside the event loop. The lock stays held across refresh IO;
    an explicit save before IO makes interrupted rotation unsafe to repeat.
    """

    def __init__(self, directory: Path):
        self.directory = directory.absolute()
        if os.name != "posix" or fcntl is None:
            raise LocalStoreError("protected_storage_unsupported")
        if os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_JOB"):
            raise LocalStoreError("managed_runtime_forbidden")
        # Reject symlinked paths rather than resolve them silently.
        for component in (self.directory, *self.directory.parents):
            if component.is_symlink():
                raise LocalStoreError("unsafe_local_store")
            if (component / ".git").exists():
                raise LocalStoreError("local_store_in_repository")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._check(self.directory, directory=True)

    @staticmethod
    def _check(path: Path, *, directory=False):
        info = path.lstat()
        expected = 0o700 if directory else 0o600
        if (
            info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != expected
            or (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink != 1)
        ):
            raise LocalStoreError("unsafe_local_store")

    @contextmanager
    def transaction(self):
        self._check(self.directory, directory=True)
        lock_path = self.directory / "runtime.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            self._check(lock_path)
            deadline = time.monotonic() + 10
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LocalStoreError("local_store_busy") from None
                    time.sleep(0.01)
            path = self.directory / "state.json"
            if path.exists() or path.is_symlink():
                self._check(path)
                file_descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(file_descriptor, "rb") as file:
                    payload = file.read(2 * 1024 * 1024 + 1)
                if len(payload) > 2 * 1024 * 1024:
                    raise LocalStoreError("local_store_capacity")
                try:
                    state = LocalState.model_validate_json(payload)
                    if state.schema_version != 1:
                        raise ValueError()
                    UUID(state.runtime_id)
                    UUID(state.host_id.removeprefix("urn:uuid:"))
                    for connection_id, registration in state.registrations.items():
                        if str(UUID(connection_id)) != registration.connection_id:
                            raise ValueError()
                except ValueError:
                    raise LocalStoreError("local_store_invalid") from None
            else:
                state = LocalState(host_id=f"urn:uuid:{uuid4()}", runtime_id=str(uuid4()))
                self._write(state)
            yield LocalTransaction(self, state)
        finally:
            os.close(descriptor)

    def _write(self, state: LocalState):
        # Revalidate mutations before they become canonical.
        try:
            state = LocalState.model_validate(state.model_dump())
        except ValueError:
            raise LocalStoreError("local_store_invalid") from None
        payload = state.model_dump_json().encode()
        if len(payload) > 2 * 1024 * 1024:
            raise LocalStoreError("local_store_capacity")
        self._check(self.directory, directory=True)
        descriptor, name = tempfile.mkstemp(prefix=".state-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self.directory / "state.json")
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def claim(self, identity: str, fingerprint: str, connection: str, revision: int):
        with self.transaction() as tx:
            registration = tx.state.registrations.get(connection)
            if (
                registration is None
                or registration.revision != revision
                or registration.state != "connected"
                or registration.refresh_pending
            ):
                raise LocalStoreError("connection_changed")
            if identity in tx.state.receipts:
                raise LocalStoreError("dispatch_already_claimed")
            if len(tx.state.receipts) >= 4096:
                raise LocalStoreError("local_store_capacity")
            tx.state.receipts[identity] = {"fingerprint": fingerprint, "status": "unknown"}
            tx.save()

    def settle(self, identity: str, status: str):
        if status not in {"success", "failure", "rejected", "incomplete"}:
            raise LocalStoreError("dispatch_status_invalid")
        with self.transaction() as tx:
            receipt = tx.state.receipts[identity]
            if receipt["status"] != "unknown":
                raise LocalStoreError("dispatch_already_settled")
            receipt["status"] = status
            tx.save()
