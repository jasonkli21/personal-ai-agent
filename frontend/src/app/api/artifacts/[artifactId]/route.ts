import { NextRequest, NextResponse } from "next/server";
import { proxyApi } from "../../../../lib/conversation-proxy";

export async function GET(request: NextRequest, { params }: { params: Promise<{ artifactId: string }> }) {
  if (process.env.ARTIFACTS_ENABLED !== "true") {
    return NextResponse.json({ error: { code: "not_found", message: "Artifact access is unavailable." } }, { status: 404 });
  }
  const { artifactId } = await params;
  return proxyApi(request, `/v1/artifacts/${encodeURIComponent(artifactId)}`);
}
