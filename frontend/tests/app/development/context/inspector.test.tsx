import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ContextInspector from "../../../../src/app/development/context/inspector";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("is absent by default without making a request", () => {
  const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
  const { container } = render(<ContextInspector />);
  expect(container).toBeEmptyDOMElement();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("shows enabled selection metadata and exclusion reasons", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    counter_kind: "estimated", budget: { capacity: 220, response_reserve: 30, safety_margin: 10, input_budget: 180, selected_total: 150 },
    selected: [{ id: "newest", role: "user", characters: 20 }],
    excluded: [{ id: "older", role: "assistant", characters: 100, reason: "summary_covered" }],
    summary: { id: "summary-1", covers_through_message_id: "older", source_message_ids: ["older"], counter_kind: "provider", summary_token_count: 42 }, overflow: null, diagnostics: [],
  })));
  vi.stubGlobal("fetch", fetchMock);
  render(<ContextInspector enabled />);
  fireEvent.change(screen.getByLabelText("Conversation ID"), { target: { value: "conversation-1" } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect context" }));
  expect(await screen.findByText(/Counter: estimated/)).toBeInTheDocument();
  expect(screen.getByText(/older: summary_covered/)).toBeInTheDocument();
  expect(screen.getByText(/Working summary summary-1/)).toBeInTheDocument();
  expect(screen.getByText(/42 provider tokens/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/conversations/conversation-1/context", expect.objectContaining({ cache: "no-store" }));
});

it("shows supplied memory provenance and selected versus excluded records", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    counter_kind: "estimated", budget: null, selected: [], excluded: [], summary: null, overflow: null, diagnostics: [],
    memory: { mode: "supplied-record fit estimate; no semantic query or prior-use claim", tokens: 100, requested_variant: "fixed", applied_variant: "fixed", policy_version: "score-v1", lifecycle_event_ids: [], records: [
      { id: "memory-1", type: "preference", source_conversation_id: "source", source_message_ids: ["user-1"], source_records: [], effective_at: "2026-10-02", selected: true, selection_kind: "fit_estimate", reason: null, similarity: null, score: null, score_reason: "similarity_unavailable_in_inspector", score_components: null, estimated_tokens: 30 },
      { id: "memory-2", type: "explicit_correction", source_conversation_id: "source", source_message_ids: ["user-2"], source_records: [], effective_at: "2026-10-02", selected: false, selection_kind: "fit_estimate", reason: "budget", similarity: null, score: null, score_reason: "similarity_unavailable_in_inspector", score_components: null, estimated_tokens: 60 },
    ] },
  })));
  vi.stubGlobal("fetch", fetchMock);
  render(<ContextInspector enabled memoryEnabled />);
  fireEvent.change(screen.getByLabelText("Conversation ID"), { target: { value: "conversation-1" } });
  fireEvent.change(screen.getByLabelText(/Memory IDs/), { target: { value: "memory-1, memory-2" } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect context" }));
  expect(await screen.findByText(/no semantic query or prior-use claim/)).toBeInTheDocument();
  expect(screen.getByText(/preference memory-1: fit estimate selected/)).toBeInTheDocument();
  expect(screen.getByText(/explicit_correction memory-2: excluded \(budget\)/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/conversations/conversation-1/context?memory_ids=memory-1&memory_ids=memory-2", expect.objectContaining({ cache: "no-store" }));
});

it("shows retained actual decisions beside the estimated current view", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    inspection_request_id: "inspect-14",
    trace_state: "available",
    actual_build_trace: {
      request_id: "generation-14", conversation_id: "conversation-1", user_message_id: "user-1", assistant_message_id: "assistant-1", recorded_at: "2026-10-07T10:00:00Z",
      build_schema_version: "context-build-v1", policy_version: "context-build-policy-v1", planner_version: "deterministic-context-planner-v1",
      counter_kind: "estimated", counter_version: "fixture-counter-v1", global_input_tokens: 500, actual_input_tokens: 180, effective_sensitivity: "personal",
      requested_sources: [{ provider_id: "global_profile", operation: "profile", fields: ["preferred_units"], field_count: 1, fields_truncated: false, max_results: 1, max_bytes: 1024, max_tokens: 64, required: false }],
      requested_source_count: 1, requested_sources_truncated: false,
      planning_decisions: [{ stage: "planning", source_id: "profile.units:v1", source_id_hash: null, item_id_hash: null, provider_id: "global_profile", source_version: null, operation: "profile", category: "profile_units", disposition: "selected", fields: ["preferred_units"], field_count: 1, fields_truncated: false, authority: null, sensitivity: null, token_count: null, reason: "eligible" }],
      planning_decision_count: 1, planning_decisions_truncated: false,
      source_decisions: [{ stage: "build", source_id: null, source_id_hash: "abc123", item_id_hash: "def456", provider_id: "global_profile", source_version: "global-profile-v1:7", operation: "profile", category: "global_profile", disposition: "selected", fields: [], authority: "authoritative", sensitivity: "sensitive", token_count: 12, reason: null }],
      source_decision_count: 1, source_decisions_truncated: false, source_budgets: [{ category: "global_profile", token_limit: 100, token_count: 12, counter_kind: "estimated", injected_item_count: 1, omitted_item_count: 0 }],
      provider_failures: [], provider_failure_count: 0, provider_failures_truncated: false,
      selected_message_ids: ["user-1"], selected_message_count: 1, selected_messages_truncated: false,
      excluded_messages: [], excluded_message_count: 0, excluded_messages_truncated: false,
    },
    counter_kind: "estimated", budget: { capacity: 500, response_reserve: 50, safety_margin: 10, input_budget: 440, selected_total: 180 },
    selected: [], excluded: [], summary: null, overflow: null, diagnostics: [],
  }), { headers: { "X-Request-ID": "inspect-14" } }));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("crypto", { randomUUID: () => "inspect-14" });
  render(<ContextInspector enabled />);
  fireEvent.change(screen.getByLabelText("Conversation ID"), { target: { value: "conversation-1" } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect context" }));

  expect(await screen.findByText(/Retained actual build/)).toBeInTheDocument();
  expect(screen.getByText(/generation-14/)).toBeInTheDocument();
  expect(screen.getByText(/sha256|abc123/)).toBeInTheDocument();
  expect(screen.getByText(/Estimated current view/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/conversations/conversation-1/context", expect.objectContaining({
    cache: "no-store",
    headers: { "X-Application-ID": "personal_ai", "X-Request-ID": "inspect-14" },
  }));
});
