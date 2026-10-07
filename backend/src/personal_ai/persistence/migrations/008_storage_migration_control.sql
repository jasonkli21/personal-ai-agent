-- Migration control is deliberately separate from the records being imported.
CREATE TABLE IF NOT EXISTS storage_migration_epochs (
    epoch_id text PRIMARY KEY CHECK (length(epoch_id) BETWEEN 1 AND 120),
    source_project_id text NOT NULL CHECK (length(source_project_id) BETWEEN 1 AND 200),
    source_database_id text NOT NULL DEFAULT '(default)',
    source_schema_version text NOT NULL,
    target_schema_version text NOT NULL,
    config_fingerprint char(64) NOT NULL CHECK (config_fingerprint ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('backfill', 'final-delta', 'blocked')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS storage_migration_checkpoints (
    epoch_id text NOT NULL REFERENCES storage_migration_epochs(epoch_id) ON DELETE RESTRICT,
    family text NOT NULL,
    last_source_document_id text,
    generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
    scan_state text NOT NULL DEFAULT 'pending' CHECK (scan_state IN ('pending', 'running', 'complete')),
    scanned_count bigint NOT NULL DEFAULT 0 CHECK (scanned_count >= 0),
    applied_count bigint NOT NULL DEFAULT 0 CHECK (applied_count >= 0),
    rejected_count bigint NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (epoch_id, family)
);

CREATE TABLE IF NOT EXISTS storage_migration_records (
    epoch_id text NOT NULL REFERENCES storage_migration_epochs(epoch_id) ON DELETE RESTRICT,
    family text NOT NULL,
    source_document_id text NOT NULL CHECK (length(source_document_id) BETWEEN 1 AND 512),
    logical_id text NOT NULL CHECK (length(logical_id) BETWEEN 1 AND 512),
    target_store text NOT NULL CHECK (target_store IN ('dynamodb', 'postgres')),
    source_version text NOT NULL,
    source_hash char(64) NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    mapped_hash char(64) CHECK (mapped_hash IS NULL OR mapped_hash ~ '^[0-9a-f]{64}$'),
    target_hash char(64) NOT NULL CHECK (target_hash ~ '^[0-9a-f]{64}$'),
    disposition text NOT NULL CHECK (disposition IN ('applied', 'rejected', 'source-deleted', 'disposed')),
    rejection_code text,
    disposition_code text,
    seen_generation bigint NOT NULL DEFAULT 0 CHECK (seen_generation >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (epoch_id, family, source_document_id),
    CHECK ((disposition = 'rejected') = (rejection_code IS NOT NULL)),
    CHECK ((disposition = 'disposed') = (disposition_code IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS storage_migration_records_generation_idx
    ON storage_migration_records(epoch_id, family, seen_generation, disposition);

-- Older Firestore lifecycle operation documents describe completed work but do
-- not contain the P10.3 receipt protocol's attempt, fingerprint, or deadline.
-- Keep those original records queryable without inventing receipt semantics.
CREATE TABLE IF NOT EXISTS legacy_memory_lifecycle_operations (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    record_id text NOT NULL CHECK (length(record_id) BETWEEN 1 AND 512),
    owner_id text NOT NULL,
    application_id text NOT NULL,
    workspace_id text,
    created_at timestamptz NOT NULL,
    payload jsonb NOT NULL CHECK (pg_column_size(payload) <= 32768),
    PRIMARY KEY (scope_id, record_id)
);

CREATE INDEX IF NOT EXISTS legacy_memory_lifecycle_operations_scope_idx
    ON legacy_memory_lifecycle_operations(owner_id, application_id, workspace_id, created_at, record_id);
