-- Compact evaluation state and exact per-case quality-waiver bindings.
CREATE TABLE provider_matrix_runs (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    evaluation_run_id uuid NOT NULL,
    owner_id text NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 200),
    application_id text NOT NULL CHECK (length(application_id) BETWEEN 2 AND 42),
    workspace_id text CHECK (workspace_id IS NULL OR length(workspace_id) BETWEEN 1 AND 100),
    status text NOT NULL CHECK (status IN ('running','completed','partial','failed','offline_baseline')),
    start_payload jsonb NOT NULL CHECK (octet_length(start_payload::text) <= 65536),
    completion_payload jsonb CHECK (completion_payload IS NULL OR octet_length(completion_payload::text) <= 65536),
    created_at timestamptz NOT NULL,
    completed_at timestamptz,
    PRIMARY KEY (scope_id, evaluation_run_id),
    CHECK ((status='running' AND completion_payload IS NULL AND completed_at IS NULL)
        OR (status<>'running' AND completion_payload IS NOT NULL AND completed_at IS NOT NULL))
);

CREATE INDEX provider_matrix_runs_owner_time_idx
    ON provider_matrix_runs(owner_id,application_id,workspace_id,created_at DESC,evaluation_run_id);
CREATE INDEX provider_matrix_runs_status_idx
    ON provider_matrix_runs(status,created_at);

CREATE TABLE provider_matrix_cases (
    scope_id text NOT NULL,
    evaluation_run_id uuid NOT NULL,
    fixture_id text NOT NULL CHECK (length(fixture_id) BETWEEN 1 AND 200),
    endpoint_profile_id text NOT NULL CHECK (length(endpoint_profile_id) BETWEEN 1 AND 200),
    endpoint_profile_version integer NOT NULL CHECK (endpoint_profile_version BETWEEN 1 AND 2147483647),
    request_id text NOT NULL CHECK (length(request_id) BETWEEN 1 AND 200),
    case_identity_sha256 text NOT NULL CHECK (case_identity_sha256 ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('planned','measured','not_run','failed','synthetic_baseline')),
    gate_payload jsonb NOT NULL CHECK (octet_length(gate_payload::text) <= 8192),
    case_payload jsonb CHECK (case_payload IS NULL OR octet_length(case_payload::text) <= 16384),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (scope_id,evaluation_run_id,fixture_id,endpoint_profile_id,endpoint_profile_version),
    UNIQUE (scope_id,request_id),
    FOREIGN KEY (scope_id,evaluation_run_id)
        REFERENCES provider_matrix_runs(scope_id,evaluation_run_id) ON DELETE CASCADE,
    CHECK ((status='planned' AND case_payload IS NULL)
        OR (status<>'planned' AND case_payload IS NOT NULL))
);

CREATE INDEX provider_matrix_cases_status_idx
    ON provider_matrix_cases(scope_id,evaluation_run_id,status);
CREATE INDEX provider_matrix_cases_identity_idx
    ON provider_matrix_cases(scope_id,case_identity_sha256,endpoint_profile_id,endpoint_profile_version);

CREATE TABLE provider_matrix_quality_profiles (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    quality_evidence_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision BETWEEN 1 AND 2147483647),
    evaluation_run_id uuid NOT NULL,
    task_profile_id text NOT NULL CHECK (length(task_profile_id) BETWEEN 1 AND 200),
    task_profile_version integer NOT NULL CHECK (task_profile_version BETWEEN 1 AND 2147483647),
    endpoint_profile_id text NOT NULL CHECK (length(endpoint_profile_id) BETWEEN 1 AND 200),
    endpoint_profile_version integer NOT NULL CHECK (endpoint_profile_version BETWEEN 1 AND 2147483647),
    quality_profile_id text NOT NULL CHECK (length(quality_profile_id) BETWEEN 1 AND 200),
    quality_profile_version integer NOT NULL CHECK (quality_profile_version BETWEEN 1 AND 2147483647),
    policy_version text NOT NULL CHECK (length(policy_version) BETWEEN 1 AND 200),
    status text NOT NULL CHECK (status IN ('unpromoted','qualified','rejected')),
    measured_at timestamptz NOT NULL,
    fresh_until timestamptz NOT NULL,
    payload jsonb NOT NULL CHECK (octet_length(payload::text) <= 32768),
    PRIMARY KEY (scope_id,quality_evidence_id,revision),
    FOREIGN KEY (scope_id,evaluation_run_id)
        REFERENCES provider_matrix_runs(scope_id,evaluation_run_id),
    CHECK (fresh_until > measured_at)
);

CREATE INDEX provider_matrix_quality_lookup_idx
    ON provider_matrix_quality_profiles(
        scope_id,task_profile_id,task_profile_version,endpoint_profile_id,
        endpoint_profile_version,quality_profile_id,quality_profile_version,
        policy_version,status,measured_at DESC
    );

CREATE TABLE provider_matrix_quality_heads (
    scope_id text NOT NULL,
    quality_evidence_id uuid NOT NULL,
    current_revision integer NOT NULL CHECK (current_revision BETWEEN 1 AND 2147483647),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (scope_id,quality_evidence_id),
    FOREIGN KEY (scope_id,quality_evidence_id,current_revision)
        REFERENCES provider_matrix_quality_profiles(scope_id,quality_evidence_id,revision)
);
