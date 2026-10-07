DROP TABLE IF EXISTS legacy_memory_lifecycle_operations;
DROP TABLE IF EXISTS storage_migration_records;
DROP TABLE IF EXISTS storage_migration_checkpoints;
DROP TABLE IF EXISTS storage_migration_epochs;

ALTER TABLE derived_memory_sources
    DROP COLUMN IF EXISTS source_document_id,
    DROP COLUMN IF EXISTS scope_version,
    DROP COLUMN IF EXISTS source_payload;

ALTER TABLE memory_lifecycle_operations
    DROP COLUMN IF EXISTS payload;

ALTER TABLE domain_provider_rate_limits
    DROP COLUMN IF EXISTS payload;
