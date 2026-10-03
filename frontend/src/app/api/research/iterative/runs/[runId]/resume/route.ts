import { NextRequest } from "next/server";
import { proxyIterativeResearchApi } from "../../../../../../../lib/research-proxy";

export const dynamic = "force-dynamic";
export async function POST(request: NextRequest, { params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return proxyIterativeResearchApi(request, `/runs/${encodeURIComponent(runId)}/resume`);
}
