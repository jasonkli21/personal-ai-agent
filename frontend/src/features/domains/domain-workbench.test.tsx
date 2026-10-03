import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DomainComparisonResult, DomainFixture } from "../../lib/domain-api";
import DomainWorkbench from "./domain-workbench";

const fetchMock = vi.fn();
const fixture: DomainFixture = {
  fixture_id: "shopping-stale-offer",
  domain_id: "shopping",
  title: "Expired offer needs new research",
  description: "Expired prices cannot satisfy a current budget.",
};
const result: DomainComparisonResult = {
  schema_version: "domain-comparison-v1",
  registration: {
    domain_id: "shopping",
    source_policy_version: "shopping-sources-v1",
    field_schema_version: "shopping-comparison-v1",
    feature_policy_version: "shopping-features-v1",
    fields: [
      { key: "total_price", label: "Quoted total" },
      { key: "compatibility", label: "Compatibility" },
    ],
  },
  comparison: {
    id: "comparison-123",
    decision_id: "decision-123",
    domain_id: "shopping",
    state: "research_needed",
    rendered_at: "2026-10-02T12:00:00Z",
    decision_policy_versions: { resolution: "resolve-v2", constraints: "constraint-v1", ranking: "rank-v1" },
    constraints: [{ attribute: "compatibility", operator: "exact", value: { kind: "text", value: "USB-C" }, source: "user" }],
    available_filters: ["eligible", "fresh", "conflicts"],
    rows: [{
      candidate_id: "candidate-1",
      name: "Synthetic headlamp offer",
      eligible: false,
      selected: false,
      rank: null,
      score: null,
      exclusion_reasons: ["required_total_price_stale"],
      features: [],
      cells: [
        {
          field: "total_price", label: "Quoted total", value: "50.00 USD", status: "stale",
          note: "This observation has expired.", claim_ids: ["claim-1"], sources: [{
            evidence_id: "evidence-1",
            source_observation_id: "observation-1",
            url: "https://example.org/offer",
            title: "Synthetic merchant offer",
            attribution: "Synthetic fixture; not a live offer.",
            policy_url: null,
            observed_at: "2026-10-01T12:00:00Z",
            expires_at: "2026-10-01T18:00:00Z",
          }],
        },
        { field: "compatibility", label: "Compatibility", value: "USB-C / Lightning", status: "conflicting", note: "Sources disagree.", claim_ids: [], sources: [] },
      ],
    }],
  },
  provider_observations: [],
};
const travelResult: DomainComparisonResult = {
  ...result,
  registration: { ...result.registration, domain_id: "travel" },
  comparison: { ...result.comparison, domain_id: "travel" },
};

function json(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("domain comparison workbench", () => {
  it("shows the policy notice for OpenStreetMap and submits only the entered place query", async () => {
    fetchMock.mockResolvedValueOnce(json([])).mockResolvedValueOnce(json(travelResult));
    render(<DomainWorkbench domain="travel" adapter="osm_nominatim" />);
    expect(await screen.findByRole("link", { name: "Nominatim usage policy" }))
      .toHaveAttribute("href", "https://operations.osmfoundation.org/policies/nominatim/");
    fireEvent.change(screen.getByLabelText("Place or area name"), { target: { value: "Example Park" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ query: "Example Park", max_results: 8 });
  });

  it("renders constraints, stale and conflict states, source evidence, and local filters", async () => {
    fetchMock.mockResolvedValueOnce(json([fixture])).mockResolvedValueOnce(json(result));
    render(<DomainWorkbench domain="shopping" adapter="fake" />);
    fireEvent.click(await screen.findByRole("button", { name: "Run synthetic example" }));

    expect(await screen.findByText("More current evidence is needed")).toBeInTheDocument();
    expect(screen.getAllByText("Compatibility")[0].closest("li")).toHaveTextContent(/exact USB-C.*your filter/);
    expect(screen.getByText("Expired")).toBeInTheDocument();
    expect(screen.getByText("Conflict")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Synthetic merchant offer" })).toHaveAttribute("href", "https://example.org/offer");
    expect(screen.getByText(/Synthetic fixture; not a live offer/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Fresh evidence only"));
    expect(screen.getByText("No candidates match these display filters.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reports load errors without inventing comparison rows", async () => {
    fetchMock.mockResolvedValueOnce(json([fixture])).mockResolvedValueOnce(new Response(
      JSON.stringify({ error: { message: "Source unavailable." } }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    ));
    render(<DomainWorkbench domain="shopping" adapter="open_food_facts" />);
    fireEvent.click(await screen.findByRole("button", { name: "Run synthetic example" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Source unavailable.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("accepts public HTTP evidence and policy links allowed by the shared URL policy", async () => {
    const httpResult = structuredClone(result);
    httpResult.comparison.rows[0].cells[0].sources[0].url = "http://example.org/offer";
    httpResult.comparison.rows[0].cells[0].sources[0].policy_url = "http://example.org/policy";
    httpResult.provider_observations = [{
      provider: "synthetic",
      attribution: "Synthetic source",
      policy_url: "http://example.org/provider-policy",
      observed_at: "2026-10-01T12:00:00Z",
      expires_at: "2026-10-02T12:00:00Z",
    }];
    fetchMock.mockResolvedValueOnce(json([fixture])).mockResolvedValueOnce(json(httpResult));
    render(<DomainWorkbench domain="shopping" adapter="fake" />);
    fireEvent.click(await screen.findByRole("button", { name: "Run synthetic example" }));
    expect(await screen.findByRole("link", { name: "Synthetic merchant offer" }))
      .toHaveAttribute("href", "http://example.org/offer");
    expect(screen.getByRole("link", { name: "Source use and attribution policy" }))
      .toHaveAttribute("href", "http://example.org/policy");
    expect(screen.getByRole("link", { name: "Provider policy" }))
      .toHaveAttribute("href", "http://example.org/provider-policy");
  });

  it("turns malformed rendered fields into a recoverable error", async () => {
    const malformed = structuredClone(result) as unknown as Record<string, unknown>;
    const registration = malformed.registration as { fields: Record<string, unknown>[] };
    delete registration.fields[0].label;
    fetchMock.mockResolvedValueOnce(json([fixture])).mockResolvedValueOnce(json(malformed));
    render(<DomainWorkbench domain="shopping" adapter="fake" />);
    fireEvent.click(await screen.findByRole("button", { name: "Run synthetic example" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid field registration");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("rejects absent exclusion reasons before the workbench renders them", async () => {
    const malformed = structuredClone(result) as unknown as Record<string, unknown>;
    const comparison = malformed.comparison as { rows: Record<string, unknown>[] };
    delete comparison.rows[0].exclusion_reasons;
    fetchMock.mockResolvedValueOnce(json([fixture])).mockResolvedValueOnce(json(malformed));
    render(<DomainWorkbench domain="shopping" adapter="fake" />);
    fireEvent.click(await screen.findByRole("button", { name: "Run synthetic example" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid candidate");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("rejects unsafe cell policy links", async () => {
    const malformed = structuredClone(result) as unknown as Record<string, unknown>;
    const comparison = malformed.comparison as { rows: Array<{ cells: Array<{ sources: Array<Record<string, unknown>> }> }> };
    comparison.rows[0].cells[0].sources[0].policy_url = "javascript:alert(1)";
    malformed.provider_observations = [{
      provider: "synthetic",
      attribution: "Synthetic source",
      policy_url: "javascript:alert(1)",
      observed_at: "2026-10-01T12:00:00Z",
      expires_at: "2026-10-02T12:00:00Z",
    }];
    fetchMock.mockResolvedValueOnce(json([fixture])).mockResolvedValueOnce(json(malformed));
    render(<DomainWorkbench domain="shopping" adapter="fake" />);
    fireEvent.click(await screen.findByRole("button", { name: "Run synthetic example" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("unsafe source link");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("rejects unsafe provider policy links when cell links are safe", async () => {
    const malformed = structuredClone(result) as unknown as Record<string, unknown>;
    const comparison = malformed.comparison as { rows: Array<{ cells: Array<{ sources: Array<Record<string, unknown>> }> }> };
    comparison.rows[0].cells[0].sources[0].policy_url = null;
    malformed.provider_observations = [{
      provider: "synthetic",
      attribution: "Synthetic source",
      policy_url: "https://[3fff::1]/policy",
      observed_at: "2026-10-01T12:00:00Z",
      expires_at: "2026-10-02T12:00:00Z",
    }];
    fetchMock.mockResolvedValueOnce(json([fixture])).mockResolvedValueOnce(json(malformed));
    render(<DomainWorkbench domain="shopping" adapter="fake" />);
    fireEvent.click(await screen.findByRole("button", { name: "Run synthetic example" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid provider metadata");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("explains when a lookup has no candidates instead of blaming the filters", async () => {
    fetchMock.mockResolvedValueOnce(json([fixture])).mockResolvedValueOnce(json({
      ...result,
      comparison: { ...result.comparison, state: "no_verified_match", rows: [] },
    }));
    render(<DomainWorkbench domain="shopping" adapter="open_food_facts" />);
    fireEvent.click(await screen.findByRole("button", { name: "Run synthetic example" }));
    expect(await screen.findByText(/No candidates were returned/)).toBeInTheDocument();
    expect(screen.queryByText("No candidates match these display filters.")).not.toBeInTheDocument();
  });
});
