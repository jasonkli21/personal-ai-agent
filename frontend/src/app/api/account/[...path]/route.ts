import { NextRequest } from "next/server";

import { proxyApi } from "../../../../lib/conversation-proxy";

function accountPath(request: NextRequest) {
  const suffix = request.nextUrl.pathname.slice("/api/account".length);
  return proxyApi(request, `/v1/account${suffix}`);
}

export const GET = accountPath;
export const POST = accountPath;
