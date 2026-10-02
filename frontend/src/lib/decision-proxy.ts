import { NextRequest, NextResponse } from "next/server";
import { proxyApi } from "./conversation-proxy";

export function proxyDecisionApi(request: NextRequest, path = "", inspection = false) {
  if (process.env.DECISION_ENABLED !== "true" ||
      (inspection && process.env.DECISION_INSPECTION_ENABLED !== "true")) {
    return NextResponse.json({ error: { code: "not_found", message: "Decision support is unavailable." } }, { status: 404 });
  }
  return proxyApi(request, `/v1/decisions${path}`);
}
