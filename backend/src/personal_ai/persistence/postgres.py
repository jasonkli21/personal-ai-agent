"""Bounded Psycopg boundary and typed-family repository primitives.

Repository callers keep their existing synchronous contracts and offload blocking
work at their existing async boundaries. The database also exposes an async pool
for repositories that are introduced with async-native contracts later.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, date, datetime
from importlib.resources import files
from time import monotonic
from typing import Any
from urllib.parse import parse_qs, urlsplit

from personal_ai.auth.scope import ApplicationScope

FAMILY_TABLES = frozenset(
    {
        "memory_lifecycle_states",
        "memory_lifecycle_events",
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
    }
)


class PersistenceUnavailable(RuntimeError):
    """A persistence dependency did not complete within its configured bound."""


class PersistenceConflict(RuntimeError):
    """A stable identity, revision, replay key, or scope conflicts with stored data."""


class PersistenceRecordNotFound(LookupError):
    """An identifier does not resolve inside the caller's authorized scope."""


class _DeadlineConnection:
    """Apply a caller's remaining budget to every statement in a transaction."""

    def __init__(self, connection, *, deadline, statement_timeout_ms, lock_timeout_ms):
        self._connection = connection
        self._deadline = deadline
        self._statement_timeout_ms = statement_timeout_ms
        self._lock_timeout_ms = lock_timeout_ms

    def _remaining_ms(self):
        remaining = None if self._deadline is None else self._deadline - monotonic()
        if remaining is not None and remaining <= 0:
            raise TimeoutError("postgres operation deadline exceeded")
        return remaining

    def execute(self, query, params=None, **kwargs):
        remaining = self._remaining_ms()
        statement_ms = self._statement_timeout_ms
        lock_ms = self._lock_timeout_ms
        if remaining is not None:
            remaining_ms = max(1, int(remaining * 1000))
            statement_ms = min(statement_ms, remaining_ms)
            lock_ms = min(lock_ms, remaining_ms)
        self._connection.execute(
            "SELECT set_config('statement_timeout', %s, true), "
            "set_config('lock_timeout', %s, true)",
            (f"{statement_ms}ms", f"{lock_ms}ms"),
        )
        self._remaining_ms()
        try:
            return self._connection.execute(query, params, **kwargs)
        except Exception as error:
            if getattr(error, "sqlstate", None) == "57014" and self._deadline is not None:
                raise TimeoutError("postgres operation deadline exceeded") from error
            raise

    def check_deadline(self):
        self._remaining_ms()

    def __getattr__(self, name):
        return getattr(self._connection, name)


class PostgresDatabase:
    """Psycopg 3 pools with explicit local endpoint and time bounds."""

    def __init__(
        self,
        dsn: str,
        *,
        environment: str = "local",
        min_size: int = 1,
        max_size: int = 8,
        connect_timeout: int = 5,
        statement_timeout_ms: int = 5_000,
        lock_timeout_ms: int = 2_000,
        pool_timeout: float = 5,
        prepare_threshold: int | None = 5,
    ) -> None:
        if not dsn.strip():
            raise ValueError("postgres_dsn_required")
        if not 0 <= min_size <= max_size <= 16 or max_size < 1:
            raise ValueError("postgres_pool_bounds_invalid")
        if not 1 <= connect_timeout <= 30 or not 1 <= statement_timeout_ms <= 120_000:
            raise ValueError("postgres_timeout_bounds_invalid")
        self._dsn = dsn
        self._environment = environment
        self._min_size, self._max_size = min_size, max_size
        self._connect_timeout = connect_timeout
        self._statement_timeout_ms = statement_timeout_ms
        self._lock_timeout_ms = lock_timeout_ms
        self._pool_timeout = pool_timeout
        self._prepare_threshold = prepare_threshold
        self._pool = None
        self._async_pool = None
        self._validate_endpoint()

    def _validate_endpoint(self) -> None:
        parsed = urlsplit(self._dsn)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
            raise ValueError("postgres_dsn_invalid")
        host = parsed.hostname.rstrip(".").lower()
        local_hosts = {"localhost", "127.0.0.1", "::1", "postgres", "postgres-test"}
        if self._environment in {"staging", "production"} and host in local_hosts:
            raise ValueError("local_postgres_endpoint_forbidden")
        if self._environment in {"local", "test"} and host not in local_hosts:
            raise ValueError("cloud_postgres_endpoint_forbidden")
        if self._environment in {"staging", "production"}:
            query = parse_qs(parsed.query)
            if query.get("sslmode") != ["verify-full"]:
                raise ValueError("postgres_tls_verification_required")

    def open(self) -> None:
        if self._pool is not None:
            return
        try:
            from psycopg.conninfo import make_conninfo
            from psycopg_pool import ConnectionPool
        except ImportError as error:  # pragma: no cover - packaging failure
            raise RuntimeError("psycopg_pool_required") from error
        options = (
            f"-c statement_timeout={self._statement_timeout_ms} "
            f"-c lock_timeout={self._lock_timeout_ms}"
        )
        conninfo = make_conninfo(
            self._dsn,
            connect_timeout=self._connect_timeout,
            options=options,
            application_name="personal-ai",
        )
        self._pool = ConnectionPool(
            conninfo,
            min_size=self._min_size,
            max_size=self._max_size,
            timeout=self._pool_timeout,
            kwargs={"prepare_threshold": self._prepare_threshold},
            open=True,
        )

    async def open_async(self) -> None:
        if self._async_pool is not None:
            return
        try:
            from psycopg.conninfo import make_conninfo
            from psycopg_pool import AsyncConnectionPool
        except ImportError as error:  # pragma: no cover - packaging failure
            raise RuntimeError("psycopg_pool_required") from error
        options = (
            f"-c statement_timeout={self._statement_timeout_ms} "
            f"-c lock_timeout={self._lock_timeout_ms}"
        )
        conninfo = make_conninfo(
            self._dsn,
            connect_timeout=self._connect_timeout,
            options=options,
            application_name="personal-ai",
        )
        self._async_pool = AsyncConnectionPool(
            conninfo,
            min_size=self._min_size,
            max_size=self._max_size,
            timeout=self._pool_timeout,
            kwargs={"prepare_threshold": self._prepare_threshold},
            open=False,
        )
        await self._async_pool.open()

    @contextmanager
    def connection(
        self, *, timeout_seconds: float | None = None, deadline: float | None = None,
        snapshot: bool = False,
    ) -> Iterator[Any]:
        if timeout_seconds is not None:
            if timeout_seconds <= 0:
                raise TimeoutError("postgres operation deadline exceeded")
            relative_deadline = monotonic() + timeout_seconds
            deadline = relative_deadline if deadline is None else min(deadline, relative_deadline)
        remaining = None if deadline is None else deadline - monotonic()
        if remaining is not None and remaining <= 0:
            raise TimeoutError("postgres operation deadline exceeded")
        pool_timeout = self._pool_timeout if remaining is None else min(self._pool_timeout, remaining)
        self.open()
        try:
            with (
                self._pool.connection(timeout=pool_timeout) as raw_connection,
                raw_connection.transaction(),
            ):
                if snapshot:
                    raw_connection.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    )
                connection = _DeadlineConnection(
                    raw_connection,
                    deadline=deadline,
                    statement_timeout_ms=self._statement_timeout_ms,
                    lock_timeout_ms=self._lock_timeout_ms,
                )
                yield connection
                connection.check_deadline()
        except Exception as error:
            if deadline is not None and monotonic() >= deadline:
                raise TimeoutError("postgres operation deadline exceeded") from error
            if _is_connection_error(error):
                raise PersistenceUnavailable("postgres_unavailable") from error
            raise

    @contextmanager
    def transaction(
        self, *, timeout_seconds: float | None = None, deadline: float | None = None,
        snapshot: bool = False,
    ) -> Iterator[Any]:
        """Alias that makes transaction-group intent explicit at call sites."""
        with self.connection(
            timeout_seconds=timeout_seconds, deadline=deadline, snapshot=snapshot
        ) as connection:
            yield connection

    @asynccontextmanager
    async def aconnection(self):
        await self.open_async()
        async with (
            self._async_pool.connection(timeout=self._pool_timeout) as connection,
            connection.transaction(),
        ):
            yield connection

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    async def close_async(self) -> None:
        if self._async_pool is not None:
            await self._async_pool.close()
            self._async_pool = None

    def migrate(self) -> tuple[int, ...]:
        """Apply checksum-pinned SQL migrations under a transaction advisory lock."""
        self.open()
        applied: list[int] = []
        migration_dir = files("personal_ai.persistence").joinpath("migrations")
        migrations = sorted(
            item for item in migration_dir.iterdir() if item.name.endswith(".sql")
        )
        for resource in migrations:
            prefix, _, _ = resource.name.partition("_")
            try:
                version = int(prefix)
            except ValueError as error:
                raise RuntimeError("migration_filename_invalid") from error
            sql = resource.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            with self.transaction() as connection:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(%s, %s)", (0x504149, 10)
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "version integer PRIMARY KEY, checksum text NOT NULL, "
                    "applied_at timestamptz NOT NULL DEFAULT now())"
                )
                row = connection.execute(
                    "SELECT checksum FROM schema_migrations WHERE version = %s",
                    (version,),
                ).fetchone()
                if row is not None:
                    if row[0] != checksum:
                        raise RuntimeError("migration_checksum_mismatch")
                    continue
                connection.execute(sql, prepare=False)
                connection.execute(
                    "INSERT INTO schema_migrations(version, checksum) VALUES (%s, %s)",
                    (version, checksum),
                )
                applied.append(version)
        return tuple(applied)


class PostgresPayloadRepository:
    """Typed family-table access for bounded snapshots and transaction groups."""

    def __init__(self, database: PostgresDatabase, family: str) -> None:
        if family not in FAMILY_TABLES:
            raise ValueError("persistence_family_invalid")
        self.database = database
        self.family = family

    @staticmethod
    def scope_id(owner_id: str, scope: ApplicationScope) -> str:
        """Unambiguous scope identity; null workspace differs from every value."""
        parts = (owner_id, scope.application_id, scope.workspace_id)
        encoded = []
        for part in parts:
            if part is None:
                encoded.append("N")
            else:
                value = str(part)
                encoded.append(f"V{len(value.encode('utf-8'))}:{value}")
        return "S2" + "".join(encoded)

    @staticmethod
    def _json(value: Any) -> str:
        try:
            serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            raise ValueError("persistence_payload_invalid") from error
        if len(serialized.encode("utf-8")) > 262_144:
            raise ValueError("persistence_payload_too_large")
        return serialized

    def get(self, *, owner_id: str, scope: ApplicationScope, record_id: str) -> dict[str, Any]:
        query = f"SELECT payload FROM {self.family} WHERE scope_id = %s AND record_id = %s AND owner_id = %s AND application_id = %s AND workspace_id IS NOT DISTINCT FROM %s"
        with self.database.connection() as connection:
            row = connection.execute(
                query,
                (
                    self.scope_id(owner_id, scope),
                    record_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                ),
            ).fetchone()
        if row is None:
            raise PersistenceRecordNotFound("record not found")
        return row[0]

    def create(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        record_id: str,
        payload: dict[str, Any],
        status: str | None = None,
        revision: int = 1,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
        fingerprint: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        serialized = self._json(payload)
        timestamp = _datetime(created_at) or datetime.now(UTC)
        query = f"INSERT INTO {self.family}(record_id, scope_id, owner_id, application_id, workspace_id, record_version, status, revision, created_at, expires_at, fingerprint, idempotency_key, payload) VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s::jsonb)"
        try:
            with self.database.connection() as connection:
                _ensure_namespace(connection, owner_id, scope)
                connection.execute(
                    query,
                    (
                        record_id,
                        self.scope_id(owner_id, scope),
                        owner_id,
                        scope.application_id,
                        scope.workspace_id,
                        status,
                        revision,
                        timestamp,
                        _datetime(expires_at),
                        fingerprint,
                        idempotency_key,
                        serialized,
                    ),
                )
        except Exception as error:
            if _is_unique_violation(error):
                raise PersistenceConflict("record identity already exists") from error
            raise
        return payload

    def get_replay(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        idempotency_key: str,
    ) -> tuple[str, str | None, dict[str, Any], int] | None:
        """Resolve a scoped replay key without disclosing another namespace."""
        if not idempotency_key or len(idempotency_key) > 300:
            raise ValueError("idempotency_key_invalid")
        with self.database.connection() as connection:
            row = connection.execute(
                f"SELECT record_id,fingerprint,payload,revision FROM {self.family} "
                "WHERE scope_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND idempotency_key=%s",
                (
                    self.scope_id(owner_id, scope), owner_id, scope.application_id,
                    scope.workspace_id, idempotency_key,
                ),
            ).fetchone()
        return None if row is None else (row[0], row[1], row[2], row[3])

    def create_idempotent(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        record_id: str,
        idempotency_key: str,
        fingerprint: str,
        payload: dict[str, Any],
        status: str | None = None,
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Commit an immutable family record and replay key in one transaction."""
        if not idempotency_key or len(idempotency_key) > 300:
            raise ValueError("idempotency_key_invalid")
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ValueError("fingerprint_invalid")
        try:
            with self.database.transaction() as connection:
                scope_id = _ensure_namespace(connection, owner_id, scope)
                existing = connection.execute(
                    f"SELECT record_id,fingerprint,payload FROM {self.family} "
                    "WHERE scope_id=%s AND idempotency_key=%s FOR UPDATE",
                    (scope_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    if existing[1] != fingerprint:
                        raise PersistenceConflict("idempotency fingerprint conflict")
                    return existing[2], False
                connection.execute(
                    f"INSERT INTO {self.family}(record_id,scope_id,owner_id,application_id,"
                    "workspace_id,record_version,status,revision,created_at,expires_at,fingerprint,"
                    "idempotency_key,payload) VALUES (%s,%s,%s,%s,%s,1,%s,1,%s,%s,%s,%s,%s::jsonb)",
                    (
                        record_id, scope_id, owner_id, scope.application_id, scope.workspace_id,
                        status, _datetime(created_at) or datetime.now(UTC), _datetime(expires_at),
                        fingerprint, idempotency_key, self._json(payload),
                    ),
                )
        except Exception as error:
            if not _is_unique_violation(error):
                raise
            replay = self.get_replay(
                owner_id=owner_id, scope=scope, idempotency_key=idempotency_key
            )
            if replay is None:
                raise PersistenceConflict("idempotency key conflicted with another record") from error
            if replay[1] != fingerprint:
                raise PersistenceConflict("idempotency fingerprint conflict") from error
            return replay[2], False
        return payload, True

    def append_event(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        aggregate_id: str,
        record_id: str,
        payload: dict[str, Any],
        fingerprint: str,
        idempotency_key: str,
        created_at: datetime | None = None,
    ) -> tuple[dict[str, Any], int, bool]:
        """Append one ordered event with scoped replay arbitration in one P transaction."""
        if self.family not in {"memory_lifecycle_events", "audit_events"}:
            raise ValueError("event_family_invalid")
        if not aggregate_id or len(aggregate_id) > 512:
            raise ValueError("aggregate_id_invalid")
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ValueError("fingerprint_invalid")
        timestamp = _datetime(created_at) or datetime.now(UTC)
        scope_id = self.scope_id(owner_id, scope)
        replay = self._get_event_replay(owner_id, scope, idempotency_key)
        if replay is not None:
            if replay[1] != fingerprint:
                raise PersistenceConflict("event idempotency fingerprint conflict")
            return replay[2], replay[3], False
        try:
            with self.database.transaction() as connection:
                _ensure_namespace(connection, owner_id, scope)
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    (f"{scope_id}:{self.family}:{aggregate_id}",),
                )
                existing = connection.execute(
                    f"SELECT record_id,fingerprint,payload,event_sequence FROM {self.family} "
                    "WHERE scope_id=%s AND idempotency_key=%s FOR UPDATE",
                    (scope_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    if existing[1] != fingerprint:
                        raise PersistenceConflict("event idempotency fingerprint conflict")
                    return existing[2], existing[3], False
                sequence = connection.execute(
                    f"SELECT COALESCE(MAX(event_sequence),0)+1 FROM {self.family} "
                    "WHERE scope_id=%s AND aggregate_id=%s",
                    (scope_id, aggregate_id),
                ).fetchone()[0]
                connection.execute(
                    f"INSERT INTO {self.family}(record_id,scope_id,owner_id,application_id,"
                    "workspace_id,record_version,status,revision,event_sequence,aggregate_id,"
                    "created_at,fingerprint,idempotency_key,payload) "
                    "VALUES (%s,%s,%s,%s,%s,1,'active',1,%s,%s,%s,%s,%s,%s::jsonb)",
                    (
                        record_id, scope_id, owner_id, scope.application_id, scope.workspace_id,
                        sequence, aggregate_id, timestamp, fingerprint, idempotency_key,
                        self._json(payload),
                    ),
                )
        except Exception as error:
            if not _is_unique_violation(error):
                raise
            replay = self._get_event_replay(owner_id, scope, idempotency_key)
            if replay is None or replay[1] != fingerprint:
                raise PersistenceConflict("event replay conflict") from error
            return replay[2], replay[3], False
        return payload, sequence, True

    def _get_event_replay(
        self, owner_id: str, scope: ApplicationScope, idempotency_key: str
    ) -> tuple[str, str | None, dict[str, Any], int] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                f"SELECT record_id,fingerprint,payload,event_sequence FROM {self.family} "
                "WHERE scope_id=%s AND owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND idempotency_key=%s",
                (
                    self.scope_id(owner_id, scope), owner_id, scope.application_id,
                    scope.workspace_id, idempotency_key,
                ),
            ).fetchone()
        if row is None:
            return None
        if row[3] is None:
            raise PersistenceConflict("event replay record has no sequence")
        return row[0], row[1], row[2], row[3]

    def replace(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        record_id: str,
        expected_revision: int,
        payload: dict[str, Any],
        status: str | None = None,
        expires_at: datetime | None = None,
    ) -> int:
        query = f"UPDATE {self.family} SET payload=%s::jsonb, status=%s, expires_at=%s, revision=revision+1 WHERE scope_id=%s AND record_id=%s AND owner_id=%s AND application_id=%s AND workspace_id IS NOT DISTINCT FROM %s AND revision=%s RETURNING revision"
        with self.database.connection() as connection:
            row = connection.execute(
                query,
                (
                    self._json(payload),
                    status,
                    _datetime(expires_at),
                    self.scope_id(owner_id, scope),
                    record_id,
                    owner_id,
                    scope.application_id,
                    scope.workspace_id,
                    expected_revision,
                ),
            ).fetchone()
        if row is None:
            raise PersistenceConflict("record revision or scope changed")
        return row[0]

    def indexed(
        self,
        *,
        owner_id: str,
        scope: ApplicationScope,
        status: str | None = None,
        before: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("persistence_limit_invalid")
        clauses = [
            "scope_id = %s",
            "owner_id = %s",
            "application_id = %s",
            "workspace_id IS NOT DISTINCT FROM %s",
        ]
        params: list[Any] = [
            self.scope_id(owner_id, scope),
            owner_id,
            scope.application_id,
            scope.workspace_id,
        ]
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if before is not None:
            clauses.append("expires_at < %s")
            params.append(_datetime(before))
        params.append(limit)
        query = (
            f"SELECT payload FROM {self.family} WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at, record_id LIMIT %s"
        )
        with self.database.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [row[0] for row in rows]


class PostgresFamilyTransaction:
    """A repository-scoped transaction for preserving same-store write groups."""

    def __init__(self, database: PostgresDatabase, *, owner_id: str, scope: ApplicationScope):
        self.database = database
        self.owner_id = owner_id
        self.scope = scope
        self.scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        with self.database.transaction() as connection:
            _ensure_namespace(connection, self.owner_id, self.scope)
            yield connection


def _ensure_namespace(connection: Any, owner_id: str, scope: ApplicationScope) -> str:
    scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
    connection.execute(
        "INSERT INTO scope_namespaces(scope_id, owner_id, application_id, workspace_id) "
        "VALUES (%s,%s,%s,%s) ON CONFLICT (scope_id) DO NOTHING",
        (scope_id, owner_id, scope.application_id, scope.workspace_id),
    )
    row = connection.execute(
        "SELECT owner_id, application_id, workspace_id FROM scope_namespaces WHERE scope_id=%s",
        (scope_id,),
    ).fetchone()
    if row != (owner_id, scope.application_id, scope.workspace_id):
        raise PersistenceConflict("scope namespace collision")
    return scope_id


def _datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time(), UTC)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp_invalid")
    return value.astimezone(UTC)


def _is_unique_violation(error: Exception) -> bool:
    return error.__class__.__name__ == "UniqueViolation"


def _is_connection_error(error: Exception) -> bool:
    return error.__class__.__name__ in {
        "OperationalError",
        "PoolTimeout",
        "ConnectionTimeout",
        "ConnectionFailure",
    }
