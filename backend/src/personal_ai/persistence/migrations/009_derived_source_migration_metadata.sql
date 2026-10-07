-- Preserve the source relation envelope and timestamp during P10.4 migration.
ALTER TABLE derived_memory_sources
    ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE derived_memory_sources
    ADD COLUMN IF NOT EXISTS source_document_id text;
ALTER TABLE derived_memory_sources
    ADD COLUMN IF NOT EXISTS scope_version smallint NOT NULL DEFAULT 2
        CHECK (scope_version IN (1, 2));
ALTER TABLE derived_memory_sources
    ADD COLUMN IF NOT EXISTS source_payload jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (pg_column_size(source_payload) <= 32768);
