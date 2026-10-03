import { ApiError } from "./api";
import type { ResearchSession } from "./research-api";
import { authenticatedFetch } from "./auth";

export type IterativeRunState =
  | "pending" | "assessing" | "planning" | "searching" | "extracting" | "synthesizing"
  | "completed" | "insufficient" | "failed" | "cancelled";
export type IterativeRun = {
  schema_version: "iterative-research-v1";
  id: string;
  session_id: string;
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
  gaps: { semantic_key: string; gap_class: string; required: boolean; status: "open" | "resolved" | "unresolvable"; reason_code: string }[];
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
const stopReasons = new Set([
  "sufficient", "iteration_budget_exhausted", "query_budget_exhausted", "source_budget_exhausted",
  "token_budget_exhausted", "provider_cost_budget_exhausted", "elapsed_budget_exhausted",
  "no_productive_query", "provider_error", "synthesis_error", "side_effect_uncertain",
  "cancelled", "evidence_insufficient",
]);
const gapClasses = new Set([
  "initial_coverage", "required_fact_missing", "evidence_stale", "source_conflict",
  "candidate_coverage", "identity_ambiguity", "citation_support",
]);
const gapReasons = new Set([
  "initial_coverage", "missing_required_claim", "expired_evidence",
  "competing_source_observations", "candidate_not_covered", "identity_review",
  "citation_unavailable", "unsupported_query_template",
]);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function uuid(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}
function boundedInt(value: unknown, maximum: number, minimum = 0): value is number {
  return Number.isSafeInteger(value) && (value as number) >= minimum && (value as number) <= maximum;
}
function decimal(value: unknown): value is string {
  return typeof value === "string" && /^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value);
}
function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}
function safeLink(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 2048) return false;
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) && !!parsed.hostname && !parsed.username && !parsed.password;
  } catch { return false; }
}

function validProgress(value: unknown): value is IterativeProgress {
  if (!record(value)) return false;
  const keys = new Set([
    "schema_version", "run_id", "session_id", "sequence", "event_type", "state", "iteration",
    "query_count", "source_count", "evidence_count", "gap_count", "citation_count", "stop_reason", "decision_state",
  ]);
  if (Object.keys(value).some(key => !keys.has(key))) return false;
  if (value.schema_version !== "iterative-research-v1" || !uuid(value.run_id) || !uuid(value.session_id) ||
      !boundedInt(value.sequence, 127) || typeof value.event_type !== "string" || !eventTypes.has(value.event_type)) return false;
  if (value.state !== undefined && (typeof value.state !== "string" || !["pending", "assessing", "planning", "searching", "extracting", "synthesizing", "completed", "insufficient", "failed", "cancelled"].includes(value.state))) return false;
  if (value.iteration !== undefined && !boundedInt(value.iteration, 4)) return false;
  if (value.query_count !== undefined && !boundedInt(value.query_count, 3)) return false;
  if (value.source_count !== undefined && !boundedInt(value.source_count, 12)) return false;
  if (value.evidence_count !== undefined && !boundedInt(value.evidence_count, 12)) return false;
  if (value.gap_count !== undefined && !boundedInt(value.gap_count, 160)) return false;
  if (value.citation_count !== undefined && !boundedInt(value.citation_count, 144)) return false;
  if (value.stop_reason !== undefined && (typeof value.stop_reason !== "string" || !stopReasons.has(value.stop_reason))) return false;
  if (value.decision_state !== undefined && value.decision_state !== null &&
      !["recommended", "eligible_unranked", "research_needed", "no_verified_match"].includes(String(value.decision_state))) return false;
  return true;
}

const runStates = new Set<IterativeRunState>(["pending", "assessing", "planning", "searching", "extracting", "synthesizing", "completed", "insufficient", "failed", "cancelled"]);
function validSession(value: unknown): value is ResearchSession {
  if (!record(value) || value.schema_version !== "research-v1" || !uuid(value.id) ||
      !["pending", "running", "completed", "insufficient", "failed", "expired"].includes(String(value.state)) ||
      !record(value.request) || typeof value.request.question !== "string" || value.request.question.length > 500 ||
      !["general", "current"].includes(String(value.request.freshness)) || !uuid(value.request.idempotency_key) ||
      !(value.answer === null || typeof value.answer === "string" && value.answer.length <= 20000) ||
      !(value.failure_code === null || typeof value.failure_code === "string" && value.failure_code.length <= 80) ||
      !timestamp(value.expires_at) || !Array.isArray(value.citations) || value.citations.length > 144 ||
      !Array.isArray(value.attempts) || value.attempts.length > 18) return false;
  const numbers = new Set<number>();
  for (const citation of value.citations) {
    if (!record(citation) || !boundedInt(citation.number, 144, 1) || numbers.has(citation.number) ||
        !uuid(citation.evidence_id) || !uuid(citation.source_observation_id) || !safeLink(citation.url) ||
        !(citation.title === null || typeof citation.title === "string" && citation.title.length <= 300) ||
        !timestamp(citation.observed_at) || !timestamp(citation.expires_at)) return false;
    numbers.add(citation.number);
  }
  return value.attempts.every(item => record(item) && ["fake", "brave"].includes(String(item.adapter)));
}

function validRun(value: unknown): value is IterativeRun {
  if (!record(value) || value.schema_version !== "iterative-research-v1" || !uuid(value.id) || !uuid(value.session_id) ||
      typeof value.state !== "string" || !runStates.has(value.state as IterativeRunState) ||
      !(value.terminal_reason === null || typeof value.terminal_reason === "string" && stopReasons.has(value.terminal_reason)) ||
      !boundedInt(value.current_iteration, 5) || !Array.isArray(value.decision_ids) || value.decision_ids.length > 6 ||
      !value.decision_ids.every(uuid) || !record(value.budget) || !record(value.usage) ||
      !Array.isArray(value.gaps) || value.gaps.length > 512 || !Array.isArray(value.events) || value.events.length > 128) return false;
  const b = value.budget, u = value.usage;
  if (!boundedInt(b.max_iterations, 5, 1) || !boundedInt(b.max_queries, 3, 1) || !boundedInt(b.max_sources, 12, 1) ||
      !boundedInt(b.max_elapsed_seconds, 300, 1) || !boundedInt(b.max_tokens, 32768, 512) ||
      !decimal(b.max_provider_cost_usd) || !Array.isArray(b.allowed_domains) || b.allowed_domains.length < 1 || b.allowed_domains.length > 12 ||
      !b.allowed_domains.every(domain => typeof domain === "string" && /^[a-z0-9.-]+$/.test(domain)) ||
      !boundedInt(u.iterations, b.max_iterations) || !boundedInt(u.queries, b.max_queries) || !boundedInt(u.sources, b.max_sources) ||
      !boundedInt(u.tokens, b.max_tokens) || !decimal(u.provider_cost_usd) || !decimal(u.elapsed_seconds) ||
      !boundedInt(u.allowed_domains, b.allowed_domains.length)) return false;
  if (value.decision_state !== null && !["recommended", "eligible_unranked", "research_needed", "no_verified_match"].includes(String(value.decision_state))) return false;
  if (!value.gaps.every(gap => record(gap) && typeof gap.semantic_key === "string" && gap.semantic_key.length > 0 && gap.semantic_key.length <= 300 &&
      gapClasses.has(String(gap.gap_class)) && typeof gap.required === "boolean" &&
      ["open", "resolved", "unresolvable"].includes(String(gap.status)) && gapReasons.has(String(gap.reason_code)))) return false;
  return value.events.every((event, index) => record(event) && event.sequence === index && eventTypes.has(String(event.event_type)) && timestamp(event.occurred_at));
}

async function response(path: string, init?: RequestInit) {
  const res = await authenticatedFetch(`/api/research/iterative${path}`, {
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
        let parsed: unknown;
        try { parsed = JSON.parse(dataText); } catch { throw new ApiError("Invalid iterative research progress."); }
        if (!validProgress(parsed)) throw new ApiError("Invalid iterative research progress.");
        const data = parsed;
        if (!eventTypes.has(eventType) ||
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
        if (buffer.trim() !== "") throw new ApiError("Incomplete iterative research progress frame.");
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
    const res = await response(`/runs/${encodeURIComponent(runId)}/resume`, {
      method: "POST", signal, headers: { "Last-Event-ID": String(after) },
    });
    // A live lease is returned as a finite persisted-event snapshot. Recovery may
    // also finish with a terminal event, so both outcomes are valid here.
    return readProgress(res, onProgress, { after, expectedRunId: runId, terminalRequired: false });
  },
  async events(runId: string, after: number, onProgress: (data: IterativeProgress) => void, signal?: AbortSignal) {
    const res = await response(`/runs/${encodeURIComponent(runId)}/events?after=${after}`, { signal });
    return readProgress(res, onProgress, { after, expectedRunId: runId, terminalRequired: false });
  },
  async get(runId: string, signal?: AbortSignal): Promise<IterativeResearchDetail> {
    const value: unknown = await (await response(`/runs/${encodeURIComponent(runId)}`, { signal })).json();
    if (!record(value) || !validRun(value.run) || !validSession(value.session) ||
        value.run.id !== runId || value.run.session_id !== value.session.id) {
      throw new ApiError("Invalid saved research response.");
    }
    return value as IterativeResearchDetail;
  },
  async cancel(runId: string, signal?: AbortSignal): Promise<IterativeRun> {
    const value: unknown = await (await response(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST", signal })).json();
    if (!validRun(value) || value.id !== runId) throw new ApiError("Invalid saved research response.");
    return value;
  },
};
