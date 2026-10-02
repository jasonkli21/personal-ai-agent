import { NextRequest } from "next/server";
import { proxyResearchApi } from "../../../lib/research-proxy";

export const dynamic = "force-dynamic";
export function POST(request: NextRequest) { return proxyResearchApi(request); }
