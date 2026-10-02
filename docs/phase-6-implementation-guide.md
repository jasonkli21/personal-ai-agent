# Phase 6 implementation guide

Phase 6 decision support is implemented locally as of 2026-10-02 after explicit
user authorization. `DECISION_ENABLED` and `DECISION_INSPECTION_ENABLED` remain
false by default. This guide describes the delivered contracts and the checks
that still require an emulator, provider rights review, or deployment.

## Scope delivered

The shared platform can persist canonical research candidates, aliases,
immutable evidence-backed claims, identity-resolution events, evidence
snapshots, decision snapshots, and candidate evaluations. A decision uses one
of two paths:

- A completed, unexpired, owner-scoped Phase 5 session whose selected evidence
  supports each referenced claim.
- Explicitly supplied evidence with a canonical public source URL, owner ID,
  bounded excerpt, content fingerprint, observation time, and expiry. A
  research-session ID is not required.

Neither path writes bookings, purchases, itineraries, or other authoritative
domain-application state. The current `local` owner is not authentication.
Phase 7 domain adapters and Phase 8 iterative research remain out of scope.

## Contracts and policy

The versioned Pydantic contracts live in `personal_ai.entities.research`,
`personal_ai.decisions.contracts`, and `personal_ai.decisions.repositories`.
Accepted architecture decisions are recorded in
[ADR 0012](decisions/0012-evidence-grounded-decision-support.md). The
`decision-v1` response includes a reproducible decision snapshot, exact source
references, canonical entities, claims, match outcomes, and one evaluation per
candidate.

Resolution accepts a unique exact stable identifier. Name similarity alone
never merges entities; a scored match also needs an independently matching,
fresh, verified claim. Ambiguous matches abstain and remain separate research
candidates. Resolution stops with a safe error if its bounded entity scan would
be truncated.

Claims remain immutable when later sources report a different value. Fresh
same-scope disagreement is `conflicting`; expired claims are `stale`; absent
facts are `missing`. Required unknown, stale, unverified, and conflicting
attributes fail closed. A claim is verified only when the excerpt contains its
original literal and a deterministic type-specific parser confirms that the
literal agrees with the proposed typed value; matching uses token boundaries,
and future-dated observations are rejected. Ambiguous formats and currencies
remain unverified. Supported hard-constraint operators are exact,
maximum, minimum, range, set, geospatial radius, date-window coverage, and
availability. Known length and mass units use deterministic base conversions;
unknown units and currency comparisons across currencies produce `unknown`;
no foreign-exchange conversion is performed.

Preferences score candidates only after hard-constraint filtering. The initial
hand-authored feature is typed-value preference fit with stable normalized-name
and entity-ID tie breakers. Scores describe fit to that policy, not factual
confidence. If ranking fails, the eligible set is preserved as
`eligible_unranked` without scores or ranks. Results use `recommended`,
`eligible_unranked`, `research_needed`, and `no_verified_match` states.

## Storage and API

`FirestoreDecisionRepository` keeps Firestore behind the repository contract.
It writes entity/alias/claim/match/evaluation records and the decision plus
evidence snapshots atomically, with append-only claims and idempotent decision
replay. Index definitions are in the root `firestore.indexes.json` for
`canonical_entities`, `entity_aliases`, `entity_claims`, `entity_matches`,
`decision_snapshots`, `decision_evidence_snapshots`, and
`candidate_evaluations`.

Backend routes are:

- `POST /v1/decisions` to validate and persist a decision.
- `GET /v1/decisions/{decision_id}` to retrieve its immutable result.
- `GET /v1/decisions/{decision_id}/inspection` for separately gated,
  development-only candidate and policy diagnostics.

Browser requests go through the Next.js `/api/decisions` proxy. `/decisions`
loads a saved decision by ID and displays evidence-backed facts, observation
and expiry times, requirement results, and source links. The separate
`/development/decisions` view also displays resolution and inspection data.
Neither view shows raw private memory or hidden model reasoning. A decision is
created through the API; this phase does not add a candidate-authoring form.

For a local synthetic browser check, enable `DECISION_ENABLED=true` in both
backend and frontend environment files. Enable
`DECISION_INSPECTION_ENABLED=true` in both files only for the development
inspector. For session-backed requests, Phase 5 must also be deliberately
configured and a completed session must exist. Keep the fixed owner and public
bootstrap away from sensitive personal data.

## Evaluation and verification

Run `make decision-eval` for the 15 deterministic synthetic fixtures. The
machine-readable result follows
`evaluation/decision-evaluation.schema.json` and reports each fixture's
decision ID, evidence-snapshot ID, policy versions, outcomes, result, and pass
status. Backend tests exercise the session-backed and supplied-evidence paths,
constraint operators, conflict/expiry handling, idempotency, owner scoping,
ranking fallback, exact provenance, route gates, and Firestore repository
serialization/transaction behavior through fakes.

See [Phase 6 release evidence](releases/phase-6-decision-support.md) for the
tested revision, offline command results, and remaining external gaps. The
fakes do not establish real Firestore transaction behavior or index readiness.
Brave data use still requires suitable storage and AI-use rights. Gemini and
deployed browser cancellation checks are opt-in and are not prerequisites for
offline CI.
