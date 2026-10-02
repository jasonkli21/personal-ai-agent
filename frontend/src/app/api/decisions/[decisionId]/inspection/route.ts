import { NextRequest } from "next/server";
import { proxyDecisionApi } from "../../../../../lib/decision-proxy";

export async function GET(request: NextRequest, { params }: { params: Promise<{ decisionId: string }> }) {
  const { decisionId } = await params;
  return proxyDecisionApi(request, `/${encodeURIComponent(decisionId)}/inspection`, true);
}
