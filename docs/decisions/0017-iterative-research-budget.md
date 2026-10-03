# ADR 0017: Versioned iterative research budgets

- Status: accepted
- Date: 2026-10-02

## Context

Bounded iteration must account for its work before dispatch, preserve enough
capacity to produce a cited result, and explain partial completion without
using max iterations as a proxy for evidence sufficiency.

## Decision

Each iterative run snapshots policy `iterative-research-policy-v1` and budget
`evidence-quality-budget-v1`. Defaults are at most 3 total iterations, 3
queries, 12 sources, 90 seconds elapsed, 16,000 input/synthesis tokens, and
USD 0.05 estimated provider cost. The initial synthesis reserve is 4,096
tokens plus the configured synthesis cost estimate. At most 12 exact hostnames
may be allowed, and follow-up results outside the recorded allowlist are
excluded before extraction. Operators may lower or raise these values only
within validated ceilings; the snapshot never changes after creation.

Ledger entries cover iterations, queries, sources, tokens, provider cost,
elapsed seconds, and allowed domains. Reservations are durable before work.
Provider work with unknown outcome settles its complete reservation. Elapsed
time is recorded at each transition and checked again before dispatch. A
candidate source is charged against the source cap before it enters the
session. Token use is settled from the shared context assembler's counter;
unavailable or timed-out counts consume the complete remaining token reserve.

Stopping uses explicit reasons: `sufficient`, `iteration_budget_exhausted`,
`query_budget_exhausted`, `source_budget_exhausted`, `token_budget_exhausted`,
`provider_cost_budget_exhausted`, `elapsed_budget_exhausted`,
`no_productive_query`, `provider_error`, `synthesis_error`,
`side_effect_uncertain`, `cancelled`, and `evidence_insufficient`. Each
non-sufficient terminal result includes its still-open named gaps. Query
normalization is case-folded whitespace normalization with URL punctuation
retained; any repeated query is skipped and cannot trigger another attempt.

## Consequences

- Fake and public adapters use the same reservation and settlement path.
- Cost is a transparent estimate unless a provider returns billing metadata;
  provider results currently do not expose that data.
- The default is intentionally small and the independent run/progress gates
  default off. Existing single-pass limits and behavior stay in place.
- Promotion requires paired fixture evidence showing useful coverage without
  constraint, provenance, freshness, or budget regression.
