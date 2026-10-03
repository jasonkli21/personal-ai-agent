// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { GET, POST } from "../../../../src/app/api/account/[...path]/route";

const proxy = vi.hoisted(() => vi.fn(() => new Response("{}")));
vi.mock("../../../../src/lib/conversation-proxy", () => ({ proxyApi: proxy }));

afterEach(() => { vi.unstubAllEnvs(); proxy.mockClear(); });

it("keeps disabled account operations behind the server gates", async () => {
  vi.stubEnv("EXPORT_ENABLED", "false");
  vi.stubEnv("DELETION_ENABLED", "false");
  expect((await POST(new NextRequest("http://localhost/api/account/export", { method: "POST" }))).status).toBe(404);
  expect((await GET(new NextRequest("http://localhost/api/account/deletion/request-id"))).status).toBe(404);
  expect(proxy).not.toHaveBeenCalled();
});

it("forwards independently enabled account operations", async () => {
  vi.stubEnv("EXPORT_ENABLED", "true");
  vi.stubEnv("DELETION_ENABLED", "false");
  const request = new NextRequest("http://localhost/api/account/export", { method: "POST" });
  expect((await POST(request)).status).toBe(200);
  expect(proxy).toHaveBeenCalledWith(request, "/v1/account/export");
  expect((await GET(new NextRequest("http://localhost/api/account/deletion/request-id"))).status).toBe(404);
});
