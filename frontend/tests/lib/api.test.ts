// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { conversationsApi, type Message, type StreamHandlers } from "../../src/lib/api";

const assistant: Message = {
  id: "assistant", conversation_id: "conversation", owner_id: "local",
  role: "assistant", content: "Hello 🌍", status: "completed",
  created_at: "2026-01-01T00:00:00Z", parent_message_id: "user",
  supersedes_message_id: null, model: "fake", error_code: null,
};
function handlers(): StreamHandlers {
  return { onMessageCreated: vi.fn(), onDelta: vi.fn(), onCompleted: vi.fn(), onError: vi.fn() };
}
function frame(event: string, data: unknown) { return `event: ${event}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`; }
function mockResponse(chunks: Uint8Array[], closed = true) {
  const cancel = vi.fn();
  const body = new ReadableStream<Uint8Array>({
    start(controller) { for (const chunk of chunks) controller.enqueue(chunk); if (closed) controller.close(); },
    cancel,
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
  return { body, cancel };
}
afterEach(() => vi.unstubAllGlobals());

describe("chat SSE protocol", () => {
  it("handles byte-split UTF-8 and CRLF frames and stops at completion", async () => {
    const bytes = new TextEncoder().encode(frame("response.delta", { message_id: assistant.id, delta: assistant.content }) + frame("response.completed", { message: assistant }));
    const { body, cancel } = mockResponse(Array.from(bytes, (byte) => new Uint8Array([byte])), false);
    const events = handlers();
    await conversationsApi.send("conversation", "Hi", events);
    expect(events.onDelta).toHaveBeenCalledWith(assistant.id, assistant.content);
    expect(events.onCompleted).toHaveBeenCalledOnce();
    expect(cancel).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
  });

  it.each(["", frame("response.delta", { message_id: "assistant", delta: "Partial" })])("rejects EOF without a terminal event", async (text) => {
    const { body } = mockResponse([new TextEncoder().encode(text)]);
    const events = handlers();
    await expect(conversationsApi.send("conversation", "Hi", events)).rejects.toThrow("interrupted");
    expect(events.onCompleted).not.toHaveBeenCalled();
    expect(body.locked).toBe(false);
    if (text) expect(events.onDelta).toHaveBeenCalledWith("assistant", "Partial");
  });

  it("recognizes a terminal error without waiting for EOF", async () => {
    const error = { message_id: "assistant", code: "llm_timeout", message: "Please retry." };
    const { cancel } = mockResponse([new TextEncoder().encode(frame("response.error", error))], false);
    const events = handlers();
    await conversationsApi.send("conversation", "Hi", events);
    expect(events.onError).toHaveBeenCalledWith(error);
    expect(cancel).toHaveBeenCalledOnce();
  });

  it.each([
    "event: response.completed\ndata: {broken}\n\n",
    frame("response.completed", { message: { id: "assistant" } }),
    frame("response.delta", { message_id: "assistant", delta: 7 }),
  ])("cancels and unlocks malformed streams", async (text) => {
    const { body, cancel } = mockResponse([new TextEncoder().encode(text)], false);
    await expect(conversationsApi.send("conversation", "Hi", handlers())).rejects.toThrow("could not be read");
    expect(cancel).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
  });

  it("does not dispatch a terminal frame missing its boundary", async () => {
    mockResponse([new TextEncoder().encode(frame("response.completed", { message: assistant }).trimEnd())]);
    const events = handlers();
    await expect(conversationsApi.send("conversation", "Hi", events)).rejects.toThrow("interrupted");
    expect(events.onCompleted).not.toHaveBeenCalled();
  });

  it("forwards a caller's abort signal", async () => {
    mockResponse([new TextEncoder().encode(frame("response.completed", { message: assistant }))]);
    const controller = new AbortController();
    await conversationsApi.send("conversation", "Hi", handlers(), controller.signal);
    expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ signal: controller.signal }));
  });
});
