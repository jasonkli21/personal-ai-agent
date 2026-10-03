# Phase 9 implementation evidence

**Date:** 2026-10-03

**Tested code revision:** `dd27cc0`

**Environment:** local synthetic tests; no cloud credentials or real provider calls

## Automated checks

| Check | Result |
| --- | --- |
| Backend tests (`python -m pytest -q`) | 458 passed, 12 skipped; one Starlette `httpx` deprecation warning |
| Backend lint (`python -m ruff check .`) | Passed |
| Backend package build (`uv build --no-build-isolation`) | Passed; source distribution and wheel produced |
| Context evaluation | 5/5 fixtures passed |
| Memory evaluation | 14/14 fixtures passed |
| Memory lifecycle evaluation | 60/60 fixtures passed |
| Frontend tests (`pnpm run test`) | 82 passed across 15 files |
| Frontend lint and TypeScript typecheck | Passed |
| Frontend production build | Passed; existing autoprefixer warning in `domain-workbench.module.css` and Next.js ESLint-plugin configuration warning remain |
| Deployment shell syntax (`bash -n infrastructure/gcp/deploy.sh`) | Passed |
| `git diff --check` and internal Markdown links | Passed |

The frontend checks used the bundled Node `v24.19.0` runtime because Node 22
was not available on `PATH`; Node 22 compatibility was not verified. Docker
was unavailable, so image builds were not run.

## Not verified outside the repository

- Google sign-in, production token/key rotation, Cloud Run IAM, Firestore
  transactions/indexes/TTL, Pub/Sub retries, Cloud Scheduler OIDC, and the
  migration tool were not exercised against a Google project or emulator.
- No staging or production deployment was performed. No provider account,
  terms, retention, training, or residency setting was reviewed.
- No Firestore backup schedule was created and no restore or deletion-aware
  restore drill was run. The script's optional schedule support does not
  establish recovery readiness.
- Export was not compared with Firestore records or downloaded in a browser.
  Deletion confirmation still ends at `confirmed_pending_operator`; it does
  not physically delete owner data, derived records, or backups.
- Cloud dashboards/alerts and provider usage reconciliation are not
  provisioned. Daily budgets conservatively reserve requests and tokens and
  do not settle against actual provider usage.
- P9.9 has no versioned release-result artifact, promotion-blocking workflow,
  or staging readiness rehearsal.

Phase 9 therefore remains incomplete. Keep production access and gated account
operations off until the open rows in the [release checklist](phase-9-release-checklist.md)
have dated evidence and operator approval.

## Post-implementation review (2026-10-03)

The [repository review](repository-review-2026-10-03.md) records fixes and
remaining findings against `4ff354b6f881fa87550fd442b5b5240c365f86e5` plus its
uncommitted cleanup changes. The final backend suite passed 501 tests with
12 opt-in checks skipped; the frontend passed 95 tests across 19 files. All
seven evaluations, lint/typechecks, package/frontend builds, offline lockfile
validation, deployment syntax/fake-CLI checks and documentation consistency
checks passed. The final frontend pass used Node 22.23.3; an earlier Node 24
pass also included a loopback production startup smoke. Python 3.12, Docker,
real providers, emulator and cloud behavior remain unverified.

The review found the original generic owner rewrite unsafe for strict schemas,
nested ownership and owner-derived keys. Apply now supports chat-only legacy
data and refuses unsupported collections before writes. Full Phase 3–8
migration remains open. Provider budgets are request estimates rather than
complete provider accounting. Deletion, restore, operational release and
external acceptance gaps above remain open.
