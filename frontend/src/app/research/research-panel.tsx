"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
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

export default function ResearchPanel({ initialSessionId, inspectionEnabled = false }: { initialSessionId?: string; inspectionEnabled?: boolean }) {
  const [question, setQuestion] = useState("");
  const [freshness, setFreshness] = useState<"general" | "current">("general");
  const [session, setSession] = useState<ResearchSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [inspection, setInspection] = useState<unknown>(null);
  const controller = useRef<AbortController | null>(null);
  const request = useRef<{ question: string; freshness: string; key: string } | null>(null);
  const active = useRef(false);

  useEffect(() => {
    if (!initialSessionId) return;
    const abort = new AbortController();
    researchApi.get(initialSessionId, abort.signal).then(value => {
      setSession(value); setQuestion(value.request.question); setFreshness(value.request.freshness);
    }).catch(() => { if (!abort.signal.aborted) setError("The saved research session could not be loaded."); });
    return () => abort.abort();
  }, [initialSessionId]);
  useEffect(() => () => controller.current?.abort(), []);

  async function refresh() {
    if (!session) return;
    try { setSession(await researchApi.get(session.id)); setError(""); }
    catch { setError("The saved session could not be refreshed. Please retry."); }
  }

  async function submit() {
    if (active.current || !question.trim()) return;
    active.current = true; setBusy(true); setError(""); setInspection(null);
    const abort = new AbortController(); controller.current = abort;
    if (!request.current || request.current.question !== question || request.current.freshness !== freshness) {
      request.current = { question, freshness, key: crypto.randomUUID() };
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
      <div className={styles.actions}>
        <button disabled={busy || !question.trim()} type="submit">{error ? "Retry request" : "Research"}</button>
        {busy && <button type="button" onClick={() => controller.current?.abort()}>Stop</button>}
        {session && <button disabled={busy} type="button" onClick={() => void refresh()}>Refresh saved session</button>}
        {error && !busy && <button type="button" onClick={() => { request.current = null; setSession(null); setError(""); setProgress(""); }}>Start a new request</button>}
      </div>
    </form>
    {progress && <p role="status">{progress}</p>}
    {error && <p role="alert">{error}</p>}
    {session && <section className={styles.result} aria-label="Research result">
      <h2>{resultExpired ? "Evidence expired" : stateNames[session.state]}</h2>
      {session.attempts.some(a => a.adapter === "fake") && <p>Synthetic demo: these sources do not describe the real world.</p>}
      {session.state === "completed" && !resultExpired && <>
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
