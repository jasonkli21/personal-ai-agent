CREATE INDEX IF NOT EXISTS domain_lookup_idempotency_record_idx
    ON domain_lookup_idempotency(application_id, workspace_id, record_id);
