# Phase 1 vertical-slice verification record

**Latest local verification:** 2026-10-01, review remediation on `7fb4ca2` (uncommitted working tree)

**Initial tested revision:** `7301bdd` (working tree had a README-only modification)

## Initial local verification

The complete automated Phase 1 suite was run without cloud credentials or a
model key:

- Backend: 32 tests passed; 1 credentialed Gemini manual test skipped.
- Backend lint: Ruff passed.
- Frontend: 10 tests passed.
- Frontend lint and TypeScript type-check: passed.
- Deployment shell syntax and diff whitespace: passed on 2026-08-19;
  `git diff --check` is also checked for this documentation update.

The checks were executed using the existing project virtual environment and
installed frontend dependencies. A developer following the README activates
`backend/.venv` before the Make commands and installs frontend dependencies
from the committed lockfile.

The frontend check initially encountered pnpm dependency reconciliation and a
missing `node` on `PATH`. After reconciliation, Vitest, ESLint, and TypeScript
were run directly with the bundled Node runtime on `PATH` and passed. Backend
checks used `backend/.venv/bin/python`. This validates the suites, not a clean
installation or production build.

The 2026-08-19 baseline at `b9265ac` recorded 30 backend passes (one skipped)
and 8 frontend passes. Those counts included the earlier review hardening.

## Cloud verification

No credentialed GCP deployment or Gemini smoke test was performed in this
session because no GCP access or provider key was supplied. The required
post-deploy procedure is in the [deployment checklist](../phase-1-deployment-checklist.md).
This record contains no keys, URLs, or chat content.

Firestore Emulator persistence remains unverified. Automated client-disconnect
integration was subsequently added and verified locally in the remediation below. See the [verification closeout plan](../phase-1-verification-plan.md).

## Locked dependency and build verification — 2026-10-01

Verified the build-management changes on top of `dcef20a` before their commit:

- Resolved and checked `backend/uv.lock`; installed its dev/build dependencies
  into a fresh temporary Python 3.11 environment. Backend tests: 32 passed,
  one credentialed test skipped; Ruff passed.
- Built the backend source distribution and wheel with locked build tools.
- Installed the production dependencies and noneditable application into a
  separate fresh environment using the Docker sync sequence. Application,
  Gemini adapter, and Firestore adapter imports passed; pytest was absent.
- Frontend pnpm 11.19.0 frozen-lockfile install passed. All 10 tests, ESLint,
  TypeScript, and the Next.js production build passed.
- Documentation links, workflow YAML parsing, deployment shell syntax, and
  diff whitespace checks passed.

Docker was unavailable locally, so container builds were not run. CI now
includes both Docker builds and Python 3.11/3.12 backend checks; their results
are not yet recorded. Provider, emulator, and deployed verification remain
open. No Phase 2 implementation was started.


## Independent-review remediation — 2026-10-01

Verified the Phase 1 fixes in the working tree on top of `7fb4ca2`:

- Backend: 69 passed, one credentialed Gemini manual test skipped; Ruff passed.
- Actual ASGI 2.3/2.4 regressions cover abandoned response bodies, disconnects,
  asynchronous provider teardown, partial failures, and terminal-state protection.
- The real Gemini adapter with an injected offline SDK stream verifies that a
  timeout after partial output persists a failed turn and closes the provider.
  Provider iteration stays in one task across yields, preserving SDK timeout scopes.
- Offline storage tests cover atomic replacement/rollback, concurrent snapshots,
  stale recovery, lazy query errors, and configured emulator transport selection.
- Frontend: 27 tests passed; ESLint, TypeScript, and Next.js production build passed.
  Coverage includes incomplete SSE streams, malformed frames, reader cleanup,
  UI unmount cancellation, and upstream proxy abort propagation.
- Backend lockfile validation and source-distribution/wheel build passed with
  the locked build tools; `anyio` is now an explicit runtime dependency.
- Documentation links, workflow YAML parsing, deployment shell syntax, and
  diff whitespace checks passed.

Backend checks used `/tmp/personal-ai-build-check/bin/python`; frontend checks
used the bundled Node runtime and installed locked dependencies. These are local
results, not credentialed integration or clean container-build results.

See [review remediation](../phase-1-review-fixes.md) for the finding-to-fix map.
Docker/CI, real emulator persistence across restart, credentialed Gemini, and
synthetic deployed browser verification remain pending. Phase 2 was not started.
