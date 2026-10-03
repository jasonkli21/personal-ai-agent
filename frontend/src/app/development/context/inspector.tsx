"use client";

import { authenticatedFetch } from "../../../lib/auth";
import { FormEvent, useState } from "react";

type Metadata = { id: string; role: string; characters: number; reason?: string };
type MemorySource = { memory_id: string; conversation_id: string; turn_id: string; message_ids: string[] };
type MemoryEvent = { id: string; type: string; reason_code: string; policy_version: string; occurred_at: string; related_memory_ids: string[] };
type Lifecycle = { status: string; state_version: number; retrieval_count: number; importance: number | null; superseded_by_memory_id: string | null; consolidated_into_memory_ids: string[]; last_retrieved_at: string | null };
type Report = {
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
  if (!enabled) return null;

  async function inspect(event: FormEvent) {
    event.preventDefault();
    setPending(true); setError(null); setReport(null);
    try {
      const search = new URLSearchParams();
      memoryIds.split(",").map(id => id.trim()).filter(Boolean).forEach(id => search.append("memory_ids", id));
      const suffix = search.size ? `?${search.toString()}` : "";
      const response = await authenticatedFetch(`/api/conversations/${encodeURIComponent(conversationId.trim())}/context${suffix}`, { cache: "no-store" });
      if (!response.ok) throw new Error("Context inspection is unavailable for this conversation.");
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
      <h2>Selection report</h2>
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
