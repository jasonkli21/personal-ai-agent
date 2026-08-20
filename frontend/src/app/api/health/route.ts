import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

  try {
    const response = await fetch(`${apiBaseUrl}/health`, { cache: "no-store" });
    const body = await response.json();

    return NextResponse.json({ web: "ok", api: body }, { status: response.status });
  } catch {
    return NextResponse.json(
      { web: "ok", api: { status: "unreachable" } },
      { status: 503 },
    );
  }
}
