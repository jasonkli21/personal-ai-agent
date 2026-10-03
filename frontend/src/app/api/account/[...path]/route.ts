import { NextRequest, NextResponse } from "next/server";

import { proxyApi } from "../../../../lib/conversation-proxy";

function accountPath(request: NextRequest) {
  const suffix = request.nextUrl.pathname.slice("/api/account".length);
  const enabled = suffix === "/export"
    ? process.env.EXPORT_ENABLED === "true"
    : suffix.startsWith("/deletion") && process.env.DELETION_ENABLED === "true";
  if (!enabled) {
    return NextResponse.json({ error: { code: "not_found", message: "This account operation is unavailable." } }, { status: 404 });
  }
  return proxyApi(request, `/v1/account${suffix}`);
}

export const GET = accountPath;
export const POST = accountPath;
