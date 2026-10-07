"""Deterministic local persistence readiness and bootstrap commands."""

from __future__ import annotations

import argparse
import os

from personal_ai.persistence.dynamodb import DynamoDBRuntimeTable
from personal_ai.persistence.postgres import PostgresDatabase


def _targets(*, test: bool = False):
    dsn = os.environ.get(
        "PERSISTENCE_TEST_POSTGRES_DSN" if test else "PERSISTENCE_POSTGRES_DSN", ""
    )
    endpoint = os.environ.get(
        "PERSISTENCE_TEST_DYNAMODB_ENDPOINT" if test else "DYNAMODB_LOCAL_ENDPOINT", ""
    )
    if not dsn or not endpoint:
        raise SystemExit("explicit local Postgres DSN and DynamoDB Local endpoint are required")
    return (
        PostgresDatabase(dsn, environment="test" if test else "local"),
        DynamoDBRuntimeTable(
            endpoint,
            table_name=os.environ.get("DYNAMODB_TABLE_NAME", "personal-ai-runtime-v1"),
            region=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("ready", "bootstrap"))
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    database, table = _targets(test=args.test)
    try:
        if args.command == "bootstrap":
            versions = database.migrate()
            table.bootstrap()
            print(f"Postgres schema ready; migrations applied: {list(versions)}")
            print(f"DynamoDB Local table ready: {table.table_name}")
        else:
            with database.connection() as connection:
                connection.execute("SELECT 1").fetchone()
            table.client.list_tables(Limit=1)
            print("Postgres and DynamoDB Local are ready")
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
