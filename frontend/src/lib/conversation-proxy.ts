import { NextRequest, NextResponse } from "next/server";

/** Proxy conversation API calls without exposing the backend URL to the browser. */
export async function proxyConversationApi(request: NextRequest, path = "") {
  const baseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";
  const upstreamAbort = new AbortController();
  const abort = () => upstreamAbort.abort();
  request.signal.addEventListener("abort", abort, { once: true });
  const cleanup = () => request.signal.removeEventListener("abort", abort);
  try {
    if (request.signal.aborted) upstreamAbort.abort();
    upstreamAbort.signal.throwIfAborted();
    const response = await fetch(`${baseUrl}/v1/conversations${path}`, {
      method: request.method,
      body: request.method === "POST" ? await request.text() : undefined,
      headers: request.method === "POST" ? { "Content-Type": "application/json" } : undefined,
      cache: "no-store",
      signal: upstreamAbort.signal,
    });
    const headers = new Headers();
    for (const name of ["Content-Type", "Cache-Control", "X-Accel-Buffering", "X-Request-ID"]) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    if (!response.body) {
      cleanup();
      return new NextResponse(null, { status: response.status, headers });
    }
    const reader = response.body.getReader();
    let finished = false;
    const body = new ReadableStream<Uint8Array>({
      async pull(controller) {
        try {
          const { done, value } = await reader.read();
          if (finished) return;
          if (done) {
            finished = true;
            cleanup();
            reader.releaseLock();
            controller.close();
          } else {
            controller.enqueue(value);
          }
        } catch (error) {
          if (finished) return;
          finished = true;
          cleanup();
          upstreamAbort.abort();
          try { await reader.cancel(); } catch { /* The upstream stream already failed. */ }
          reader.releaseLock();
          controller.error(error);
        }
      },
      async cancel(reason) {
        if (finished) return;
        finished = true;
        cleanup();
        upstreamAbort.abort();
        try { await reader.cancel(reason); } catch { /* Aborted fetches may already be closed. */ }
        reader.releaseLock();
      },
    });
    return new NextResponse(body, { status: response.status, headers });
  } catch {
    cleanup();
    upstreamAbort.abort();
    return NextResponse.json(
      { error: { code: "api_unavailable", message: "The Personal AI service is unavailable. Please try again." } },
      { status: 503 },
    );
  }
}
