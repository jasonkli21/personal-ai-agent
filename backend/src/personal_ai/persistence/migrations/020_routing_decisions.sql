-- Canonical bounded replay facts. Prompts, embeddings and provider responses
-- are not stored here; later outcomes append without rewriting decision facts.
CREATE TABLE IF NOT EXISTS routing_decisions (
    decision_id uuid NOT NULL,
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    owner_id text NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 200),
    application_id text NOT NULL CHECK (length(application_id) BETWEEN 2 AND 42),
    workspace_id text CHECK (workspace_id IS NULL OR length(workspace_id) BETWEEN 1 AND 100),
    request_id text NOT NULL CHECK (length(request_id) BETWEEN 1 AND 200),
    run_id text CHECK (run_id IS NULL OR length(run_id) BETWEEN 1 AND 200),
    parent_decision_id uuid,
    root_decision_id uuid NOT NULL,
    reselection_depth smallint NOT NULL DEFAULT 0 CHECK (reselection_depth BETWEEN 0 AND 4),
    reselection_count smallint NOT NULL DEFAULT 0 CHECK (reselection_count BETWEEN 0 AND 4),
    lifecycle_status text NOT NULL CHECK (lifecycle_status IN ('preparing','no_route')),
    decision_facts jsonb NOT NULL CHECK (octet_length(decision_facts::text) <= 98304),
    outcome_events jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(outcome_events) = 'array')
        CHECK (jsonb_array_length(outcome_events) BETWEEN 1 AND 32)
        CHECK (octet_length(outcome_events::text) <= 65536),
    invocation_ids uuid[] NOT NULL DEFAULT '{}'
        CHECK (cardinality(invocation_ids) <= 32),
    attempt_ids uuid[] NOT NULL DEFAULT '{}'
        CHECK (cardinality(attempt_ids) <= 32),
    evaluation_run_ids uuid[] NOT NULL DEFAULT '{}'
        CHECK (cardinality(evaluation_run_ids) <= 32),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    replay_until timestamptz NOT NULL,
    PRIMARY KEY (scope_id, decision_id),
    FOREIGN KEY (scope_id,parent_decision_id)
        REFERENCES routing_decisions(scope_id,decision_id) ON DELETE CASCADE,
    FOREIGN KEY (scope_id,root_decision_id)
        REFERENCES routing_decisions(scope_id,decision_id) ON DELETE CASCADE,
    CHECK (
        (reselection_depth=0 AND decision_id=root_decision_id AND parent_decision_id IS NULL)
        OR (reselection_depth>0 AND decision_id<>root_decision_id AND parent_decision_id IS NOT NULL)
    ),
    CHECK (replay_until > created_at),
    CHECK (replay_until <= created_at + interval '90 days')
);

CREATE INDEX routing_decisions_owner_time_idx
    ON routing_decisions(owner_id,application_id,workspace_id,created_at DESC,decision_id);
CREATE INDEX routing_decisions_request_idx
    ON routing_decisions(owner_id,application_id,workspace_id,request_id,created_at DESC);
CREATE INDEX routing_decisions_run_idx
    ON routing_decisions(owner_id,application_id,workspace_id,run_id,created_at DESC)
    WHERE run_id IS NOT NULL;
CREATE INDEX routing_decisions_invocation_idx
    ON routing_decisions USING gin(invocation_ids);
CREATE INDEX routing_decisions_attempt_idx
    ON routing_decisions USING gin(attempt_ids);
CREATE INDEX routing_decisions_evaluation_idx
    ON routing_decisions USING gin(evaluation_run_ids);
CREATE INDEX routing_decisions_expiry_idx
    ON routing_decisions(replay_until,decision_id);
CREATE INDEX routing_decisions_root_idx
    ON routing_decisions(scope_id,root_decision_id,reselection_depth,created_at);
