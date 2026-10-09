-- Postgres owns the canonical invocation lifecycle, quota reservations and
-- compact owner-attributed aggregates. Prompts, responses and credentials are
-- intentionally absent from these tables.
CREATE TABLE IF NOT EXISTS provider_invocations (
    invocation_id uuid PRIMARY KEY,
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    owner_id text NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 200),
    application_id text NOT NULL CHECK (length(application_id) BETWEEN 2 AND 42),
    workspace_id text CHECK (workspace_id IS NULL OR length(workspace_id) BETWEEN 1 AND 100),
    task_id text NOT NULL CHECK (length(task_id) BETWEEN 1 AND 200),
    operation text NOT NULL CHECK (length(operation) BETWEEN 1 AND 80),
    request_id text NOT NULL CHECK (length(request_id) BETWEEN 1 AND 200),
    run_id text CHECK (run_id IS NULL OR length(run_id) <= 200),
    endpoint_profile_id text NOT NULL CHECK (length(endpoint_profile_id) BETWEEN 1 AND 200),
    endpoint_profile_version integer NOT NULL CHECK (endpoint_profile_version > 0),
    provider_id text NOT NULL CHECK (length(provider_id) BETWEEN 1 AND 200),
    model_id text NOT NULL CHECK (length(model_id) BETWEEN 1 AND 200),
    endpoint_id text NOT NULL CHECK (length(endpoint_id) BETWEEN 1 AND 200),
    deployment_id text NOT NULL CHECK (length(deployment_id) BETWEEN 1 AND 200),
    credential_source text NOT NULL CHECK (length(credential_source) BETWEEN 1 AND 80),
    credential_scope_id text CHECK (credential_scope_id IS NULL OR length(credential_scope_id) <= 200),
    account_scope_id text CHECK (account_scope_id IS NULL OR length(account_scope_id) <= 200),
    project_scope_id text CHECK (project_scope_id IS NULL OR length(project_scope_id) <= 200),
    tier_id text NOT NULL CHECK (length(tier_id) BETWEEN 1 AND 80),
    execution_mode text NOT NULL CHECK (execution_mode IN ('STRICT_FREE','EXPLICIT_BYOK','CHATGPT_PLAN')),
    cost_class text NOT NULL CHECK (cost_class IN ('VERIFIED_FREE','USER_BILLED','SUBSCRIPTION','UNKNOWN')),
    billing_owner text NOT NULL CHECK (billing_owner IN ('provider_account','user','subscription','unknown')),
    serializer_id text NOT NULL CHECK (length(serializer_id) BETWEEN 1 AND 200),
    runtime_id text NOT NULL CHECK (length(runtime_id) BETWEEN 1 AND 200),
    routing_decision_id text CHECK (routing_decision_id IS NULL OR length(routing_decision_id) <= 200),
    routing_strategy_id text CHECK (routing_strategy_id IS NULL OR length(routing_strategy_id) <= 200),
    routing_strategy_version text CHECK (routing_strategy_version IS NULL OR length(routing_strategy_version) <= 100),
    registry_version text CHECK (registry_version IS NULL OR length(registry_version) <= 100),
    policy_version text CHECK (policy_version IS NULL OR length(policy_version) <= 100),
    input_tokens_estimate bigint CHECK (input_tokens_estimate IS NULL OR input_tokens_estimate >= 0),
    output_tokens_bound bigint CHECK (output_tokens_bound IS NULL OR output_tokens_bound >= 0),
    quota_confidence text NOT NULL CHECK (quota_confidence IN ('exact','derived','configured','unknown')),
    outcome text NOT NULL DEFAULT 'running'
        CHECK (outcome IN ('running','success','incomplete','rejected','rate_limited','server_error','timeout','failure','unknown')),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    retention_until timestamptz NOT NULL,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX IF NOT EXISTS provider_invocations_owner_time_idx
    ON provider_invocations(owner_id, application_id, workspace_id, started_at DESC, invocation_id);
CREATE INDEX IF NOT EXISTS provider_invocations_request_idx
    ON provider_invocations(owner_id, request_id, started_at DESC, invocation_id);
CREATE INDEX IF NOT EXISTS provider_invocations_expiry_idx
    ON provider_invocations(retention_until, invocation_id);

CREATE TABLE IF NOT EXISTS provider_attempts (
    attempt_id uuid PRIMARY KEY,
    invocation_id uuid NOT NULL REFERENCES provider_invocations(invocation_id) ON DELETE CASCADE,
    parent_attempt_id uuid REFERENCES provider_attempts(attempt_id) ON DELETE SET NULL,
    send_number integer NOT NULL CHECK (send_number BETWEEN 1 AND 256),
    status text NOT NULL
        CHECK (status IN ('pending','success','incomplete','rejected','rate_limited','server_error','timeout','failure','unknown')),
    error_code text CHECK (error_code IS NULL OR length(error_code) <= 100),
    http_status integer CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    latency_ms integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
    reserved_tokens bigint NOT NULL DEFAULT 0 CHECK (reserved_tokens >= 0),
    input_tokens bigint CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens bigint CHECK (output_tokens IS NULL OR output_tokens >= 0),
    total_tokens bigint CHECK (total_tokens IS NULL OR total_tokens >= 0),
    usage_source text NOT NULL DEFAULT 'unknown' CHECK (length(usage_source) <= 80),
    usage_confidence text NOT NULL DEFAULT 'unknown'
        CHECK (usage_confidence IN ('exact','derived','configured','unknown')),
    unit_usage jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (pg_column_size(unit_usage) <= 1024),
    unit_usage_source text NOT NULL DEFAULT 'unknown' CHECK (length(unit_usage_source) <= 80),
    unit_usage_confidence text NOT NULL DEFAULT 'unknown'
        CHECK (unit_usage_confidence IN ('exact','derived','configured','unknown')),
    rate_limit_facts jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (pg_column_size(rate_limit_facts) <= 4096),
    operational_event_status text NOT NULL DEFAULT 'pending'
        CHECK (operational_event_status IN ('pending','published','failed')),
    retention_until timestamptz NOT NULL,
    UNIQUE (invocation_id, send_number),
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX IF NOT EXISTS provider_attempts_invocation_idx
    ON provider_attempts(invocation_id, send_number);
CREATE INDEX IF NOT EXISTS provider_attempts_retention_idx
    ON provider_attempts(retention_until, attempt_id);
CREATE INDEX IF NOT EXISTS provider_attempts_event_sync_idx
    ON provider_attempts(operational_event_status, started_at, attempt_id)
    WHERE operational_event_status <> 'published';

-- Bucket identity is account authority, not endpoint or credential identity.
-- A row is one observed quota window; unknown snapshots keep NULL capacity.
CREATE TABLE IF NOT EXISTS provider_quota_bucket_windows (
    bucket_id text NOT NULL CHECK (length(bucket_id) BETWEEN 1 AND 200),
    authority_scope_id text NOT NULL CHECK (length(authority_scope_id) BETWEEN 1 AND 200),
    unit text NOT NULL CHECK (length(unit) BETWEEN 1 AND 80),
    window_start timestamptz NOT NULL,
    window_seconds integer CHECK (window_seconds IS NULL OR window_seconds BETWEEN 1 AND 31536000),
    reset_at timestamptz,
    source text NOT NULL CHECK (source IN ('provider_contract','provider_headers','operator_attestation','unknown')),
    confidence text NOT NULL CHECK (confidence IN ('exact','derived','configured','unknown')),
    evidence_reference text CHECK (evidence_reference IS NULL OR length(evidence_reference) <= 500),
    limit_units bigint CHECK (limit_units IS NULL OR limit_units >= 0),
    reported_remaining bigint CHECK (reported_remaining IS NULL OR reported_remaining >= 0),
    observed_at timestamptz,
    fresh_until timestamptz,
    consumed_units bigint NOT NULL DEFAULT 0 CHECK (consumed_units >= 0),
    reserved_units bigint NOT NULL DEFAULT 0 CHECK (reserved_units >= 0),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (bucket_id, window_start),
    CHECK (fresh_until IS NULL OR observed_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS provider_quota_bucket_latest_idx
    ON provider_quota_bucket_windows(bucket_id, window_start DESC);

CREATE TABLE IF NOT EXISTS provider_quota_reservations (
    attempt_id uuid NOT NULL REFERENCES provider_attempts(attempt_id) ON DELETE CASCADE,
    bucket_id text NOT NULL CHECK (length(bucket_id) BETWEEN 1 AND 200),
    authority_scope_id text NOT NULL CHECK (length(authority_scope_id) BETWEEN 1 AND 200),
    unit text NOT NULL CHECK (length(unit) BETWEEN 1 AND 80),
    window_start timestamptz NOT NULL,
    reserved_units bigint NOT NULL CHECK (reserved_units >= 0),
    settled_units bigint CHECK (settled_units IS NULL OR settled_units >= 0),
    state text NOT NULL CHECK (state IN ('reserved','settled','uncertain','unknown')),
    confidence text NOT NULL CHECK (confidence IN ('exact','derived','configured','unknown')),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (attempt_id, bucket_id),
    FOREIGN KEY (bucket_id, window_start)
        REFERENCES provider_quota_bucket_windows(bucket_id, window_start) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS provider_endpoint_health (
    endpoint_profile_id text NOT NULL CHECK (length(endpoint_profile_id) BETWEEN 1 AND 200),
    endpoint_profile_version integer NOT NULL CHECK (endpoint_profile_version > 0),
    health_status text NOT NULL CHECK (health_status IN ('unknown','healthy','degraded','cooldown')),
    failure_streak integer NOT NULL DEFAULT 0 CHECK (failure_streak >= 0),
    cooldown_until timestamptz,
    last_status text CHECK (last_status IS NULL OR length(last_status) <= 40),
    last_http_status integer CHECK (last_http_status IS NULL OR last_http_status BETWEEN 100 AND 599),
    last_success_at timestamptz,
    last_failure_at timestamptz,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (endpoint_profile_id, endpoint_profile_version)
);

CREATE TABLE IF NOT EXISTS provider_usage_daily_aggregates (
    owner_id text NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 200),
    application_id text NOT NULL CHECK (length(application_id) BETWEEN 2 AND 42),
    workspace_id text CHECK (workspace_id IS NULL OR length(workspace_id) BETWEEN 1 AND 100),
    usage_day date NOT NULL,
    provider_id text NOT NULL CHECK (length(provider_id) BETWEEN 1 AND 200),
    model_id text NOT NULL CHECK (length(model_id) BETWEEN 1 AND 200),
    endpoint_profile_id text NOT NULL CHECK (length(endpoint_profile_id) BETWEEN 1 AND 200),
    task_id text NOT NULL CHECK (length(task_id) BETWEEN 1 AND 200),
    operation text NOT NULL CHECK (length(operation) BETWEEN 1 AND 80),
    attempts bigint NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    successes bigint NOT NULL DEFAULT 0 CHECK (successes >= 0),
    rate_limited bigint NOT NULL DEFAULT 0 CHECK (rate_limited >= 0),
    server_errors bigint NOT NULL DEFAULT 0 CHECK (server_errors >= 0),
    failures bigint NOT NULL DEFAULT 0 CHECK (failures >= 0),
    retries bigint NOT NULL DEFAULT 0 CHECK (retries >= 0),
    latency_total_ms bigint NOT NULL DEFAULT 0 CHECK (latency_total_ms >= 0),
    input_tokens bigint NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens bigint NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    exact_usage_attempts bigint NOT NULL DEFAULT 0 CHECK (exact_usage_attempts >= 0),
    derived_usage_attempts bigint NOT NULL DEFAULT 0 CHECK (derived_usage_attempts >= 0),
    unknown_usage_attempts bigint NOT NULL DEFAULT 0 CHECK (unknown_usage_attempts >= 0),
    updated_at timestamptz NOT NULL,
    UNIQUE NULLS NOT DISTINCT (owner_id, application_id, workspace_id, usage_day,
                              endpoint_profile_id, task_id, operation)
);

CREATE INDEX IF NOT EXISTS provider_usage_daily_owner_idx
    ON provider_usage_daily_aggregates(owner_id, application_id, workspace_id, usage_day DESC);
