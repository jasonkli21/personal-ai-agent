# Next-scope Phase 1 implementation evidence — 2026-10-05

## Revision and configuration

- Implementation plan reconciled against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`.
- Implementation started from repository revision `e139b46fdc201c1ba7fd8e7794d006eb6ad3e09c`.
- Backend test interpreter: Python 3.11.15 from `backend/.venv`.
- Frontend runtime: bundled Node.js 24.19.0 and pnpm 11.19.0. The repository setup calls for Node 22; Node 22 was not available on `PATH` in this environment.
- Offline checks use fake repositories/providers and synthetic fixtures. No credentials or live service calls were used.

## Local checks

| Check | Result |
| --- | --- |
| `make backend-test` with `backend/.venv/bin` on `PATH` | Passed: 569 passed, 12 skipped. Skips are opt-in manual/provider/emulator checks. |
| `make backend-lint` with `backend/.venv/bin` on `PATH` | Passed: Ruff reports all checks passed. |
| `make frontend-test` | Passed: 19 files, 95 tests. |
| `make frontend-lint` | Passed. |
| `make frontend-typecheck` | Passed for app and test TypeScript configurations. |
| `make context-eval memory-eval memory-lifecycle-eval research-eval decision-eval domain-eval iterative-research-eval itinerary-proposal-eval` | Passed: command exited 0. |
| `python3 -m json.tool firestore.indexes.json` | Passed: index file parses as JSON. |
| `git diff --check` | Passed before commit. |

## Acceptance evidence

- Same-owner application/workspace isolation, legacy v1 defaults, scoped memory
  identities, lifecycle replay identities, route isolation, forged-owner
  rejection, and fail-closed workspace authorization have focused regression
  coverage in `backend/tests/test_application_scope.py` and related tests.
- Export regression coverage verifies that pages containing more than 250
  foreign-scope records do not hide a legacy standalone record.
- Frontend API/proxy tests cover scope headers and proxy forwarding.
- Existing conversation, branch, memory lifecycle, research, decision, domain,
  proposal, extraction, and account-data tests all pass in the backend suite.

## Remaining verification gaps

- Firestore composite/vector indexes are defined but not provisioned or checked
  against a live Firestore emulator/project.
- Workspace membership remains denied by default. No deployed application
  membership authority was configured or tested.
- Cloud Run IAM, deployed Next.js-to-API identity forwarding, provider behavior,
  backup/recovery, and production release gates were not exercised.
- No legacy data was backfilled or reassigned. Existing Phase 9 physical
  deletion, full owner migration, provider accounting, and operational gates
  remain separate open work.
