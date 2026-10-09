"""Bounded, provider-neutral usage accounting records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from personal_ai.usage.quota import QuotaObservation

if TYPE_CHECKING:
    from personal_ai.llm.metadata import ProviderRateLimitMetadata
    from personal_ai.routing.contracts import EndpointCandidateRequirements, EndpointProfile
    from personal_ai.usage.quota import EndpointRuntimeSnapshot

AttemptOutcome = Literal[
    "success",
    "incomplete",
    "rejected",
    "rate_limited",
    "server_error",
    "timeout",
    "failure",
    "unknown",
]
UsageConfidence = Literal["exact", "derived", "configured", "unknown"]


class UsageAdmissionDenied(RuntimeError):
    """A known attempt, token, quota or endpoint-health budget denied dispatch."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProviderEndpoint:
    """Immutable accounting projection for fixed-provider/lookup adapters, not a catalog."""

    endpoint_profile_id: str
    profile_version: int
    provider_id: str
    model_id: str
    endpoint_id: str
    deployment_id: str
    credential_source: str
    credential_scope_id: str | None
    account_scope_id: str | None
    project_scope_id: str | None
    tier_id: str
    execution_mode: str
    cost_class: str
    billing_owner: str
    serializer_id: str
    runtime_id: str
    quota_membership: Literal["verified", "unknown", "ambiguous"] = "unknown"
    registry_version: str | None = None
    registry_revision: int | None = None
    quota_buckets: tuple[QuotaObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class InvocationMetadata:
    """Immutable logical operation identity, without request or credential data."""

    invocation_id: UUID
    owner_id: str
    application_id: str
    workspace_id: str | None
    task_id: str
    operation: str
    request_id: str
    run_id: str | None
    endpoint: ProviderEndpoint
    routing_decision_id: str | None = None
    routing_strategy_id: str | None = None
    routing_strategy_version: str | None = None
    registry_version: str | None = None
    policy_version: str | None = None
    input_tokens_estimate: int | None = None
    output_tokens_bound: int | None = None


@dataclass(frozen=True, slots=True)
class AttemptMetadata:
    """Physical send identity reserved immediately before HTTP dispatch."""

    attempt_id: UUID
    parent_attempt_id: UUID | None
    send_number: int
    started_at: datetime
    reservation_units: tuple[tuple[str, int], ...]
    reserved_tokens: int = 0


@dataclass(frozen=True, slots=True)
class AttemptResult:
    """Safe terminal facts for one physical attempt."""

    outcome: AttemptOutcome
    completed_at: datetime
    latency_ms: int
    http_status: int | None = None
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    usage_source: str = "unknown"
    usage_confidence: UsageConfidence = "unknown"
    unit_usage: tuple[tuple[str, int], ...] = ()
    unit_usage_source: str = "unknown"
    unit_usage_confidence: UsageConfidence = "unknown"
    rate_limits: ProviderRateLimitMetadata | None = None

    def __post_init__(self) -> None:
        names = [name for name, _ in self.unit_usage]
        if len(names) != len(set(names)):
            raise ValueError("provider_unit_usage_duplicate")
        if any(
            not name or len(name) > 80 or isinstance(value, bool) or value < 0
            for name, value in self.unit_usage
        ):
            raise ValueError("provider_unit_usage_invalid")


class ProviderUsageAccounting(Protocol):
    """The blocking canonical ledger and optional operational event publisher."""

    def begin_invocation(self, invocation: InvocationMetadata) -> None: ...

    def reserve_attempt(
        self, invocation: InvocationMetadata, attempt: AttemptMetadata, *, max_attempts: int
    ) -> AttemptMetadata | None: ...

    def assert_request_budget_in_transaction(
        self, connection, invocation: InvocationMetadata, *, max_reserved_tokens: int,
        quota_limits: dict[str, int],
    ) -> None: ...

    def assert_invocation_unstarted_in_transaction(
        self, connection, invocation: InvocationMetadata,
    ) -> None: ...

    def settle_attempt(
        self, invocation: InvocationMetadata, attempt: AttemptMetadata, result: AttemptResult
    ) -> None: ...

    def complete_invocation(
        self, invocation: InvocationMetadata, *, outcome: AttemptOutcome,
        completed_at: datetime
    ) -> None: ...

    def routing_snapshots(
        self,
        connection,
        profiles: Sequence[EndpointProfile],
        requirements: EndpointCandidateRequirements,
        *,
        operation: str,
        now: datetime,
        check_capacity: bool = True,
    ) -> dict[str, EndpointRuntimeSnapshot]: ...

    def summary(self, *, owner_id: str, application_id: str, workspace_id: str | None,
                days: int = 30) -> dict: ...

    def purge_expired(self, *, limit: int) -> int: ...

    def reconcile_operational_events(self, *, limit: int) -> int: ...

    def resolve_stale_attempts(self, *, limit: int) -> int: ...
