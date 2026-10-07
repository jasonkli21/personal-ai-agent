-- The receipt identity remains the P10.3 operation/attempt pair. This opaque
-- envelope lets the migration ledger compare the exact historical Firestore
-- record without reconstructing its scope version or provenance fields.
ALTER TABLE memory_lifecycle_operations
    ADD COLUMN IF NOT EXISTS payload jsonb
        CHECK (payload IS NULL OR pg_column_size(payload) <= 32768);
