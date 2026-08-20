import { NextRequest } from "next/server";

import { proxyConversationApi } from "../../../../lib/conversation-proxy";

export const dynamic = "force-dynamic";
type Context = { params: Promise<{ conversationId: string }> };

export async function GET(_request: NextRequest, { params }: Context) {
  const { conversationId } = await params;
  return proxyConversationApi(_request, `/${encodeURIComponent(conversationId)}`);
}
