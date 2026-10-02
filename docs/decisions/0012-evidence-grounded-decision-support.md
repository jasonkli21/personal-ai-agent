# ADR 0012: Evidence-grounded decision support

- Status: Accepted
- Date: 2026-10-02
- Phase: 6

## Context

Phase 5 retains bounded, owner-scoped source observations and expiring evidence.
Reusable decisions need stable candidate identity, hard-constraint outcomes,
and ranking details without converting an observation into permanent entity
truth or writing an external application's authoritative state.

## Decision

- Store canonical research entities separately from immutable, owner-scoped
  claims. Claims keep typed and original values, source references, observation
  time, expiry, and a verification status.
- Snapshot the complete source attribution, observation, expiry, policy, and
  content-fingerprint metadata used by a decision. A Phase 5 session may supply
  that snapshot, but a caller may also provide explicitly attributed and
  validated evidence without a research session.
- Require evidence ownership to match the decision owner. Session evidence must
  belong to the owner, be selected by that session, and remain fresh at the
  injected decision time. Direct evidence must use a canonical public URL and
  provide a bounded excerpt whose fingerprint matches its content.
- Resolve exact stable identifiers first. Name similarity alone never selects
  an entity. Name plus an independently matching fresh claim may pass the
  versioned threshold; ambiguous candidates remain review outcomes. New
  candidates are persisted separately, so resolution never destructively
  merges identity records.
- Conflicting values for a shared stable identifier key veto an automatic
  exact or scored match. Claim verification requires a simple explicit
  subject/attribute/value assertion with affirmative polarity; it does not
  infer that a literal elsewhere in the passage belongs to a candidate.
  Scored matching uses only identity attributes such as model, SKU, catalog or
  product ID, and standard product identifiers; price, color, and availability
  are not identity evidence.
  Resolution is `resolve-v2`; assertion verification is separately versioned
  as `claim-verification-v2`. Missing claim-version metadata remains v1 and
  cannot qualify for current decisions.
- Evaluate typed hard constraints before preferences. Unknown, stale,
  conflicting, or unverified required attributes fail closed. Currency rates
  are not guessed; unsupported currency or unit conversion yields unknown.
- Persist immutable decision, evidence, entity-match, and candidate-evaluation
  records with explicit policy versions and deterministic tie-breaking. Scores
  describe policy fit, not factual confidence. Ranking failure preserves the
  eligible set as unranked.
- Keep decision creation and inspection disabled by default. Inspection is
  read-only and exposes metadata, source links, and policy results without
  private memory content or hidden model reasoning. Results are research
  decision support, not bookings, purchases, or domain-app state.

## Consequences

- Claim expiry and disagreement remain visible after the canonical entity is
  persisted.
- Repeated identical evidence is idempotent; a later source update adds a new
  claim and does not rewrite the old observation.
- Optional values can remain unknown when their field contract allows it;
  explicit user constraints cannot be relaxed by preferences.
- The initial ranking is deterministic and intentionally small. Changing
  thresholds, normalization, or weights requires a policy-version change and
  fixture comparison.
- Direct evidence is caller-supplied, not independently authenticated by the
  current `local` owner boundary. The public bootstrap remains unsuitable for
  sensitive data.

## Rejected alternatives

- Treating the latest claim as true would hide source conflicts and make old
  decisions impossible to reconstruct.
- Matching on a similar title alone would silently merge distinct candidates.
- Requiring every decision to originate in a Phase 5 session would prevent
  reusable decisions over other explicitly supplied evidence sources.
- Asking a model to decide hard-constraint pass/fail would make deterministic
  requirements non-reproducible.
