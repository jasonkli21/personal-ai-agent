import { afterEach, describe, expect, it, vi } from "vitest";
import { researchApi } from "./research-api";

const id = "session-1";
const terminal = `event: research.terminal\ndata: ${JSON.stringify({schema_version:"research-v1",session_id:id,state:"completed"})}\n\n`;
function stream(text: string) { return new Response(text, {headers:{"Content-Type":"text/event-stream"}}); }
afterEach(() => vi.unstubAllGlobals());

describe("research client", () => {
  it("preserves request idempotency and forwards cancellation", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("{}")); vi.stubGlobal("fetch", fetch);
    const signal = new AbortController().signal;
    await researchApi.create("Question", "current", "same-key", signal);
    expect(fetch).toHaveBeenCalledWith("/api/research", expect.objectContaining({
      method:"POST", signal, body:JSON.stringify({schema_version:"research-v1",question:"Question",freshness:"current",idempotency_key:"same-key"}),
    }));
  });
  it("parses split CRLF milestones and requires matching terminal", async () => {
    const text = terminal.replaceAll("\n", "\r\n");
    const body = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(text.slice(0,13))); c.enqueue(new TextEncoder().encode(text.slice(13))); c.close(); } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, {headers:{"Content-Type":"text/event-stream"}})));
    const progress = vi.fn(); await researchApi.run(id, progress);
    expect(progress).toHaveBeenCalledWith("terminal", expect.objectContaining({state:"completed"}));
    expect(body.locked).toBe(false);
  });
  it.each(["", terminal.replace(id,"wrong-session"), terminal.replace("completed","running"), "event: research.planned\ndata: {}\n\n"])("rejects interrupted or invalid frames", async text => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream(text)));
    await expect(researchApi.run(id, vi.fn())).rejects.toThrow();
  });
  it("bounds progress buffers", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream("x".repeat(8193))));
    await expect(researchApi.run(id, vi.fn())).rejects.toThrow("limit");
  });
});
