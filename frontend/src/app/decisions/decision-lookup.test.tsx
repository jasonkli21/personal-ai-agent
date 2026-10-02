import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import DecisionLookup from "./decision-lookup";

const fetch = vi.fn();
const ref = {
  evidence_id: "evidence-1", source_observation_id: "source-1", owner_id: "local",
  research_session_id: null, origin: "supplied", url: "https://example.org/widget",
  title: "Synthetic product source", observed_at: "2026-10-02T10:00:00Z",
  expires_at: "2026-10-03T10:00:00Z", expiry_policy: "supplied", content_fingerprint: "a".repeat(64),
};
const result = {
  schema_version: "decision-v1",
  decision: {
    id: "decision-1", state: "recommended", selected_entity_id: "entity-1", research_session_id: null,
    created_at: "2026-10-02T12:00:00Z",
    policy_versions: {
      identity: "identity-v1", resolution: "resolve-v1", constraints: "constraint-v1", ranking: "rank-v1",
      entity_match_threshold: 0.86, ranking_policy: { policy_version: "rank-v1", feature_weights: { preference: 1 } },
    },
  },
  recommendation: {
    status: "recommended", selected_entity_id: "entity-1", candidate_order: ["entity-1"],
    supporting_claim_ids: ["claim-1"], evidence_ids: ["evidence-1"], explanation_codes: ["fresh_attributed_claim"],
  },
  evidence_snapshot: { id: "snapshot-1", evidence_refs: [ref] },
  entities: [{ id: "entity-1", canonical_name: "Blue Widget", entity_type: "object" }],
  claims: [{
    id: "claim-1", entity_id: "entity-1", attribute: "price", typed_value: { kind: "money", amount: 40, currency: "USD" },
    original_value: "$40", unit: null, currency: "USD", evidence_refs: [ref], observed_at: ref.observed_at,
    expires_at: ref.expires_at, claim_status: "verified", scope: null,
  }],
  evaluations: [{
    entity_id: "entity-1", eligibility: true, identity_outcome: "matched", identity_confidence: 1,
    claim_ids: ["claim-1"], attribute_statuses: [], constraint_outcomes: [], feature_values: [],
    score: 0, rank: 1, exclusion_reasons: [],
  }],
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); fetch.mockReset(); });

it("shows the source-backed candidate facts, expiry and citation link", async () => {
  fetch.mockResolvedValueOnce(new Response(JSON.stringify(result), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  render(<DecisionLookup />);
  fireEvent.change(screen.getByLabelText("Decision ID"), { target: { value: "decision-1" } });
  fireEvent.click(screen.getByRole("button", { name: "Load decision" }));
  expect(await screen.findByRole("heading", { name: "Recommended" })).toBeInTheDocument();
  expect(screen.getByText(/price: \$40/)).toBeInTheDocument();
  expect(screen.getByText(/expires/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Synthetic product source" })).toHaveAttribute("href", ref.url);
});

it("loads policy and identity detail only in the development inspector", async () => {
  fetch.mockResolvedValueOnce(new Response(JSON.stringify(result), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      schema_version: "decision-inspection-v1", decision_id: "decision-1", state: "recommended",
      policy_versions: result.decision.policy_versions, selected_entity_id: "entity-1", selected: result.evaluations,
      excluded: [], matches: [{
        id: "match-1", candidate_entity_id: "entity-1", candidate_entity_ids: ["entity-1"],
        selected_entity_id: "entity-1", outcome: "matched", confidence: 1, feature_values: { identifier_exact: 1 },
      }], evidence_refs: [ref],
    }), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  render(<DecisionLookup initialDecisionId="decision-1" inspectionEnabled />);
  expect(await screen.findByRole("heading", { name: "Development decision inspector" })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "Resolution trace" })).toBeInTheDocument();
  expect(screen.getByText(/Identity: matched, confidence 100%/)).toBeInTheDocument();
});
