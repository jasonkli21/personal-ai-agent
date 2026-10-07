-- Preserve the complete global Firestore operational envelope during P10.4.
ALTER TABLE domain_provider_rate_limits
    ADD COLUMN IF NOT EXISTS payload jsonb
        CHECK (payload IS NULL OR pg_column_size(payload) <= 32768);
