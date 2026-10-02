// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { proxyDecisionApi } from "./decision-proxy";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("gates decisions and inspection before upstream access", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  const request = new NextRequest("http://localhost/api/decisions/id");
  expect((await proxyDecisionApi(request, "/id")).status).toBe(404);
  vi.stubEnv("DECISION_ENABLED", "true");
  expect((await proxyDecisionApi(request, "/id/inspection", true)).status).toBe(404);
  expect(fetch).not.toHaveBeenCalled();
});

it("forwards an enabled read through the server-side API proxy", async () => {
  vi.stubEnv("DECISION_ENABLED", "true");
  const fetch = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const response = await proxyDecisionApi(new NextRequest("http://localhost/api/decisions/id"), "/id");
  expect(response.status).toBe(200);
  expect(fetch).toHaveBeenCalledWith("http://localhost:8000/v1/decisions/id", expect.objectContaining({ method: "GET" }));
});

it("forwards decision creation without exposing the API base to the browser", async () => {
  vi.stubEnv("DECISION_ENABLED", "true");
  const fetch = vi.fn().mockResolvedValue(new Response("{}", { status: 201 }));
  vi.stubGlobal("fetch", fetch);
  const body = JSON.stringify({ schema_version: "decision-v1" });
  const request = new NextRequest("http://localhost/api/decisions", {
    method: "POST", headers: { "Content-Type": "application/json" }, body,
  });
  const response = await proxyDecisionApi(request);
  expect(response.status).toBe(201);
  expect(fetch).toHaveBeenCalledWith("http://localhost:8000/v1/decisions", expect.objectContaining({ method: "POST", body }));
});
