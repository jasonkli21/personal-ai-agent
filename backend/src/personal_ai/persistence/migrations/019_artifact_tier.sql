-- Compact references only. Immutable bodies live in private GCS; no DB blob mirror.
CREATE TABLE artifact_metadata (
    artifact_id uuid PRIMARY KEY,
    owner_id text NOT NULL,
    application_id text NOT NULL,
    workspace_id text,
    kind text NOT NULL CHECK (kind IN ('context_trace','routing_trace','evaluation','export','debug_replay')),
    identity text NOT NULL,
    routing_decision_id uuid,
    invocation_id uuid,
    evaluation_run_id uuid,
    cascade_run_id uuid,
    status text NOT NULL CHECK (status IN ('pending','ready','missing','deleting','deleted')),
    revision bigint NOT NULL CHECK (revision > 0),
    compressed_bytes bigint NOT NULL CHECK (compressed_bytes BETWEEN 1 AND 1048576),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    last_checked_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL CHECK (octet_length(payload::text) <= 8192),
    CHECK (expires_at > created_at AND expires_at <= created_at + interval '90 days')
);
CREATE INDEX artifact_scope_list ON artifact_metadata(owner_id,application_id,workspace_id,created_at);
CREATE INDEX artifact_reconcile ON artifact_metadata(status,expires_at,artifact_id);
CREATE INDEX artifact_routing_join ON artifact_metadata(owner_id,application_id,workspace_id,routing_decision_id);
CREATE INDEX artifact_invocation_join ON artifact_metadata(owner_id,application_id,workspace_id,invocation_id);
CREATE INDEX artifact_evaluation_join ON artifact_metadata(owner_id,application_id,workspace_id,evaluation_run_id);
CREATE TABLE artifact_storage_budgets (
    budget_day date PRIMARY KEY,
    operations bigint NOT NULL CHECK (operations >= 0),
    write_bytes bigint NOT NULL CHECK (write_bytes >= 0),
    read_bytes bigint NOT NULL CHECK (read_bytes >= 0),
    objects bigint NOT NULL CHECK (objects >= 0)
);
-- Owner-wide fence survives physical body cleanup; it is never an access grant.
CREATE TABLE artifact_owner_fences (
    owner_id text PRIMARY KEY,
    fenced_at timestamptz NOT NULL DEFAULT now(),
    deletion_request_id uuid
);
