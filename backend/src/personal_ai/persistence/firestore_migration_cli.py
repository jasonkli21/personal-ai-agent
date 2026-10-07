"""Operator entry point for P10.4; never participates in normal runtime startup."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
from dataclasses import asdict
from pathlib import Path

from personal_ai.persistence.firestore_migration import (
    DynamoDBMigrationTarget,
    GoogleFirestoreMigrationSource,
    PostgresMigrationControl,
    PostgresMigrationTarget,
    run_migration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded Firestore-to-polyglot migration")
    parser.add_argument("--source-project", required=True)
    parser.add_argument("--source-database", default="(default)")
    parser.add_argument("--epoch", required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-records", type=int, default=500_000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--final-delta", action="store_true")
    parser.add_argument("--writers-frozen", action="store_true")
    parser.add_argument("--review-expired-counters", action="store_true")
    parser.add_argument("--strict-zero-report", type=Path)
    parser.add_argument("--strict-zero-maximum-age-days", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environment = os.environ.get("APP_ENVIRONMENT", "production")
    local_ddb_endpoint = os.environ.get("P10_MIGRATION_DYNAMODB_LOCAL_ENDPOINT", "")
    local_firestore = bool(os.environ.get("FIRESTORE_EMULATOR_HOST", "").strip())
    if environment in {"staging", "production"} and local_ddb_endpoint:
        raise SystemExit("deployed migration cannot target DynamoDB Local")
    if not local_firestore or (not args.dry_run and not local_ddb_endpoint):
        if args.strict_zero_report is None or args.strict_zero_maximum_age_days is None:
            raise SystemExit(
                "cloud source reads or targets require --strict-zero-report and "
                "--strict-zero-maximum-age-days"
            )
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
            raise SystemExit("strict-$0 gate blocks migration: " + ",".join(failures))
    source = GoogleFirestoreMigrationSource(
        args.source_project, database_id=args.source_database
    )
    if args.dry_run:
        result = run_migration(
            source=source,
            control=None,
            postgres_target=None,
            dynamodb_target=None,
            epoch_id=args.epoch,
            database_id=args.source_database,
            batch_size=args.batch_size,
            max_records=args.max_records,
            dry_run=True,
            final_delta=args.final_delta,
            writers_frozen=args.writers_frozen,
            review_expired_counters=args.review_expired_counters,
        )
        print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
        return 0 if not result.rejected else 2

    dsn = os.environ.get("P10_MIGRATION_POSTGRES_DSN", "")
    if not dsn:
        raise SystemExit("P10_MIGRATION_POSTGRES_DSN is required")
    if environment in {"staging", "production"}:
        from personal_ai.persistence.neon import NeonDirectDatabase

        database = NeonDirectDatabase(dsn, environment=environment, max_size=2)
    else:
        from personal_ai.persistence.postgres import PostgresDatabase

        database = PostgresDatabase(
            dsn,
            environment=environment,
            min_size=0,
            max_size=2,
            connect_timeout=5,
            statement_timeout_ms=30_000,
            lock_timeout_ms=5_000,
            pool_timeout=10,
            prepare_threshold=None,
        )
    table = None
    try:
        with database.connection() as connection:
            version = connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
        if version is None or int(version) < 12:
            raise SystemExit("P10 target SQL migrations 001–012 must be applied with migration credentials")

        if local_ddb_endpoint:
            from personal_ai.persistence.dynamodb import DynamoDBRuntimeTable

            table = DynamoDBRuntimeTable(
                local_ddb_endpoint,
                table_name=os.environ.get("P10_DYNAMODB_TABLE_NAME", "personal-ai-runtime-v1"),
                region=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            )
        else:
            role_arn = os.environ.get("P10_MIGRATION_AWS_ROLE_ARN", "")
            audience = os.environ.get("P10_AWS_OIDC_AUDIENCE", "")
            if not role_arn or not audience:
                raise SystemExit(
                    "P10_MIGRATION_AWS_ROLE_ARN and P10_AWS_OIDC_AUDIENCE are required"
                )
            from personal_ai.persistence.dynamodb_cloud import (
                FederatedDynamoDBConfig,
                FederatedDynamoDBRuntimeTable,
            )

            table = FederatedDynamoDBRuntimeTable(FederatedDynamoDBConfig(
                region=os.environ.get("AWS_REGION", "us-east-1"),
                table_name=os.environ.get("P10_DYNAMODB_TABLE_NAME", "personal-ai-runtime-v1"),
                role_arn=role_arn,
                identity_token_audience=audience,
                role_session_name="personal-ai-migration",
            ))
        result = run_migration(
            source=source,
            control=PostgresMigrationControl(database),
            postgres_target=PostgresMigrationTarget(database, PostgresMigrationControl(database)),
            dynamodb_target=DynamoDBMigrationTarget(table),
            epoch_id=args.epoch,
            database_id=args.source_database,
            batch_size=args.batch_size,
            max_records=args.max_records,
            final_delta=args.final_delta,
            writers_frozen=args.writers_frozen,
            review_expired_counters=args.review_expired_counters,
        )
        print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
        return 0 if not result.rejected and not result.conflicts else 2
    finally:
        if table is not None:
            table.close()
        database.close()


if __name__ == "__main__":
    sys.exit(main())
