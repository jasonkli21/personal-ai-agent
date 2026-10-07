"""Backend-neutral account counters and shared provider control adapters."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from time import monotonic

from personal_ai.auth.scope import ApplicationScope
from personal_ai.persistence.dynamodb import DynamoDBRuntimeTable, _b64
from personal_ai.persistence.postgres import (
    PostgresDatabase,
    PostgresPayloadRepository,
    _ensure_namespace,
)


class PostgresDailyBudgetRepository:
    """Atomic account-wide daily usage reservation in Postgres."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    def reserve_daily(
        self, owner_id: str, calls: int, tokens: int, call_limit: int, token_limit: int
    ) -> int:
        if calls < 0 or tokens < 0 or call_limit < 1 or token_limit < 1:
            raise ValueError("usage_reservation_invalid")
        from personal_ai.auth.safeguards import SafeguardDenied

        if calls > call_limit or tokens > token_limit:
            raise SafeguardDenied("daily_budget_exceeded", 1)

        now = datetime.now(UTC)
        day = now.date()
        period_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC)
        retry_after = int((period_end - now).total_seconds())
        expires_at = period_end + timedelta(days=90)
        scope = ApplicationScope(application_id="personal_ai", workspace_id=None)
        scope_id = PostgresPayloadRepository.scope_id(owner_id, scope)
        record_id = f"usage:{day.isoformat()}"
        with self.database.transaction() as connection:
            _ensure_namespace(connection, owner_id, scope)
            row = connection.execute(
                "INSERT INTO usage_budgets(scope_id,record_id,owner_id,application_id,workspace_id,"
                "record_version,status,revision,created_at,expires_at,budget_day,provider_calls,input_tokens,payload) "
                "VALUES (%s,%s,%s,%s,NULL,1,'active',1,%s,%s,%s,%s,%s,'{}'::jsonb) "
                "ON CONFLICT (scope_id,budget_day) WHERE budget_day IS NOT NULL DO UPDATE SET "
                "provider_calls=usage_budgets.provider_calls+EXCLUDED.provider_calls, "
                "input_tokens=usage_budgets.input_tokens+EXCLUDED.input_tokens, "
                "revision=usage_budgets.revision+1,updated_at=%s,expires_at=EXCLUDED.expires_at "
                "WHERE usage_budgets.provider_calls+EXCLUDED.provider_calls<=%s "
                "AND usage_budgets.input_tokens+EXCLUDED.input_tokens<=%s "
                "RETURNING provider_calls,input_tokens",
                (
                    scope_id,
                    record_id,
                    owner_id,
                    scope.application_id,
                    now,
                    expires_at,
                    day,
                    calls,
                    tokens,
                    now,
                    call_limit,
                    token_limit,
                ),
            ).fetchone()
        if row is None:
            raise SafeguardDenied("daily_budget_exceeded", retry_after)
        return retry_after


class DynamoDBSafeguardStore:
    """DynamoDB owner-wide request windows plus a Postgres daily budget adapter."""

    def __init__(self, table: DynamoDBRuntimeTable, daily_budgets: PostgresDailyBudgetRepository):
        self.table = table
        self.daily_budgets = daily_budgets

    def consume_request(self, owner_id: str, limit: int) -> int:
        from botocore.exceptions import ClientError

        from personal_ai.auth.safeguards import SafeguardDenied, SafeguardUnavailable

        now = datetime.now(UTC)
        epoch = int(now.timestamp() // 60)
        retry_after = 60 - int(now.timestamp() % 60)
        key = {"PK": f"OWNER#{_b64(owner_id)}", "SK": f"RATE#{epoch}"}
        try:
            self.table.client.update_item(
                TableName=self.table.table_name,
                Key=_ddb_marshal(key),
                UpdateExpression="SET #start=if_not_exists(#start,:start),#expires=:expires,#policy=:policy ADD #count :one",
                ConditionExpression="attribute_not_exists(#count) OR #count < :limit",
                ExpressionAttributeNames={
                    "#start": "window_start", "#expires": "expires_at",
                    "#policy": "policy_version", "#count": "request_count",
                },
                ExpressionAttributeValues=_ddb_marshal({
                    ":start": _minute_timestamp(epoch),
                    ":expires": _minute_timestamp(epoch + 2),
                    ":policy": "request-rate-v1",
                    ":one": 1,
                    ":limit": limit,
                }),
            )
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code == "ConditionalCheckFailedException":
                raise SafeguardDenied("rate_limit_exceeded", retry_after) from error
            raise SafeguardUnavailable("request safeguard unavailable") from error
        return retry_after

    def reserve_daily(self, owner_id: str, calls: int, tokens: int, call_limit: int, token_limit: int) -> int:
        return self.daily_budgets.reserve_daily(owner_id, calls, tokens, call_limit, token_limit)


class PostgresDomainProviderRateLimiter:
    """Shared serialized interval slots backed by one compact Postgres control row."""

    def __init__(self, database: PostgresDatabase, provider: str):
        if not provider or len(provider) > 100:
            raise ValueError("provider_id_invalid")
        self.database = database
        self.provider = provider

    async def wait(self, interval: float, *, deadline: float) -> None:
        loop = asyncio.get_running_loop()
        slot = await loop.run_in_executor(None, self._reserve, interval, deadline)
        delay = max(0.0, slot - monotonic())
        if delay >= max(0.0, deadline - monotonic()):
            raise TimeoutError("provider request deadline")
        await asyncio.sleep(delay)
        if monotonic() >= deadline:
            raise TimeoutError("provider request deadline")

    def _reserve(self, interval: float, deadline: float) -> float:
        wall_now = datetime.now(UTC)
        monotonic_now = monotonic()
        if deadline - monotonic_now <= 0:
            raise TimeoutError("provider request deadline")
        with self.database.transaction() as connection:
            row = connection.execute(
                "INSERT INTO domain_provider_rate_limits(provider_id,next_available_at,revision,updated_at) "
                "VALUES (%s,%s + (%s * interval '1 second'),1,%s) "
                "ON CONFLICT(provider_id) DO UPDATE SET next_available_at="
                "GREATEST(domain_provider_rate_limits.next_available_at,%s) + (%s * interval '1 second'),"
                "revision=domain_provider_rate_limits.revision+1,updated_at=EXCLUDED.updated_at "
                "RETURNING next_available_at",
                (self.provider, wall_now, interval, wall_now, wall_now, interval),
            ).fetchone()
            slot = row[0] - timedelta(seconds=interval)
            slot_monotonic = monotonic_now + max(0.0, (slot - wall_now).total_seconds())
            if slot_monotonic >= deadline:
                raise TimeoutError("provider request deadline")
            return slot_monotonic


def _ddb_marshal(value):
    from boto3.dynamodb.types import TypeSerializer

    serializer = TypeSerializer()
    return {key: serializer.serialize(item) for key, item in value.items()}


def _minute_timestamp(epoch: int) -> str:
    return datetime.fromtimestamp(epoch * 60, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
