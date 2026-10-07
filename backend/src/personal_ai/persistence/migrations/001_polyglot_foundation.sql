CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS scope_namespaces (
    scope_id text PRIMARY KEY,
    owner_id text NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 200),
    application_id text NOT NULL CHECK (length(application_id) BETWEEN 2 AND 42),
    workspace_id text,
    scope_kind text NOT NULL DEFAULT 'private'
        CHECK (scope_kind IN ('private', 'account', 'shared', 'global')),
    scope_version smallint NOT NULL DEFAULT 2 CHECK (scope_version IN (1, 2)),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (owner_id, application_id, workspace_id)
);

DO $families$
DECLARE
    family text;
    families text[] := ARRAY[
        'memory_lifecycle_states', 'memory_lifecycle_events',
        'research_sessions',
        'research_request_keys', 'iterative_research_runs',
        'iterative_research_request_keys', 'canonical_entities', 'entity_aliases',
        'entity_claims', 'entity_matches', 'decision_snapshots',
        'decision_evidence_snapshots', 'candidate_evaluations',
        'domain_claim_extensions', 'provider_observations',
        'domain_comparison_views', 'domain_lookup_idempotency',
        'itinerary_proposals', 'booking_document_extractions',
        'identity_mappings', 'account_lifecycle_requests', 'audit_events',
        'usage_budgets'
    ];
BEGIN
    FOREACH family IN ARRAY families LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I (
                scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
                record_id text NOT NULL CHECK (length(record_id) BETWEEN 1 AND 512),
                owner_id text NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 200),
                application_id text NOT NULL CHECK (length(application_id) BETWEEN 2 AND 42),
                workspace_id text,
                record_version smallint NOT NULL DEFAULT 1 CHECK (record_version > 0),
                status text CHECK (status IS NULL OR length(status) <= 80),
                revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
                event_sequence bigint CHECK (event_sequence IS NULL OR event_sequence > 0),
                created_at timestamptz NOT NULL,
                updated_at timestamptz,
                expires_at timestamptz,
                fingerprint char(64),
                idempotency_key text,
                payload jsonb NOT NULL CHECK (pg_column_size(payload) <= 262144),
                PRIMARY KEY (scope_id, record_id),
                CHECK (workspace_id IS NULL OR length(workspace_id) BETWEEN 1 AND 100),
                CHECK (fingerprint IS NULL OR fingerprint ~ ''^[0-9a-f]{64}$'')
            )', family
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (owner_id, application_id, workspace_id, created_at, record_id)',
            family || '_scope_created_idx', family
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (scope_id, status, expires_at, record_id) WHERE expires_at IS NOT NULL',
            family || '_scope_expiry_idx', family
        );
    END LOOP;
END
$families$;

ALTER TABLE usage_budgets ADD COLUMN IF NOT EXISTS budget_day date;
ALTER TABLE usage_budgets ADD COLUMN IF NOT EXISTS provider_calls integer NOT NULL DEFAULT 0
    CHECK (provider_calls >= 0);
ALTER TABLE usage_budgets ADD COLUMN IF NOT EXISTS input_tokens bigint NOT NULL DEFAULT 0
    CHECK (input_tokens >= 0);
CREATE UNIQUE INDEX IF NOT EXISTS usage_budgets_owner_day_uq
    ON usage_budgets(scope_id, budget_day) WHERE budget_day IS NOT NULL;

-- Memory embeddings have one lossless source representation. pgvector is used
-- only by transient casts in exact-search SQL; no second vector column/index.
CREATE TABLE IF NOT EXISTS memories (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    record_id text NOT NULL,
    owner_id text NOT NULL,
    application_id text NOT NULL,
    workspace_id text,
    memory_type text NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'rejected')),
    source_conversation_id text NOT NULL,
    source_turn_id text NOT NULL,
    source_message_ids text[] NOT NULL CHECK (cardinality(source_message_ids) BETWEEN 1 AND 2),
    source_fingerprint char(64) NOT NULL CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
    embedding_provider text NOT NULL,
    embedding_model text NOT NULL,
    embedding_dimensions integer NOT NULL CHECK (embedding_dimensions BETWEEN 1 AND 2048),
    embedding_normalization text NOT NULL CHECK (embedding_normalization = 'l2'),
    document_task text NOT NULL,
    query_task text NOT NULL,
    embedding double precision[] NOT NULL,
    created_at timestamptz NOT NULL,
    effective_at timestamptz NOT NULL,
    payload jsonb NOT NULL CHECK (pg_column_size(payload) <= 32768),
    PRIMARY KEY (scope_id, record_id),
    CHECK (cardinality(embedding) = embedding_dimensions),
    CHECK (array_position(embedding, 'NaN'::float8) IS NULL),
    CHECK (array_position(embedding, 'Infinity'::float8) IS NULL),
    CHECK (array_position(embedding, '-Infinity'::float8) IS NULL)
);
CREATE INDEX IF NOT EXISTS memories_scope_space_idx
    ON memories(scope_id, status, embedding_provider, embedding_model,
                         embedding_dimensions, embedding_normalization,
                         document_task, query_task, memory_type, record_id);
CREATE INDEX IF NOT EXISTS memories_source_idx
    ON memories(scope_id, source_conversation_id, source_turn_id);

CREATE TABLE IF NOT EXISTS derived_memories (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    record_id text NOT NULL,
    owner_id text NOT NULL,
    application_id text NOT NULL,
    workspace_id text,
    memory_type text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'rejected')),
    source_set_identity char(64) NOT NULL CHECK (source_set_identity ~ '^[0-9a-f]{64}$'),
    embedding_provider text NOT NULL,
    embedding_model text NOT NULL,
    embedding_dimensions integer NOT NULL CHECK (embedding_dimensions BETWEEN 1 AND 2048),
    embedding_normalization text NOT NULL CHECK (embedding_normalization = 'l2'),
    document_task text NOT NULL,
    query_task text NOT NULL,
    embedding double precision[] NOT NULL,
    created_at timestamptz NOT NULL,
    effective_at timestamptz NOT NULL,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    payload jsonb NOT NULL CHECK (pg_column_size(payload) <= 32768),
    PRIMARY KEY (scope_id, record_id),
    CHECK (workspace_id IS NULL OR length(workspace_id) BETWEEN 1 AND 100),
    CHECK (cardinality(embedding) = embedding_dimensions),
    CHECK (array_position(embedding, 'NaN'::float8) IS NULL),
    CHECK (array_position(embedding, 'Infinity'::float8) IS NULL),
    CHECK (array_position(embedding, '-Infinity'::float8) IS NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS derived_memories_source_set_uq
    ON derived_memories(scope_id, source_set_identity);
CREATE INDEX IF NOT EXISTS derived_memories_scope_space_idx
    ON derived_memories(scope_id, embedding_provider, embedding_model,
                        embedding_dimensions, embedding_normalization,
                        document_task, query_task, record_id);

CREATE TABLE IF NOT EXISTS derived_memory_sources (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    derived_memory_id text NOT NULL,
    source_memory_id text NOT NULL,
    source_ordinal smallint NOT NULL CHECK (source_ordinal BETWEEN 1 AND 4),
    source_fingerprint char(64) NOT NULL CHECK (source_fingerprint ~ '^[0-9a-f]{64}$'),
    source_conversation_id text NOT NULL,
    source_turn_id text NOT NULL,
    source_message_ids text[] NOT NULL CHECK (cardinality(source_message_ids) BETWEEN 1 AND 2),
    excerpt text NOT NULL CHECK (length(excerpt) BETWEEN 1 AND 1000),
    PRIMARY KEY (scope_id, derived_memory_id, source_memory_id),
    UNIQUE (scope_id, derived_memory_id, source_ordinal),
    FOREIGN KEY (scope_id, derived_memory_id)
        REFERENCES derived_memories(scope_id, record_id) ON DELETE RESTRICT,
    FOREIGN KEY (scope_id, source_memory_id)
        REFERENCES memories(scope_id, record_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS derived_memory_sources_original_idx
    ON derived_memory_sources(scope_id, source_memory_id, derived_memory_id);

CREATE TABLE IF NOT EXISTS memory_lifecycle_operations (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    owner_id text NOT NULL,
    application_id text NOT NULL,
    workspace_id text,
    operation_id text NOT NULL,
    attempt_id text NOT NULL,
    fingerprint char(64) NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    outcome text NOT NULL CHECK (outcome IN ('applied', 'aborted')),
    result_refs jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (pg_column_size(result_refs) <= 16384),
    execution_deadline timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scope_id, operation_id, attempt_id),
    CHECK (workspace_id IS NULL OR length(workspace_id) BETWEEN 1 AND 100)
);
CREATE INDEX IF NOT EXISTS memory_lifecycle_operations_owner_idx
    ON memory_lifecycle_operations(owner_id, application_id, workspace_id, created_at);

CREATE TABLE IF NOT EXISTS domain_registrations (
    module_id text NOT NULL,
    module_version text NOT NULL,
    policy_version text NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    payload jsonb NOT NULL CHECK (pg_column_size(payload) <= 32768),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (module_id, module_version, policy_version)
);

CREATE TABLE IF NOT EXISTS domain_provider_rate_limits (
    provider_id text PRIMARY KEY,
    next_available_at timestamptz NOT NULL,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS identity_mappings_principal_uq
    ON identity_mappings ((payload->>'issuer'), (payload->>'subject'));
CREATE UNIQUE INDEX IF NOT EXISTS research_request_keys_replay_uq
    ON research_request_keys(scope_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS iterative_research_request_keys_replay_uq
    ON iterative_research_request_keys(scope_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS domain_lookup_idempotency_replay_uq
    ON domain_lookup_idempotency(scope_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS itinerary_proposals_replay_uq
    ON itinerary_proposals(scope_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS booking_document_extractions_replay_uq
    ON booking_document_extractions(scope_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS memory_lifecycle_events_idempotency_uq
    ON memory_lifecycle_events(scope_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS memory_lifecycle_events_order_idx
    ON memory_lifecycle_events(scope_id, record_id, event_sequence);
