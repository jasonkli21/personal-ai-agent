-- Aggregate identity must retain endpoint revisions. Pre-migration aggregates
-- have no trustworthy revision, so their version remains NULL.
ALTER TABLE provider_invocations
    ADD COLUMN IF NOT EXISTS quota_membership text NOT NULL DEFAULT 'unknown'
        CHECK (quota_membership IN ('verified','unknown','ambiguous'));

ALTER TABLE provider_usage_daily_aggregates
    ADD COLUMN IF NOT EXISTS endpoint_profile_version integer
        CHECK (endpoint_profile_version IS NULL OR endpoint_profile_version > 0);

DO $$
DECLARE
    existing_constraint record;
BEGIN
    FOR existing_constraint IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'provider_usage_daily_aggregates'::regclass
          AND contype = 'u'
    LOOP
        EXECUTE format(
            'ALTER TABLE provider_usage_daily_aggregates DROP CONSTRAINT %I',
            existing_constraint.conname
        );
    END LOOP;
END $$;

ALTER TABLE provider_usage_daily_aggregates
    ADD CONSTRAINT provider_usage_daily_aggregates_profile_version_key
    UNIQUE NULLS NOT DISTINCT (
        owner_id,
        application_id,
        workspace_id,
        usage_day,
        endpoint_profile_id,
        endpoint_profile_version,
        task_id,
        operation
    );
