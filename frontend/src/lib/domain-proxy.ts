import { NextRequest, NextResponse } from "next/server";
import { proxyApi } from "./conversation-proxy";

export function proxyDomainApi(request: NextRequest, domainId: string, path: string, inspection = false) {
  const enabled = process.env.DECISION_ENABLED === "true" &&
    process.env[`${domainId.toUpperCase()}_ENABLED`] === "true";
  if (!enabled || !["travel", "shopping"].includes(domainId) ||
      (inspection && process.env.DOMAIN_INSPECTION_ENABLED !== "true")) {
    return NextResponse.json({
      error: { code: "not_found", message: "This comparison is unavailable." },
    }, { status: 404 });
  }
  return proxyApi(request, `/v1/domains/${encodeURIComponent(domainId)}${path}`);
}
