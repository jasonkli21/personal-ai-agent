# Phase 1 vertical-slice verification record

**Latest local verification:** 2026-10-01

**Tested revision:** `7301bdd` (working tree had a README-only modification)

## Local verification

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
and 8 frontend passes. The latest counts include subsequent review hardening.

## Cloud verification

No credentialed GCP deployment or Gemini smoke test was performed in this
session because no GCP access or provider key was supplied. The required
post-deploy procedure is in the [deployment checklist](../phase-1-deployment-checklist.md).
This record contains no keys, URLs, or chat content.

Firestore Emulator persistence and automated client-disconnect integration
also remain unverified. See the [verification closeout plan](../phase-1-verification-plan.md).
