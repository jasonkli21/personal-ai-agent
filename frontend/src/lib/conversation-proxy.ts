import { NextRequest, NextResponse } from "next/server";

type CachedServiceToken = { value: string; expiresAt: number };
let cachedServiceToken: CachedServiceToken | null = null;

function tokenExpiry(token: string) {
  const payloadPart = token.split(".")[1];
  if (!payloadPart) return 0;
  try {
    const normalized = payloadPart.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(Buffer.from(normalized, "base64").toString("utf8")) as { exp?: unknown };
    return typeof payload.exp === "number" ? payload.exp * 1000 : 0;
  } catch {
    return 0;
  }
}

async function cloudRunServiceToken(audience: string) {
  if (process.env.API_IAM_AUTH_ENABLED !== "true") return null;
  if (cachedServiceToken && cachedServiceToken.expiresAt > Date.now() + 60_000) {
    return cachedServiceToken.value;
  }

  const metadataUrl = new URL(
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity",
  );
  metadataUrl.searchParams.set("audience", audience);
  const response = await fetch(metadataUrl, {
    headers: { "Metadata-Flavor": "Google" },
    cache: "no-store",
    signal: AbortSignal.timeout(2500),
  });
  if (!response.ok) throw new Error("api_service_identity_unavailable");
  const value = await response.text();
  const expiresAt = tokenExpiry(value);
  if (value.length > 8192 || expiresAt <= Date.now() + 60_000) {
    throw new Error("api_service_identity_unavailable");
  }
  cachedServiceToken = { value, expiresAt };
  return value;
}

/** Build non-overlapping end-user and Cloud Run service identity headers. */
export async function backendAuthorizationHeaders(request: Request, apiBaseUrl: string) {
  const headers = new Headers();
  const userAuthorization = request.headers.get("authorization");
  const userToken = userAuthorization?.startsWith("Bearer ")
    ? userAuthorization.slice("Bearer ".length).trim()
    : null;
  const serviceToken = await cloudRunServiceToken(new URL(apiBaseUrl).origin);

  if (serviceToken) {
    headers.set("Authorization", `Bearer ${serviceToken}`);
    if (userToken) headers.set("X-User-ID-Token", userToken);
  } else if (userToken) {
    // Local API development validates the user token directly when OIDC is enabled.
    headers.set("Authorization", `Bearer ${userToken}`);
  }
  return headers;
}

/** Proxy conversation API calls without exposing the backend URL to the browser. */
export async function proxyApi(request: NextRequest, path: string) {
  const baseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";
  const upstreamAbort = new AbortController();
  const abort = () => upstreamAbort.abort();
  request.signal.addEventListener("abort", abort, { once: true });
  const cleanup = () => request.signal.removeEventListener("abort", abort);
  try {
    if (request.signal.aborted) upstreamAbort.abort();
    upstreamAbort.signal.throwIfAborted();
    const headers = await backendAuthorizationHeaders(request, baseUrl);
    // Scope labels and correlation are forwarded as untrusted request metadata;
    // backend authentication remains the sole source of owner identity.
    for (const name of [
      "X-Application-ID",
      "X-Workspace-ID",
      "X-Request-ID",
      "X-Client-Capabilities",
      "X-Client-Context",
    ]) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    if (request.method === "POST") headers.set("Content-Type", "application/json");
    const lastEventId = request.headers.get("Last-Event-ID");
    if (lastEventId) headers.set("Last-Event-ID", lastEventId);

    const response = await fetch(`${baseUrl}${path}`, {
      method: request.method,
      body: request.method === "POST" ? await request.text() : undefined,
      headers,
      cache: "no-store",
      signal: upstreamAbort.signal,
    });
    const responseHeaders = new Headers();
    for (const name of ["Content-Type", "Content-Disposition", "Cache-Control", "X-Accel-Buffering", "X-Request-ID"]) {
      const value = response.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    if (!response.body) {
      cleanup();
      return new NextResponse(null, { status: response.status, headers: responseHeaders });
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
    return new NextResponse(body, { status: response.status, headers: responseHeaders });
  } catch {
    cleanup();
    upstreamAbort.abort();
    return NextResponse.json(
      { error: { code: "api_unavailable", message: "The Personal AI service is unavailable. Please try again." } },
      { status: 503 },
    );
  }
}

export function proxyConversationApi(request: NextRequest, path = "") {
  return proxyApi(request, `/v1/conversations${path}`);
}
