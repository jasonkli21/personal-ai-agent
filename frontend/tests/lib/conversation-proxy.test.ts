// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { proxyConversationApi } from "../../src/lib/conversation-proxy";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("conversation streaming proxy", () => {
  it("forwards the allowlisted scope and correlation headers without owner claims", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("ok"));
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest("http://localhost/api/conversations", {
      headers: {
        "X-Application-ID": "travel",
        "X-Workspace-ID": "team-a",
        "X-Request-ID": "trace-123",
        "X-Client-Capabilities": "chat.streaming",
        "X-Client-Context": "{\"surface\":\"web\"}",
        "X-Owner-ID": "forged-owner",
        "X-Idempotency-Key": "operation-key",
      },
    });
    await proxyConversationApi(request);
    const forwarded = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(Object.fromEntries([
      "X-Application-ID", "X-Workspace-ID", "X-Request-ID",
      "X-Client-Capabilities", "X-Client-Context",
    ].map((name) => [name, forwarded.get(name)]) )).toEqual({
      "X-Application-ID": "travel",
      "X-Workspace-ID": "team-a",
      "X-Request-ID": "trace-123",
      "X-Client-Capabilities": "chat.streaming",
      "X-Client-Context": "{\"surface\":\"web\"}",
    });
    expect(forwarded.has("X-Owner-ID")).toBe(false);
    expect(forwarded.has("X-Idempotency-Key")).toBe(false);
  });

  it("preserves status and streaming headers while forwarding the body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("data", { headers: { "Content-Type": "text/event-stream", "X-Request-ID": "request" } })));
    const response = await proxyConversationApi(new NextRequest("http://localhost/api/conversations"));
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/event-stream");
    expect(response.headers.get("X-Request-ID")).toBe("request");
    expect(await response.text()).toBe("data");
  });

  it("aborts the upstream fetch when the incoming request disconnects", async () => {
    let upstreamSignal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn((_url, init) => {
      upstreamSignal = init.signal;
      return new Promise((_resolve, reject) => upstreamSignal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true }));
    }));
    const controller = new AbortController();
    const pending = proxyConversationApi(new NextRequest("http://localhost/api/conversations", { signal: controller.signal }));
    await vi.waitFor(() => expect(upstreamSignal).toBeDefined());
    controller.abort();
    expect(upstreamSignal?.aborted).toBe(true);
    expect((await pending).status).toBe(503);
  });

  it("aborts and cancels upstream when the downstream body is cancelled", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ start(c) { c.enqueue(new TextEncoder().encode("partial")); }, cancel });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body));
    vi.stubGlobal("fetch", fetchMock);
    const response = await proxyConversationApi(new NextRequest("http://localhost/api/conversations"));
    const reader = response.body!.getReader();
    await reader.read();
    await reader.cancel("browser closed");
    const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;
    expect(signal.aborted).toBe(true);
    expect(cancel).toHaveBeenCalledWith("browser closed");
    expect(body.locked).toBe(false);
  });

  it("does not issue an upstream request for an already aborted caller", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController(); controller.abort();
    expect((await proxyConversationApi(new NextRequest("http://localhost/api/conversations", { signal: controller.signal }))).status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("propagates abort after headers while a body read is pending", async () => {
    let upstreamSignal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn((_url, init) => {
      upstreamSignal = init.signal;
      return Promise.resolve(new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          upstreamSignal!.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")), { once: true });
        },
      })));
    }));
    const caller = new AbortController();
    const response = await proxyConversationApi(new NextRequest("http://localhost/api/conversations", { signal: caller.signal }));
    const pending = response.body!.getReader().read();
    caller.abort();
    await expect(pending).rejects.toThrow("Aborted");
    expect(upstreamSignal?.aborted).toBe(true);
  });

  it("removes the abort listener after normal upstream completion", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("done"));
    vi.stubGlobal("fetch", fetchMock);
    const caller = new AbortController();
    const response = await proxyConversationApi(new NextRequest("http://localhost/api/conversations", { signal: caller.signal }));
    expect(await response.text()).toBe("done");
    caller.abort();
    expect((fetchMock.mock.calls[0][1].signal as AbortSignal).aborted).toBe(false);
  });
});
