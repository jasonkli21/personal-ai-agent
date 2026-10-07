"""Explicit schema/bootstrap command, separate from runtime process startup."""

from __future__ import annotations

import argparse
import json
import os
import runpy
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply the versioned P10 Postgres schema")
    parser.add_argument("--environment", choices=("local", "staging", "production"), required=True)
    parser.add_argument("--strict-zero-report", type=Path)
    parser.add_argument("--strict-zero-maximum-age-days", type=int)
    args = parser.parse_args(argv)
    if args.environment != "local":
        if args.strict_zero_report is None or args.strict_zero_maximum_age_days is None:
            raise SystemExit("cloud schema work requires strict-$0 review evidence")
        root = Path(__file__).resolve().parents[4]
        gate = runpy.run_path(root / "infrastructure/phase10/strict_zero_release_gate.py")
        try:
            report = json.loads(args.strict_zero_report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit("strict-$0 report is unreadable") from error
        failures = gate["validate_report"](
            report, maximum_age_days=args.strict_zero_maximum_age_days
        )
        if failures:
            raise SystemExit("strict-$0 gate blocks schema work: " + ",".join(failures))
    dsn = os.environ.get("P10_SCHEMA_POSTGRES_DSN", "")
    if not dsn:
        raise SystemExit("P10_SCHEMA_POSTGRES_DSN is required")
    if args.environment in {"staging", "production"}:
        from personal_ai.persistence.neon import NeonDirectDatabase

        database = NeonDirectDatabase(dsn, environment=args.environment, max_size=1)
    else:
        from personal_ai.persistence.postgres import PostgresDatabase

        database = PostgresDatabase(
            dsn,
            environment=args.environment,
            min_size=0,
            max_size=1,
            connect_timeout=5,
            statement_timeout_ms=60_000,
            lock_timeout_ms=10_000,
            pool_timeout=10,
            prepare_threshold=None,
        )
    try:
        versions = database.migrate()
        with database.connection() as connection:
            current = connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
        print(f"Postgres schema version: {current}; migrations applied: {list(versions)}")
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
