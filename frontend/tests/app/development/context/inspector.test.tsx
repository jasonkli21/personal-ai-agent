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
