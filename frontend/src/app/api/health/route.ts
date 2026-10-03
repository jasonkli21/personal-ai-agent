import { NextRequest, NextResponse } from "next/server";
import { backendAuthorizationHeaders } from "../../../lib/conversation-proxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

  try {
    const headers = await backendAuthorizationHeaders(request, apiBaseUrl);
    const response = await fetch(`${apiBaseUrl}/health`, {
      cache: "no-store",
      headers,
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(5000)]),
    });
    const body = await response.json();

    return NextResponse.json({ web: "ok", api: body }, { status: response.status });
  } catch {
    return NextResponse.json(
      { web: "ok", api: { status: "unreachable" } },
      { status: 503 },
    );
  }
}
