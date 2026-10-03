// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { proxyIterativeResearchApi, proxyResearchApi } from "./research-proxy";

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

it("keeps iterative routes closed until all three independent gates are enabled", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  const request = new NextRequest("http://localhost/api/research/iterative/runs/run-1");
  vi.stubEnv("RESEARCH_ENABLED", "true");
  vi.stubEnv("ITERATIVE_RESEARCH_ENABLED", "true");
  expect((await proxyIterativeResearchApi(request, "/runs/run-1")).status).toBe(404);
  vi.stubEnv("ITERATIVE_PROGRESS_ENABLED", "true");
  vi.stubEnv("ITERATIVE_RESEARCH_ENABLED", "false");
  expect((await proxyIterativeResearchApi(request, "/runs/run-1")).status).toBe(404);
  expect(fetch).not.toHaveBeenCalled();
});

it("proxies an enabled reconnect route through the same-origin API boundary", async () => {
  vi.stubEnv("RESEARCH_ENABLED", "true");
  vi.stubEnv("ITERATIVE_RESEARCH_ENABLED", "true");
  vi.stubEnv("ITERATIVE_PROGRESS_ENABLED", "true");
  const fetch = vi.fn().mockResolvedValue(Response.json({ ok: true }));
  vi.stubGlobal("fetch", fetch);
  const response = await proxyIterativeResearchApi(
    new NextRequest("http://localhost/api/research/iterative/runs/run-1/events?after=2"),
    "/runs/run-1/events?after=2",
  );
  expect(response.status).toBe(200);
  expect(fetch).toHaveBeenCalledWith("http://localhost:8000/v1/research/iterative/runs/run-1/events?after=2", expect.objectContaining({ cache: "no-store" }));
});

it("forwards the resume cursor header to the backend", async () => {
  vi.stubEnv("RESEARCH_ENABLED", "true");
  vi.stubEnv("ITERATIVE_RESEARCH_ENABLED", "true");
  vi.stubEnv("ITERATIVE_PROGRESS_ENABLED", "true");
  const fetch = vi.fn().mockResolvedValue(Response.json({ ok: true }));
  vi.stubGlobal("fetch", fetch);
  await proxyIterativeResearchApi(
    new NextRequest("http://localhost/api/research/iterative/runs/run-1/resume", {
      method: "POST", headers: { "Last-Event-ID": "7" },
    }),
    "/runs/run-1/resume",
  );
  expect(new Headers(fetch.mock.calls[0][1].headers).get("Last-Event-ID")).toBe("7");
});
