DROP INDEX IF EXISTS domain_lookup_idempotency_replay_uq;

CREATE UNIQUE INDEX domain_lookup_idempotency_replay_uq
    ON domain_lookup_idempotency(scope_id, (payload->>'domain_id'), idempotency_key)
    WHERE idempotency_key IS NOT NULL;
