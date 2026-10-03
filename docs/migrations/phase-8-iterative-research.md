# Phase 8 storage definition

Phase 8 adds two top-level collections without changing existing records:

- `iterative_research_runs/{run_id}` stores one bounded
  `iterative-research-v1` aggregate. Its event stream, iterations, assessments,
  gaps, ledger, budget snapshot, and optional user-authored decision intent are
  updated atomically by run revision.
- `iterative_research_request_keys/{sha256(owner_id:idempotency_key)}` maps one
  owner-scoped idempotency key to a run ID. The mapping stores no question or
  query text.

The run has a bounded 128-event/ledger cap, 5-iteration cap, 6-assessment cap,
512 immutable gap-history cap, 6-decision-snapshot cap, 3-query cap, and
12-source/citation-selection cap. Candidate/constraint combinations are
bounded to 30. Full evidence and source text remain in
`research_sessions`; the run does not copy provider passages. There are no
collection scans or composite queries for runs: run and idempotency mappings
are point reads. `firestore.indexes.json` disables indexing on the run's
structured snapshots and append-only arrays. No existing collection is
rewritten and there is no backfill.

For a new Firestore project, apply the normal root index manifest. For an
existing project, deploy the `iterative_research_runs` field exemptions from
that manifest before enabling `ITERATIVE_RESEARCH_ENABLED`. No index creation
is required. The repository writes the run/session result in a bounded
transaction; emulator/restart verification remains external and is not implied
by fake repository tests.
