import { afterEach, describe, expect, it, vi } from "vitest";
import { iterativeResearchApi, type IterativeProgress } from "./iterative-research-api";

afterEach(() => vi.unstubAllGlobals());

function event(sequence: number, runId = "run-1", eventType = "planning", state = "planning") {
  const data: IterativeProgress = {
    schema_version: "iterative-research-v1", run_id: runId, session_id: "session-1",
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
    const complete = event(0) + event(1, "run-1", "completed", "completed");
    const fetch = vi.fn().mockResolvedValue(stream([complete.slice(0, 31), complete.slice(31)]));
    vi.stubGlobal("fetch", fetch);
    const progress: IterativeProgress[] = [];

    const result = await iterativeResearchApi.start(
      { question: "What is supported?", freshness: "general", idempotency_key: "key-1" },
      value => progress.push(value),
    );

    expect(result.runId).toBe("run-1");
    expect(result.lastSequence).toBe(1);
    expect(progress.map(value => value.sequence)).toEqual([0, 1]);
    expect(fetch).toHaveBeenCalledWith("/api/research/iterative", expect.objectContaining({ method: "POST" }));
  });

  it("rejects a sequence gap during replay", async () => {
    const fetch = vi.fn().mockResolvedValue(stream([event(5)]));
    vi.stubGlobal("fetch", fetch);
    await expect(iterativeResearchApi.events("run-1", 3, vi.fn())).rejects.toThrow("Invalid iterative research progress");
  });

  it("rejects an event from a different run during replay", async () => {
    const fetch = vi.fn().mockResolvedValue(stream([event(4, "other-run")]));
    vi.stubGlobal("fetch", fetch);
    await expect(iterativeResearchApi.events("run-1", 3, vi.fn())).rejects.toThrow("Invalid iterative research progress");
  });

  it("allows a live-lease resume response to contain only persisted progress", async () => {
    const fetch = vi.fn().mockResolvedValue(stream([event(0, "run-1", "searching", "searching")]));
    vi.stubGlobal("fetch", fetch);
    const progress: IterativeProgress[] = [];

    await expect(iterativeResearchApi.resume("run-1", -1, value => progress.push(value))).resolves.toMatchObject({
      runId: "run-1", lastSequence: 0,
    });
    expect(progress).toHaveLength(1);
  });
});
