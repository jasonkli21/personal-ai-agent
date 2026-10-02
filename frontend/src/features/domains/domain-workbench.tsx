"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { ApiError } from "../../lib/api";
import {
  domainApi,
  type ComparisonCell,
  type ComparisonRow,
  type DomainComparisonResult,
  type DomainFixture,
  type DomainId,
} from "../../lib/domain-api";
import styles from "./domain-workbench.module.css";

const statusLabels: Record<ComparisonCell["status"], string> = {
  verified: "Verified",
  conflicting: "Conflict",
  stale: "Expired",
  missing: "Missing",
  unverified: "Unverified",
  derived: "Derived",
};

function stateLabel(state: DomainComparisonResult["comparison"]["state"]) {
  return ({
    recommended: "Recommended from the available evidence",
    eligible_unranked: "Eligible, but there is not enough evidence to rank",
    research_needed: "More current evidence is needed",
    no_verified_match: "No verified match meets the requirements",
  } as const)[state];
}

function readable(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(readable).join(", ");
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    if (object.kind === "money") return `${object.amount} ${object.currency}`;
    if (object.kind === "location") return `${object.latitude}, ${object.longitude}`;
    if (object.kind === "date_window") return `${object.start} to ${object.end}`;
    if ("value" in object) return readable(object.value);
    if ("start" in object && "end" in object) return `${readable(object.start)} to ${readable(object.end)}`;
    return Object.entries(object).map(([key, item]) => `${key}: ${readable(item)}`).join(", ");
  }
  return "Not specified";
}

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

function SourceList({ cell }: { cell: ComparisonCell }) {
  if (!cell.sources.length) return null;
  return <details className={styles.sources}>
    <summary>Evidence ({cell.sources.length})</summary>
    <ul>
      {cell.sources.map(source => <li key={`${source.evidence_id}:${source.source_observation_id}`}>
        <a href={source.url} target="_blank" rel="noreferrer">{source.title || "Open original source"}</a>
        {source.attribution && <p>{source.attribution}</p>}
        <p>Observed <time dateTime={source.observed_at}>{formatTime(source.observed_at)}</time>; expires <time dateTime={source.expires_at}>{formatTime(source.expires_at)}</time>.</p>
        {source.policy_url && <p><a href={source.policy_url} target="_blank" rel="noreferrer">Source use and attribution policy</a></p>}
      </li>)}
    </ul>
  </details>;
}

function Cell({ cell }: { cell: ComparisonCell }) {
  return <div className={styles.cell}>
    <span className={styles.badge} data-status={cell.status}>{statusLabels[cell.status]}</span>
    <div>{cell.value ?? "No sourced value"}</div>
    {cell.note && <p className={styles.muted}>{cell.note}</p>}
    <SourceList cell={cell} />
  </div>;
}

function CandidateRationale({ row, selected }: { row: ComparisonRow; selected: boolean }) {
  return <details className={styles.rationale}>
    <summary>{selected ? "Why this result was selected" : "Candidate rationale"}</summary>
    <p>{row.eligible
      ? row.score === null ? "This candidate passed the recorded requirements but could not be scored from current evidence."
        : `Eligible; combined score ${(row.score * 100).toFixed(0)}%${row.rank ? `, rank ${row.rank}` : ""}.`
      : `Excluded: ${row.exclusion_reasons.join(", ") || "a required fact was missing or could not be verified"}.`}</p>
    {row.features.length > 0 && <ul>
      {row.features.map(feature => <li key={feature.name}>
        {feature.name.replace(/^(travel|shopping)\./, "").replaceAll("_", " ")}: {feature.value === null ? "unknown" : `${(feature.value * 100).toFixed(0)}%`}
      </li>)}
    </ul>}
  </details>;
}

function ConstraintList({ result }: { result: DomainComparisonResult }) {
  if (!result.comparison.constraints.length) return <p>No hard constraints were recorded for this comparison.</p>;
  const labels = new Map(result.registration.fields.map(field => [field.key, field.label]));
  return <ul className={styles.constraints}>
    {result.comparison.constraints.map((constraint, index) => <li key={`${constraint.attribute}:${index}`}>
      <strong>{labels.get(constraint.attribute) ?? constraint.attribute.replaceAll("_", " ")}</strong>{" "}
      {constraint.operator.replaceAll("_", " ")} {readable(constraint.value)}
      {constraint.upper_value !== undefined && ` to ${readable(constraint.upper_value)}`}
      <span className={styles.muted}> · {constraint.source === "system" ? "safety requirement" : "your filter"}</span>
    </li>)}
  </ul>;
}

function Comparison({ result }: { result: DomainComparisonResult }) {
  const [eligibleOnly, setEligibleOnly] = useState(false);
  const [freshOnly, setFreshOnly] = useState(false);
  const [conflictsOnly, setConflictsOnly] = useState(false);
  const visibleRows = useMemo(() => result.comparison.rows.filter(row => {
    if (eligibleOnly && !row.eligible) return false;
    if (freshOnly && (row.cells.some(cell => cell.status === "stale") ||
        !row.cells.some(cell => cell.sources.some(source => Date.parse(source.expires_at) > Date.now())))) return false;
    if (conflictsOnly && !row.cells.some(cell => cell.status === "conflicting")) return false;
    return true;
  }), [result, eligibleOnly, freshOnly, conflictsOnly]);
  const columns = result.registration.fields.filter(field =>
    result.comparison.rows.some(row => row.cells.some(cell => cell.field === field.key)),
  );

  return <section className={styles.result} aria-live="polite">
    <div className={styles.resultHeading}>
      <div><span className={styles.state} data-state={result.comparison.state}>{stateLabel(result.comparison.state)}</span>
        <p>Evidence snapshot rendered <time dateTime={result.comparison.rendered_at}>{formatTime(result.comparison.rendered_at)}</time>.</p>
      </div>
      <label className={styles.loadSaved}>Comparison ID
        <span className="sr-only">A saved comparison ID</span>
        <input value={result.comparison.id} readOnly aria-label="Saved comparison ID" />
      </label>
    </div>

    <details className={styles.filters} open>
      <summary>Requirements and local filters</summary>
      <ConstraintList result={result} />
      <p className={styles.muted}>These display filters only change the rows shown; they do not rerun research or change the saved decision.</p>
      <div className={styles.filterControls}>
        <label><input type="checkbox" checked={eligibleOnly} onChange={event => setEligibleOnly(event.target.checked)} /> Eligible only</label>
        <label><input type="checkbox" checked={freshOnly} onChange={event => setFreshOnly(event.target.checked)} /> Fresh evidence only</label>
        <label><input type="checkbox" checked={conflictsOnly} onChange={event => setConflictsOnly(event.target.checked)} /> Conflicts only</label>
      </div>
    </details>

    {visibleRows.length === 0 ? <p className={styles.empty}>{result.comparison.rows.length === 0
      ? "No candidates were returned. Try a different query or gather evidence from another source."
      : "No candidates match these display filters."}</p> :
      <div className={styles.tableScroll} role="region" aria-label="Candidate comparison" tabIndex={0}>
        <table>
          <caption>{result.registration.domain_id === "travel" ? "Travel" : "Shopping"} candidate comparison</caption>
          <thead><tr><th scope="col">Candidate</th>{columns.map(field => <th scope="col" key={field.key}>{field.label}</th>)}</tr></thead>
          <tbody>{visibleRows.map(row => <tr key={row.candidate_id}>
            <th scope="row">
              <strong>{row.name}</strong>
              {row.selected && <span className={styles.selected}>Selected</span>}
              <CandidateRationale row={row} selected={row.selected} />
            </th>
            {columns.map(field => {
              const cell = row.cells.find(item => item.field === field.key);
              return <td key={field.key}>{cell ? <Cell cell={cell} /> : <span className={styles.muted}>No sourced value</span>}</td>;
            })}
          </tr>)}</tbody>
        </table>
      </div>}
    <details className={styles.provenance}>
      <summary>Decision and source details</summary>
      <p>Decision ID: <code>{result.comparison.decision_id}</code></p>
      <p>Policies: fields {result.registration.field_schema_version}; features {result.registration.feature_policy_version}; shared decision policy {result.comparison.decision_policy_versions?.ranking ?? "rank-v1"}.</p>
      <ul>{result.provider_observations.map((item, index) => <li key={`${item.provider}:${index}`}>
        {item.attribution}; observed {formatTime(item.observed_at)}, expires {formatTime(item.expires_at)}.
        {item.policy_url && <> <a href={item.policy_url} target="_blank" rel="noreferrer">Provider policy</a></>}
      </li>)}</ul>
    </details>
  </section>;
}

export default function DomainWorkbench({ domain, adapter }: { domain: DomainId; adapter: string }) {
  const [fixtures, setFixtures] = useState<DomainFixture[]>([]);
  const [fixtureId, setFixtureId] = useState("");
  const [query, setQuery] = useState("");
  const [comparisonId, setComparisonId] = useState("");
  const [result, setResult] = useState<DomainComparisonResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const heading = domain === "travel" ? "Travel comparison" : "Shopping comparison";

  useEffect(() => {
    let active = true;
    void domainApi.fixtures(domain).then(items => {
      if (!active) return;
      setFixtures(items);
      setFixtureId(items[0]?.fixture_id ?? "");
    }).catch(() => {
      if (active) setError("Examples could not be loaded. Retry the page or check the domain feature gate.");
    });
    return () => { active = false; };
  }, [domain]);

  async function run(action: () => Promise<DomainComparisonResult>) {
    setLoading(true); setError(null); setResult(null);
    try {
      const saved = await action();
      setResult(saved);
      setComparisonId(saved.comparison.id);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The comparison could not be completed. Please retry.");
    } finally { setLoading(false); }
  }

  function submitLookup(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    void run(() => domainApi.lookup(domain, query.trim()));
  }

  function submitFixture(event: FormEvent) {
    event.preventDefault();
    if (!fixtureId) return;
    void run(() => domainApi.runFixture(domain, fixtureId));
  }

  function loadSaved(event: FormEvent) {
    event.preventDefault();
    if (!comparisonId.trim()) return;
    void run(() => domainApi.get(domain, comparisonId.trim()));
  }

  return <main className={styles.shell}>
    <header className={styles.intro}>
      <p className={styles.eyebrow}>Phase 7 · evidence-based comparison</p>
      <h1>{heading}</h1>
      <p>Compare sourced candidates against visible requirements. Current prices, stock, opening hours, and travel details can change; the saved observation times and source links stay attached to each fact.</p>
    </header>

    {domain === "travel" && adapter === "osm_nominatim" && <aside className={styles.policyNotice}>
      <h2>OpenStreetMap place lookup</h2>
      <p>The place text you submit is sent to Nominatim. Keep private itinerary and personal details out of place searches. This lookup is rate-limited, does not provide hotel rates or current availability, and does not support autocomplete or bulk searches.</p>
      <p>Map data © OpenStreetMap contributors, available under the ODbL. <a href="https://operations.osmfoundation.org/policies/nominatim/" target="_blank" rel="noreferrer">Nominatim usage policy</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap attribution and license</a></p>
    </aside>}
    {domain === "shopping" && adapter === "open_food_facts" && <aside className={styles.policyNotice}>
      <h2>Open Food Facts product catalog</h2>
      <p>Only the exact barcode is sent. Catalog entries are user-contributed and may be incomplete or incorrect. This source identifies products; it does not provide current merchant offers, stock, or delivery terms.</p>
      <p>Product data from Open Food Facts is available under the ODbL; individual contents use the Database Contents License. <a href="https://openfoodfacts.github.io/openfoodfacts-server/api/" target="_blank" rel="noreferrer">Open Food Facts API and attribution</a> · <a href="https://openfoodfacts.github.io/openfoodfacts-server/api/tutorials/license-be-on-the-legal-side/" target="_blank" rel="noreferrer">Open Food Facts data licenses</a></p>
    </aside>}
    {adapter === "fake" && <p className={styles.demoNotice}>The configured lookup source is synthetic and returns example data.</p>}

    <div className={styles.forms}>
      <form onSubmit={submitLookup} className={styles.lookup}>
        <h2>{domain === "travel" ? "Look up a place" : "Look up a product"}</h2>
        <label htmlFor="domain-query">{domain === "travel" ? "Place or area name" : "Exact barcode"}</label>
        <input id="domain-query" value={query} onChange={event => setQuery(event.target.value)} maxLength={300} required placeholder={domain === "travel" ? "Example: Golden Gate Park" : "Enter an 8–14 digit barcode"} />
        <p className={styles.muted}>{domain === "travel" ? "Place records can help with location discovery. Stay price, booking availability, and operating hours require separate current evidence." : "A catalog match does not establish a merchant offer, total cost, or current availability."}</p>
        <button disabled={loading || !query.trim()}>{loading ? "Looking up…" : "Look up"}</button>
      </form>
      <form onSubmit={submitFixture} className={styles.example}>
        <h2>Try a synthetic comparison</h2>
        <label htmlFor="domain-fixture">Example</label>
        <select id="domain-fixture" value={fixtureId} onChange={event => setFixtureId(event.target.value)} disabled={fixtures.length === 0}>
          {fixtures.map(item => <option value={item.fixture_id} key={item.fixture_id}>{item.title}</option>)}
        </select>
        {fixtures.find(item => item.fixture_id === fixtureId) && <p className={styles.muted}>{fixtures.find(item => item.fixture_id === fixtureId)?.description}</p>}
        <button disabled={loading || !fixtureId}>{loading ? "Comparing…" : "Run synthetic example"}</button>
      </form>
    </div>

    <form onSubmit={loadSaved} className={styles.savedForm}>
      <label htmlFor="comparison-id">Load a saved comparison ID</label>
      <input id="comparison-id" value={comparisonId} onChange={event => setComparisonId(event.target.value)} />
      <button disabled={loading || !comparisonId.trim()}>Load comparison</button>
    </form>

    {loading && <p className={styles.loading} role="status">Preparing the evidence-backed comparison…</p>}
    {error && <div className={styles.error} role="alert"><p>{error}</p><button onClick={() => setError(null)}>Dismiss</button></div>}
    {!result && !loading && !error && <p className={styles.empty}>Run a lookup or a synthetic example to see candidates, requirements, and source evidence.</p>}
    {result && <Comparison result={result} />}
    <footer className={styles.footer}><p>Feature gates are controlled by the server. The local owner setting is not an authentication boundary. Do not enter sensitive trip, purchase, or account information.</p></footer>
  </main>;
}
