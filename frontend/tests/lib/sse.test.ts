// @vitest-environment node
import { describe, expect, it } from "vitest";
import { readSseFrames } from "../../src/lib/sse";

async function collect(text: string, frameCharacters: number) {
  const frames = [];
  for await (const frame of readSseFrames(new Response(text), { frameCharacters, totalBytes: 65536 })) frames.push(frame);
  return frames;
}

describe("SSE framing", () => {
  it("bounds individual frames even when many valid frames share one network chunk", async () => {
    const text = "event: progress\ndata: {}\n\n";
    const frames = await collect(text.repeat(400), 8192);
    expect(frames).toHaveLength(400);
    expect(frames[0]).toEqual({ event: "progress", data: "{}", id: undefined });
  });

  it("rejects an oversized frame and an unterminated tail", async () => {
    await expect(collect(`data: ${"x".repeat(8192)}\n\n`, 8192)).rejects.toThrow("limit");
    await expect(collect("data: {}", 8192)).rejects.toThrow("incomplete");
  });

  it("ignores comment keepalives and preserves multiline data whitespace", async () => {
    expect(await collect(": ping\n\nevent: progress\ndata:   a\ndata: b\n\n", 8192))
      .toEqual([{ event: "progress", data: "  a\nb", id: undefined }]);
  });
});
