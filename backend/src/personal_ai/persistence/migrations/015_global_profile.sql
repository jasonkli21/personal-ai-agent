-- Owner-wide AI profile values are sparse, typed, and shareable per field.
-- The canonical profile namespace is personal_ai with no workspace; callers
-- receive only fields explicitly shared with their application.
CREATE TABLE IF NOT EXISTS global_profiles (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    record_id text NOT NULL CHECK (record_id = 'owner-global-profile-v1'),
    owner_id text NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 200),
    application_id text NOT NULL CHECK (application_id = 'personal_ai'),
    workspace_id text CHECK (workspace_id IS NULL),
    record_version smallint NOT NULL DEFAULT 1 CHECK (record_version = 1),
    status text CHECK (status IS NULL OR length(status) <= 80),
    revision bigint NOT NULL CHECK (revision > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    expires_at timestamptz,
    fingerprint char(64),
    idempotency_key text,
    payload jsonb NOT NULL CHECK (pg_column_size(payload) <= 16384),
    PRIMARY KEY (scope_id, record_id),
    CHECK (fingerprint IS NULL OR fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS global_profiles_owner_updated_idx
    ON global_profiles(owner_id, updated_at, record_id);
