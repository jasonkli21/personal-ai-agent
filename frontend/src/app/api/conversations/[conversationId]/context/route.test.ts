// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { GET } from "./route";
const proxy = vi.hoisted(() => vi.fn());
vi.mock("../../../../../lib/conversation-proxy", () => ({ proxyConversationApi: proxy }));
afterEach(() => { vi.unstubAllEnvs(); proxy.mockReset(); });
it("returns 404 by default without contacting the backend", async () => {
  vi.stubEnv("CONTEXT_INSPECTION_ENABLED", "false");
  const response = await GET(new NextRequest("http://localhost/api/conversations/id/context"), { params: Promise.resolve({ conversationId: "id" }) });
  expect(response.status).toBe(404);
  expect(proxy).not.toHaveBeenCalled();
});
it("forwards enabled inspection through the existing proxy", async () => {
  vi.stubEnv("CONTEXT_INSPECTION_ENABLED", "true");
  proxy.mockResolvedValue(new Response("{}"));
  const request = new NextRequest("http://localhost/api/conversations/id/context");
  await GET(request, { params: Promise.resolve({ conversationId: "id" }) });
  expect(proxy).toHaveBeenCalledWith(request, "/id/context");
});
