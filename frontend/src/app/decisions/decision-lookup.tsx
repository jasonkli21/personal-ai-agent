"use client";

import { FormEvent, useEffect, useState } from "react";
import { decisionApi, type CandidateEvaluation, type DecisionInspection, type DecisionResult } from "../../lib/decision-api";

function readableState(state: string) {
  return ({
    recommended: "Recommended",
    eligible_unranked: "Eligible, not ranked",
    research_needed: "More verified research is needed",
    no_verified_match: "No verified match",
  } as Record<string, string>)[state] ?? state;
}

function DecisionDetails({ result, inspection }: { result: DecisionResult; inspection?: DecisionInspection | null }) {
  const names = new Map(result.entities.map(entity => [entity.id, entity.canonical_name]));
  const claims = new Map(result.claims.map(claim => [claim.id, claim]));
  const evaluations = inspection
    ? [...inspection.selected, ...inspection.excluded]
    : result.evaluations;
  const ordered = [...evaluations].sort((a, b) => {
    if (a.entity_id === result.decision.selected_entity_id) return -1;
    if (b.entity_id === result.decision.selected_entity_id) return 1;
    return (a.rank ?? Number.MAX_SAFE_INTEGER) - (b.rank ?? Number.MAX_SAFE_INTEGER);
  });
  return <section aria-live="polite">
    <h2>{readableState(result.decision.state)}</h2>
    <p>Decision {result.decision.id}; created {new Date(result.decision.created_at).toLocaleString()}.</p>
    <p>Policy versions: identity {result.decision.policy_versions.identity}, resolution {result.decision.policy_versions.resolution}, constraints {result.decision.policy_versions.constraints}, ranking {result.decision.policy_versions.ranking}.</p>
    {result.decision.research_session_id && <p>Evidence came from research session {result.decision.research_session_id}.</p>}
    {result.recommendation.explanation_codes.length > 0 && <p>Decision notes: {result.recommendation.explanation_codes.join(", ")}.</p>}
    <ol>
      {ordered.map((evaluation: CandidateEvaluation) => {
        const entityName = names.get(evaluation.entity_id) ?? evaluation.entity_id;
        const candidateClaims = evaluation.claim_ids.map(id => claims.get(id)).filter((claim) => claim !== undefined);
        const supportingClaims = result.recommendation.selected_entity_id === evaluation.entity_id
          ? result.recommendation.supporting_claim_ids
          : [];
        return <li key={evaluation.entity_id}>
          <h3>{entityName}{result.decision.selected_entity_id === evaluation.entity_id ? " — selected" : ""}</h3>
          <p>{evaluation.eligibility
            ? evaluation.constraint_outcomes.length > 0 ? "Meets verified requirements" : "Eligible; no hard constraints were recorded"
            : `Not eligible: ${evaluation.exclusion_reasons.join(", ") || "identity or evidence needs review"}`}</p>
          {candidateClaims.length > 0 && <p>Evidence freshness is evaluated as of the saved decision; current availability is not guaranteed.</p>}
          {evaluation.score !== null && <p>Preference score: {(evaluation.score * 100).toFixed(0)}%{evaluation.rank ? `; rank ${evaluation.rank}` : ""}.</p>}
          {candidateClaims.length > 0 && <><h4>Evidence-backed facts</h4><ul>
            {candidateClaims.map(claim => <li key={claim.id}>
              {claim.attribute}: {claim.original_value}; {claim.claim_status}; {Date.parse(claim.expires_at) > Date.now() ? "fresh" : "expired"}; observed {new Date(claim.observed_at).toLocaleString()}; expires {new Date(claim.expires_at).toLocaleString()}.
              <ul>{claim.evidence_refs.map(reference => <li key={`${reference.evidence_id}:${reference.source_observation_id}`}>
                <a href={reference.url} target="_blank" rel="noreferrer">{reference.title ?? reference.url}</a>
                {supportingClaims.includes(claim.id) && " (supports the selected result)"}
              </li>)}</ul>
            </li>)}
          </ul></>}
          {evaluation.attribute_statuses.length > 0 && <><h4>Compared facts</h4><ul>
            {evaluation.attribute_statuses.map(status => <li key={`${status.attribute}:${status.scope ?? ""}`}>
              {status.attribute}: {status.status} ({status.reason})
            </li>)}
          </ul></>}
          {evaluation.constraint_outcomes.length > 0 && <><h4>Requirements</h4><ul>
            {evaluation.constraint_outcomes.map(outcome => <li key={`${outcome.attribute}:${outcome.reason}`}>
              {outcome.attribute}: {outcome.outcome} ({outcome.reason})
            </li>)}
          </ul></>}
          {evaluation.feature_values.length > 0 && <><h4>Preference features</h4><ul>
            {evaluation.feature_values.map(feature => <li key={feature.name}>
              {feature.name}: {feature.value === null ? `unknown (${feature.missing_treatment})` : `${(feature.value * 100).toFixed(0)}%`} at weight {(feature.weight * 100).toFixed(0)}%
            </li>)}
          </ul></>}
          {inspection && <p>Identity: {evaluation.identity_outcome}, confidence {(evaluation.identity_confidence * 100).toFixed(0)}%.</p>}
        </li>;
      })}
    </ol>
    {inspection && <section><h3>Resolution trace</h3>
      <ul>{inspection.matches.map(match => <li key={match.id}>
        {match.outcome}; candidates {match.candidate_entity_ids.map(id => names.get(id) ?? id).join(", ") || "none"}; confidence {(match.confidence * 100).toFixed(0)}%.
      </li>)}</ul>
      <p>Inspection evidence references: {inspection.evidence_refs.length}.</p>
    </section>}
  </section>;
}

export default function DecisionLookup({ initialDecisionId = "", inspectionEnabled = false }: { initialDecisionId?: string; inspectionEnabled?: boolean }) {
  const [decisionId, setDecisionId] = useState(initialDecisionId);
  const [result, setResult] = useState<DecisionResult | null>(null);
  const [inspection, setInspection] = useState<DecisionInspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function load(id: string) {
    setPending(true); setError(null); setResult(null); setInspection(null);
    try {
      const saved = await decisionApi.get(id);
      setResult(saved);
      if (inspectionEnabled) setInspection(await decisionApi.inspect(id));
      window.history.replaceState(null, "", `${inspectionEnabled ? "/development/decisions" : "/decisions"}?id=${encodeURIComponent(id)}`);
    } catch {
      setError("This decision could not be loaded. Check the ID and feature gates.");
    } finally { setPending(false); }
  }

  useEffect(() => { if (initialDecisionId.trim()) void load(initialDecisionId.trim()); }, [initialDecisionId]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (decisionId.trim()) void load(decisionId.trim());
  }

  return <main style={{ maxWidth: 960, margin: "2rem auto", padding: "1rem" }}>
    <h1>{inspectionEnabled ? "Development decision inspector" : "Decision result"}</h1>
    <p>{inspectionEnabled
      ? "Read-only candidate, constraint, ranking, policy and source diagnostics."
      : "A source-backed comparison with requirement status, observation times and citations."}</p>
    <form onSubmit={submit}>
      <label htmlFor="decision-id">Decision ID</label>{" "}
      <input id="decision-id" value={decisionId} onChange={event => setDecisionId(event.target.value)} />{" "}
      <button disabled={pending || !decisionId.trim()}>{pending ? "Loading…" : "Load decision"}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {result && <DecisionDetails result={result} inspection={inspection} />}
  </main>;
}
