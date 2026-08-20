import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, path = "") {
  const baseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${baseUrl}/v1/conversations${path}`, {
      method: request.method,
      body: request.method === "POST" ? await request.text() : undefined,
      headers: request.method === "POST" ? { "Content-Type": "application/json" } : undefined,
      cache: "no-store",
    });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch {
    return NextResponse.json({ error: { code: "api_unavailable", message: "The Personal AI service is unavailable. Please try again." } }, { status: 503 });
  }
}

export async function GET(request: NextRequest) { return proxy(request); }
export async function POST(request: NextRequest) { return proxy(request); }
