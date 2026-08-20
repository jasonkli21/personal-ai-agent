import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
type Context = { params: Promise<{ conversationId: string }> };

export async function GET(_request: NextRequest, { params }: Context) {
  const { conversationId } = await params;
  const baseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${baseUrl}/v1/conversations/${encodeURIComponent(conversationId)}`, { cache: "no-store" });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch {
    return NextResponse.json({ error: { code: "api_unavailable", message: "The Personal AI service is unavailable. Please try again." } }, { status: 503 });
  }
}
