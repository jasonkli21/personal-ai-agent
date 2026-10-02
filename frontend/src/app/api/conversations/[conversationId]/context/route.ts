import { NextRequest, NextResponse } from "next/server";
import { proxyConversationApi } from "../../../../../lib/conversation-proxy";

export async function GET(request: NextRequest, { params }: { params: Promise<{ conversationId: string }> }) {
  if (process.env.CONTEXT_INSPECTION_ENABLED !== "true") {
    return NextResponse.json({ error: { code: "not_found", message: "The requested resource was not found." } }, { status: 404 });
  }
  const { conversationId } = await params;
  const ids = request.nextUrl.searchParams.getAll("memory_ids");
  if (ids.length && process.env.MEMORY_INSPECTION_ENABLED !== "true" &&
      process.env.MEMORY_LIFECYCLE_INSPECTION_ENABLED !== "true") {
    return NextResponse.json({ error: { code: "not_found", message: "The requested resource was not found." } }, { status: 404 });
  }
  const search = new URLSearchParams();
  ids.forEach(id => search.append("memory_ids", id));
  const suffix = search.size ? `?${search.toString()}` : "";
  return proxyConversationApi(request, `/${encodeURIComponent(conversationId)}/context${suffix}`);
}
