import { NextRequest, NextResponse } from "next/server";
import { proxyConversationApi } from "../../../../../lib/conversation-proxy";

export async function GET(request: NextRequest, { params }: { params: Promise<{ conversationId: string }> }) {
  if (process.env.CONTEXT_INSPECTION_ENABLED !== "true") {
    return NextResponse.json({ error: { code: "not_found", message: "The requested resource was not found." } }, { status: 404 });
  }
  const { conversationId } = await params;
  return proxyConversationApi(request, `/${encodeURIComponent(conversationId)}/context`);
}
