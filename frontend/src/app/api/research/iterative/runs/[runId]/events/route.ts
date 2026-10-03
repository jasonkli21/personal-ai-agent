import { NextRequest } from "next/server";
import { proxyIterativeResearchApi } from "../../../../../../../lib/research-proxy";

export const dynamic = "force-dynamic";
export async function GET(request: NextRequest, { params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  const after = request.nextUrl.searchParams.get("after") ?? "-1";
  return proxyIterativeResearchApi(
    request,
    `/runs/${encodeURIComponent(runId)}/events?after=${encodeURIComponent(after)}`,
  );
}
