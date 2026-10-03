export type SseFrame = { event: string; data: string; id?: string };

export class SseError extends Error {
  constructor(readonly kind: "missing_body" | "limit" | "incomplete") {
    super(`Invalid response stream: ${kind}`);
    this.name = "SseError";
  }
}

/** Read bounded SSE frames independently of transport chunk boundaries. */
export async function* readSseFrames(
  response: Response,
  limits: { frameCharacters: number; totalBytes: number },
): AsyncGenerator<SseFrame> {
  if (!response.body) throw new SseError("missing_body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let bytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      bytes += value?.byteLength ?? 0;
      if (bytes > limits.totalBytes) throw new SseError("limit");
      buffer += decoder.decode(value, { stream: !done });
      let boundary = /\r?\n\r?\n/.exec(buffer);
      while (boundary) {
        if (boundary.index > limits.frameCharacters) throw new SseError("limit");
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const lines = frame.split(/\r?\n/);
        const field = (name: string) => lines.find(line => line.startsWith(`${name}:`))?.slice(name.length + 1).trim();
        const data = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).replace(/^ /, "")).join("\n");
        // Comment-only keepalives do not carry application events.
        if (lines.some(line => line && !line.startsWith(":"))) {
          yield { event: field("event") ?? "", data, id: field("id") };
        }
        boundary = /\r?\n\r?\n/.exec(buffer);
      }
      if (buffer.length > limits.frameCharacters) throw new SseError("limit");
      if (done) {
        if (buffer.trim()) throw new SseError("incomplete");
        return;
      }
    }
  } finally {
    // Breaking on a terminal event and read/validation failures both tear down
    // the network stream. A browser disconnect must reach the upstream service.
    try { await reader.cancel(); } catch { /* The upstream may already be closed. */ }
    reader.releaseLock();
  }
}
