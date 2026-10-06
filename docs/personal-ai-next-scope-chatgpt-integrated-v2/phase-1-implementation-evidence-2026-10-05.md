# Next-scope Phase 1 implementation evidence — 2026-10-05

## Revision and configuration

- Audited target commit `029ed26`; bounded scope-pagination follow-up tested at
  commit `bf7550e9a012d684caf42f18c0cdedf2a004447b`.
- Governing plan reconciled against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`.
- Backend test interpreter: Python 3.11.15 from `backend/.venv`.
- Frontend runtime: bundled Node.js 24.19.0 and pnpm 11.19.0. The repository setup calls for Node 22; Node 22 was not available on `PATH` in this environment.
- Offline checks use fake repositories/providers and synthetic fixtures. No credentials or live service calls were used.

## Local checks

| Check | Result |
| --- | --- |
| `make backend-test` with `backend/.venv/bin` on `PATH` | Passed on `bf7550e`: 580 passed, 12 skipped. Skips are opt-in manual/provider/emulator checks. |
| `make backend-lint` with `backend/.venv/bin` on `PATH` | Passed: Ruff reports all checks passed. |
| `make frontend-test` with bundled Node.js on `PATH` | Passed: 19 files, 96 tests. |
| `make frontend-lint` | Passed. |
| `make frontend-typecheck` | Passed for app and test TypeScript configurations. |
| `make context-eval memory-eval memory-lifecycle-eval research-eval decision-eval domain-eval iterative-research-eval itinerary-proposal-eval` on `bf7550e` | Passed: command exited 0. |
| `backend/.venv/bin/python -m json.tool firestore.indexes.json` | Passed: index file parses as JSON. |
| `git diff --check` | Passed for the code follow-up; documentation update checked separately. |

## Acceptance evidence

- Focused regressions cover app/workspace iterative run-ID partitioning,
  legacy research-query and iterative-run child envelopes, standalone vector
  ranking and decision result limits past 120 foreign records, maintenance
  discovery skipping foreign records before state lookup, bounded conversation
  pagination, export joins for legacy ownerless evaluation and domain claim
  extension rows, non-standalone deletion-intent rejection, and persisted-scope
  chat creation events.
- The conversation proxy test asserts the exact scope/correlation allowlist
  and rejects forwarding owner and idempotency claims.
- Decision lookups, lifecycle candidate/dependency discovery, and booking
  extraction expiry use bounded pagination that applies scope before the
  requested result cap.
- The backend suite covers existing conversation, branch, memory lifecycle,
  research, decision, domain, proposal, extraction, and account-data contracts.
  It does not yet constitute the plan's complete same-owner app/workspace
  matrix for every record family, Firestore replay, worker delivery,
  cancellation, and accepted workspace membership.

## Remaining verification gaps

- Firestore composite/vector indexes are defined, reviewed offline, and parse as
  JSON, but are not provisioned or checked against a live Firestore emulator/project.
- Firestore cannot query documents with absent scope fields. Standalone legacy
  reads therefore use a bounded owner-prefiltered compatibility scan and filter
  scope before result limits or vector ranking. That scan still reads newer
  foreign app/workspace documents. It restores eligible standalone recall but
  does not meet the review's zero-foreign-read requirement. Preventing those
  reads requires a separate legacy discriminator or storage partition; this
  remains an open isolation item and no backfill or record movement was
  performed.
- Workspace membership remains denied by default. No deployed application
  membership authority was configured or tested.
- Cloud Run IAM, deployed Next.js-to-API identity forwarding, provider behavior,
  backup/recovery, and production release gates were not exercised.
- No legacy data was backfilled or reassigned. Existing Phase 9 physical
  deletion, full owner migration, provider accounting, and operational gates
  remain separate open work.

Next-scope Phase 1 is not closed by this evidence: the full local scope matrix
and zero-foreign-read legacy storage boundary remain unresolved.
