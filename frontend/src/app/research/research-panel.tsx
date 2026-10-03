"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { iterativeResearchApi, type IterativeProgress, type IterativeRun, type IterativeResearchDetail } from "../../lib/iterative-research-api";
import { researchApi, type ResearchSession } from "../../lib/research-api";
import styles from "./research.module.css";

const progressNames: Record<string, string> = {
  started: "Research started", planned: "Search planned", attempt: "Searching sources",
  evidence: "Checking source evidence", selected: "Preparing cited excerpts", terminal: "Research finished",
};
const stateNames = {
  pending: "Ready to research", running: "Research in progress", completed: "Cited evidence",
  insufficient: "Insufficient evidence", failed: "Research failed", expired: "Evidence expired",
};
const iterativeProgressNames: Record<string, string> = {
  planning: "Preparing the next research step", searching: "Searching allowed sources",
  extracting: "Checking source evidence", assessing: "Assessing evidence gaps",
  follow_up: "Preparing a focused follow-up", synthesizing: "Preparing cited excerpts",
  completed: "Research completed", incomplete: "Research incomplete",
  cancelled: "Research cancelled", failed: "Research failed",
};
const terminalRunStates = new Set(["completed", "insufficient", "failed", "cancelled"]);

export default function ResearchPanel({ initialSessionId, initialRunId, iterativeEnabled = false, inspectionEnabled = false }: { initialSessionId?: string; initialRunId?: string; iterativeEnabled?: boolean; inspectionEnabled?: boolean }) {
  const [question, setQuestion] = useState("");
  const [freshness, setFreshness] = useState<"general" | "current">("general");
  const [session, setSession] = useState<ResearchSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [inspection, setInspection] = useState<unknown>(null);
  const [iterativeMode, setIterativeMode] = useState(Boolean(initialRunId));
  const [iterativeRun, setIterativeRun] = useState<IterativeRun | null>(null);
  const [iterativeRunId, setIterativeRunId] = useState<string | null>(initialRunId ?? null);
  const [timeline, setTimeline] = useState<IterativeProgress[]>([]);
  const [reconnecting, setReconnecting] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const request = useRef<{ question: string; freshness: string; key: string; mode: "single" | "iterative" } | null>(null);
  const active = useRef(false);

  useEffect(() => {
    if (!initialSessionId) return;
    const abort = new AbortController();
    researchApi.get(initialSessionId, abort.signal).then(value => {
      setSession(value); setQuestion(value.request.question); setFreshness(value.request.freshness);
    }).catch(() => { if (!abort.signal.aborted) setError("The saved research session could not be loaded."); });
    return () => abort.abort();
  }, [initialSessionId]);
  const applyIterativeDetail = useCallback((detail: IterativeResearchDetail) => {
    setIterativeRun(detail.run);
    setSession(detail.session);
    setQuestion(detail.session.request.question);
    setFreshness(detail.session.request.freshness);
  }, []);

  const onIterativeProgress = useCallback((data: IterativeProgress) => {
    setIterativeRunId(data.run_id);
    setTimeline(previous => previous.some(item => item.sequence === data.sequence)
      ? previous
      : [...previous, data].sort((left, right) => left.sequence - right.sequence));
    setProgress(iterativeProgressNames[data.event_type] ?? "Research is in progress");
  }, []);

  useEffect(() => {
    if (!initialRunId) return;
    const abort = new AbortController();
    setIterativeMode(true);
    setIterativeRunId(initialRunId);
    iterativeResearchApi.get(initialRunId, abort.signal).then(async detail => {
      applyIterativeDetail(detail);
      const replay = await iterativeResearchApi.events(initialRunId, -1, onIterativeProgress, abort.signal);
      if (replay.runId) setIterativeRunId(replay.runId);
    }).catch(() => { if (!abort.signal.aborted) setError("The saved iterative research run could not be loaded."); });
    return () => abort.abort();
  }, [initialRunId, applyIterativeDetail, onIterativeProgress]);
  useEffect(() => () => controller.current?.abort(), []);

  async function refresh() {
    if (!session) return;
    try { setSession(await researchApi.get(session.id)); setError(""); }
    catch { setError("The saved session could not be refreshed. Please retry."); }
  }

  async function submit() {
    if (iterativeMode) return submitIterative();
    if (active.current || !question.trim()) return;
    active.current = true; setBusy(true); setError(""); setInspection(null);
    const abort = new AbortController(); controller.current = abort;
    if (!request.current || request.current.question !== question || request.current.freshness !== freshness || request.current.mode !== "single") {
      request.current = { question, freshness, key: crypto.randomUUID(), mode: "single" };
    }
    let saved: ResearchSession | null = null;
    try {
      saved = await researchApi.create(question, freshness, request.current.key, abort.signal);
      setSession(saved);
      window.history.replaceState(null, "", `/research?session=${encodeURIComponent(saved.id)}`);
      await researchApi.run(saved.id, event => setProgress(progressNames[event]), abort.signal);
      const detail = await researchApi.get(saved.id, abort.signal);
      setSession(detail);
      if (detail.state !== "pending" && detail.state !== "running") request.current = null;
    } catch {
      setError(abort.signal.aborted ? "Research stopped. Refresh the saved session to check its status." : "The connection was interrupted. Retry the request or refresh the saved session.");
      if (saved && !abort.signal.aborted) {
        try { setSession(await researchApi.get(saved.id)); } catch { /* Keep its ID for recovery. */ }
      }
    } finally {
      active.current = false; setBusy(false); controller.current = null;
    }
  }

  async function submitIterative() {
    if (active.current || !question.trim()) return;
    active.current = true; setBusy(true); setError(""); setInspection(null);
    setIterativeRun(null); setIterativeRunId(null); setTimeline([]); setProgress("Preparing the next research step");
    const abort = new AbortController(); controller.current = abort;
    if (!request.current || request.current.question !== question || request.current.freshness !== freshness || request.current.mode !== "iterative") {
      request.current = { question, freshness, key: crypto.randomUUID(), mode: "iterative" };
    }
    let savedRunId: string | null = null;
    try {
      const started = await iterativeResearchApi.start({
        question, freshness, idempotency_key: request.current.key,
      }, data => {
        savedRunId = data.run_id;
        onIterativeProgress(data);
      }, abort.signal);
      if (started.runId) {
        savedRunId = started.runId;
        setIterativeRunId(started.runId);
        window.history.replaceState(null, "", `/research?run=${encodeURIComponent(started.runId)}`);
        const detail = await iterativeResearchApi.get(started.runId, abort.signal);
        applyIterativeDetail(detail);
        if (terminalRunStates.has(detail.run.state)) request.current = null;
      }
    } catch {
      setError(abort.signal.aborted
        ? "The connection closed. Reconnect to the saved run to read its persisted status."
        : "Research was interrupted. Reconnect to the saved run or retry with the same request key.");
      if (savedRunId) {
        setIterativeRunId(savedRunId);
        try { applyIterativeDetail(await iterativeResearchApi.get(savedRunId)); } catch { /* Keep the saved run ID for recovery. */ }
      }
    } finally {
      active.current = false; setBusy(false); controller.current = null;
    }
  }

  async function refreshIterative() {
    if (!iterativeRunId || active.current) return;
    setReconnecting(true); setError("");
    const abort = new AbortController(); controller.current = abort;
    try {
      const detail = await iterativeResearchApi.get(iterativeRunId, abort.signal);
      applyIterativeDetail(detail);
      const after = timeline.reduce((last, item) => Math.max(last, item.sequence), -1);
      await iterativeResearchApi.events(iterativeRunId, after, onIterativeProgress, abort.signal);
      applyIterativeDetail(await iterativeResearchApi.get(iterativeRunId, abort.signal));
    } catch {
      if (!abort.signal.aborted) setError("Persisted research progress could not be refreshed.");
    } finally {
      setReconnecting(false); controller.current = null;
    }
  }

  async function resumeIterative() {
    if (!iterativeRunId || active.current) return;
    active.current = true; setBusy(true); setError("");
    const abort = new AbortController(); controller.current = abort;
    try {
      const after = timeline.reduce((last, item) => Math.max(last, item.sequence), -1);
      await iterativeResearchApi.resume(iterativeRunId, after, onIterativeProgress, abort.signal);
      applyIterativeDetail(await iterativeResearchApi.get(iterativeRunId, abort.signal));
    } catch {
      if (!abort.signal.aborted) setError("The saved run could not resume safely. Its recorded status remains available.");
    } finally {
      active.current = false; setBusy(false); controller.current = null;
    }
  }

  async function cancelIterative() {
    if (!iterativeRunId || iterativeRun && terminalRunStates.has(iterativeRun.state)) return;
    setError("");
    try {
      await iterativeResearchApi.cancel(iterativeRunId);
      applyIterativeDetail(await iterativeResearchApi.get(iterativeRunId));
    } catch {
      setError("The run could not be cancelled. Refresh to check its persisted status.");
    }
  }

  // A result can expire while the page is open. Recheck at its deadline and hide locally.
  const [expiredLocally, setExpiredLocally] = useState(false);
  useEffect(() => {
    const remaining = session ? Date.parse(session.expires_at) - Date.now() : Infinity;
    const expired = session?.state === "completed" && remaining <= 0;
    setExpiredLocally(Boolean(expired));
    if (session?.state !== "completed" || expired) return;
    const timer = setTimeout(() => setExpiredLocally(true), Math.min(remaining, 2147483647));
    return () => clearTimeout(timer);
  }, [session]);

  const resultExpired = expiredLocally || Boolean(session?.state === "completed" && Date.parse(session.expires_at) <= Date.now());

  return <main className={styles.page}>
    <Link href="/">Back to chat</Link>
    <h1>Research</h1>
    <p>Explore source excerpts with citations. Observations may be incomplete or disagree.</p>
    <form className={styles.form} onSubmit={event => { event.preventDefault(); void submit(); }}>
      <label htmlFor="research-question">Research question</label>
      <textarea id="research-question" maxLength={500} value={question} disabled={busy} onChange={e => setQuestion(e.target.value)} required rows={4} />
      <label htmlFor="research-freshness">Freshness</label>
      <select id="research-freshness" value={freshness} disabled={busy} onChange={e => setFreshness(e.target.value as "general" | "current")}>
        <option value="general">General — expires within 24 hours</option>
        <option value="current">Current — expires within 1 hour</option>
      </select>
      {iterativeEnabled && <>
        <label htmlFor="research-mode">Research mode</label>
        <select id="research-mode" value={iterativeMode ? "iterative" : "single"} disabled={busy} onChange={e => setIterativeMode(e.target.value === "iterative")}>
          <option value="single">Single pass</option>
          <option value="iterative">Bounded follow-up research</option>
        </select>
      </>}
      <div className={styles.actions}>
        <button disabled={busy || !question.trim()} type="submit">{error ? "Retry request" : iterativeMode ? "Start bounded research" : "Research"}</button>
        {busy && !iterativeMode && <button type="button" onClick={() => controller.current?.abort()}>Stop</button>}
        {iterativeMode && iterativeRunId && (!iterativeRun || !terminalRunStates.has(iterativeRun.state)) && <button type="button" onClick={() => void cancelIterative()}>Cancel research</button>}
        {session && !iterativeMode && <button disabled={busy} type="button" onClick={() => void refresh()}>Refresh saved session</button>}
        {iterativeMode && iterativeRunId && <>
          <button disabled={busy || reconnecting} type="button" onClick={() => void refreshIterative()}>{reconnecting ? "Reconnecting…" : "Reconnect timeline"}</button>
          {iterativeRun && !terminalRunStates.has(iterativeRun.state) && <button disabled={busy} type="button" onClick={() => void resumeIterative()}>Resume saved run</button>}
        </>}
        {error && !busy && <button type="button" onClick={() => { request.current = null; setSession(null); setIterativeRun(null); setIterativeRunId(null); setTimeline([]); setError(""); setProgress(""); }}>Start a new request</button>}
      </div>
    </form>
    {progress && <p role="status">{progress}</p>}
    {error && <p role="alert">{error}</p>}
    {iterativeMode && iterativeRun && <section className={styles.result} aria-label="Iterative research status">
      <h2>{iterativeRun.state === "completed" ? "Sufficient cited result" : iterativeRun.state === "insufficient" ? "Incomplete research" : iterativeRun.state === "cancelled" ? "Research cancelled" : iterativeRun.state === "failed" ? "Research failed" : "Research in progress"}</h2>
      <p>Iteration {iterativeRun.usage.iterations} of {iterativeRun.budget.max_iterations}; {iterativeRun.usage.queries} of {iterativeRun.budget.max_queries} queries; {iterativeRun.usage.sources} of {iterativeRun.budget.max_sources} sources.</p>
      <p>Stop reason: {iterativeRun.terminal_reason ?? "still running"}. Decision status: {iterativeRun.decision_state ?? "not requested"}.</p>
      {iterativeRun.gaps.some(gap => gap.status !== "resolved") && <>
        <h3>Unresolved evidence gaps</h3>
        <ul>{iterativeRun.gaps.filter(gap => gap.status !== "resolved").map((gap, index) => <li key={`${gap.gap_class}-${gap.reason_code}-${index}`}>
          {gap.gap_class.replaceAll("_", " ")} — {gap.status}{gap.required ? " (required)" : ""}
        </li>)}</ul>
      </>}
      {timeline.length > 0 && <>
        <h3>Research timeline</h3>
        <ol aria-label="Research timeline">{timeline.map(event => <li key={event.sequence}>
          {iterativeProgressNames[event.event_type] ?? "Research status updated"}
          {event.iteration !== undefined ? ` · iteration ${event.iteration + 1}` : ""}
          {event.query_count !== undefined ? ` · ${event.query_count} queries` : ""}
          {event.source_count !== undefined ? ` · ${event.source_count} sources` : ""}
          {event.gap_count !== undefined ? ` · ${event.gap_count} open gaps` : ""}
        </li>)}</ol>
      </>}
      {iterativeRun.decision_ids.length > 0 && <p>Phase 6 decision snapshots: {iterativeRun.decision_ids.length}</p>}
    </section>}
    {session && <section className={styles.result} aria-label="Research result">
      <h2>{resultExpired ? "Evidence expired" : iterativeMode && iterativeRun?.state === "insufficient" ? "Partial cited evidence" : stateNames[session.state]}</h2>
      {session.attempts.some(a => a.adapter === "fake") && <p>Synthetic demo: these sources do not describe the real world.</p>}
      {session.state === "completed" && !resultExpired && <>
        {iterativeMode && iterativeRun?.state === "insufficient" && <p>This supported excerpt is partial. The unresolved gaps above remain visible.</p>}
        <p className={styles.answer}>{session.answer}</p>
        <h3>Sources</h3>
        <ol>{session.citations.map(c => <li key={c.number}>
          <a href={c.url} target="_blank" rel="noopener noreferrer">{c.title || c.url}</a>
          <small>Observed {new Date(c.observed_at).toLocaleString()}; expires {new Date(c.expires_at).toLocaleString()}</small>
        </li>)}</ol>
      </>}
      {(session.state === "expired" || resultExpired) && <p>Start new research to obtain current observations. This saved answer is no longer eligible.</p>}
      {session.state === "insufficient" && <p>Available sources could not support a complete, valid cited answer. Try a more specific question.</p>}
      {session.state === "failed" && <p>The investigation could not finish. Start a new request to try again.</p>}
      <p><Link href={`/research?session=${encodeURIComponent(session.id)}`}>Reopen this research session</Link></p>
      {inspectionEnabled && <button type="button" onClick={() => { void researchApi.inspect(session.id).then(setInspection).catch(() => setError("Inspection is unavailable.")); }}>Inspect research</button>}
      {inspection !== null && <pre className={styles.inspection}>{JSON.stringify(inspection, null, 2)}</pre>}
    </section>}
  </main>;
}
