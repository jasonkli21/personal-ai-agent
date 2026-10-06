import { ApiError, applicationScopeHeaders, type ApplicationScopeRequest } from "./api";
import { authenticatedFetch } from "./auth";
import { readSseFrames, SseError } from "./sse";

export type ResearchState = "pending" | "running" | "completed" | "insufficient" | "failed" | "expired";
export type ResearchCitation = {
  number: number; evidence_id: string; source_observation_id: string; url: string;
  title: string | null; observed_at: string; expires_at: string;
};
export type ResearchSession = {
  schema_version: "research-v1"; id: string; state: ResearchState;
  request: { question: string; freshness: "general" | "current"; idempotency_key: string };
  answer: string | null; failure_code: string | null; expires_at: string;
  citations: ResearchCitation[]; attempts: { adapter: "fake" | "brave" }[];
};
export type ResearchProgress = {
  schema_version: "research-v1"; session_id: string; state?: ResearchState;
  query_count?: number; source_count?: number; evidence_count?: number;
};

async function response(path: string, init?: RequestInit, scope?: ApplicationScopeRequest) {
  const res = await authenticatedFetch(`/api/research${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...applicationScopeHeaders(scope), ...init?.headers },
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new ApiError(error.error?.message ?? "Research is unavailable. Please retry.", res.status);
  }
  return res;
}

const states = new Set(["pending", "running", "completed", "insufficient", "failed", "expired"]);
const events = new Set(["started", "planned", "attempt", "evidence", "selected", "terminal"]);

export const researchApi = {
  async create(question: string, freshness: "general" | "current", key: string, signal?: AbortSignal, scope?: ApplicationScopeRequest): Promise<ResearchSession> {
    return (await response("", { method: "POST", signal, body: JSON.stringify({
      schema_version: "research-v1", question, freshness, idempotency_key: key,
    }) }, scope)).json();
  },
  async get(id: string, signal?: AbortSignal, scope?: ApplicationScopeRequest): Promise<ResearchSession> {
    return (await response(`/${encodeURIComponent(id)}`, { signal }, scope)).json();
  },
  async inspect(id: string, scope?: ApplicationScopeRequest) {
    return (await response(`/${encodeURIComponent(id)}/inspection`, undefined, scope)).json();
  },
  async run(id: string, onProgress: (event: string, data: ResearchProgress) => void, signal?: AbortSignal, scope?: ApplicationScopeRequest) {
    const res = await response(`/${encodeURIComponent(id)}/run`, { method: "POST", signal }, scope);
    if (!res.body || !res.headers.get("content-type")?.startsWith("text/event-stream")) {
      throw new ApiError("Research progress could not be read.");
    }
    try {
      for await (const { event: name, data: dataText } of readSseFrames(res, { frameCharacters: 8192, totalBytes: 65536 })) {
        const data = JSON.parse(dataText) as ResearchProgress;
        const kind = name.replace(/^research\./, "");
        if (!name.startsWith("research.") || !events.has(kind) ||
            data.schema_version !== "research-v1" || data.session_id !== id) throw new ApiError("Invalid research progress.");
        if (kind === "terminal" && (!data.state || !states.has(data.state) || ["pending", "running"].includes(data.state))) {
          throw new ApiError("Invalid research completion.");
        }
        onProgress(kind, data);
        if (kind === "terminal") return;
      }
      throw new ApiError("Research was interrupted. Check the saved session.");
    } catch (error) {
      if (error instanceof SseError && error.kind === "limit") throw new ApiError("Research progress exceeded its limit.");
      throw error instanceof ApiError ? error : new ApiError("Research progress could not be read.");
    }
  },
};
