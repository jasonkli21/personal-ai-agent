ALTER TABLE storage_migration_records
    ADD COLUMN IF NOT EXISTS owner_id text;
ALTER TABLE storage_migration_records
    ADD COLUMN IF NOT EXISTS application_id text;
ALTER TABLE storage_migration_records
    ADD COLUMN IF NOT EXISTS workspace_id text;
ALTER TABLE storage_migration_records
    ADD COLUMN IF NOT EXISTS target_locator jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (pg_column_size(target_locator) <= 8192);

CREATE UNIQUE INDEX IF NOT EXISTS storage_migration_target_identity_uq
    ON storage_migration_records(
        epoch_id, family, target_store, logical_id, owner_id, application_id,
        (COALESCE(workspace_id, ''))
    )
    WHERE disposition IN ('applied', 'rejected') AND target_hash <> repeat('0', 64);
