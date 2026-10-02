import { NextRequest } from "next/server";
import { proxyResearchApi } from "../../../../../lib/research-proxy";

export const dynamic = "force-dynamic";
export async function POST(request: NextRequest, { params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  return proxyResearchApi(request, `/${encodeURIComponent(sessionId)}/run`);
}
