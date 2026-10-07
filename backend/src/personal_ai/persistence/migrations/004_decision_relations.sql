-- Immutable claim attribution is indexed as a relation for evidence lookup.
CREATE TABLE IF NOT EXISTS entity_claim_evidence (
    scope_id text NOT NULL REFERENCES scope_namespaces(scope_id),
    owner_id text NOT NULL,
    application_id text NOT NULL,
    workspace_id text,
    evidence_id text NOT NULL,
    entity_id text NOT NULL,
    claim_id text NOT NULL,
    PRIMARY KEY (scope_id, evidence_id, claim_id),
    FOREIGN KEY (scope_id, claim_id)
        REFERENCES entity_claims(scope_id, record_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS entity_claim_evidence_owner_idx
    ON entity_claim_evidence(scope_id, owner_id, evidence_id, entity_id, claim_id);

CREATE INDEX IF NOT EXISTS entity_matches_decision_idx
    ON entity_matches(scope_id, (payload->>'decision_id'), created_at, record_id);
CREATE INDEX IF NOT EXISTS candidate_evaluations_decision_idx
    ON candidate_evaluations(scope_id, (payload->>'decision_id'), created_at, record_id);
CREATE INDEX IF NOT EXISTS entity_aliases_entity_idx
    ON entity_aliases(scope_id, owner_id, (payload->>'entity_id'), record_id);
CREATE INDEX IF NOT EXISTS entity_claims_entity_attribute_idx
    ON entity_claims(scope_id, owner_id, (payload->>'entity_id'), (payload->>'attribute'), record_id);
