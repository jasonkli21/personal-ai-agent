"use client";

import { authenticatedFetch } from "../../../lib/auth";
import { FormEvent, useState } from "react";

type Metadata = { id: string; role: string; characters: number; reason?: string };
type TraceDecision = { stage: string; source_id: string | null; source_id_hash: string | null; item_id_hash: string | null; provider_id: string | null; source_version: string | null; operation: string | null; category: string; disposition: string; fields: string[]; field_count: number; fields_truncated: boolean; authority: string | null; sensitivity: string | null; token_count: number | null; reason: string | null };
type ActualBuildTrace = { request_id: string; conversation_id: string; user_message_id: string; assistant_message_id: string; recorded_at: string; build_schema_version: string; policy_version: string; planner_version: string | null; counter_kind: string; counter_version: string; global_input_tokens: number; actual_input_tokens: number; effective_sensitivity: string; requested_sources: { provider_id: string; operation: string; fields: string[]; field_count: number; fields_truncated: boolean; max_results: number; max_bytes: number; max_tokens: number | null; required: boolean }[]; requested_source_count: number; requested_sources_truncated: boolean; planning_decisions: TraceDecision[]; planning_decision_count: number; planning_decisions_truncated: boolean; source_decisions: TraceDecision[]; source_decision_count: number; source_decisions_truncated: boolean; source_budgets: { category: string; token_limit: number; token_count: number; counter_kind: string; injected_item_count: number; omitted_item_count: number }[]; provider_failures: { provider_id: string; operation: string; reason: string }[]; provider_failure_count: number; provider_failures_truncated: boolean; selected_message_ids: string[]; selected_message_count: number; selected_messages_truncated: boolean; excluded_messages: { message_id: string; reason: string }[]; excluded_message_count: number; excluded_messages_truncated: boolean };
type MemorySource = { memory_id: string; conversation_id: string; turn_id: string; message_ids: string[] };
type MemoryEvent = { id: string; type: string; reason_code: string; policy_version: string; occurred_at: string; related_memory_ids: string[] };
type Lifecycle = { status: string; state_version: number; retrieval_count: number; importance: number | null; superseded_by_memory_id: string | null; consolidated_into_memory_ids: string[]; last_retrieved_at: string | null };
type Report = {
  inspection_request_id: string | null;
  trace_state: "available" | "manifest_missing" | "historical_schema_unsupported";
  trace_missing_reason: string | null;
  actual_build_trace: ActualBuildTrace | null;
  memory?: { mode: string; tokens: number; requested_variant: string | null; applied_variant: string | null; policy_version: string | null; lifecycle_event_ids: string[]; records: { id: string; type: string; source_conversation_id: string | null; source_message_ids: string[]; source_records: MemorySource[]; effective_at: string; selected: boolean; selection_kind: string; reason: string | null; similarity: number | null; score: number | null; score_reason: string | null; score_components: { importance: number | null; recency: number | null; frequency: number | null; confidence: number | null } | null; lifecycle?: Lifecycle; events?: MemoryEvent[]; estimated_tokens: number }[] };
  counter_kind: string;
  budget: { capacity: number; response_reserve: number; safety_margin: number; input_budget: number; selected_total: number } | null;
  selected: Metadata[];
  excluded: Metadata[];
  summary: { id: string; covers_through_message_id: string; source_message_ids: string[]; counter_kind: string; summary_token_count: number } | null;
  overflow: string | null;
  diagnostics: string[];
};

export default function ContextInspector({ enabled = false, memoryEnabled = false, lifecycleEnabled = false }: { enabled?: boolean; memoryEnabled?: boolean; lifecycleEnabled?: boolean }) {
  const [conversationId, setConversationId] = useState("");
  const [memoryIds, setMemoryIds] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [inspectionRequestId, setInspectionRequestId] = useState<string | null>(null);
  if (!enabled) return null;

  async function inspect(event: FormEvent) {
    event.preventDefault();
    setPending(true); setError(null); setReport(null); setInspectionRequestId(null);
    try {
      const search = new URLSearchParams();
      memoryIds.split(",").map(id => id.trim()).filter(Boolean).forEach(id => search.append("memory_ids", id));
      const suffix = search.size ? `?${search.toString()}` : "";
      const requestId = crypto.randomUUID();
      const response = await authenticatedFetch(`/api/conversations/${encodeURIComponent(conversationId.trim())}/context${suffix}`, {
        cache: "no-store",
        headers: { "X-Application-ID": "personal_ai", "X-Request-ID": requestId },
      });
      if (!response.ok) throw new Error("Context inspection is unavailable for this conversation.");
      setInspectionRequestId(response.headers.get("X-Request-ID") ?? requestId);
      setReport(await response.json() as Report);
    } catch { setError("Context inspection is unavailable for this conversation."); }
    finally { setPending(false); }
  }

  return <main style={{ maxWidth: 900, margin: "2rem auto", padding: "1rem" }}>
    <h1>Development context inspector</h1>
    <p>Read-only planning estimate for the latest user turn. This view never calls a model or creates a summary.</p>
    <form onSubmit={inspect}><label htmlFor="conversation-id">Conversation ID</label>{" "}
      <input id="conversation-id" value={conversationId} onChange={e => setConversationId(e.target.value)} />{" "}
      {(memoryEnabled || lifecycleEnabled) && <><label htmlFor="memory-ids">Memory IDs (optional, comma separated)</label>{" "}
      <input id="memory-ids" value={memoryIds} onChange={e => setMemoryIds(e.target.value)} />{" "}</>}
      <button disabled={pending || !conversationId.trim()}>{pending ? "Inspecting…" : "Inspect context"}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {report && <section aria-live="polite">
      <h2>Context inspection</h2>
      <p>Inspection request ID: {inspectionRequestId ?? report.inspection_request_id ?? "unavailable"}.</p>
      {report.actual_build_trace ? <section>
        <h3>Retained actual build</h3>
        <p>Generation request ID: {report.actual_build_trace.request_id}. Turn {report.actual_build_trace.user_message_id} → {report.actual_build_trace.assistant_message_id}.</p>
        <p>Schema {report.actual_build_trace.build_schema_version}; policy {report.actual_build_trace.policy_version}; planner {report.actual_build_trace.planner_version ?? "not used"}.</p>
        <p>{report.actual_build_trace.actual_input_tokens} / {report.actual_build_trace.global_input_tokens} {report.actual_build_trace.counter_kind} tokens; counter version {report.actual_build_trace.counter_version}; effective sensitivity {report.actual_build_trace.effective_sensitivity}.</p>
        <h4>Requested sources</h4>
        {report.actual_build_trace.requested_sources.length ? <><ul>{report.actual_build_trace.requested_sources.map((source, index) => <li key={`${source.provider_id}:${source.operation}:${index}`}>{source.provider_id}.{source.operation}; fields {source.fields.join(", ") || "none"}{source.fields_truncated ? ` (showing ${source.fields.length} of ${source.field_count})` : ""}; limits {source.max_results} results, {source.max_bytes} bytes, {source.max_tokens ?? "no operation token limit"} tokens{source.required ? "; required" : ""}.</li>)}</ul>{report.actual_build_trace.requested_sources_truncated && <p>Showing {report.actual_build_trace.requested_sources.length} of {report.actual_build_trace.requested_source_count} requested source operations.</p>}</> : <p>No provider source operations were requested.</p>}
        {!!report.actual_build_trace.planning_decisions.length && <><h4>Planning decisions</h4><ul>{report.actual_build_trace.planning_decisions.map((decision, index) => <li key={`${decision.source_id ?? decision.provider_id ?? decision.category}:${index}`}>{decision.category} {decision.source_id ?? decision.provider_id ?? "source"}: {decision.disposition}{decision.reason ? ` (${decision.reason})` : ""}; fields {decision.fields.join(", ") || "none"}{decision.fields_truncated ? ` (showing ${decision.fields.length} of ${decision.field_count})` : ""}.</li>)}</ul>{report.actual_build_trace.planning_decisions_truncated && <p>Showing {report.actual_build_trace.planning_decisions.length} of {report.actual_build_trace.planning_decision_count} planning decisions.</p>}</>}
        <h4>Built source decisions</h4>
        {report.actual_build_trace.source_decisions.length ? <ul>{report.actual_build_trace.source_decisions.map((decision, index) => <li key={`${decision.item_id_hash ?? decision.source_id_hash ?? index}:${index}`}>{decision.category} {decision.provider_id ?? "source"} ({decision.source_id_hash ?? decision.source_id ?? "identifier unavailable"}){decision.item_id_hash ? ` / item ${decision.item_id_hash}` : ""}{decision.source_version ? `; source version ${decision.source_version}` : ""}: {decision.disposition}; {decision.authority ?? "authority unknown"} authority, {decision.sensitivity ?? "sensitivity unknown"} sensitivity, {decision.token_count ?? "unavailable"} tokens{decision.reason ? ` (${decision.reason})` : ""}.</li>)}</ul> : <p>No source items were built.</p>}
        {report.actual_build_trace.source_decisions_truncated && <p>Showing {report.actual_build_trace.source_decisions.length} of {report.actual_build_trace.source_decision_count} source decisions; the trace is bounded.</p>}
        <h4>Per-source budgets</h4><ul>{report.actual_build_trace.source_budgets.map(source => <li key={source.category}>{source.category}: {source.token_count} / {source.token_limit} {source.counter_kind} tokens; {source.injected_item_count} included, {source.omitted_item_count} omitted.</li>)}</ul>
        {!!report.actual_build_trace.provider_failures.length && <><h4>Provider outcomes</h4><ul>{report.actual_build_trace.provider_failures.map((failure, index) => <li key={`${failure.provider_id}:${failure.operation}:${index}`}>{failure.provider_id}.{failure.operation}: {failure.reason}.</li>)}</ul>{report.actual_build_trace.provider_failures_truncated && <p>Showing {report.actual_build_trace.provider_failures.length} of {report.actual_build_trace.provider_failure_count} provider failures.</p>}</>}
        <p>Selected conversation messages: {report.actual_build_trace.selected_message_count}{report.actual_build_trace.selected_messages_truncated ? ` (first ${report.actual_build_trace.selected_message_ids.length} retained)` : ""}.</p>
        {!!report.actual_build_trace.excluded_messages.length && <><p>Excluded messages</p><ul>{report.actual_build_trace.excluded_messages.map(item => <li key={item.message_id}>{item.message_id}: {item.reason}</li>)}</ul></>}
        {report.actual_build_trace.excluded_messages_truncated && <p>Excluded-message list is bounded ({report.actual_build_trace.excluded_message_count} total).</p>}
      </section> : <p>{report.trace_state === "historical_schema_unsupported" ? "A retained actual-build manifest uses an unsupported historical schema; it cannot be displayed." : "No retained actual-build manifest matches the latest user turn."} The view below is a current estimate and may differ from what an earlier request used.</p>}
      <h3>Estimated current view</h3>
      <p>Counter: {report.counter_kind}. Estimates can differ from provider-authoritative counts used for model requests.</p>
      {report.overflow && <p role="alert">Rejected: {report.overflow}. Edit the newest message to fit.</p>}
      {report.budget && <dl>
        <dt>Context capacity</dt><dd>{report.budget.capacity}</dd>
        <dt>Response reserve</dt><dd>{report.budget.response_reserve}</dd>
        <dt>Safety margin</dt><dd>{report.budget.safety_margin}</dd>
        <dt>Input budget</dt><dd>{report.budget.input_budget}</dd>
        <dt>Selected input</dt><dd>{report.budget.selected_total}</dd>
      </dl>}
      <p>{report.summary ? `Working summary ${report.summary.id}, covering through ${report.summary.covers_through_message_id} (${report.summary.source_message_ids.length} source messages; ${report.summary.summary_token_count} ${report.summary.counter_kind} tokens).` : "No compatible working summary selected."}</p>
      {report.memory && <section><h3>Historical personal memory</h3>
        <p>{report.memory.mode}. Variant requested/applied: {report.memory.requested_variant ?? "n/a"}/{report.memory.applied_variant ?? "n/a"}; scoring policy: {report.memory.policy_version ?? "n/a"}. Selected memory block: {report.memory.tokens} estimated tokens.</p>
        <ul>{report.memory.records.map(m => <li key={m.id}>
          <p>{m.type} {m.id}: {m.selected ? "fit estimate selected" : `excluded (${m.reason})`}; effective {m.effective_at}; {m.estimated_tokens} estimated content tokens.</p>
          <p>Similarity: {m.similarity ?? "unavailable"}; score: {m.score ?? "unavailable"} ({m.score_reason ?? "no scoring metadata"}). Components: {m.score_components ? `importance ${m.score_components.importance ?? "n/a"}, recency ${m.score_components.recency?.toFixed(3) ?? "n/a"}, frequency ${m.score_components.frequency ?? "n/a"}, confidence ${m.score_components.confidence ?? "n/a"}` : "unavailable"}.</p>
          {m.source_records?.length > 0 && <p>Provenance: {m.source_records.map(source => `${source.memory_id} from ${source.conversation_id}, messages ${source.message_ids.join(", ")}`).join("; ")}.</p>}
          {m.lifecycle && <p>Lifecycle: {m.lifecycle.status}, version {m.lifecycle.state_version}, retrievals {m.lifecycle.retrieval_count}, importance {m.lifecycle.importance ?? "unset"}; superseded by {m.lifecycle.superseded_by_memory_id ?? "none"}; consolidated into {m.lifecycle.consolidated_into_memory_ids.join(", ") || "none"}; last retrieved {m.lifecycle.last_retrieved_at ?? "never"}.</p>}
          {!!m.events?.length && <ul>{m.events.map(event => <li key={event.id}>{event.type} ({event.reason_code}, {event.policy_version}) at {event.occurred_at}; related IDs {event.related_memory_ids.join(", ") || "none"}.</li>)}</ul>}
        </li>)}</ul>
      </section>}
      <h3>Selected messages</h3><ul>{report.selected.map(m => <li key={m.id}>{m.role} {m.id} ({m.characters} characters)</li>)}</ul>
      <h3>Excluded messages</h3><ul>{report.excluded.map(m => <li key={m.id}>{m.role} {m.id}: {m.reason}</li>)}</ul>
      {report.diagnostics.length > 0 && <p>Diagnostics: {report.diagnostics.join(", ")}</p>}
    </section>}
  </main>;
}
