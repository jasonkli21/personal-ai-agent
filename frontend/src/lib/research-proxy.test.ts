// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { proxyResearchApi } from "./research-proxy";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
it("gates research and inspection before upstream access", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  expect((await proxyResearchApi(new NextRequest("http://localhost/api/research"))).status).toBe(404);
  vi.stubEnv("RESEARCH_ENABLED", "true");
  expect((await proxyResearchApi(new NextRequest("http://localhost/api/research/s/inspection"),"/s/inspection",true)).status).toBe(404);
  expect(fetch).not.toHaveBeenCalled();
});
it("preserves progress and aborts the research upstream on cancellation", async () => {
  vi.stubEnv("RESEARCH_ENABLED", "true");
  const cancel = vi.fn();
  const upstream = new ReadableStream<Uint8Array>({start(c) { c.enqueue(new TextEncoder().encode("progress")); },cancel});
  const fetch = vi.fn().mockResolvedValue(new Response(upstream, {headers:{"Content-Type":"text/event-stream"}}));
  vi.stubGlobal("fetch", fetch);
  const response = await proxyResearchApi(new NextRequest("http://localhost/api/research/s/run", {method:"POST"}),"/s/run");
  expect(fetch).toHaveBeenCalledWith("http://localhost:8000/v1/research/s/run", expect.objectContaining({method:"POST"}));
  const reader = response.body!.getReader(); await reader.read(); await reader.cancel("closed");
  expect(fetch.mock.calls[0][1].signal.aborted).toBe(true); expect(cancel).toHaveBeenCalledWith("closed");
});
