import { afterEach, describe, expect, it, vi } from "vitest";
import { iterativeResearchApi, type IterativeProgress } from "./iterative-research-api";

afterEach(() => vi.unstubAllGlobals());

const runId = "11111111-1111-4111-8111-111111111111";
const sessionId = "22222222-2222-4222-8222-222222222222";

function event(sequence: number, runIdValue = runId, eventType = "planning", state = "planning") {
  const data: IterativeProgress = {
    schema_version: "iterative-research-v1", run_id: runIdValue, session_id: sessionId,
    sequence, event_type: eventType, state: state as IterativeProgress["state"],
  };
  return `id: ${sequence}\nevent: research.iterative.${eventType}\ndata: ${JSON.stringify(data)}\n\n`;
}

function stream(chunks: string[]) {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}

describe("iterative research progress API", () => {
  it("validates and reads split SSE frames while returning the durable run ID", async () => {
    const complete = event(0, runId) + event(1, runId, "completed", "completed");
    const fetch = vi.fn().mockResolvedValue(stream([complete.slice(0, 31), complete.slice(31)]));
    vi.stubGlobal("fetch", fetch);
    const progress: IterativeProgress[] = [];

    const result = await iterativeResearchApi.start(
      { question: "What is supported?", freshness: "general", idempotency_key: "key-1" },
      value => progress.push(value),
    );

    expect(result.runId).toBe(runId);
    expect(result.lastSequence).toBe(1);
    expect(progress.map(value => value.sequence)).toEqual([0, 1]);
    expect(fetch).toHaveBeenCalledWith("/api/research/iterative", expect.objectContaining({ method: "POST" }));
  });

  it("rejects a sequence gap during replay", async () => {
    const fetch = vi.fn().mockResolvedValue(stream([event(5, runId)]));
    vi.stubGlobal("fetch", fetch);
    await expect(iterativeResearchApi.events("run-1", 3, vi.fn())).rejects.toThrow("Invalid iterative research progress");
  });

  it("rejects an event from a different run during replay", async () => {
    const fetch = vi.fn().mockResolvedValue(stream([event(4, "33333333-3333-4333-8333-333333333333")]));
    vi.stubGlobal("fetch", fetch);
    await expect(iterativeResearchApi.events("run-1", 3, vi.fn())).rejects.toThrow("Invalid iterative research progress");
  });

  it("allows a live-lease resume response to contain only persisted progress", async () => {
    const fetch = vi.fn().mockResolvedValue(stream([event(0, runId, "searching", "searching")]));
    vi.stubGlobal("fetch", fetch);
    const progress: IterativeProgress[] = [];

    await expect(iterativeResearchApi.resume(runId, -1, value => progress.push(value))).resolves.toMatchObject({
      runId, lastSequence: 0,
    });
    expect(progress).toHaveLength(1);
  });

  it("sends a nonempty Last-Event-ID when resuming from a persisted timeline cursor", async () => {
    const fetch = vi.fn().mockResolvedValue(stream([event(1, runId)]));
    vi.stubGlobal("fetch", fetch);

    await iterativeResearchApi.resume(runId, 0, vi.fn());

    expect(fetch).toHaveBeenCalledWith(`/api/research/iterative/runs/${runId}/resume`, expect.objectContaining({
      method: "POST", headers: expect.objectContaining({ "Last-Event-ID": "0" }),
    }));
  });

  it("rejects unexpected rendered progress fields and malformed saved responses", async () => {
    const invalid = event(0, runId).replace('"sequence":0', '"sequence":0,"private_answer":"leak"');
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream([invalid])));
    await expect(iterativeResearchApi.events(runId, -1, vi.fn())).rejects.toThrow("Invalid iterative research progress");

    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(Response.json({ run: {}, session: {} }))));
    await expect(iterativeResearchApi.get(runId)).rejects.toThrow("Invalid saved research response");
    await expect(iterativeResearchApi.cancel(runId)).rejects.toThrow("Invalid saved research response");
  });

  it("rejects citations whose rendered source URL is not HTTP(S)", async () => {
    const run = {
      schema_version: "iterative-research-v1", id: runId, session_id: sessionId,
      state: "completed", terminal_reason: "sufficient", current_iteration: 1,
      decision_state: null, decision_ids: [],
      budget: {
        max_iterations: 3, max_queries: 3, max_sources: 12, max_elapsed_seconds: 90,
        max_tokens: 16000, max_provider_cost_usd: "0.05", allowed_domains: ["example.org"],
      },
      usage: { iterations: 1, queries: 1, sources: 1, tokens: 100, provider_cost_usd: "0", elapsed_seconds: "2", allowed_domains: 1 },
      gaps: [], events: [],
    };
    const session = {
      schema_version: "research-v1", id: sessionId, state: "completed",
      request: { question: "Synthetic research?", freshness: "general", idempotency_key: sessionId },
      answer: "Synthetic supported excerpt.", failure_code: null,
      expires_at: "2099-01-01T00:00:00Z", attempts: [],
      citations: [{
        number: 1, evidence_id: "44444444-4444-4444-8444-444444444444",
        source_observation_id: "55555555-5555-4555-8555-555555555555",
        url: "javascript:alert(1)", title: "Unsafe source",
        observed_at: "2026-10-02T00:00:00Z", expires_at: "2099-01-01T00:00:00Z",
      }],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ run, session })));
    await expect(iterativeResearchApi.get(runId)).rejects.toThrow("Invalid saved research response");
  });

  it("rejects a partial trailing SSE frame", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream([event(0, runId).trimEnd()])));
    await expect(iterativeResearchApi.events(runId, -1, vi.fn())).rejects.toThrow("Incomplete iterative research progress frame");
  });
});
