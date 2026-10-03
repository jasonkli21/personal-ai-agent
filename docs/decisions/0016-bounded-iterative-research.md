# ADR 0016: Bounded iterative research state

- Status: accepted
- Date: 2026-10-02

## Context

Phase 5 persists one request-owned pass. Iteration needs a durable owner of
state, leases, idempotency, immutable policy snapshots, safe progress, and
recovery without changing the single-pass route. Search results, extracted
evidence, citations, and decisions must continue to use the Phase 5–6
contracts.

## Decision

An opt-in Phase 8 run is a separate `iterative-research-v1` aggregate in
`iterative_research_runs`; its idempotency mapping is stored in
`iterative_research_request_keys`. The run links to one Phase 5
`ResearchSession`, whose existing bounded owner-scoped aggregate remains the
source of query, attempt, source, evidence, selection, and citation
provenance. The run aggregate stores a frozen policy/budget snapshot, a
monotonic event stream, iteration/gap records, and append-only per-dimension
budget ledger entries. Bounded arrays remain in one Firestore document so a
state change and its public event are one transaction; no event query or
composite index is needed. Requests and evidence remain in the existing
research session document. Large arrays in both collections receive field
index exemptions.

Only `IterativeResearchService` may advance the finite state machine. It
persists the next state and safe event before starting an adapter or model
call. Search and synthesis output is committed to the Phase 5 session before
the run records the completed side effect. A started adapter attempt without
a committed terminal result is uncertain after lease loss and is never
replayed. The run settles the reserved maximum cost and stops incomplete.
Committed results are recovered by their stable query/attempt identity and
are not dispatched again. Cancellation is a terminal compare-and-set; every
subsequent run or session write checks the same owner, lease, revision, and
nonterminal state. SSE renders persisted events only. The event GET and
timeline reads never execute work.

Budget snapshots are immutable and versioned. Query, source, token, provider
cost, elapsed time, iteration, and domain dimensions have explicit finite
ceilings. Every dispatch reserves each applicable dimension first, including
a fixed synthesis token/cost reserve. A timeout or lost provider acknowledgement
settles the full provider-call estimate conservatively. For providers that do
not report billing, `settled` cost is a configured upper-bound estimate, not a
provider invoice. The feature and progress gates default off; single-pass
research remains the default and retains its existing endpoint and SSE events.

Optional decision intents contain candidate identities and user constraints,
not model-supplied facts. Assessment invokes the shared Phase 6 decision path
against an ephemeral view of the current Phase 5 evidence. Unknown required
facts, conflicts, stale evidence, and ambiguous identity remain gaps. The
planner can emit only a validated query proposal tied to one such gap; it
cannot alter a constraint or assert a claim. The final answer and persisted
decision are incomplete when the shared evaluator cannot establish a safe
result.

## Consequences

- A crash after provider dispatch but before result commit can lose a result;
  recovery does not pay for a duplicate request or pretend the result exists.
- Firestore transactions update the run and associated Phase 5 session in one
  fenced commit where a result could otherwise race with cancellation.
- The Phase 5 aggregate caps remain authoritative. Iterative settings cannot
  exceed three total queries or twelve sources in this version.
- No worker, autonomous follow-up after terminal state, authentication, or
  provider call outside the existing adapter boundary is added.
- Budget cost accounting is deliberately conservative and estimated when the
  adapter does not expose actual billing metadata.

## Rejected alternatives

- Replaying an interrupted provider attempt could duplicate charges and
  results, so uncertain calls stop the run.
- Treating SSE as run state would lose progress on disconnect and permit
  reconnect to repeat work.
- Replacing the Phase 5 session or calling search providers from the new
  orchestrator would fork provenance and URL/content policy.
- Model-proposed facts or changed constraints would bypass Phase 6's
  deterministic evidence verification and hard-constraint ordering.
