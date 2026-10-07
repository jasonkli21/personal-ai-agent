ALTER TABLE memory_lifecycle_events ADD COLUMN IF NOT EXISTS aggregate_id text;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS aggregate_id text;

UPDATE memory_lifecycle_events SET aggregate_id = record_id WHERE aggregate_id IS NULL;
UPDATE audit_events SET aggregate_id = record_id WHERE aggregate_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS memory_lifecycle_events_aggregate_sequence_uq
    ON memory_lifecycle_events(scope_id, aggregate_id, event_sequence)
    WHERE aggregate_id IS NOT NULL AND event_sequence IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS audit_events_aggregate_sequence_uq
    ON audit_events(scope_id, aggregate_id, event_sequence)
    WHERE aggregate_id IS NOT NULL AND event_sequence IS NOT NULL;

CREATE INDEX IF NOT EXISTS memory_lifecycle_events_aggregate_order_idx
    ON memory_lifecycle_events(scope_id, aggregate_id, event_sequence)
    WHERE aggregate_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS audit_events_aggregate_order_idx
    ON audit_events(scope_id, aggregate_id, event_sequence)
    WHERE aggregate_id IS NOT NULL;
