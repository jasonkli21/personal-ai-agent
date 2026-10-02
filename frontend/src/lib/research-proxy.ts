import { NextRequest, NextResponse } from "next/server";
import { proxyApi } from "./conversation-proxy";

export function proxyResearchApi(request: NextRequest, path = "", inspection = false) {
  if (process.env.RESEARCH_ENABLED !== "true" ||
      (inspection && process.env.RESEARCH_INSPECTION_ENABLED !== "true")) {
    return NextResponse.json({ error: { code: "not_found", message: "Research is unavailable." } }, { status: 404 });
  }
  return proxyApi(request, `/v1/research${path}`);
}
