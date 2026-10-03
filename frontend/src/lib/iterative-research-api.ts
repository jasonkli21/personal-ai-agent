import { ApiError } from "./api";
import type { ResearchSession } from "./research-api";

export type IterativeRunState =
  | "pending" | "assessing" | "planning" | "searching" | "extracting" | "synthesizing"
  | "completed" | "insufficient" | "failed" | "cancelled";
export type IterativeRun = {
  schema_version: "iterative-research-v1";
  id: string;
  state: IterativeRunState;
  terminal_reason: string | null;
  current_iteration: number;
  decision_state: "recommended" | "eligible_unranked" | "research_needed" | "no_verified_match" | null;
  decision_ids: string[];
  budget: {
    max_iterations: number; max_queries: number; max_sources: number; max_elapsed_seconds: number;
    max_tokens: number; max_provider_cost_usd: string; allowed_domains: string[];
  };
  usage: {
    iterations: number; queries: number; sources: number; tokens: number;
    provider_cost_usd: string; elapsed_seconds: string; allowed_domains: number;
  };
  gaps: { gap_class: string; required: boolean; status: "open" | "resolved" | "unresolvable"; reason_code: string }[];
  events: { sequence: number; event_type: string; occurred_at: string }[];
};
export type IterativeResearchDetail = { run: IterativeRun; session: ResearchSession };
export type IterativeProgress = {
  schema_version: "iterative-research-v1";
  run_id: string;
  session_id: string;
  sequence: number;
  event_type: string;
  state?: IterativeRunState;
  iteration?: number;
  query_count?: number;
  source_count?: number;
  evidence_count?: number;
  gap_count?: number;
  citation_count?: number;
  stop_reason?: string;
  decision_state?: IterativeRun["decision_state"];
};

type Request = {
  question: string;
  freshness: "general" | "current";
  idempotency_key: string;
};

const terminalStates = new Set<IterativeRunState>(["completed", "insufficient", "failed", "cancelled"]);
const eventTypes = new Set([
  "planning", "searching", "extracting", "assessing", "follow_up",
  "synthesizing", "completed", "incomplete", "cancelled", "failed",
]);

async function response(path: string, init?: RequestInit) {
  const res = await fetch(`/api/research/iterative${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new ApiError(error.error?.message ?? "Iterative research is unavailable. Please retry.", res.status);
  }
  return res;
}

async function readProgress(
  res: Response,
  onProgress: (data: IterativeProgress) => void,
  options: { after: number; expectedRunId?: string; terminalRequired: boolean },
) {
  if (!res.body || !res.headers.get("content-type")?.startsWith("text/event-stream")) {
    throw new ApiError("Research progress could not be read.");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", bytes = 0, terminal = false, runId = options.expectedRunId;
  let lastSequence = options.after;
  try {
    while (true) {
      const { done, value } = await reader.read();
      bytes += value?.byteLength ?? 0;
      buffer += decoder.decode(value, { stream: !done });
      if (buffer.length > 8192 || bytes > 65536) throw new ApiError("Research progress exceeded its limit.");
      let match = /\r?\n\r?\n/.exec(buffer);
      while (match) {
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const lines = frame.split(/\r?\n/);
        const eventName = lines.find(line => line.startsWith("event:"))?.slice(6).trim() ?? "";
        const eventId = lines.find(line => line.startsWith("id:"))?.slice(3).trim();
        const dataText = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).trim()).join("\n");
        if (!eventName.startsWith("research.iterative.") || !dataText || !eventId) {
          throw new ApiError("Invalid iterative research progress.");
        }
        const eventType = eventName.slice("research.iterative.".length);
        const data = JSON.parse(dataText) as IterativeProgress;
        if (!eventTypes.has(eventType) || data.schema_version !== "iterative-research-v1" ||
            !data.run_id || !data.session_id || !Number.isSafeInteger(data.sequence) ||
            Number(eventId) !== data.sequence || data.sequence !== lastSequence + 1 ||
            runId && data.run_id !== runId || data.event_type !== eventType) {
          throw new ApiError("Invalid iterative research progress.");
        }
        if (runId === undefined) runId = data.run_id;
        if (data.state && terminalStates.has(data.state)) terminal = true;
        lastSequence = data.sequence;
        onProgress(data);
        match = /\r?\n\r?\n/.exec(buffer);
      }
      if (done) {
        if (options.terminalRequired && !terminal) {
          throw new ApiError("Research was interrupted. Reconnect to the saved run.");
        }
        return { runId, lastSequence };
      }
      if (terminal && options.terminalRequired) return { runId, lastSequence };
    }
  } catch (error) {
    throw error instanceof ApiError ? error : new ApiError("Research progress could not be read.");
  } finally {
    try { await reader.cancel(); } catch { /* The upstream may already be closed. */ }
    reader.releaseLock();
  }
}

export const iterativeResearchApi = {
  async start(request: Request, onProgress: (data: IterativeProgress) => void, signal?: AbortSignal) {
    const res = await response("", {
      method: "POST", signal,
      body: JSON.stringify({ schema_version: "iterative-research-request-v1", ...request }),
    });
    return readProgress(res, onProgress, { after: -1, terminalRequired: true });
  },
  async resume(runId: string, after: number, onProgress: (data: IterativeProgress) => void, signal?: AbortSignal) {
    const res = await response(`/runs/${encodeURIComponent(runId)}/resume`, { method: "POST", signal });
    // A live lease is returned as a finite persisted-event snapshot. Recovery may
    // also finish with a terminal event, so both outcomes are valid here.
    return readProgress(res, onProgress, { after, expectedRunId: runId, terminalRequired: false });
  },
  async events(runId: string, after: number, onProgress: (data: IterativeProgress) => void, signal?: AbortSignal) {
    const res = await response(`/runs/${encodeURIComponent(runId)}/events?after=${after}`, { signal });
    return readProgress(res, onProgress, { after, expectedRunId: runId, terminalRequired: false });
  },
  async get(runId: string, signal?: AbortSignal): Promise<IterativeResearchDetail> {
    return (await response(`/runs/${encodeURIComponent(runId)}`, { signal })).json();
  },
  async cancel(runId: string, signal?: AbortSignal): Promise<IterativeRun> {
    return (await response(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST", signal })).json();
  },
};
