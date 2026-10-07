CREATE INDEX IF NOT EXISTS usage_budgets_expiry_cleanup_idx
    ON usage_budgets(expires_at, scope_id, record_id)
    WHERE expires_at IS NOT NULL;
