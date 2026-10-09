from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import anyio
import httpx
import pytest

from personal_ai.persistence.postgres import PostgresDatabase
from personal_ai.persistence.postgres_usage import PostgresProviderUsageAccounting
from personal_ai.search.providers import brave
from personal_ai.search.providers.brave import BraveSearchAdapter, SearchError
from personal_ai.settings import Settings
from personal_ai.usage.accounting import unit_reservations
from personal_ai.usage.contracts import (
    AttemptMetadata,
    AttemptResult,
    InvocationMetadata,
    ProviderEndpoint,
    UsageAdmissionDenied,
)
from personal_ai.usage.quota import QuotaObservation as QuotaBucket

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
    window_seconds: int = 3600,
    reservation_units_per_request: int | None = None,
) -> QuotaBucket:
    return QuotaBucket(
        bucket_id=bucket_id,
        authority_scope_id=authority,
        operations=frozenset({"bounded_generation"}),
        unit=unit,
        window_seconds=window_seconds,
        source="operator_attestation" if limit is not None else "unknown",
        confidence="reported" if limit is not None else "unknown",
        reservation_units_per_request=reservation_units_per_request,
        evidence_reference="synthetic:provider-usage-test" if limit is not None else None,
        limit=limit,
    )


def _invocation(
    owner: str,
    request_id: str,
    endpoint: ProviderEndpoint,
    *,
    invocation_id=None,
    task_id="provider_usage_test",
) -> InvocationMetadata:
    return InvocationMetadata(
        invocation_id=invocation_id or uuid4(),
        owner_id=owner,
        application_id="personal_ai",
        workspace_id=None,
        task_id=task_id,
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
    profile_version: int = 1,
    model_id: str | None = None,
    quota_membership: str = "verified",
) -> ProviderEndpoint:
    return ProviderEndpoint(
        endpoint_profile_id=profile_id,
        profile_version=profile_version,
        provider_id="synthetic-provider",
        model_id=model_id or profile_id,
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
        quota_membership=quota_membership,
        quota_buckets=buckets,
    )


def _attempt(
    *,
    reservation_units=None,
    reserved_tokens=0,
    started_at=None,
    send_number=1,
    parent_attempt_id=None,
) -> AttemptMetadata:
    return AttemptMetadata(
        attempt_id=uuid4(),
        parent_attempt_id=parent_attempt_id,
        send_number=send_number,
        started_at=started_at or datetime.now(UTC),
        reservation_units=reservation_units or unit_reservations(),
        reserved_tokens=reserved_tokens,
    )


def _settle(
    accounting,
    invocation,
    attempt,
    *,
    unit_usage=(),
    usage_confidence="exact",
    outcome="success",
    completed_at=None,
):
    accounting.settle_attempt(
        invocation,
        attempt,
        AttemptResult(
            outcome=outcome,
            completed_at=completed_at or datetime.now(UTC),
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


@pytest.mark.parametrize(
    ("membership", "denial"),
    [
        ("unknown", "provider_quota_membership_unknown"),
        ("ambiguous", "provider_quota_membership_ambiguous"),
    ],
)
def test_unverified_quota_membership_is_denied_before_attempt_reservation(
    postgres_database,
    membership,
    denial,
):
    bucket = _bucket(f"membership-{uuid4()}", f"account-{uuid4()}", limit=None)
    endpoint = _endpoint(
        f"synthetic:endpoint-{uuid4()}",
        account=bucket.authority_scope_id,
        credential="synthetic:key",
        buckets=(bucket,),
        quota_membership=membership,
    )
    invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    attempt = _attempt()
    accounting = PostgresProviderUsageAccounting(postgres_database)
    accounting.begin_invocation(invocation)

    with pytest.raises(UsageAdmissionDenied, match=denial):
        accounting.reserve_attempt(invocation, attempt, max_attempts=10)

    with postgres_database.connection(snapshot=True) as connection:
        attempts = connection.execute(
            "SELECT count(*) FROM provider_attempts WHERE invocation_id=%s",
            (invocation.invocation_id,),
        ).fetchone()[0]
        attribution = connection.execute(
            "SELECT quota_membership,quota_confidence,outcome FROM provider_invocations "
            "WHERE invocation_id=%s",
            (invocation.invocation_id,),
        ).fetchone()
    assert attempts == 0
    assert attribution == (membership, "unknown", "rejected")


def test_brave_unknown_membership_does_not_reach_http_transport(postgres_database):
    send_count = 0

    def transport(_request):
        nonlocal send_count
        send_count += 1
        return httpx.Response(200, json={})

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
    adapter = BraveSearchAdapter(
        settings,
        transport=httpx.MockTransport(transport),
        usage_accounting=PostgresProviderUsageAccounting(postgres_database),
    )
    brave._NEXT_REQUEST = 0

    with pytest.raises(SearchError):
        anyio.run(adapter.search, "synthetic query", 1)

    assert send_count == 0
    with postgres_database.connection(snapshot=True) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM provider_attempts a JOIN provider_invocations i USING(invocation_id) "
                "WHERE i.endpoint_profile_id='brave:search' AND i.task_id='web_research_search'"
            ).fetchone()[0]
            == 0
        )


def test_operator_quota_correction_applies_downward_and_never_grants_mid_window_increase(
    postgres_database,
):
    bucket_id = f"synthetic-corrected-{uuid4()}"
    authority = f"synthetic-account-{uuid4()}"
    accounting = PostgresProviderUsageAccounting(postgres_database)

    for index in range(9):
        bucket = _bucket(bucket_id, authority, limit=100)
        endpoint = _endpoint(
            f"synthetic:endpoint-{index}",
            account=authority,
            credential=f"synthetic:key-{index}",
            buckets=(bucket,),
        )
        invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
        attempt = _attempt()
        accounting.begin_invocation(invocation)
        accounting.reserve_attempt(invocation, attempt, max_attempts=10)
        _settle(accounting, invocation, attempt)

    corrected = _bucket(bucket_id, authority, limit=10)
    endpoint = _endpoint(
        f"synthetic:endpoint-{uuid4()}",
        account=authority,
        credential="synthetic:key",
        buckets=(corrected,),
    )
    invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    attempt = _attempt()
    accounting.begin_invocation(invocation)
    accounting.reserve_attempt(invocation, attempt, max_attempts=10)
    _settle(accounting, invocation, attempt)

    increased = _bucket(bucket_id, authority, limit=100)
    endpoint = _endpoint(
        f"synthetic:endpoint-{uuid4()}",
        account=authority,
        credential="synthetic:key",
        buckets=(increased,),
    )
    invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    accounting.begin_invocation(invocation)
    with pytest.raises(UsageAdmissionDenied, match="provider_quota_exhausted"):
        accounting.reserve_attempt(invocation, _attempt(), max_attempts=10)

    state = _bucket_state(postgres_database, bucket_id)
    assert state[3] == 10
    assert state[-2:] == (10, 0)


def test_changed_quota_window_identity_is_rejected(postgres_database):
    bucket_id = f"synthetic-window-{uuid4()}"
    authority = f"synthetic-account-{uuid4()}"
    accounting = PostgresProviderUsageAccounting(postgres_database)
    first_bucket = _bucket(bucket_id, authority, limit=10, window_seconds=3600)
    endpoint = _endpoint(
        f"synthetic:endpoint-{uuid4()}",
        account=authority,
        credential="synthetic:key",
        buckets=(first_bucket,),
    )
    invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    attempt = _attempt()
    accounting.begin_invocation(invocation)
    accounting.reserve_attempt(invocation, attempt, max_attempts=10)

    changed = _bucket(bucket_id, authority, limit=10, window_seconds=7200)
    next_endpoint = _endpoint(
        f"synthetic:endpoint-{uuid4()}",
        account=authority,
        credential="synthetic:key",
        buckets=(changed,),
    )
    next_invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", next_endpoint)
    accounting.begin_invocation(next_invocation)
    with pytest.raises(ValueError, match="provider_quota_window_identity_conflict"):
        accounting.reserve_attempt(next_invocation, _attempt(), max_attempts=10)


def test_retry_lineage_and_timeout_fence_are_persisted(postgres_database):
    bucket_id = f"synthetic-retry-{uuid4()}"
    authority = f"synthetic-account-{uuid4()}"
    bucket = _bucket(bucket_id, authority, limit=10)
    endpoint = _endpoint(
        "synthetic:retry",
        account=authority,
        credential="synthetic:key",
        buckets=(bucket,),
    )
    invocation = _invocation(
        f"owner-{uuid4()}",
        f"request-{uuid4()}",
        endpoint,
        invocation_id=uuid4(),
        task_id="web_research_search",
    )
    accounting = PostgresProviderUsageAccounting(postgres_database)
    first = _attempt()
    second = _attempt(
        send_number=2,
        parent_attempt_id=first.attempt_id,
        started_at=datetime.now(UTC) + timedelta(seconds=6),
    )
    second = AttemptMetadata(
        attempt_id=second.attempt_id,
        parent_attempt_id=first.attempt_id,
        send_number=2,
        started_at=second.started_at,
        reservation_units=second.reservation_units,
    )
    accounting.begin_invocation(invocation)
    accounting.reserve_attempt(invocation, first, max_attempts=10)
    _settle(accounting, invocation, first, outcome="server_error")
    accounting.reserve_attempt(invocation, second, max_attempts=10)
    _settle(
        accounting,
        invocation,
        second,
        completed_at=second.started_at + timedelta(seconds=1),
    )
    accounting.complete_invocation(invocation, outcome="success", completed_at=datetime.now(UTC))

    timeout_invocation = _invocation(
        f"owner-{uuid4()}",
        f"request-{uuid4()}",
        endpoint,
        invocation_id=uuid4(),
        task_id="iterative_research_search",
    )
    timed_out = _attempt()
    accounting.begin_invocation(timeout_invocation)
    accounting.reserve_attempt(timeout_invocation, timed_out, max_attempts=10)
    _settle(accounting, timeout_invocation, timed_out, outcome="timeout")
    accounting.complete_invocation(
        timeout_invocation, outcome="timeout", completed_at=datetime.now(UTC)
    )
    retry = AttemptMetadata(
        attempt_id=uuid4(),
        parent_attempt_id=timed_out.attempt_id,
        send_number=2,
        started_at=datetime.now(UTC),
        reservation_units=unit_reservations(),
    )
    with pytest.raises(UsageAdmissionDenied, match="provider_outcome_unresolved"):
        accounting.reserve_attempt(timeout_invocation, retry, max_attempts=10)

    with postgres_database.connection(snapshot=True) as connection:
        retry_rows = connection.execute(
            "SELECT send_number,parent_attempt_id,status FROM provider_attempts "
            "WHERE invocation_id=%s ORDER BY send_number",
            (invocation.invocation_id,),
        ).fetchall()
        aggregate = connection.execute(
            "SELECT attempts,retries,endpoint_profile_version FROM provider_usage_daily_aggregates "
            "WHERE owner_id=%s AND task_id='web_research_search'",
            (invocation.owner_id,),
        ).fetchone()
        timed_out_state = connection.execute(
            "SELECT i.outcome,count(a.attempt_id) FROM provider_invocations i "
            "JOIN provider_attempts a USING(invocation_id) WHERE i.invocation_id=%s "
            "GROUP BY i.outcome",
            (timeout_invocation.invocation_id,),
        ).fetchone()

    assert retry_rows == [(1, None, "server_error"), (2, first.attempt_id, "success")]
    assert aggregate == (2, 1, endpoint.profile_version)
    assert timed_out_state == ("timeout", 1)


def test_daily_aggregates_separate_profile_versions_and_retention_removes_both(
    postgres_database,
):
    authority = f"synthetic-account-{uuid4()}"
    bucket = _bucket(f"synthetic-aggregate-{uuid4()}", authority, limit=20)
    accounting = PostgresProviderUsageAccounting(postgres_database, retention_days=7)
    owner = f"owner-{uuid4()}"
    for version, model_id in ((1, "model-a"), (2, "model-b")):
        endpoint = _endpoint(
            "synthetic:versioned",
            account=authority,
            credential="synthetic:key",
            buckets=(bucket,),
            profile_version=version,
            model_id=model_id,
        )
        invocation = _invocation(
            owner,
            f"request-{uuid4()}",
            endpoint,
            task_id="versioned_summary_test",
        )
        attempt = _attempt()
        accounting.begin_invocation(invocation)
        accounting.reserve_attempt(invocation, attempt, max_attempts=10)
        _settle(accounting, invocation, attempt)

    summary = accounting.summary(
        owner_id=invocation.owner_id,
        application_id=invocation.application_id,
        workspace_id=None,
        days=30,
    )
    matching = [
        group
        for group in summary["groups"]
        if group["endpoint_profile_id"] == "synthetic:versioned"
    ]
    assert {(group["endpoint_profile_version"], group["model_id"]) for group in matching} == {
        (1, "model-a"),
        (2, "model-b"),
    }

    with postgres_database.transaction() as connection:
        connection.execute(
            "UPDATE provider_usage_daily_aggregates SET usage_day=current_date-100 "
            "WHERE endpoint_profile_id='synthetic:versioned'"
        )
    accounting.purge_expired(limit=100)
    with postgres_database.connection(snapshot=True) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM provider_usage_daily_aggregates "
                "WHERE endpoint_profile_id='synthetic:versioned'"
            ).fetchone()[0]
            == 0
        )


def test_late_live_result_cannot_overwrite_stale_unknown_and_keeps_quota_consumed(
    postgres_database,
):
    authority = f"synthetic-account-{uuid4()}"
    bucket = _bucket(f"synthetic-live-{uuid4()}", authority, limit=10)
    endpoint = _endpoint(
        f"synthetic:endpoint-{uuid4()}",
        account=authority,
        credential="synthetic:key",
        buckets=(bucket,),
    )
    accounting = PostgresProviderUsageAccounting(postgres_database, stale_attempt_seconds=120)

    live_invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    live_attempt = _attempt(started_at=datetime.now(UTC) - timedelta(seconds=119))
    accounting.begin_invocation(live_invocation)
    accounting.reserve_attempt(live_invocation, live_attempt, max_attempts=10)
    assert accounting.resolve_stale_attempts(limit=10) == 0
    _settle(accounting, live_invocation, live_attempt)
    accounting.complete_invocation(
        live_invocation, outcome="success", completed_at=datetime.now(UTC)
    )

    orphan_invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    orphan_attempt = _attempt(started_at=datetime.now(UTC) - timedelta(seconds=121))
    accounting.begin_invocation(orphan_invocation)
    accounting.reserve_attempt(orphan_invocation, orphan_attempt, max_attempts=10)
    assert accounting.resolve_stale_attempts(limit=10) == 1
    _settle(accounting, orphan_invocation, orphan_attempt, outcome="success")
    accounting.complete_invocation(
        orphan_invocation, outcome="success", completed_at=datetime.now(UTC)
    )

    with postgres_database.connection(snapshot=True) as connection:
        attempt_state = connection.execute(
            "SELECT a.status,i.outcome,r.state FROM provider_attempts a "
            "JOIN provider_invocations i USING(invocation_id) "
            "JOIN provider_quota_reservations r USING(attempt_id) WHERE a.attempt_id=%s",
            (orphan_attempt.attempt_id,),
        ).fetchone()
    assert attempt_state == ("unknown", "unknown", "uncertain")
    assert _bucket_state(postgres_database, bucket.bucket_id)[-2:] == (2, 0)


def test_quota_windows_age_out_but_active_and_referenced_windows_remain(postgres_database):
    now = datetime.now(UTC)
    retention_days = 7
    accounting = PostgresProviderUsageAccounting(postgres_database, retention_days=retention_days)
    old_unreferenced_ids = []
    for index in range(3):
        authority = f"old-account-{uuid4()}"
        bucket = _bucket(f"old-bucket-{uuid4()}", authority, limit=20)
        endpoint = _endpoint(
            f"old:endpoint-{index}-{uuid4()}",
            account=authority,
            credential="synthetic:key",
            buckets=(bucket,),
        )
        invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
        attempt = _attempt(started_at=now - timedelta(days=20))
        accounting.begin_invocation(invocation)
        accounting.reserve_attempt(invocation, attempt, max_attempts=10)
        _settle(
            accounting,
            invocation,
            attempt,
            completed_at=attempt.started_at + timedelta(seconds=5),
        )
        old_unreferenced_ids.append(bucket.bucket_id)
        with postgres_database.transaction() as connection:
            connection.execute(
                "DELETE FROM provider_quota_reservations WHERE attempt_id=%s",
                (attempt.attempt_id,),
            )

    old_authority = f"old-reference-account-{uuid4()}"
    old_bucket = _bucket(f"old-reference-{uuid4()}", old_authority, limit=20)
    old_endpoint = _endpoint(
        "old:referenced",
        account=old_authority,
        credential="synthetic:key",
        buckets=(old_bucket,),
    )
    old_invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", old_endpoint)
    old_attempt = _attempt(started_at=now - timedelta(days=20))
    accounting.begin_invocation(old_invocation)
    accounting.reserve_attempt(old_invocation, old_attempt, max_attempts=10)
    with postgres_database.transaction() as connection:
        connection.execute(
            "UPDATE provider_invocations SET retention_until=%s WHERE invocation_id=%s",
            (now + timedelta(days=1), old_invocation.invocation_id),
        )

    active_authority = f"active-account-{uuid4()}"
    active_bucket = _bucket(f"active-bucket-{uuid4()}", active_authority, limit=20)
    active_endpoint = _endpoint(
        "active:endpoint",
        account=active_authority,
        credential="synthetic:key",
        buckets=(active_bucket,),
    )
    active_invocation = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", active_endpoint)
    active_attempt = _attempt()
    accounting.begin_invocation(active_invocation)
    accounting.reserve_attempt(active_invocation, active_attempt, max_attempts=10)

    accounting.purge_expired(limit=100)
    with postgres_database.connection(snapshot=True) as connection:
        retained_ids = {
            row[0]
            for row in connection.execute(
                "SELECT bucket_id FROM provider_quota_bucket_windows WHERE bucket_id = ANY(%s)",
                ([*old_unreferenced_ids, old_bucket.bucket_id, active_bucket.bucket_id],),
            ).fetchall()
        }
    assert retained_ids == {old_bucket.bucket_id, active_bucket.bucket_id}

    with postgres_database.transaction() as connection:
        connection.execute(
            "DELETE FROM provider_quota_reservations WHERE attempt_id=%s",
            (old_attempt.attempt_id,),
        )
    accounting.purge_expired(limit=100)
    with postgres_database.connection(snapshot=True) as connection:
        remaining = connection.execute(
            "SELECT count(*) FROM provider_quota_bucket_windows WHERE bucket_id=%s",
            (old_bucket.bucket_id,),
        ).fetchone()[0]
        active = connection.execute(
            "SELECT count(*) FROM provider_quota_bucket_windows WHERE bucket_id=%s",
            (active_bucket.bucket_id,),
        ).fetchone()[0]
    assert remaining == 0
    assert active == 1


def test_shared_endpoint_reservation_and_settlement_follow_one_lock_order(postgres_database):
    authority = f"synthetic-account-{uuid4()}"
    bucket = _bucket(f"shared-lock-order-{uuid4()}", authority, limit=100)
    endpoint = _endpoint(
        f"synthetic:endpoint-{uuid4()}",
        account=authority,
        credential="synthetic:key",
        buckets=(bucket,),
    )
    accounting = PostgresProviderUsageAccounting(postgres_database)
    first = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    first_attempt = _attempt()
    accounting.reserve_attempt(first, first_attempt, max_attempts=10)
    # Seed health as well as the quota window to exercise both lock families.
    _settle(accounting, first, first_attempt)
    pending = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    pending_attempt = _attempt()
    accounting.reserve_attempt(pending, pending_attempt, max_attempts=10)
    incoming = _invocation(f"owner-{uuid4()}", f"request-{uuid4()}", endpoint)
    incoming_attempt = _attempt()
    barrier = Barrier(2)

    def settle():
        barrier.wait(timeout=5)
        _settle(accounting, pending, pending_attempt)

    def reserve():
        barrier.wait(timeout=5)
        return accounting.reserve_attempt(incoming, incoming_attempt, max_attempts=10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        settled = pool.submit(settle)
        admitted = pool.submit(reserve)
        assert admitted.result(timeout=10).attempt_id == incoming_attempt.attempt_id
        settled.result(timeout=10)
    assert _bucket_state(postgres_database, bucket.bucket_id)[-2:] == (2, 1)
