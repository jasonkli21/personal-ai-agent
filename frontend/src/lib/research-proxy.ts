import { NextRequest, NextResponse } from "next/server";
import { proxyApi } from "./conversation-proxy";

export function proxyResearchApi(request: NextRequest, path = "", inspection = false) {
  if (process.env.RESEARCH_ENABLED !== "true" ||
      (inspection && process.env.RESEARCH_INSPECTION_ENABLED !== "true")) {
    return NextResponse.json({ error: { code: "not_found", message: "Research is unavailable." } }, { status: 404 });
  }
  return proxyApi(request, `/v1/research${path}`);
}

export function proxyIterativeResearchApi(request: NextRequest, path = "") {
  if (process.env.RESEARCH_ENABLED !== "true" ||
      process.env.ITERATIVE_RESEARCH_ENABLED !== "true" ||
      process.env.ITERATIVE_PROGRESS_ENABLED !== "true") {
    return NextResponse.json({ error: { code: "not_found", message: "Iterative research is unavailable." } }, { status: 404 });
  }
  return proxyApi(request, `/v1/research/iterative${path}`);
}
