import { applicationScopeHeaders, type ApplicationScopeRequest } from "./api";
import { authenticatedFetch } from "./auth";

export type EvidenceReference = {
  evidence_id: string;
  source_observation_id: string;
  owner_id: string;
  research_session_id: string | null;
  origin: "research_session" | "supplied";
  url: string;
  title: string | null;
  observed_at: string;
  expires_at: string;
  expiry_policy: string;
  content_fingerprint: string;
};

export type Claim = {
  id: string;
  entity_id: string;
  attribute: string;
  typed_value: { kind: string; value?: string | number | boolean; amount?: string | number; currency?: string; unit?: string };
  original_value: string;
  unit: string | null;
  currency: string | null;
  evidence_refs: EvidenceReference[];
  observed_at: string;
  expires_at: string;
  claim_status: "verified" | "unverified" | "retracted";
  scope: string | null;
};

export type ConstraintOutcome = { attribute: string; outcome: "pass" | "fail" | "unknown"; reason: string };
export type AttributeStatus = { attribute: string; scope: string | null; status: string; reason: string; claim_ids: string[] };
export type FeatureScore = { name: string; value: number | null; weight: number; missing_treatment: string };
export type CandidateEvaluation = {
  entity_id: string;
  eligibility: boolean;
  identity_outcome: string;
  identity_confidence: number;
  claim_ids: string[];
  attribute_statuses: AttributeStatus[];
  constraint_outcomes: ConstraintOutcome[];
  feature_values: FeatureScore[];
  score: number | null;
  rank: number | null;
  exclusion_reasons: string[];
};

export type DecisionResult = {
  schema_version: "decision-v1";
  decision: {
    id: string;
    state: "recommended" | "eligible_unranked" | "research_needed" | "no_verified_match";
    selected_entity_id: string | null;
    research_session_id: string | null;
    created_at: string;
    policy_versions: {
      identity: string;
      resolution: string;
      claim_verification: string;
      constraints: string;
      ranking: string;
      entity_match_threshold: number;
      ranking_policy: { policy_version: string; feature_weights: Record<string, number> };
    };
  };
  recommendation: { status: string; selected_entity_id: string | null; candidate_order: string[]; supporting_claim_ids: string[]; evidence_ids: string[]; explanation_codes: string[] };
  evidence_snapshot: { id: string; evidence_refs: EvidenceReference[] };
  entities: { id: string; canonical_name: string; entity_type: string }[];
  claims: Claim[];
  evaluations: CandidateEvaluation[];
};

export type DecisionInspection = {
  schema_version: "decision-inspection-v1";
  decision_id: string;
  state: string;
  policy_versions: DecisionResult["decision"]["policy_versions"];
  selected_entity_id: string | null;
  selected: CandidateEvaluation[];
  excluded: CandidateEvaluation[];
  matches: { id: string; candidate_entity_id: string; candidate_entity_ids: string[]; selected_entity_id: string | null; outcome: string; confidence: number; feature_values: Record<string, number> }[];
  evidence_refs: EvidenceReference[];
};

async function getJson<T>(path: string, init?: RequestInit, scope?: ApplicationScopeRequest): Promise<T> {
  const response = await authenticatedFetch(path, {
    ...init,
    cache: "no-store",
    headers: { ...applicationScopeHeaders(scope), ...init?.headers },
  });
  if (!response.ok) throw new Error("Decision details are unavailable.");
  return response.json() as Promise<T>;
}

export const decisionApi = {
  create(request: unknown, scope?: ApplicationScopeRequest) {
    return getJson<DecisionResult>("/api/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, scope);
  },
  get(id: string, scope?: ApplicationScopeRequest) {
    return getJson<DecisionResult>(`/api/decisions/${encodeURIComponent(id)}`, undefined, scope);
  },
  inspect(id: string, scope?: ApplicationScopeRequest) {
    return getJson<DecisionInspection>(`/api/decisions/${encodeURIComponent(id)}/inspection`, undefined, scope);
  },
};
