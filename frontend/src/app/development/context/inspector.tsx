"use client";

import { FormEvent, useState } from "react";

type Metadata = { id: string; role: string; characters: number; reason?: string };
type Report = {
  counter_kind: string;
  budget: { capacity: number; response_reserve: number; safety_margin: number; input_budget: number; selected_total: number } | null;
  selected: Metadata[];
  excluded: Metadata[];
  summary: { id: string; covers_through_message_id: string; source_message_ids: string[]; counter_kind: string; summary_token_count: number } | null;
  overflow: string | null;
  diagnostics: string[];
};

export default function ContextInspector({ enabled = false }: { enabled?: boolean }) {
  const [conversationId, setConversationId] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  if (!enabled) return null;

  async function inspect(event: FormEvent) {
    event.preventDefault();
    setPending(true); setError(null); setReport(null);
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(conversationId.trim())}/context`, { cache: "no-store" });
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
      <h3>Selected messages</h3><ul>{report.selected.map(m => <li key={m.id}>{m.role} {m.id} ({m.characters} characters)</li>)}</ul>
      <h3>Excluded messages</h3><ul>{report.excluded.map(m => <li key={m.id}>{m.role} {m.id}: {m.reason}</li>)}</ul>
      {report.diagnostics.length > 0 && <p>Diagnostics: {report.diagnostics.join(", ")}</p>}
    </section>}
  </main>;
}
