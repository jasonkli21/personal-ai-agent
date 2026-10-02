// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { proxyDomainApi } from "./domain-proxy";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("blocks disabled domains before making an upstream request", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubEnv("DECISION_ENABLED", "true");
  vi.stubEnv("TRAVEL_ENABLED", "false");
  const response = await proxyDomainApi(new NextRequest("http://localhost/api/domains/travel/fixtures"), "travel", "/fixtures");
  expect(response.status).toBe(404);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("proxies a permitted shopping comparison through the backend", async () => {
  vi.stubEnv("DECISION_ENABLED", "true");
  vi.stubEnv("SHOPPING_ENABLED", "true");
  const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", fetchMock);
  await proxyDomainApi(new NextRequest("http://localhost/api/domains/shopping/fixtures"), "shopping", "/fixtures");
  expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/v1/domains/shopping/fixtures", expect.objectContaining({ method: "GET" }));
});
