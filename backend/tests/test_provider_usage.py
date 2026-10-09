from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import anyio

from personal_ai.auth.account_data import EXPORT_COLLECTIONS
from personal_ai.auth.owner_data import OWNER_DATA_COLLECTIONS
from personal_ai.persistence.dynamodb_usage import (
    PROVIDER_USAGE_EVENT_FIELDS,
    DynamoDBProviderUsageEventRepository,
)
from personal_ai.persistence.postgres_usage import _operational_event
from personal_ai.routing.configured import build_initial_endpoint_profiles
from personal_ai.settings import Settings
from personal_ai.usage.accounting import new_invocation, unit_reservations
from personal_ai.usage.async_call import AsyncProviderCall, rate_limit_metadata
from personal_ai.usage.context import bind_usage_task
from personal_ai.usage.contracts import AttemptMetadata, AttemptResult, ProviderEndpoint
from personal_ai.usage.profiles import public_lookup_endpoint


def _endpoint() -> ProviderEndpoint:
    return ProviderEndpoint(
        endpoint_profile_id="fixture:endpoint",
        profile_version=1,
        provider_id="fixture-provider",
        model_id="fixture-model",
        endpoint_id="fixture-http-v1",
        deployment_id="fixture.example-v1",
        credential_source="none",
        credential_scope_id=None,
        account_scope_id=None,
        project_scope_id=None,
        tier_id="unknown",
        execution_mode="STRICT_FREE",
        cost_class="UNKNOWN",
        billing_owner="unknown",
        serializer_id="fixture-json-v1",
        runtime_id="httpx-v1",
    )


def test_invocations_inherit_task_and_run_scope_and_get_unique_fallback_request_ids():
    with bind_usage_task("research_synthesis", run_id="research-run-7"):
        first = new_invocation(
            _endpoint(), operation="generation", quota_operation="bounded_generation"
        )
        second = new_invocation(
            _endpoint(), operation="generation", quota_operation="bounded_generation"
        )

    assert first.task_id == second.task_id == "research_synthesis"
    assert first.run_id == second.run_id == "research-run-7"
    assert first.owner_id == "local"
    assert first.request_id != "unscoped"
    assert first.request_id != second.request_id


def test_provider_unit_reservations_preserve_separate_token_and_request_units():
    assert dict(unit_reservations(input_tokens=11, output_tokens=7)) == {
        "input_tokens": 11,
        "output_tokens": 7,
        "requests": 1,
        "tokens": 18,
    }
    assert dict(unit_reservations(additional_units={"neurons": 250})) == {
        "neurons": 250,
        "requests": 1,
    }


def test_public_lookup_profile_keeps_quota_capacity_unknown():
    endpoint = public_lookup_endpoint(
        provider_id="nominatim",
        model_id="geocoding-v1",
        endpoint_id="nominatim-search-v1",
        deployment_id="nominatim.openstreetmap.org",
        authority_scope_id="public-service",
    )

    bucket = endpoint.quota_buckets[0]
    assert bucket.authority_scope_id == "public-service"
    assert bucket.unit == "requests"
    assert bucket.confidence == "unknown"
    assert bucket.limit is None and bucket.remaining is None
    assert endpoint.quota_membership == "verified"


def test_brave_prepaid_tier_requires_and_carries_its_attestation():
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        ai_model="synthetic",
        research_enabled=True,
        research_search_adapter="brave",
        research_provider_storage_approved=True,
        research_api_key="synthetic-secret",
        research_brave_prepaid_verified=True,
        research_brave_auto_reload_disabled=True,
        research_brave_no_paid_balance_verified=True,
        research_brave_source_rights_verified=True,
        research_brave_account_scope_id="synthetic-brave-account",
        research_brave_preflight_reference="operator-preflight:synthetic-brave",
    )
    profile = next(
        item for item in build_initial_endpoint_profiles(settings)
        if item.endpoint_profile_id == "brave:search"
    )

    assert profile.tier_verified
    assert profile.strict_free_attestation is not None
    assert profile.strict_free_attestation.paid_overflow_excluded
    assert profile.strict_free_attestation.account_scope_id == "synthetic-brave-account"


def test_rate_limit_metadata_parses_only_bounded_numeric_facts():
    facts = rate_limit_metadata({
        "x-ratelimit-limit-requests": "20",
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-requests": "2s",
        "x-ratelimit-limit-tokens": "bad-secret-value",
        "retry-after": "1.5",
    })

    assert facts is not None
    assert facts.requests_limit == 20
    assert facts.requests_remaining == 0
    assert facts.requests_reset_seconds == 2
    assert facts.tokens_limit is None
    assert facts.retry_after_seconds == 1.5


def test_usage_records_are_included_in_owner_export_inventory():
    required = {
        "provider_invocations",
        "provider_attempts",
        "provider_quota_reservations",
        "provider_usage_daily_aggregates",
        "provider_usage_events",
    }
    assert required.issubset(OWNER_DATA_COLLECTIONS)
    assert required.issubset(EXPORT_COLLECTIONS)


def test_operational_event_schema_matches_the_export_contract():
    invocation = new_invocation(
        _endpoint(), operation="generation", quota_operation="bounded_generation"
    )
    started_at = datetime.now(UTC)
    attempt = AttemptMetadata(
        attempt_id=uuid4(), parent_attempt_id=None, send_number=1,
        started_at=started_at, reservation_units=(("requests", 1),),
    )
    result = AttemptResult(
        outcome="success", completed_at=datetime.now(UTC), latency_ms=8,
        unit_usage=(("neurons", 4),), unit_usage_source="provider_response",
        unit_usage_confidence="exact",
    )

    event = _operational_event(invocation, attempt, result)

    assert set(event) == PROVIDER_USAGE_EVENT_FIELDS
    assert "prompt" not in event and "response" not in event


def test_dynamodb_event_retention_uses_bounded_explicit_deletes():
    class Table:
        def __init__(self, locators):
            self.locators = locators
            self.queries = []
            self.transactions = []

        def query(self, **kwargs):
            self.queries.append(kwargs)
            return self.locators

        def transact(self, operations):
            self.transactions.append(operations)

    now = datetime.now(UTC)
    table = Table([{
        "PK": "MAINT#USAGE_EVENTS",
        "SK": "EXP#00000000000000000001#attempt",
        "record_pk": "N2#owner#USAGE",
        "record_sk": "PUE#2026-10-01T00:00:00.000000Z#attempt",
        "expires_at": int((now - timedelta(seconds=1)).timestamp()),
    }])
    repository = DynamoDBProviderUsageEventRepository(table)

    removed = repository.purge_expired(now=now, limit=10)

    assert removed == 1
    assert table.queries[0]["partition"] == "MAINT#USAGE_EVENTS"
    assert table.queries[0]["limit"] == 10
    assert len(table.transactions) == 1
    assert len(table.transactions[0]) == 2


def test_explicit_research_retries_keep_one_invocation_and_task_lineage():
    class Accounting:
        def __init__(self):
            self.invocations = []
            self.attempts = []
            self.completed = []

        def begin_invocation(self, invocation):
            self.invocations.append(invocation)

        def reserve_attempt(self, invocation, attempt, *, max_attempts):
            self.attempts.append((invocation, attempt, max_attempts))

        def settle_attempt(self, invocation, attempt, result):
            pass

        def complete_invocation(self, invocation, *, outcome, completed_at):
            self.completed.append((invocation, outcome))

    async def run():
        accounting = Accounting()
        for task_id in ("web_research_search", "iterative_research_search"):
            invocation_id = uuid4()
            for send_number, outcome in ((1, "server_error"), (2, "success")):
                with bind_usage_task(
                    task_id,
                    run_id=f"{task_id}-run",
                    request_id=f"{task_id}-request",
                    invocation_id=invocation_id,
                    send_number=send_number,
                ):
                    call = await AsyncProviderCall.begin(
                        accounting,
                        _endpoint(),
                        operation="search",
                        quota_operation="search",
                        max_attempts=3,
                    )
                    await call.reserve()
                    await call.finish(outcome)
        return accounting

    accounting = anyio.run(run)
    assert len(accounting.invocations) == 4
    assert len({item.invocation_id for item in accounting.invocations}) == 2
    assert {item.task_id for item in accounting.invocations} == {
        "web_research_search", "iterative_research_search"
    }
    assert {item.run_id for item in accounting.invocations} == {
        "web_research_search-run", "iterative_research_search-run"
    }
    assert {item.request_id for item in accounting.invocations} == {
        "web_research_search-request", "iterative_research_search-request"
    }
    for first, second in (
        (accounting.attempts[0][1], accounting.attempts[1][1]),
        (accounting.attempts[2][1], accounting.attempts[3][1]),
    ):
        assert first.send_number == 1 and first.parent_attempt_id is None
        assert second.send_number == 2 and second.parent_attempt_id == first.attempt_id
    assert accounting.completed[-1][1] == "success"
