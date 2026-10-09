"""Canonical Postgres ledger for provider invocations and physical sends."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from math import ceil
from types import SimpleNamespace
from uuid import UUID, uuid5

from personal_ai.persistence.postgres import PostgresDatabase, _ensure_namespace
from personal_ai.usage.contracts import (
    AttemptMetadata,
    AttemptResult,
    InvocationMetadata,
    UsageAdmissionDenied,
)
from personal_ai.usage.quota import QuotaObservation as QuotaBucket

logger = logging.getLogger(__name__)
_QUOTA_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class PostgresProviderUsageAccounting:
    """Postgres authority for reservations/settlements and compact daily totals."""

    def __init__(
        self,
        database: PostgresDatabase,
        *,
        retention_days: int = 90,
        request_attempt_limit: int = 64,
        request_token_limit: int = 200_000,
        default_cooldown_seconds: int = 60,
        header_freshness_seconds: int = 60,
        stale_attempt_seconds: int = 300,
        endpoint_profile_resolver=None,
        operational_event_writer: Callable[[dict], None] | None = None,
        operational_event_purger: Callable[[datetime, int], int] | None = None,
    ) -> None:
        self.database = database
        self.retention_days = retention_days
        self.request_attempt_limit = request_attempt_limit
        self.request_token_limit = request_token_limit
        self.default_cooldown_seconds = default_cooldown_seconds
        self.header_freshness_seconds = header_freshness_seconds
        self.stale_attempt_seconds = stale_attempt_seconds
        self.endpoint_profile_resolver = endpoint_profile_resolver
        self.operational_event_writer = operational_event_writer
        self.operational_event_purger = operational_event_purger

    def begin_invocation(self, invocation: InvocationMetadata) -> None:
        """Persist logical work even when setup fails before its first network send."""
        now = datetime.now(UTC)
        retention_until = now + timedelta(days=self.retention_days)
        with self.database.transaction() as connection:
            from personal_ai.persistence.postgres_owner_lifecycle import assert_owner_unfenced

            assert_owner_unfenced(connection, invocation.owner_id)
            scope_id = _ensure_namespace(
                connection,
                invocation.owner_id,
                _scope(invocation.application_id, invocation.workspace_id),
            )
            _insert_invocation(connection, invocation, scope_id, now, retention_until)

    def reserve_attempt(self, invocation, attempt, *, max_attempts):
        # Preserve a denied logical outcome while committing no physical attempt.
        denial = None
        with self.database.transaction() as connection:
            try:
                result = self.reserve_attempt_in_transaction(
                    connection, invocation, attempt, max_attempts=max_attempts
                )
            except UsageAdmissionDenied as error:
                denial = error
        if denial is not None:
            raise denial
        return result

    def reserve_attempt_in_transaction(self, connection, invocation, attempt, *, max_attempts):
        """Small transaction-aware seam; caller owns commit, never provider IO."""
        now = attempt.started_at.astimezone(UTC)
        retention_until = now + timedelta(days=self.retention_days)
        endpoint = invocation.endpoint
        denial = None
        reserved_attempt = None
        selected_buckets = []
        from personal_ai.persistence.postgres_owner_lifecycle import (
            OwnerFenced,
            assert_owner_unfenced,
        )

        try:
            assert_owner_unfenced(connection, invocation.owner_id)
        except OwnerFenced:
            raise UsageAdmissionDenied("provider_owner_deletion_fenced") from None
        if self.endpoint_profile_resolver is not None and endpoint.credential_source != "none":
            try:
                self.endpoint_profile_resolver.assert_current_in_transaction(connection, endpoint)
            except ValueError:
                raise UsageAdmissionDenied("provider_endpoint_profile_stale") from None
        scope_id = _ensure_namespace(
            connection,
            invocation.owner_id,
            _scope(invocation.application_id, invocation.workspace_id),
        )
        request_scope = _request_budget_scope(invocation)
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"provider-usage:{request_scope}",),
        )
        _insert_invocation(connection, invocation, scope_id, now, retention_until)

        unresolved = connection.execute(
            "SELECT 1 FROM provider_attempts a JOIN provider_invocations i USING(invocation_id) "
            "WHERE i.owner_id=%s AND i.application_id=%s "
            "AND i.workspace_id IS NOT DISTINCT FROM %s AND i.request_id=%s "
            "AND a.status IN ('pending','unknown','timeout') LIMIT 1",
            (
                invocation.owner_id,
                invocation.application_id,
                invocation.workspace_id,
                invocation.request_id,
            ),
        ).fetchone()
        if unresolved is not None:
            denial = "provider_outcome_unresolved"

        attempt_count, reserved_tokens = connection.execute(
            "SELECT count(*),COALESCE(sum(reserved_tokens),0) "
            "FROM provider_attempts a JOIN provider_invocations i USING (invocation_id) "
            "WHERE i.owner_id=%s AND i.application_id=%s "
            "AND i.workspace_id IS NOT DISTINCT FROM %s AND i.request_id=%s",
            (
                invocation.owner_id,
                invocation.application_id,
                invocation.workspace_id,
                invocation.request_id,
            ),
        ).fetchone()
        call_tokens = max(0, attempt.reserved_tokens)
        if denial is None and attempt_count >= min(max_attempts, self.request_attempt_limit):
            denial = "provider_attempt_budget_exceeded"
        elif denial is None and reserved_tokens + call_tokens > self.request_token_limit:
            denial = "provider_token_budget_exceeded"

        previous_attempt = connection.execute(
            "SELECT attempt_id,send_number FROM provider_attempts "
            "WHERE invocation_id=%s ORDER BY send_number DESC LIMIT 1 FOR UPDATE",
            (invocation.invocation_id,),
        ).fetchone()
        expected_send_number = int(previous_attempt[1]) + 1 if previous_attempt else 1
        expected_parent_id = previous_attempt[0] if previous_attempt else None
        reserved_attempt = (
            attempt
            if (
                attempt.send_number == expected_send_number
                and attempt.parent_attempt_id == expected_parent_id
            )
            else replace(
                attempt,
                attempt_id=uuid5(
                    invocation.invocation_id,
                    f"provider-attempt:{expected_send_number}",
                ),
                parent_attempt_id=expected_parent_id,
                send_number=expected_send_number,
            )
        )

        applicable_buckets = _applicable_buckets(endpoint.quota_buckets, invocation.operation)
        if denial is None:
            if endpoint.quota_membership == "ambiguous":
                denial = "provider_quota_membership_ambiguous"
            elif endpoint.quota_membership != "verified" or not applicable_buckets:
                denial = "provider_quota_membership_unknown"

        if denial is None:
            for bucket in sorted(applicable_buckets, key=lambda b: b.bucket_id):
                amount = _reservation_amount(bucket, dict(attempt.reservation_units))
                window_start, reset_at, confidence = _select_quota_window(connection, bucket, now)
                _lock_or_seed_bucket(connection, bucket, window_start, reset_at, confidence, now)
                state = connection.execute(
                    "SELECT authority_scope_id,unit,window_seconds,reset_at,source,confidence,"
                    "limit_units,reported_remaining,observed_at,fresh_until,consumed_units,reserved_units "
                    "FROM provider_quota_bucket_windows WHERE bucket_id=%s AND window_start=%s "
                    "FOR UPDATE",
                    (bucket.bucket_id, window_start),
                ).fetchone()
                if state is None:
                    raise RuntimeError("provider_quota_bucket_state_missing")
                (
                    authority_scope,
                    unit,
                    _window_seconds,
                    state_reset,
                    _source,
                    state_confidence,
                    limit_units,
                    reported_remaining,
                    _observed_at,
                    fresh_until,
                    consumed,
                    reserved,
                ) = state
                if authority_scope != bucket.authority_scope_id or unit != bucket.unit:
                    raise ValueError("provider_quota_bucket_identity_conflict")
                capacity_known = (
                    state_confidence != "unknown"
                    and (limit_units is not None or reported_remaining is not None)
                    and (fresh_until is None or fresh_until > now)
                    and (state_reset is None or state_reset > now)
                )
                if capacity_known and amount is None:
                    denial = "provider_quota_unit_unpriced"
                elif capacity_known and amount is not None:
                    limits = []
                    if limit_units is not None:
                        limits.append(int(limit_units) - int(consumed) - int(reserved))
                    if reported_remaining is not None:
                        limits.append(int(reported_remaining) - int(consumed) - int(reserved))
                    if limits and min(limits) < amount:
                        denial = "provider_quota_exhausted"
                selected_buckets.append((bucket, window_start, amount, state_confidence))
                if denial is not None:
                    break

        # Settlement locks bucket windows before health. Follow the same order,
        # including across different owners sharing one endpoint/quota scope.
        _lock_endpoint_health(connection, endpoint)
        health = connection.execute(
            "SELECT health_status,cooldown_until FROM provider_endpoint_health "
            "WHERE endpoint_profile_id=%s AND endpoint_profile_version=%s FOR SHARE",
            (endpoint.endpoint_profile_id, endpoint.profile_version),
        ).fetchone()
        if denial is None and _health_unavailable(health, now):
            denial = "provider_endpoint_cooling_down"

        if denial is not None:
            # Denied admission did not dispatch a physical provider send.
            # Keep the logical outcome without inflating attempt/retry counts.
            connection.execute(
                "UPDATE provider_invocations SET outcome='rejected',"
                "completed_at=GREATEST(%s,started_at) "
                "WHERE invocation_id=%s AND outcome='running'",
                (now, invocation.invocation_id),
            )
        else:
            quota_confidences = {item[3] for item in selected_buckets}
            quota_confidence = (
                "unknown"
                if not selected_buckets or "unknown" in quota_confidences
                else "configured"
            )
            connection.execute(
                "UPDATE provider_invocations SET quota_confidence=%s WHERE invocation_id=%s",
                (quota_confidence, invocation.invocation_id),
            )
            connection.execute(
                "UPDATE provider_invocations SET outcome='running',completed_at=NULL "
                "WHERE invocation_id=%s",
                (invocation.invocation_id,),
            )
            _insert_attempt(
                connection,
                invocation,
                reserved_attempt,
                call_tokens,
                retention_until,
                status="pending",
                error_code=None,
            )
            for bucket, window_start, amount, confidence in selected_buckets:
                is_known = confidence != "unknown" and amount is not None
                reserved_amount = amount or 0
                connection.execute(
                    "INSERT INTO provider_quota_reservations(attempt_id,bucket_id,"
                    "authority_scope_id,unit,window_start,reserved_units,settled_units,state,"
                    "confidence,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s)",
                    (
                        reserved_attempt.attempt_id,
                        bucket.bucket_id,
                        bucket.authority_scope_id,
                        bucket.unit,
                        window_start,
                        reserved_amount,
                        "reserved" if is_known else "unknown",
                        confidence,
                        now,
                        now,
                    ),
                )
                if reserved_amount:
                    connection.execute(
                        "UPDATE provider_quota_bucket_windows SET reserved_units=reserved_units+%s,"
                        "updated_at=%s WHERE bucket_id=%s AND window_start=%s",
                        (reserved_amount, now, bucket.bucket_id, window_start),
                    )
        if denial is not None:
            raise UsageAdmissionDenied(denial)
        if reserved_attempt is None:
            raise RuntimeError("provider_usage_attempt_not_reserved")
        return reserved_attempt

    def runtime_rejections(self, connection, profile, requirements, *, now, check_capacity=True):
        """Current runtime authority. No failure row means no observed health failure.

        Unknown capacity remains unknown and never asserts available units; the
        strict-free static attestation excludes billable overflow independently.
        """
        from personal_ai.usage.profiles import from_profile

        endpoint = from_profile(profile)
        health = connection.execute(
            "SELECT health_status,cooldown_until FROM provider_endpoint_health "
            "WHERE endpoint_profile_id=%s AND endpoint_profile_version=%s",
            (profile.endpoint_profile_id, profile.profile_version),
        ).fetchone()
        reasons = []
        if _health_unavailable(health, now):
            reasons.append("endpoint_health_unavailable")
        if not check_capacity:
            return tuple(reasons)
        from personal_ai.usage.accounting import unit_reservations

        values = dict(
            unit_reservations(
                input_tokens=requirements.input_tokens, output_tokens=requirements.output_tokens
            )
        )
        for bucket in sorted(endpoint.quota_buckets, key=lambda b: b.bucket_id):
            if not requirements.required_capabilities.intersection(bucket.operations):
                continue
            start, reset, confidence = _select_quota_window(connection, bucket, now)
            _lock_or_seed_bucket(connection, bucket, start, reset, confidence, now)
            row = connection.execute(
                "SELECT limit_units,reported_remaining,consumed_units,reserved_units,confidence,"
                "fresh_until,reset_at FROM provider_quota_bucket_windows "
                "WHERE bucket_id=%s AND window_start=%s",
                (bucket.bucket_id, start),
            ).fetchone()
            if row is None:
                raise RuntimeError("provider_quota_state_missing")
            limit, remaining, consumed, reserved, confidence, fresh, reset = row
            known = (
                confidence != "unknown"
                and (fresh is None or fresh > now)
                and (reset is None or reset > now)
            )
            amount = _reservation_amount(bucket, values)
            if known and (limit is not None or remaining is not None):
                if amount is None:
                    reasons.append("provider_quota_unit_unpriced")
                elif (
                    min(v for v in (limit, remaining) if v is not None) - consumed - reserved
                    < amount
                ):
                    reasons.append("endpoint_quota_exhausted")
        return tuple(dict.fromkeys(reasons))

    def reserved_attempt_in_transaction(
        self, connection, invocation, attempt_id, *, expected_units, max_attempts, now
    ):
        """Resolve exact provenance directly, with the attempt locked against settlement."""
        endpoint = invocation.endpoint
        row = connection.execute(
            "SELECT i.owner_id,i.application_id,i.workspace_id,i.request_id,i.run_id,"
            "i.routing_decision_id,i.endpoint_profile_id,i.endpoint_profile_version,i.operation,"
            "i.outcome,a.started_at,a.status,a.send_number,a.parent_attempt_id,a.reserved_tokens,"
            "a.dispatch_claimed_at FROM provider_invocations i JOIN provider_attempts a USING(invocation_id) "
            "WHERE i.invocation_id=%s AND a.attempt_id=%s FOR UPDATE OF a FOR SHARE OF i",
            (invocation.invocation_id, attempt_id),
        ).fetchone()
        expected = (
            invocation.owner_id,
            invocation.application_id,
            invocation.workspace_id,
            invocation.request_id,
            invocation.run_id,
            invocation.routing_decision_id,
            endpoint.endpoint_profile_id,
            endpoint.profile_version,
            invocation.operation,
            "running",
        )
        if (
            row is None
            or row[:10] != expected
            or row[11] != "pending"
            or row[10] > now
            or (now - row[10]).total_seconds() >= self.stale_attempt_seconds
        ):
            raise UsageAdmissionDenied("routing_reservation_not_authoritative")
        if row[12] > max_attempts or row[12] < 1:
            raise UsageAdmissionDenied("routing_attempt_budget_invalid")
        if row[14] != dict(expected_units).get("tokens", 0):
            raise UsageAdmissionDenied("routing_attempt_budget_invalid")
        if row[12] == 1:
            if row[13] is not None:
                raise UsageAdmissionDenied("routing_attempt_lineage_invalid")
        else:
            previous = connection.execute(
                "SELECT attempt_id,status FROM provider_attempts "
                "WHERE invocation_id=%s AND send_number=%s FOR SHARE",
                (invocation.invocation_id, row[12] - 1),
            ).fetchone()
            if (
                previous is None
                or previous[0] != row[13]
                or previous[1] in {"pending", "unknown", "timeout"}
            ):
                raise UsageAdmissionDenied("routing_attempt_lineage_invalid")
        _insert_invocation(
            connection,
            invocation,
            _ensure_namespace(
                connection,
                invocation.owner_id,
                _scope(invocation.application_id, invocation.workspace_id),
            ),
            now,
            now + timedelta(days=self.retention_days),
        )
        buckets = connection.execute(
            "SELECT r.bucket_id,r.reserved_units,r.state,r.authority_scope_id,r.unit,"
            "w.authority_scope_id,w.unit FROM provider_quota_reservations r "
            "JOIN provider_quota_bucket_windows w USING(bucket_id,window_start) "
            "WHERE attempt_id=%s ORDER BY r.bucket_id FOR SHARE OF r,w",
            (attempt_id,),
        ).fetchall()
        bindings = {
            b.bucket_id: b for b in endpoint.quota_buckets if invocation.operation in b.operations
        }
        values = dict(expected_units)
        if not bindings or {b[0] for b in buckets} != set(bindings):
            raise UsageAdmissionDenied("routing_reservation_incomplete")
        for bucket_id, amount, state, authority, unit, window_authority, window_unit in buckets:
            binding = bindings[bucket_id]
            expected_amount = _reservation_amount(binding, values) or 0
            if (
                amount != expected_amount
                or state not in {"reserved", "unknown"}
                or authority != binding.authority_scope_id
                or window_authority != authority
                or unit != binding.unit
                or window_unit != unit
            ):
                raise UsageAdmissionDenied("routing_reservation_incomplete")
        _lock_endpoint_health(connection, endpoint)
        health = connection.execute(
            "SELECT health_status,cooldown_until FROM provider_endpoint_health "
            "WHERE endpoint_profile_id=%s AND endpoint_profile_version=%s FOR SHARE",
            (endpoint.endpoint_profile_id, endpoint.profile_version),
        ).fetchone()
        if _health_unavailable(health, now):
            raise UsageAdmissionDenied("provider_endpoint_cooling_down")
        return AttemptMetadata(
            attempt_id=attempt_id,
            parent_attempt_id=row[13],
            send_number=row[12],
            started_at=row[10],
            reservation_units=(),
            reserved_tokens=row[14],
        )

    def claim_attempt_in_transaction(self, connection, attempt_id, *, now):
        if (
            connection.execute(
                "UPDATE provider_attempts SET dispatch_claimed_at=%s WHERE attempt_id=%s "
                "AND status='pending' AND dispatch_claimed_at IS NULL RETURNING attempt_id",
                (now, attempt_id),
            ).fetchone()
            is None
        ):
            raise UsageAdmissionDenied("routing_dispatch_already_claimed")

    def attempt_outcome_in_transaction(self, connection, invocation_id, attempt_id):
        row = connection.execute(
            "SELECT status FROM provider_attempts WHERE invocation_id=%s AND attempt_id=%s FOR SHARE",
            (invocation_id, attempt_id),
        ).fetchone()
        if row is None or row[0] == "pending":
            raise UsageAdmissionDenied("provider_outcome_unresolved")
        return row[0]

    def settle_attempt(
        self,
        invocation: InvocationMetadata,
        attempt: AttemptMetadata,
        result: AttemptResult,
    ) -> None:
        completed = result.completed_at.astimezone(UTC)
        rate_limits = _rate_limit_payload(result)
        event: dict | None = None
        with self.database.transaction() as connection:
            previous = connection.execute(
                "SELECT status FROM provider_attempts WHERE attempt_id=%s FOR UPDATE",
                (attempt.attempt_id,),
            ).fetchone()
            if previous is None or previous[0] != "pending":
                return
            connection.execute(
                "UPDATE provider_attempts SET status=%s,error_code=%s,http_status=%s,"
                "completed_at=%s,latency_ms=%s,input_tokens=%s,output_tokens=%s,total_tokens=%s,"
                "usage_source=%s,usage_confidence=%s,unit_usage=%s::jsonb,unit_usage_source=%s,"
                "unit_usage_confidence=%s,rate_limit_facts=%s::jsonb "
                "WHERE attempt_id=%s",
                (
                    result.outcome,
                    _safe_code(result.error_code),
                    result.http_status,
                    completed,
                    max(0, result.latency_ms),
                    result.input_tokens,
                    result.output_tokens,
                    result.total_tokens,
                    _bounded_text(result.usage_source, 80),
                    result.usage_confidence,
                    json.dumps(dict(result.unit_usage), separators=(",", ":")),
                    _bounded_text(result.unit_usage_source, 80),
                    result.unit_usage_confidence,
                    json.dumps(rate_limits, separators=(",", ":")),
                    attempt.attempt_id,
                ),
            )
            rows = connection.execute(
                "SELECT bucket_id,authority_scope_id,unit,window_start,reserved_units,state "
                "FROM provider_quota_reservations WHERE attempt_id=%s ORDER BY bucket_id FOR UPDATE",
                (attempt.attempt_id,),
            ).fetchall()
            for bucket_id, authority, unit, window_start, reserved_units, state in rows:
                if state not in {"reserved", "unknown"}:
                    continue
                actual = _actual_unit_usage(unit, result)
                if actual is None:
                    actual = int(reserved_units)
                    reservation_state = "uncertain"
                else:
                    reservation_state = "settled"
                if state in {"reserved", "unknown"}:
                    connection.execute(
                        "UPDATE provider_quota_bucket_windows SET reserved_units=GREATEST(0,"
                        "reserved_units-%s),consumed_units=consumed_units+%s,updated_at=%s "
                        "WHERE bucket_id=%s AND window_start=%s",
                        (reserved_units, actual, completed, bucket_id, window_start),
                    )
                connection.execute(
                    "UPDATE provider_quota_reservations SET settled_units=%s,state=%s,updated_at=%s "
                    "WHERE attempt_id=%s AND bucket_id=%s",
                    (actual, reservation_state, completed, attempt.attempt_id, bucket_id),
                )
                _record_header_observation(
                    connection,
                    bucket_id=bucket_id,
                    authority_scope=authority,
                    unit=unit,
                    window_start=window_start,
                    result=result,
                    observed_at=completed,
                    freshness_seconds=self.header_freshness_seconds,
                )

            _update_endpoint_health(
                connection,
                invocation,
                result,
                completed,
                default_cooldown_seconds=self.default_cooldown_seconds,
            )
            _aggregate_attempt(
                connection,
                invocation,
                attempt,
                result.outcome,
                result.latency_ms,
                result.input_tokens or 0,
                result.output_tokens or 0,
                result.usage_confidence,
                completed,
            )
            event = _operational_event(invocation, attempt, result)

        if event is not None:
            self._publish_event(attempt.attempt_id, event)

    def complete_invocation(
        self,
        invocation: InvocationMetadata,
        *,
        outcome: str,
        completed_at: datetime,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE provider_invocations SET outcome=%s,completed_at=%s "
                "WHERE invocation_id=%s AND outcome='running'",
                (outcome, completed_at.astimezone(UTC), invocation.invocation_id),
            )

    def summary(
        self, *, owner_id: str, application_id: str, workspace_id: str | None, days: int = 30
    ) -> dict:
        if not 1 <= days <= 90:
            raise ValueError("provider_usage_summary_days_invalid")
        since = datetime.now(UTC) - timedelta(days=days)
        with self.database.connection(snapshot=True) as connection:
            groups = connection.execute(
                "SELECT provider_id,model_id,endpoint_profile_id,endpoint_profile_version,task_id,operation,"
                "sum(attempts),sum(successes),sum(rate_limited),sum(server_errors),sum(failures),"
                "sum(retries),sum(latency_total_ms),sum(input_tokens),sum(output_tokens),"
                "sum(exact_usage_attempts),sum(derived_usage_attempts),sum(unknown_usage_attempts) "
                "FROM provider_usage_daily_aggregates WHERE owner_id=%s AND application_id=%s "
                "AND workspace_id IS NOT DISTINCT FROM %s AND usage_day >= %s::date "
                "GROUP BY provider_id,model_id,endpoint_profile_id,endpoint_profile_version,task_id,operation "
                "ORDER BY sum(attempts) DESC,provider_id,model_id,task_id LIMIT 64",
                (owner_id, application_id, workspace_id, since.date()),
            ).fetchall()
            endpoints = [row[2] for row in groups]
            health_rows = []
            quota_rows = []
            quota_endpoints: set[str] = set()
            if endpoints:
                health_rows = connection.execute(
                    "SELECT endpoint_profile_id,endpoint_profile_version,health_status,"
                    "failure_streak,cooldown_until,last_status,last_http_status,last_success_at,"
                    "last_failure_at,updated_at FROM provider_endpoint_health "
                    "WHERE endpoint_profile_id = ANY(%s) ORDER BY endpoint_profile_id,endpoint_profile_version",
                    (endpoints,),
                ).fetchall()
                quota_rows = connection.execute(
                    "SELECT DISTINCT b.bucket_id,b.authority_scope_id,b.unit,b.window_start,"
                    "b.window_seconds,b.reset_at,b.source,b.confidence,b.limit_units,"
                    "b.reported_remaining,b.observed_at,b.fresh_until "
                    "FROM provider_quota_reservations r "
                    "JOIN provider_attempts a USING(attempt_id) "
                    "JOIN provider_invocations i USING(invocation_id) "
                    "JOIN provider_quota_bucket_windows b USING(bucket_id,window_start) "
                    "WHERE i.owner_id=%s AND i.application_id=%s AND i.workspace_id IS NOT DISTINCT FROM %s "
                    "AND i.started_at >= %s ORDER BY b.bucket_id,b.window_start DESC LIMIT 32",
                    (owner_id, application_id, workspace_id, since),
                ).fetchall()
                quota_endpoints = {
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT i.endpoint_profile_id FROM provider_quota_reservations r "
                        "JOIN provider_attempts a USING(attempt_id) "
                        "JOIN provider_invocations i USING(invocation_id) WHERE i.owner_id=%s "
                        "AND i.application_id=%s AND i.workspace_id IS NOT DISTINCT FROM %s "
                        "AND i.started_at >= %s",
                        (owner_id, application_id, workspace_id, since),
                    ).fetchall()
                }
        return {
            "schema_version": "provider-usage-summary-v1",
            "owner_id": owner_id,
            "application_id": application_id,
            "workspace_id": workspace_id,
            "window_days": days,
            "generated_at": datetime.now(UTC).isoformat(),
            "groups": [
                {
                    "provider_id": row[0],
                    "model_id": row[1],
                    "endpoint_profile_id": row[2],
                    "endpoint_profile_version": row[3],
                    "task_id": row[4],
                    "operation": row[5],
                    "attempts": int(row[6] or 0),
                    "successes": int(row[7] or 0),
                    "rate_limited": int(row[8] or 0),
                    "server_errors": int(row[9] or 0),
                    "failures": int(row[10] or 0),
                    "retries": int(row[11] or 0),
                    "average_latency_ms": (
                        round(int(row[12] or 0) / int(row[6]), 1) if row[6] else None
                    ),
                    "input_tokens": int(row[13] or 0),
                    "output_tokens": int(row[14] or 0),
                    "exact_usage_attempts": int(row[15] or 0),
                    "derived_usage_attempts": int(row[16] or 0),
                    "unknown_usage_attempts": int(row[17] or 0),
                }
                for row in groups
            ],
            "health": [
                {
                    "endpoint_profile_id": row[0],
                    "endpoint_profile_version": row[1],
                    "status": row[2],
                    "failure_streak": row[3],
                    "cooldown_until": _iso(row[4]),
                    "last_status": row[5],
                    "last_http_status": row[6],
                    "last_success_at": _iso(row[7]),
                    "last_failure_at": _iso(row[8]),
                    "updated_at": _iso(row[9]),
                }
                for row in health_rows
            ],
            "quota": [
                {
                    "bucket_id": row[0],
                    "authority_scope_id": row[1],
                    "unit": row[2],
                    "window_start": _iso(row[3]),
                    "window_seconds": row[4],
                    "reset_at": _iso(row[5]),
                    "source": row[6],
                    "snapshot_confidence": row[7],
                    "confidence": (
                        "unknown"
                        if (row[11] is not None and row[11] <= datetime.now(UTC))
                        or (row[5] is not None and row[5] <= datetime.now(UTC))
                        else row[7]
                    ),
                    "limit": row[8],
                    "reported_remaining": row[9],
                    "observed_at": _iso(row[10]),
                    "fresh_until": _iso(row[11]),
                }
                for row in quota_rows
            ]
            + [
                {
                    "endpoint_profile_id": endpoint_id,
                    "bucket_id": None,
                    "authority_scope_id": None,
                    "unit": None,
                    "window_start": None,
                    "window_seconds": None,
                    "reset_at": None,
                    "source": "unknown",
                    "confidence": "unknown",
                    "snapshot_confidence": "unknown",
                    "limit": None,
                    "reported_remaining": None,
                    "observed_at": None,
                    "fresh_until": None,
                }
                for endpoint_id in endpoints
                if endpoint_id not in quota_endpoints
            ],
        }

    def purge_expired(self, *, limit: int) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("provider_usage_cleanup_limit_invalid")
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            rows = connection.execute(
                "WITH expired AS (SELECT invocation_id FROM provider_invocations "
                "WHERE retention_until<=%s ORDER BY retention_until,invocation_id "
                "LIMIT %s FOR UPDATE SKIP LOCKED) "
                "DELETE FROM provider_invocations i USING expired e "
                "WHERE i.invocation_id=e.invocation_id RETURNING i.invocation_id",
                (now, limit),
            ).fetchall()
            aggregates = connection.execute(
                "WITH expired AS (SELECT owner_id,application_id,workspace_id,usage_day,"
                "endpoint_profile_id,endpoint_profile_version,task_id,operation FROM provider_usage_daily_aggregates "
                "WHERE usage_day < %s::date ORDER BY usage_day LIMIT %s FOR UPDATE SKIP LOCKED) "
                "DELETE FROM provider_usage_daily_aggregates a USING expired e WHERE "
                "a.owner_id=e.owner_id AND a.application_id=e.application_id "
                "AND a.workspace_id IS NOT DISTINCT FROM e.workspace_id AND a.usage_day=e.usage_day "
                "AND a.endpoint_profile_id=e.endpoint_profile_id AND a.task_id=e.task_id "
                "AND a.endpoint_profile_version IS NOT DISTINCT FROM e.endpoint_profile_version "
                "AND a.operation=e.operation RETURNING a.usage_day",
                (now.date() - timedelta(days=self.retention_days), limit),
            ).fetchall()
            windows = connection.execute(
                "WITH expired AS (SELECT b.bucket_id,b.window_start "
                "FROM provider_quota_bucket_windows b WHERE b.window_start < %s "
                "AND (b.reset_at IS NULL OR b.reset_at <= %s) "
                "AND NOT EXISTS (SELECT 1 FROM provider_quota_reservations r "
                "WHERE r.bucket_id=b.bucket_id AND r.window_start=b.window_start) "
                "ORDER BY b.window_start,b.bucket_id LIMIT %s FOR UPDATE SKIP LOCKED) "
                "DELETE FROM provider_quota_bucket_windows b USING expired e "
                "WHERE b.bucket_id=e.bucket_id AND b.window_start=e.window_start "
                "RETURNING b.bucket_id",
                (now - timedelta(days=self.retention_days), now, limit),
            ).fetchall()
            health = connection.execute(
                "WITH expired AS (SELECT h.endpoint_profile_id,h.endpoint_profile_version "
                "FROM provider_endpoint_health h WHERE h.updated_at < %s "
                "AND NOT EXISTS (SELECT 1 FROM provider_invocations i "
                "WHERE i.endpoint_profile_id=h.endpoint_profile_id "
                "AND i.endpoint_profile_version=h.endpoint_profile_version "
                "AND i.started_at >= %s) ORDER BY h.updated_at LIMIT %s FOR UPDATE SKIP LOCKED) "
                "DELETE FROM provider_endpoint_health h USING expired e "
                "WHERE h.endpoint_profile_id=e.endpoint_profile_id "
                "AND h.endpoint_profile_version=e.endpoint_profile_version "
                "RETURNING h.endpoint_profile_id",
                (
                    now - timedelta(days=self.retention_days),
                    now - timedelta(days=self.retention_days),
                    limit,
                ),
            ).fetchall()
        removed = len(rows) + len(aggregates) + len(windows) + len(health)
        if self.operational_event_purger is not None:
            removed += self.operational_event_purger(now, min(limit, 100))
        return removed

    def resolve_stale_attempts(self, *, limit: int) -> int:
        """Fence sends orphaned by process death as unknown and retain their reserves."""
        if not 1 <= limit <= 100:
            raise ValueError("provider_usage_stale_attempt_limit_invalid")
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=self.stale_attempt_seconds)
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT i.invocation_id,i.owner_id,i.application_id,i.workspace_id,i.task_id,"
                "i.operation,i.provider_id,i.model_id,i.endpoint_profile_id,a.attempt_id,"
                "i.endpoint_profile_version,"
                "a.parent_attempt_id,a.started_at FROM provider_attempts a "
                "JOIN provider_invocations i USING(invocation_id) WHERE a.status='pending' "
                "AND a.started_at<=%s ORDER BY a.started_at,a.attempt_id LIMIT %s "
                "FOR UPDATE OF a SKIP LOCKED",
                (cutoff, limit),
            ).fetchall()
            for row in rows:
                (
                    invocation_id,
                    owner_id,
                    application_id,
                    workspace_id,
                    task_id,
                    operation,
                    provider_id,
                    model_id,
                    endpoint_profile_id,
                    attempt_id,
                    endpoint_profile_version,
                    parent_attempt_id,
                    started_at,
                ) = row
                latency = max(0, int((now - started_at).total_seconds() * 1000))
                connection.execute(
                    "UPDATE provider_attempts SET status='unknown',error_code='provider_outcome_unknown',"
                    "completed_at=%s,latency_ms=%s,usage_source='unknown',usage_confidence='unknown' "
                    "WHERE attempt_id=%s AND status='pending'",
                    (now, latency, attempt_id),
                )
                reservations = connection.execute(
                    "SELECT bucket_id,window_start,reserved_units,state FROM provider_quota_reservations "
                    "WHERE attempt_id=%s FOR UPDATE",
                    (attempt_id,),
                ).fetchall()
                for bucket_id, window_start, amount, state in reservations:
                    if state in {"reserved", "unknown"}:
                        connection.execute(
                            "UPDATE provider_quota_bucket_windows SET reserved_units=GREATEST(0,"
                            "reserved_units-%s),consumed_units=consumed_units+%s,updated_at=%s "
                            "WHERE bucket_id=%s AND window_start=%s",
                            (amount, amount, now, bucket_id, window_start),
                        )
                    connection.execute(
                        "UPDATE provider_quota_reservations SET settled_units=%s,state='uncertain',"
                        "updated_at=%s WHERE attempt_id=%s AND bucket_id=%s",
                        (amount, now, attempt_id, bucket_id),
                    )
                connection.execute(
                    "UPDATE provider_invocations SET outcome='unknown',completed_at=%s "
                    "WHERE invocation_id=%s AND NOT EXISTS (SELECT 1 FROM provider_attempts "
                    "WHERE invocation_id=%s AND status='pending')",
                    (now, invocation_id, invocation_id),
                )
                invocation = _aggregate_identity(
                    owner_id,
                    application_id,
                    workspace_id,
                    task_id,
                    operation,
                    provider_id,
                    model_id,
                    endpoint_profile_id,
                    endpoint_profile_version,
                )
                _aggregate_attempt(
                    connection,
                    invocation,
                    SimpleNamespace(parent_attempt_id=parent_attempt_id),
                    "unknown",
                    latency,
                    0,
                    0,
                    "unknown",
                    now,
                )
        return len(rows)

    def reconcile_operational_events(self, *, limit: int) -> int:
        if self.operational_event_writer is None:
            return 0
        if not 1 <= limit <= 100:
            raise ValueError("provider_usage_reconcile_limit_invalid")
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT i.invocation_id,i.owner_id,i.application_id,i.workspace_id,i.task_id,"
                "i.operation,i.request_id,i.run_id,i.endpoint_profile_id,i.endpoint_profile_version,"
                "i.provider_id,i.model_id,i.endpoint_id,i.deployment_id,i.credential_source,"
                "i.credential_scope_id,i.account_scope_id,i.project_scope_id,i.tier_id,"
                "i.execution_mode,i.cost_class,i.billing_owner,i.serializer_id,i.runtime_id,"
                "i.quota_membership,"
                "i.routing_decision_id,i.routing_strategy_id,i.routing_strategy_version,"
                "i.registry_version,i.policy_version,"
                "a.attempt_id,a.parent_attempt_id,a.send_number,a.status,a.error_code,a.http_status,"
                "a.started_at,a.completed_at,a.latency_ms,a.input_tokens,a.output_tokens,a.total_tokens,"
                "a.usage_source,a.usage_confidence,a.unit_usage,a.unit_usage_source,"
                "a.unit_usage_confidence,a.rate_limit_facts "
                "FROM provider_attempts a JOIN provider_invocations i USING(invocation_id) "
                "WHERE a.operational_event_status='pending' AND a.status <> 'pending' "
                "ORDER BY a.started_at,a.attempt_id LIMIT %s",
                (limit,),
            ).fetchall()
        published = 0
        for row in rows:
            event = _event_from_row(row)
            attempt_id = UUID(str(event["attempt_id"]))
            try:
                self.operational_event_writer(event)
            except Exception as error:  # noqa: BLE001 - retry on the next bounded maintenance pass
                logger.info(
                    "provider_usage_event_replay_failed attempt_id=%s error_class=%s",
                    attempt_id,
                    type(error).__name__,
                )
                continue
            self._mark_event(attempt_id, "published")
            published += 1
        return published

    def _publish_event(self, attempt_id: UUID, event: dict) -> None:
        if self.operational_event_writer is None:
            return
        try:
            self.operational_event_writer(event)
        except Exception as error:  # noqa: BLE001 - Postgres remains the authority
            logger.info(
                "provider_usage_event_publish_pending attempt_id=%s error_class=%s",
                attempt_id,
                type(error).__name__,
            )
            return
        self._mark_event(attempt_id, "published")

    def _mark_event(self, attempt_id: UUID, status: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE provider_attempts SET operational_event_status=%s WHERE attempt_id=%s",
                (status, attempt_id),
            )


def _lock_endpoint_health(connection, endpoint):
    # Lock even the bootstrap absence of a row against concurrent settlement.
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"provider-health:{endpoint.endpoint_profile_id}:{endpoint.profile_version}",),
    )


def _health_unavailable(health, now):
    if health is None:
        return False  # Explicit bootstrap: no locally observed failure.
    status, cooldown = health
    if status not in {"healthy", "degraded", "cooldown"}:
        return True
    if cooldown is not None:
        return cooldown > now
    return status != "healthy"


def _request_budget_scope(invocation: InvocationMetadata) -> str:
    """Canonical logical-request key; separate apps/workspaces, share across runs."""
    return json.dumps(
        [
            invocation.owner_id,
            invocation.application_id,
            invocation.workspace_id,
            invocation.request_id,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _scope(application_id, workspace_id):
    from personal_ai.auth.scope import ApplicationScope

    return ApplicationScope(application_id=application_id, workspace_id=workspace_id)


def _insert_invocation(connection, invocation, scope_id, now, retention_until):
    endpoint = invocation.endpoint
    quota_confidence = (
        "unknown"
        if endpoint.quota_membership != "verified"
        or not endpoint.quota_buckets
        or any(bucket.confidence == "unknown" for bucket in endpoint.quota_buckets)
        else "configured"
    )
    connection.execute(
        "INSERT INTO provider_invocations(invocation_id,scope_id,owner_id,application_id,workspace_id,"
        "task_id,operation,request_id,run_id,endpoint_profile_id,endpoint_profile_version,provider_id,"
        "model_id,endpoint_id,deployment_id,credential_source,credential_scope_id,account_scope_id,"
        "project_scope_id,tier_id,execution_mode,cost_class,billing_owner,serializer_id,runtime_id,"
        "quota_membership,"
        "routing_decision_id,routing_strategy_id,routing_strategy_version,registry_version,policy_version,"
        "input_tokens_estimate,output_tokens_bound,quota_confidence,outcome,started_at,retention_until) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
        "%s,%s,%s,%s,%s,%s,%s,%s,%s,'running',%s,%s) ON CONFLICT(invocation_id) DO NOTHING",
        (
            invocation.invocation_id,
            scope_id,
            invocation.owner_id,
            invocation.application_id,
            invocation.workspace_id,
            invocation.task_id,
            invocation.operation,
            invocation.request_id,
            invocation.run_id,
            endpoint.endpoint_profile_id,
            endpoint.profile_version,
            endpoint.provider_id,
            endpoint.model_id,
            endpoint.endpoint_id,
            endpoint.deployment_id,
            endpoint.credential_source,
            endpoint.credential_scope_id,
            endpoint.account_scope_id,
            endpoint.project_scope_id,
            endpoint.tier_id,
            endpoint.execution_mode,
            endpoint.cost_class,
            endpoint.billing_owner,
            endpoint.serializer_id,
            endpoint.runtime_id,
            endpoint.quota_membership,
            invocation.routing_decision_id,
            invocation.routing_strategy_id,
            invocation.routing_strategy_version,
            invocation.registry_version,
            invocation.policy_version,
            invocation.input_tokens_estimate,
            invocation.output_tokens_bound,
            quota_confidence,
            now,
            retention_until,
        ),
    )
    identity = connection.execute(
        "SELECT owner_id,application_id,workspace_id,task_id,operation,request_id,run_id,"
        "endpoint_profile_id,endpoint_profile_version,provider_id,model_id,endpoint_id,deployment_id,"
        "credential_source,credential_scope_id,account_scope_id,project_scope_id,tier_id,execution_mode,"
        "cost_class,billing_owner,serializer_id,runtime_id,quota_membership,routing_decision_id,"
        "routing_strategy_id,routing_strategy_version,registry_version,policy_version "
        "FROM provider_invocations WHERE invocation_id=%s",
        (invocation.invocation_id,),
    ).fetchone()
    expected = (
        invocation.owner_id,
        invocation.application_id,
        invocation.workspace_id,
        invocation.task_id,
        invocation.operation,
        invocation.request_id,
        invocation.run_id,
        endpoint.endpoint_profile_id,
        endpoint.profile_version,
        endpoint.provider_id,
        endpoint.model_id,
        endpoint.endpoint_id,
        endpoint.deployment_id,
        endpoint.credential_source,
        endpoint.credential_scope_id,
        endpoint.account_scope_id,
        endpoint.project_scope_id,
        endpoint.tier_id,
        endpoint.execution_mode,
        endpoint.cost_class,
        endpoint.billing_owner,
        endpoint.serializer_id,
        endpoint.runtime_id,
        endpoint.quota_membership,
        invocation.routing_decision_id,
        invocation.routing_strategy_id,
        invocation.routing_strategy_version,
        invocation.registry_version,
        invocation.policy_version,
    )
    if identity != expected:
        raise ValueError("provider_invocation_identity_conflict")


def _insert_attempt(
    connection,
    invocation,
    attempt,
    reserved_tokens,
    retention_until,
    *,
    status,
    error_code,
    completed_at=None,
):
    connection.execute(
        "INSERT INTO provider_attempts(attempt_id,invocation_id,parent_attempt_id,send_number,status,"
        "error_code,started_at,completed_at,latency_ms,reserved_tokens,retention_until,"
        "operational_event_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            attempt.attempt_id,
            invocation.invocation_id,
            attempt.parent_attempt_id,
            attempt.send_number,
            status,
            _safe_code(error_code),
            attempt.started_at,
            completed_at,
            0 if completed_at is not None else None,
            reserved_tokens,
            retention_until,
            "published" if status == "rejected" else "pending",
        ),
    )


def _applicable_buckets(buckets: tuple[QuotaBucket, ...], operation: str):
    return tuple(
        sorted(
            (bucket for bucket in buckets if operation in bucket.operations),
            key=lambda bucket: bucket.bucket_id,
        )
    )


def _reservation_amount(bucket: QuotaBucket, values: dict[str, int]) -> int | None:
    unit = bucket.unit
    normalized = unit.strip().lower().replace("/", "_").replace("-", "_")
    aliases = {
        "request": "requests",
        "request_count": "requests",
        "calls": "requests",
        "call": "requests",
        "provider_calls": "requests",
        "token": "tokens",
        "input_token": "input_tokens",
        "output_token": "output_tokens",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in values:
        return values[normalized]
    if "request" in normalized or normalized.endswith("_calls"):
        return values.get("requests")
    if "token" in normalized and "input" in normalized:
        return values.get("input_tokens")
    if "token" in normalized and "output" in normalized:
        return values.get("output_tokens")
    if "token" in normalized:
        return values.get("tokens")
    normalized_values = {
        name.strip().lower().replace("/", "_").replace("-", "_"): amount
        for name, amount in values.items()
    }
    return normalized_values.get(normalized, bucket.reservation_units_per_request)


def _quota_window(bucket: QuotaBucket, now: datetime):
    confidence = _bucket_confidence(bucket)
    reset_at = bucket.reset_at
    window = bucket.window_seconds
    if _unknown_daily_bucket(bucket):
        return _utc_day_start(now), None, "unknown"
    if reset_at is not None and window is not None and reset_at <= now:
        periods = int((now - reset_at).total_seconds() // window) + 1
        reset_at = reset_at + timedelta(seconds=periods * window)
        window_start = reset_at - timedelta(seconds=window)
        if confidence != "unknown":
            confidence = "derived"
    elif reset_at is not None and window is not None:
        window_start = reset_at - timedelta(seconds=window)
    else:
        # A configured duration supplies a derived rolling window. A snapshot
        # without duration keeps its original period and becomes unknown on expiry.
        window_start = bucket.observed_at or now
        if reset_at is None and window is not None:
            reset_at = window_start + timedelta(seconds=window)
            if confidence != "unknown":
                confidence = "derived"
    if bucket.fresh_until is not None and bucket.fresh_until <= now:
        confidence = "unknown"
    if reset_at is not None and reset_at <= now and bucket.reset_at is None:
        confidence = "unknown"
    return window_start.astimezone(UTC), reset_at, confidence


def _select_quota_window(connection, bucket: QuotaBucket, now: datetime):
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"provider-quota:{bucket.bucket_id}",),
    )
    latest = connection.execute(
        "SELECT window_start,reset_at,authority_scope_id,unit,confidence,source,fresh_until "
        "FROM provider_quota_bucket_windows WHERE bucket_id=%s "
        "ORDER BY window_start DESC LIMIT 1 FOR UPDATE",
        (bucket.bucket_id,),
    ).fetchone()
    if latest is None:
        return _quota_window(bucket, now)
    window_start, reset_at, authority, unit, existing_confidence, existing_source, fresh_until = (
        latest
    )
    if authority != bucket.authority_scope_id or unit != bucket.unit:
        raise ValueError("provider_quota_bucket_identity_conflict")
    if _unknown_daily_bucket(bucket):
        if (
            existing_source == "provider_headers"
            and existing_confidence != "unknown"
            and (fresh_until is None or fresh_until > now)
            and (reset_at is None or reset_at > now)
        ):
            return window_start.astimezone(UTC), reset_at, existing_confidence
        return _utc_day_start(now), None, "unknown"
    if (
        bucket.observed_at is not None
        and reset_at is not None
        and bucket.reset_at is not None
        and bucket.observed_at > window_start
        and bucket.reset_at > now
    ):
        return (
            bucket.reset_at - timedelta(seconds=bucket.window_seconds or 0),
            bucket.reset_at,
            _bucket_confidence(bucket),
        )
    if reset_at is None or reset_at > now:
        confidence = (
            "unknown"
            if bucket.fresh_until is not None and bucket.fresh_until <= now
            else existing_confidence
        )
        return window_start.astimezone(UTC), reset_at, confidence
    if bucket.window_seconds is not None:
        periods = int((now - reset_at).total_seconds() // bucket.window_seconds) + 1
        next_reset = reset_at + timedelta(seconds=periods * bucket.window_seconds)
        return (
            next_reset - timedelta(seconds=bucket.window_seconds),
            next_reset,
            "derived" if existing_confidence != "unknown" else "unknown",
        )
    # An expired non-periodic snapshot cannot authorize an invented reset.
    return window_start.astimezone(UTC), reset_at, "unknown"


def _bucket_confidence(bucket: QuotaBucket) -> str:
    if bucket.confidence == "unknown":
        return "unknown"
    if bucket.source == "provider_headers":
        return "exact"
    return "configured"


def _unknown_daily_bucket(bucket: QuotaBucket) -> bool:
    return (
        bucket.confidence == "unknown"
        and bucket.limit is None
        and bucket.remaining is None
        and bucket.window_seconds is None
        and bucket.reset_at is None
        and bucket.observed_at is None
    )


def _utc_day_start(value: datetime) -> datetime:
    value = value.astimezone(UTC)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _lock_or_seed_bucket(connection, bucket, window_start, reset_at, confidence, now):
    source = bucket.source
    observed_at = bucket.observed_at
    fresh_until = bucket.fresh_until
    if confidence == "unknown":
        source = "unknown" if bucket.source == "unknown" else bucket.source
    connection.execute(
        "INSERT INTO provider_quota_bucket_windows(bucket_id,authority_scope_id,unit,window_start,"
        "window_seconds,reset_at,source,confidence,evidence_reference,limit_units,reported_remaining,"
        "observed_at,fresh_until,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(bucket_id,window_start) DO NOTHING",
        (
            bucket.bucket_id,
            bucket.authority_scope_id,
            bucket.unit,
            window_start,
            bucket.window_seconds,
            reset_at,
            source,
            confidence,
            bucket.evidence_reference,
            bucket.limit,
            bucket.remaining,
            observed_at,
            fresh_until,
            now,
        ),
    )
    existing = connection.execute(
        "SELECT authority_scope_id,unit,window_seconds,reset_at,observed_at,source,confidence,"
        "limit_units,reported_remaining,consumed_units,reserved_units "
        "FROM provider_quota_bucket_windows "
        "WHERE bucket_id=%s AND window_start=%s FOR UPDATE",
        (bucket.bucket_id, window_start),
    ).fetchone()
    if existing is None:
        raise RuntimeError("provider_quota_bucket_state_missing")
    if existing[0] != bucket.authority_scope_id or existing[1] != bucket.unit:
        raise ValueError("provider_quota_bucket_identity_conflict")
    if (
        bucket.window_seconds is not None
        and existing[2] is not None
        and bucket.window_seconds != existing[2]
    ) or (bucket.reset_at is not None and existing[3] != bucket.reset_at):
        raise ValueError("provider_quota_window_identity_conflict")
    if observed_at is not None and (existing[4] is None or observed_at > existing[4]):
        connection.execute(
            "UPDATE provider_quota_bucket_windows SET source=%s,confidence=%s,evidence_reference=%s,"
            "limit_units=%s,reported_remaining=%s,observed_at=%s,fresh_until=%s,"
            "reset_at=COALESCE(%s,reset_at),updated_at=%s WHERE bucket_id=%s AND window_start=%s",
            (
                source,
                confidence,
                bucket.evidence_reference,
                bucket.limit,
                bucket.remaining,
                observed_at,
                fresh_until,
                reset_at,
                now,
                bucket.bucket_id,
                window_start,
            ),
        )
        return
    if existing[5] == "provider_headers":
        if bucket.limit is not None:
            connection.execute(
                "UPDATE provider_quota_bucket_windows SET limit_units=CASE WHEN limit_units IS NULL "
                "THEN %s ELSE LEAST(limit_units,%s) END,updated_at=%s WHERE bucket_id=%s AND window_start=%s",
                (bucket.limit, bucket.limit, now, bucket.bucket_id, window_start),
            )
        return
    if (
        source in {"operator_attestation", "provider_contract"}
        and confidence != "unknown"
        and (bucket.limit is not None or bucket.remaining is not None)
    ):
        # A live config correction can lower this window immediately. A higher
        # limit never restores capacity already constrained by an older fact
        # or provider remaining observation; it can take effect next window.
        existing_limit = existing[7]
        existing_remaining = existing[8]
        used = int(existing[9]) + int(existing[10])
        conservative_total = existing_limit
        if existing_remaining is not None:
            remaining_total = used + int(existing_remaining)
            conservative_total = (
                remaining_total
                if conservative_total is None
                else min(int(conservative_total), remaining_total)
            )
        if bucket.limit is not None:
            conservative_total = (
                int(bucket.limit)
                if conservative_total is None
                else min(int(conservative_total), int(bucket.limit))
            )
        if bucket.remaining is not None:
            remaining_total = used + int(bucket.remaining)
            conservative_total = (
                remaining_total
                if conservative_total is None
                else min(int(conservative_total), remaining_total)
            )
        connection.execute(
            "UPDATE provider_quota_bucket_windows SET source=%s,confidence=%s,evidence_reference=%s,"
            "limit_units=%s,reported_remaining=NULL,observed_at=NULL,fresh_until=NULL,"
            "window_seconds=COALESCE(%s,window_seconds),reset_at=COALESCE(%s,reset_at),updated_at=%s "
            "WHERE bucket_id=%s AND window_start=%s",
            (
                source,
                confidence,
                bucket.evidence_reference,
                conservative_total,
                bucket.window_seconds,
                reset_at,
                now,
                bucket.bucket_id,
                window_start,
            ),
        )


def _actual_unit_usage(unit: str, result: AttemptResult) -> int | None:
    normalized = unit.strip().lower().replace("/", "_").replace("-", "_")
    if "request" in normalized or normalized in {"calls", "call", "provider_calls"}:
        return 1
    if "input" in normalized and "token" in normalized:
        return result.input_tokens if result.usage_confidence == "exact" else None
    if "output" in normalized and "token" in normalized:
        return result.output_tokens if result.usage_confidence == "exact" else None
    if "token" in normalized:
        return result.total_tokens if result.usage_confidence == "exact" else None
    if result.unit_usage_confidence == "exact":
        unit_usage = {
            name.strip().lower().replace("/", "_").replace("-", "_"): value
            for name, value in result.unit_usage
        }
        return unit_usage.get(normalized)
    return None


def _record_header_observation(
    connection,
    *,
    bucket_id,
    authority_scope,
    unit,
    window_start,
    result,
    observed_at,
    freshness_seconds,
):
    limits = result.rate_limits
    if limits is None:
        return
    normalized = unit.strip().lower().replace("/", "_").replace("-", "_")
    is_request = "request" in normalized or normalized in {"calls", "call", "provider_calls"}
    is_token = "token" in normalized
    if is_request:
        limit, remaining, reset = (
            limits.requests_limit,
            limits.requests_remaining,
            limits.requests_reset_seconds,
        )
    elif is_token:
        limit, remaining, reset = (
            limits.tokens_limit,
            limits.tokens_remaining,
            limits.tokens_reset_seconds,
        )
    else:
        return
    if limit is None and remaining is None:
        return
    reset_at = observed_at + timedelta(seconds=reset) if reset is not None else None
    fresh_until = observed_at + timedelta(seconds=freshness_seconds)
    connection.execute(
        "UPDATE provider_quota_bucket_windows SET source='provider_headers',confidence='exact',"
        "limit_units=COALESCE(%s,limit_units),reported_remaining=%s,"
        "observed_at=%s,fresh_until=%s,reset_at=COALESCE(%s,reset_at),"
        "consumed_units=CASE WHEN %s IS NOT NULL THEN 0 ELSE consumed_units END,"
        "updated_at=%s WHERE bucket_id=%s AND authority_scope_id=%s AND unit=%s AND window_start=%s "
        "AND (observed_at IS NULL OR observed_at<=%s)",
        (
            limit,
            remaining,
            observed_at,
            fresh_until,
            reset_at,
            remaining,
            observed_at,
            bucket_id,
            authority_scope,
            unit,
            window_start,
            observed_at,
        ),
    )


def _update_endpoint_health(connection, invocation, result, now, *, default_cooldown_seconds):
    endpoint = invocation.endpoint
    _lock_endpoint_health(connection, endpoint)
    row = connection.execute(
        "SELECT failure_streak,cooldown_until FROM provider_endpoint_health "
        "WHERE endpoint_profile_id=%s AND endpoint_profile_version=%s FOR UPDATE",
        (endpoint.endpoint_profile_id, endpoint.profile_version),
    ).fetchone()
    failures = int(row[0]) if row else 0
    prior_cooldown = row[1] if row else None
    if result.outcome == "success":
        status = "healthy"
        failures = 0
        cooldown = prior_cooldown if prior_cooldown and prior_cooldown > now else None
        connection.execute(
            "INSERT INTO provider_endpoint_health(endpoint_profile_id,endpoint_profile_version,"
            "health_status,failure_streak,cooldown_until,last_status,last_http_status,last_success_at,"
            "updated_at) VALUES (%s,%s,%s,0,%s,%s,%s,%s,%s) "
            "ON CONFLICT(endpoint_profile_id,endpoint_profile_version) DO UPDATE SET "
            "health_status=EXCLUDED.health_status,failure_streak=0,cooldown_until=EXCLUDED.cooldown_until,"
            "last_status=EXCLUDED.last_status,last_http_status=EXCLUDED.last_http_status,"
            "last_success_at=EXCLUDED.last_success_at,updated_at=EXCLUDED.updated_at",
            (
                endpoint.endpoint_profile_id,
                endpoint.profile_version,
                status,
                cooldown,
                result.outcome,
                result.http_status,
                now,
                now,
            ),
        )
        return
    failures += 1
    if result.outcome == "rate_limited":
        duration = result.rate_limits.retry_after_seconds if result.rate_limits else None
        if duration is None and result.rate_limits:
            duration = (
                result.rate_limits.requests_reset_seconds or result.rate_limits.tokens_reset_seconds
            )
        delay = (
            max(1, min(3600, ceil(duration))) if duration is not None else default_cooldown_seconds
        )
        status = "cooldown"
    else:
        delay = min(default_cooldown_seconds, 5 * (2 ** min(failures - 1, 5)))
        status = "degraded"
    cooldown = now + timedelta(seconds=delay)
    if prior_cooldown is not None and prior_cooldown > cooldown:
        cooldown = prior_cooldown
    connection.execute(
        "INSERT INTO provider_endpoint_health(endpoint_profile_id,endpoint_profile_version,"
        "health_status,failure_streak,cooldown_until,last_status,last_http_status,last_failure_at,updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(endpoint_profile_id,endpoint_profile_version) DO UPDATE SET "
        "health_status=EXCLUDED.health_status,failure_streak=EXCLUDED.failure_streak,"
        "cooldown_until=EXCLUDED.cooldown_until,last_status=EXCLUDED.last_status,"
        "last_http_status=EXCLUDED.last_http_status,last_failure_at=EXCLUDED.last_failure_at,"
        "updated_at=EXCLUDED.updated_at",
        (
            endpoint.endpoint_profile_id,
            endpoint.profile_version,
            status,
            failures,
            cooldown,
            result.outcome,
            result.http_status,
            now,
            now,
        ),
    )


def _aggregate_attempt(
    connection,
    invocation,
    attempt,
    outcome,
    latency,
    input_tokens,
    output_tokens,
    usage_confidence,
    at,
):
    endpoint = invocation.endpoint
    success = int(outcome == "success")
    rate_limited = int(outcome == "rate_limited")
    server_error = int(outcome == "server_error")
    failure = int(outcome in {"incomplete", "rejected", "timeout", "failure", "unknown"})
    exact = int(usage_confidence == "exact")
    derived = int(usage_confidence == "derived")
    unknown = int(usage_confidence == "unknown")
    connection.execute(
        "INSERT INTO provider_usage_daily_aggregates(owner_id,application_id,workspace_id,usage_day,"
        "provider_id,model_id,endpoint_profile_id,endpoint_profile_version,task_id,operation,attempts,successes,rate_limited,"
        "server_errors,failures,retries,latency_total_ms,input_tokens,output_tokens,exact_usage_attempts,"
        "derived_usage_attempts,unknown_usage_attempts,updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(owner_id,application_id,workspace_id,usage_day,endpoint_profile_id,"
        "endpoint_profile_version,task_id,operation) "
        "DO UPDATE SET attempts=provider_usage_daily_aggregates.attempts+1,"
        "successes=provider_usage_daily_aggregates.successes+EXCLUDED.successes,"
        "rate_limited=provider_usage_daily_aggregates.rate_limited+EXCLUDED.rate_limited,"
        "server_errors=provider_usage_daily_aggregates.server_errors+EXCLUDED.server_errors,"
        "failures=provider_usage_daily_aggregates.failures+EXCLUDED.failures,"
        "retries=provider_usage_daily_aggregates.retries+EXCLUDED.retries,"
        "latency_total_ms=provider_usage_daily_aggregates.latency_total_ms+EXCLUDED.latency_total_ms,"
        "input_tokens=provider_usage_daily_aggregates.input_tokens+EXCLUDED.input_tokens,"
        "output_tokens=provider_usage_daily_aggregates.output_tokens+EXCLUDED.output_tokens,"
        "exact_usage_attempts=provider_usage_daily_aggregates.exact_usage_attempts+EXCLUDED.exact_usage_attempts,"
        "derived_usage_attempts=provider_usage_daily_aggregates.derived_usage_attempts+EXCLUDED.derived_usage_attempts,"
        "unknown_usage_attempts=provider_usage_daily_aggregates.unknown_usage_attempts+EXCLUDED.unknown_usage_attempts,"
        "updated_at=EXCLUDED.updated_at",
        (
            invocation.owner_id,
            invocation.application_id,
            invocation.workspace_id,
            at.date(),
            endpoint.provider_id,
            endpoint.model_id,
            endpoint.endpoint_profile_id,
            endpoint.profile_version,
            invocation.task_id,
            invocation.operation,
            success,
            rate_limited,
            server_error,
            failure,
            int(attempt.parent_attempt_id is not None),
            max(0, int(latency)),
            max(0, int(input_tokens)),
            max(0, int(output_tokens)),
            exact,
            derived,
            unknown,
            at,
        ),
    )


def _aggregate_identity(
    owner_id,
    application_id,
    workspace_id,
    task_id,
    operation,
    provider_id,
    model_id,
    endpoint_profile_id,
    endpoint_profile_version,
):
    return SimpleNamespace(
        owner_id=owner_id,
        application_id=application_id,
        workspace_id=workspace_id,
        task_id=task_id,
        operation=operation,
        endpoint=SimpleNamespace(
            provider_id=provider_id,
            model_id=model_id,
            endpoint_profile_id=endpoint_profile_id,
            profile_version=endpoint_profile_version,
        ),
    )


def _rate_limit_payload(result):
    if result.rate_limits is None:
        return {}
    values = asdict(result.rate_limits)
    return {key: value for key, value in values.items() if value is not None}


def _operational_event(invocation, attempt, result):
    endpoint = invocation.endpoint
    return {
        "schema_version": "provider-usage-event-v1",
        "event_id": str(attempt.attempt_id),
        "invocation_id": str(invocation.invocation_id),
        "attempt_id": str(attempt.attempt_id),
        "parent_attempt_id": str(attempt.parent_attempt_id) if attempt.parent_attempt_id else None,
        "send_number": attempt.send_number,
        "owner_id": invocation.owner_id,
        "application_id": invocation.application_id,
        "workspace_id": invocation.workspace_id,
        "task_id": invocation.task_id,
        "operation": invocation.operation,
        "request_id": invocation.request_id,
        "run_id": invocation.run_id,
        "endpoint_profile_id": endpoint.endpoint_profile_id,
        "endpoint_profile_version": endpoint.profile_version,
        "provider_id": endpoint.provider_id,
        "model_id": endpoint.model_id,
        "endpoint_id": endpoint.endpoint_id,
        "deployment_id": endpoint.deployment_id,
        "credential_source": endpoint.credential_source,
        "credential_scope_id": endpoint.credential_scope_id,
        "account_scope_id": endpoint.account_scope_id,
        "project_scope_id": endpoint.project_scope_id,
        "tier_id": endpoint.tier_id,
        "execution_mode": endpoint.execution_mode,
        "cost_class": endpoint.cost_class,
        "billing_owner": endpoint.billing_owner,
        "serializer_id": endpoint.serializer_id,
        "runtime_id": endpoint.runtime_id,
        "quota_membership": endpoint.quota_membership,
        "routing_decision_id": invocation.routing_decision_id,
        "routing_strategy_id": invocation.routing_strategy_id,
        "routing_strategy_version": invocation.routing_strategy_version,
        "registry_version": invocation.registry_version,
        "policy_version": invocation.policy_version,
        "status": result.outcome,
        "error_code": _safe_code(result.error_code),
        "http_status": result.http_status,
        "started_at": attempt.started_at.astimezone(UTC).isoformat(),
        "completed_at": result.completed_at.astimezone(UTC).isoformat(),
        "latency_ms": max(0, result.latency_ms),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "usage_source": result.usage_source,
        "usage_confidence": result.usage_confidence,
        "unit_usage": dict(result.unit_usage),
        "unit_usage_source": result.unit_usage_source,
        "unit_usage_confidence": result.unit_usage_confidence,
        "rate_limits": _rate_limit_payload(result),
    }


def _event_from_row(row):
    keys = (
        "invocation_id",
        "owner_id",
        "application_id",
        "workspace_id",
        "task_id",
        "operation",
        "request_id",
        "run_id",
        "endpoint_profile_id",
        "endpoint_profile_version",
        "provider_id",
        "model_id",
        "endpoint_id",
        "deployment_id",
        "credential_source",
        "credential_scope_id",
        "account_scope_id",
        "project_scope_id",
        "tier_id",
        "execution_mode",
        "cost_class",
        "billing_owner",
        "serializer_id",
        "runtime_id",
        "quota_membership",
        "routing_decision_id",
        "routing_strategy_id",
        "routing_strategy_version",
        "registry_version",
        "policy_version",
        "attempt_id",
        "parent_attempt_id",
        "send_number",
        "status",
        "error_code",
        "http_status",
        "started_at",
        "completed_at",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "usage_source",
        "usage_confidence",
        "unit_usage",
        "unit_usage_source",
        "unit_usage_confidence",
        "rate_limits",
    )
    values = dict(zip(keys, row, strict=True))
    for name in ("invocation_id", "attempt_id", "parent_attempt_id"):
        if values[name] is not None:
            values[name] = str(values[name])
    for name in ("started_at", "completed_at"):
        if values[name] is not None:
            values[name] = values[name].astimezone(UTC).isoformat()
    return {
        "schema_version": "provider-usage-event-v1",
        "event_id": values["attempt_id"],
        **{
            key: values[key]
            for key in (
                "invocation_id",
                "attempt_id",
                "parent_attempt_id",
                "send_number",
                "owner_id",
                "application_id",
                "workspace_id",
                "task_id",
                "operation",
                "request_id",
                "run_id",
                "endpoint_profile_id",
                "endpoint_profile_version",
                "provider_id",
                "model_id",
                "endpoint_id",
                "deployment_id",
                "credential_source",
                "credential_scope_id",
                "account_scope_id",
                "project_scope_id",
                "tier_id",
                "execution_mode",
                "cost_class",
                "billing_owner",
                "serializer_id",
                "runtime_id",
                "quota_membership",
                "routing_decision_id",
                "routing_strategy_id",
                "routing_strategy_version",
                "registry_version",
                "policy_version",
                "status",
                "error_code",
                "http_status",
                "started_at",
                "completed_at",
                "latency_ms",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "usage_source",
                "usage_confidence",
                "unit_usage",
                "unit_usage_source",
                "unit_usage_confidence",
            )
        },
        "rate_limits": values["rate_limits"] or {},
    }


def _safe_code(value):
    if not value:
        return None
    cleaned = "".join(char for char in str(value) if char.isalnum() or char in "._-:")
    return cleaned[:100] or None


def _bounded_text(value, limit):
    cleaned = "".join(char for char in str(value) if char.isalnum() or char in "._-:")
    return cleaned[:limit]


def _iso(value):
    return value.astimezone(UTC).isoformat() if value is not None else None
