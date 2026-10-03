# Phase 8 iterative research release evidence

**Date:** 2026-10-03  
**Tested code revision:** `3674935a5159b4387daf93be8606f854635c1546`  
**Branch:** `codex/phase-6-decision-support`

Phase 8 adds separately gated, bounded iterative research over the existing
Phase 5 evidence pipeline and Phase 6 decision service. Runs persist a frozen
policy and budget snapshot, lease/revision-fenced transitions, named evidence
gaps, safe ordered events, and planned/settled ledger entries for iterations,
queries, sources, tokens, estimated provider cost, elapsed time, and allowed
domains. Follow-up proposals contain a permitted template and IDs tied to a
named gap; they cannot supply free-form facts, queries, or changed constraints.
The browser exposes iteration only after all server and public feature gates
are enabled. Existing single-pass research remains the default.

## Offline verification

The code revision above passed these checks on 2026-10-03:

| Check | Result |
| --- | --- |
| Backend tests (`.venv/bin/python -m pytest -q`) | 427 passed, 12 skipped |
| Backend lint (`.venv/bin/ruff check .`) | Passed |
| Context evaluation | Passed |
| Memory evaluation | Passed |
| Memory lifecycle evaluation | Passed |
| Phase 5 research evaluation | Passed |
| Phase 6 decision evaluation | Passed |
| Phase 7 domain evaluation | Passed |
| Iterative research evaluation | Passed, 13/13 paired synthetic cases |
| Frontend tests | 73 passed across 13 files |
| Frontend lint and typecheck | Passed |
| Backend package build (`uv build --no-build-isolation`) | Passed |
| Frontend production build | Passed |
| `git diff --check` | Passed |

The iterative evaluator executes the actual Phase 5 single-pass service and
Phase 8 orchestrator on each shared synthetic case; it does not call a judge
model or external provider. Cases include sufficient first-pass evidence,
missing and stale required evidence, conflicts, ambiguous identity, unavailable
evidence, repeated-query suppression, budget stops, domain exclusion,
cancellation fencing, and uncertain provider recovery. Tests include retry
restart at a durable safe boundary, Firestore-shaped owner/revision transaction
checks, expired citations, reconnect reads, safe event payloads, and disabled
defaults.

Verification used Python 3.11.15, uv 0.11.13, and pnpm 11.19.0. Node 22 was
unavailable in the environment; the bundled Node 24.19.0 runtime was used for
frontend checks. The frontend build emitted existing Autoprefixer and Next.js
ESLint-plugin configuration warnings, but completed successfully. The backend
test run emitted the existing Starlette/httpx deprecation warning.

## Remaining verification gaps

Docker was unavailable, so backend and frontend container builds were not run.
No Firestore emulator, deployed GCP project, search provider, or model provider
was configured or contacted. The Firestore repository tests use an offline
SDK-shaped fake; deployed transaction/restart behavior and index readiness
remain unverified. Real provider quotas, attribution rules, and billing are
unverified; cost values remain configured estimates because the current
provider boundary exposes no billing metadata. Production browser disconnect
behavior, public authentication, and retention/deletion operations remain
future operational work. The `local` owner is still not an authenticated
personal-data boundary. All iterative and progress gates remain disabled by
default.
