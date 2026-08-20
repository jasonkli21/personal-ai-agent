import { NextRequest, NextResponse } from "next/server";

/** Proxy conversation API calls without exposing the backend URL to the browser. */
export async function proxyConversationApi(request: NextRequest, path = "") {
  const baseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${baseUrl}/v1/conversations${path}`, {
      method: request.method,
      body: request.method === "POST" ? await request.text() : undefined,
      headers: request.method === "POST" ? { "Content-Type": "application/json" } : undefined,
      cache: "no-store",
    });
    const headers = new Headers();
    for (const name of ["Content-Type", "Cache-Control", "X-Accel-Buffering", "X-Request-ID"]) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new NextResponse(response.body, { status: response.status, headers });
  } catch {
    return NextResponse.json(
      { error: { code: "api_unavailable", message: "The Personal AI service is unavailable. Please try again." } },
      { status: 503 },
    );
  }
}
