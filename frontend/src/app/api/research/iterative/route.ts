import { NextRequest } from "next/server";
import { proxyIterativeResearchApi } from "../../../../lib/research-proxy";

export const dynamic = "force-dynamic";
export function POST(request: NextRequest) {
  return proxyIterativeResearchApi(request);
}
