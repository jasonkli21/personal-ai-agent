-- Migration 022 is frozen together with migrations_py/022_routing_authorities.py
-- after release. Later corrections belong in a new numbered migration.
-- Preserve retained V1 audit records. There are no new V1 writes or executors.
ALTER TABLE artifact_owner_fences RENAME TO owner_lifecycle_fences;
ALTER TABLE routing_decisions RENAME TO routing_decisions_legacy;
ALTER TABLE provider_attempts ADD COLUMN dispatch_claimed_at timestamptz;

CREATE TABLE endpoint_profile_definitions (
    endpoint_profile_id text NOT NULL,
    profile_version integer NOT NULL CHECK(profile_version>0),
    definition_schema_version integer NOT NULL CHECK(definition_schema_version>0),
    payload jsonb NOT NULL CHECK(octet_length(payload::text)<=262144),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(endpoint_profile_id,profile_version)
);

CREATE TABLE routing_decisions (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    decision_id uuid NOT NULL,
    owner_id text NOT NULL,
    application_id text NOT NULL,
    workspace_id text,
    request_id text NOT NULL,
    run_id text,
    root_decision_id uuid NOT NULL,
    parent_decision_id uuid,
    status text NOT NULL CHECK(status IN ('selected','no_route','failed','authorized','dispatched','closed','reselected')),
    auxiliary_calls_used smallint NOT NULL DEFAULT 0 CHECK(auxiliary_calls_used BETWEEN 0 AND 16),
    decision_facts jsonb NOT NULL CHECK(octet_length(decision_facts::text)<=98304),
    created_at timestamptz NOT NULL,
    replay_until timestamptz NOT NULL,
    PRIMARY KEY(scope_id,decision_id),
    FOREIGN KEY(scope_id,root_decision_id) REFERENCES routing_decisions(scope_id,decision_id) ON DELETE CASCADE,
    FOREIGN KEY(scope_id,parent_decision_id) REFERENCES routing_decisions(scope_id,decision_id) ON DELETE CASCADE,
    CHECK(replay_until>created_at AND replay_until<=created_at+interval '90 days'),
    CHECK((parent_decision_id IS NULL AND root_decision_id=decision_id) OR
          (parent_decision_id IS NOT NULL AND root_decision_id<>decision_id))
);
CREATE INDEX routing_v2_scope_request ON routing_decisions(owner_id,application_id,workspace_id,request_id,created_at);
CREATE INDEX routing_v2_expiry ON routing_decisions(replay_until,decision_id);
CREATE INDEX routing_v2_root ON routing_decisions(scope_id,root_decision_id);
CREATE UNIQUE INDEX routing_v2_parent ON routing_decisions(scope_id,parent_decision_id)
    WHERE parent_decision_id IS NOT NULL;

CREATE TABLE routing_decision_events (
    scope_id text NOT NULL,
    decision_id uuid NOT NULL,
    event_id uuid NOT NULL,
    sequence smallint NOT NULL CHECK(sequence BETWEEN 1 AND 128),
    owner_id text NOT NULL,
    application_id text NOT NULL,
    workspace_id text,
    kind text NOT NULL CHECK(kind IN ('selected','no_route','failed','authorized','dispatched','closed','auxiliary','reselected')),
    attempt_id uuid,
    payload jsonb NOT NULL CHECK(octet_length(payload::text)<=24576),
    PRIMARY KEY(scope_id,decision_id,event_id),
    UNIQUE(scope_id,decision_id,sequence),
    FOREIGN KEY(scope_id,decision_id) REFERENCES routing_decisions(scope_id,decision_id) ON DELETE CASCADE
);
CREATE INDEX routing_v2_attempt ON routing_decision_events(attempt_id) WHERE attempt_id IS NOT NULL;

CREATE INDEX provider_invocations_scoped_request_idx
    ON provider_invocations(owner_id,application_id,workspace_id,request_id,started_at DESC,invocation_id);
