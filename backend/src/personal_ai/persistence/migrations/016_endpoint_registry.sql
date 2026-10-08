-- The system endpoint catalog is a bounded, secret-free routing snapshot.
-- It is service policy rather than owner memory or conversation runtime data.
CREATE TABLE IF NOT EXISTS endpoint_registry_snapshots (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    record_id text NOT NULL CHECK (record_id = 'endpoint-registry-v1'),
    owner_id text NOT NULL CHECK (owner_id = 'personal-ai-system'),
    application_id text NOT NULL CHECK (application_id = 'personal_ai'),
    workspace_id text CHECK (workspace_id IS NULL),
    record_version smallint NOT NULL DEFAULT 1 CHECK (record_version = 1),
    revision bigint NOT NULL CHECK (revision > 0),
    registry_version char(64) NOT NULL CHECK (registry_version ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    payload jsonb NOT NULL CHECK (pg_column_size(payload) <= 262144),
    PRIMARY KEY (scope_id, record_id)
);

CREATE INDEX IF NOT EXISTS endpoint_registry_snapshots_updated_idx
    ON endpoint_registry_snapshots(updated_at, record_id);

-- Profile IDs remain versioned identities after removal. Keeping the high-water
-- mark outside the bounded active snapshot prevents a deleted ID from being
-- reused with facts that look like an older endpoint to later evidence.
CREATE TABLE IF NOT EXISTS endpoint_profile_version_history (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    endpoint_profile_id text NOT NULL CHECK (length(endpoint_profile_id) BETWEEN 1 AND 200),
    last_profile_version integer NOT NULL CHECK (last_profile_version BETWEEN 1 AND 2147483647),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (scope_id, endpoint_profile_id)
);
