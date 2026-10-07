"""Cloud-only Neon validation; Firestore remains the selected runtime backend."""

from __future__ import annotations

from urllib.parse import urlsplit

from personal_ai.persistence.postgres import PostgresDatabase


class NeonRuntimeDatabase(PostgresDatabase):
    """Bounded transaction-pooled Neon connection for a future explicit cutover."""

    def __init__(self, dsn: str, *, environment: str, max_size: int = 4) -> None:
        if environment not in {"staging", "production"}:
            raise ValueError("neon_runtime_requires_deployed_environment")
        if not 1 <= max_size <= 4:
            raise ValueError("neon_runtime_pool_bound_invalid")
        parsed = urlsplit(dsn)
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host.endswith(".neon.tech") or "-pooler." not in host:
            raise ValueError("neon_transaction_pooler_required")
        super().__init__(
            dsn,
            environment=environment,
            min_size=0,
            max_size=max_size,
            connect_timeout=5,
            statement_timeout_ms=5_000,
            lock_timeout_ms=2_000,
            pool_timeout=3,
            prepare_threshold=None,
        )


class NeonDirectDatabase(PostgresDatabase):
    """Bounded direct Neon connection for schema and storage-migration work."""

    def __init__(self, dsn: str, *, environment: str, max_size: int = 2) -> None:
        if environment not in {"staging", "production"}:
            raise ValueError("neon_direct_requires_deployed_environment")
        if not 1 <= max_size <= 2:
            raise ValueError("neon_direct_pool_bound_invalid")
        parsed = urlsplit(dsn)
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host.endswith(".neon.tech") or "-pooler." in host:
            raise ValueError("neon_direct_endpoint_required")
        super().__init__(
            dsn,
            environment=environment,
            min_size=0,
            max_size=max_size,
            connect_timeout=5,
            statement_timeout_ms=30_000,
            lock_timeout_ms=5_000,
            pool_timeout=10,
            prepare_threshold=None,
        )
