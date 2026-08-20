import { NextRequest } from "next/server";

import { proxyConversationApi } from "../../../lib/conversation-proxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) { return proxyConversationApi(request); }
export async function POST(request: NextRequest) { return proxyConversationApi(request); }
