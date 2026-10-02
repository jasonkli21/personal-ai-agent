import { NextRequest } from "next/server";
import { proxyDecisionApi } from "../../../lib/decision-proxy";

export async function POST(request: NextRequest) {
  return proxyDecisionApi(request);
}
