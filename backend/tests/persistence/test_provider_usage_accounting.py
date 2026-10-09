from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest

from personal_ai.persistence.postgres import PostgresDatabase
from personal_ai.persistence.postgres_usage import PostgresProviderUsageAccounting
from personal_ai.routing.contracts import QuotaBucket
from personal_ai.usage.accounting import unit_reservations
from personal_ai.usage.contracts import (
    AttemptMetadata,
    AttemptResult,
    InvocationMetadata,
    ProviderEndpoint,
    UsageAdmissionDenied,
)

pytestmark = pytest.mark.persistence_integration


@pytest.fixture
def postgres_database():
    dsn = os.environ.get("PERSISTENCE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set PERSISTENCE_TEST_POSTGRES_DSN to an isolated local pgvector database")
    database = PostgresDatabase(dsn, environment="test", min_size=1, max_size=4)
    try:
        database.migrate()
        yield database
    finally:
        database.close()


def _bucket(
    bucket_id: str,
    authority: str,
    *,
    limit: int | None,
    unit: str = "requests",
    reservation_units_per_request: int | None = None,
) -> QuotaBucket:
    return QuotaBucket(
        bucket_id=bucket_id,
        authority_scope_id=authority,
        operations=frozenset({"bounded_generation"}),
        unit=unit,
        window_seconds=3600,
        source="operator_attestation" if limit is not None else "unknown",
        confidence="reported" if limit is not None else "unknown",
        reservation_units_per_request=reservation_units_per_request,
        evidence_reference="synthetic:provider-usage-test" if limit is not None else None,
        limit=limit,
    )


def _invocation(owner: str, request_id: str, endpoint: ProviderEndpoint) -> InvocationMetadata:
    return InvocationMetadata(
        invocation_id=uuid4(),
        owner_id=owner,
        application_id="personal_ai",
        workspace_id=None,
        task_id="provider_usage_test",
        operation="bounded_generation",
        request_id=request_id,
        run_id=None,
        endpoint=endpoint,
    )


def _endpoint(
    profile_id: str,
    *,
    account: str,
    credential: str,
    buckets: tuple[QuotaBucket, ...],
) -> ProviderEndpoint:
    return ProviderEndpoint(
        endpoint_profile_id=profile_id,
        profile_version=1,
        provider_id="synthetic-provider",
        model_id=profile_id,
        endpoint_id="synthetic-chat-v1",
        deployment_id="synthetic.example-v1",
        credential_source="environment",
        credential_scope_id=credential,
        account_scope_id=account,
        project_scope_id=None,
        tier_id="synthetic",
        execution_mode="STRICT_FREE",
        cost_class="UNKNOWN",
        billing_owner="unknown",
        serializer_id="synthetic-json-v1",
        runtime_id="test-http-v1",
        quota_buckets=buckets,
    )


def _attempt(*, reservation_units=None, reserved_tokens=0) -> AttemptMetadata:
    return AttemptMetadata(
        attempt_id=uuid4(),
        parent_attempt_id=None,
        send_number=1,
        started_at=datetime.now(UTC),
        reservation_units=reservation_units or unit_reservations(),
        reserved_tokens=reserved_tokens,
    )


def _settle(accounting, invocation, attempt, *, unit_usage=(), usage_confidence="exact"):
    accounting.settle_attempt(
        invocation,
        attempt,
        AttemptResult(
            outcome="success",
            completed_at=datetime.now(UTC),
            latency_ms=3,
            input_tokens=3,
            output_tokens=2,
            total_tokens=5,
            usage_source="provider",
            usage_confidence=usage_confidence,
            unit_usage=unit_usage,
            unit_usage_source="provider" if unit_usage else "unknown",
            unit_usage_confidence="exact" if unit_usage else "unknown",
        ),
    )


def _bucket_state(database, bucket_id):
    with database.connection(snapshot=True) as connection:
        return connection.execute(
            "SELECT authority_scope_id,unit,confidence,limit_units,reported_remaining,"
            "consumed_units,reserved_units FROM provider_quota_bucket_windows "
            "WHERE bucket_id=%s ORDER BY window_start DESC LIMIT 1",
            (bucket_id,),
        ).fetchone()


def test_shared_bucket_admission_is_atomic_across_owners_and_credential_rotation(
    postgres_database,
):
    bucket_id = f"synthetic-shared-{uuid4()}"
    authority = f"synthetic-account-{uuid4()}"
    bucket = _bucket(bucket_id, authority, limit=1)
    accounting = PostgresProviderUsageAccounting(postgres_database)
    invocations = [
        _invocation(
            f"owner-{index}",
            f"request-{uuid4()}",
            _endpoint(
                f"synthetic:endpoint-{index}",
                account=authority,
                credential=f"synthetic:key-{index}",
                buckets=(bucket,),
            ),
        )
        for index in range(2)
    ]
    attempts = [_attempt(), _attempt()]
    for invocation in invocations:
        accounting.begin_invocation(invocation)
    barrier = Barrier(2)

    def reserve(index):
        barrier.wait(timeout=3)
        try:
            accounting.reserve_attempt(invocations[index], attempts[index], max_attempts=10)
            return "admitted"
        except UsageAdmissionDenied as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, range(2)))

    assert outcomes.count("admitted") == 1
    assert outcomes.count("provider_quota_exhausted") == 1
    admitted = outcomes.index("admitted")
    _settle(accounting, invocations[admitted], attempts[admitted])
    state = _bucket_state(postgres_database, bucket_id)
    assert state == (authority, "requests", "derived", 1, None, 1, 0)


def test_unknown_quota_keeps_unknown_confidence_and_tracks_local_usage(postgres_database):
    bucket_id = f"synthetic-unknown-{uuid4()}"
    authority = f"synthetic-account-{uuid4()}"
    bucket = _bucket(bucket_id, authority, limit=None)
    endpoint = _endpoint(
        f"synthetic:endpoint-{uuid4()}",
        account=authority,
        credential="synthetic:key",
        buckets=(bucket,),
    )
    invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    attempt = _attempt()
    accounting = PostgresProviderUsageAccounting(postgres_database)

    accounting.begin_invocation(invocation)
    accounting.reserve_attempt(invocation, attempt, max_attempts=10)
    before = _bucket_state(postgres_database, bucket_id)
    _settle(accounting, invocation, attempt)
    after = _bucket_state(postgres_database, bucket_id)

    assert before == (authority, "requests", "unknown", None, None, 0, 1)
    assert after == (authority, "requests", "unknown", None, None, 1, 0)


def test_all_required_quota_buckets_reserve_or_deny_without_partial_units(
    postgres_database,
):
    authority_a = f"synthetic-account-a-{uuid4()}"
    authority_b = f"synthetic-account-b-{uuid4()}"
    available_id = f"synthetic-available-{uuid4()}"
    exhausted_id = f"synthetic-exhausted-{uuid4()}"
    buckets = (
        _bucket(available_id, authority_a, limit=5),
        _bucket(exhausted_id, authority_b, limit=0, unit="tokens"),
    )
    endpoint = _endpoint(
        f"synthetic:endpoint-{uuid4()}",
        account=authority_a,
        credential="synthetic:key",
        buckets=buckets,
    )
    invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    accounting = PostgresProviderUsageAccounting(postgres_database)

    accounting.begin_invocation(invocation)
    with pytest.raises(UsageAdmissionDenied, match="provider_quota_exhausted"):
        accounting.reserve_attempt(
            invocation,
            _attempt(reservation_units=unit_reservations(input_tokens=1, output_tokens=1)),
            max_attempts=10,
        )

    available = _bucket_state(postgres_database, available_id)
    exhausted = _bucket_state(postgres_database, exhausted_id)
    assert available[-1] == 0
    assert exhausted[-1] == 0


def test_generic_provider_units_reserve_estimate_and_settle_exact_usage(postgres_database):
    bucket_id = f"synthetic-neurons-{uuid4()}"
    authority = f"synthetic-account-{uuid4()}"
    bucket = _bucket(
        bucket_id,
        authority,
        limit=100,
        unit="neurons",
        reservation_units_per_request=20,
    )
    endpoint = _endpoint(
        f"synthetic:endpoint-{uuid4()}",
        account=authority,
        credential="synthetic:key",
        buckets=(bucket,),
    )
    invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    attempt = _attempt()
    events = []
    accounting = PostgresProviderUsageAccounting(
        postgres_database,
        operational_event_writer=events.append,
    )

    accounting.begin_invocation(invocation)
    accounting.reserve_attempt(invocation, attempt, max_attempts=10)
    with postgres_database.connection(snapshot=True) as connection:
        reserved = connection.execute(
            "SELECT reserved_units FROM provider_quota_reservations WHERE attempt_id=%s",
            (attempt.attempt_id,),
        ).fetchone()[0]
    _settle(
        accounting,
        invocation,
        attempt,
        unit_usage=(("neurons", 13),),
        usage_confidence="unknown",
    )
    state = _bucket_state(postgres_database, bucket_id)
    with postgres_database.connection(snapshot=True) as connection:
        settled = connection.execute(
            "SELECT settled_units,state FROM provider_quota_reservations WHERE attempt_id=%s",
            (attempt.attempt_id,),
        ).fetchone()

    assert reserved == 20
    assert settled == (13, "settled")
    assert state[-2:] == (13, 0)
    assert events[0]["unit_usage"] == {"neurons": 13}
    assert events[0]["unit_usage_confidence"] == "exact"
