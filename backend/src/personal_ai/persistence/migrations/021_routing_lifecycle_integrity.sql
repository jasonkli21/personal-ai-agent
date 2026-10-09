-- Root-scoped reservation count for auxiliary counter/summary calls. The JSON
-- event id is the idempotency key, so a retry cannot consume the budget twice.
ALTER TABLE routing_decisions
    ADD COLUMN IF NOT EXISTS auxiliary_calls_used smallint NOT NULL DEFAULT 0;

ALTER TABLE routing_decisions
    DROP CONSTRAINT IF EXISTS routing_decisions_auxiliary_calls_used_check;

ALTER TABLE routing_decisions
    ADD CONSTRAINT routing_decisions_auxiliary_calls_used_check
    CHECK (auxiliary_calls_used BETWEEN 0 AND 16);
