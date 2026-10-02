import { NextRequest } from "next/server";
import { proxyDomainApi } from "../../../../../lib/domain-proxy";

type RouteContext = { params: Promise<{ domainId: string; path: string[] }> };

async function proxy(request: NextRequest, { params }: RouteContext) {
  const { domainId, path } = await params;
  const suffix = `/${path.map(segment => encodeURIComponent(segment)).join("/")}`;
  return proxyDomainApi(request, domainId, suffix, path.includes("inspection"));
}

export const GET = proxy;
export const POST = proxy;
