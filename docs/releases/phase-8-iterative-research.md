# Phase 8 iterative research release evidence

**Date:** 2026-10-03
**Tested revision:** `54048e5` (`codex/phase-6-decision-support`), containing the completed Phase 8 review remediation and final light pass.
**Environment:** Python 3.11.15, uv 0.11.13, pnpm 11.19.0, bundled Node 24.19.0.

Phase 8 adds separately gated, bounded iterative research over the existing
Phase 5 evidence pipeline and Phase 6 decision service. A saved run freezes its
dispatch and resource policy, fences its backing Phase 5 session, records
immutable assessment-qualified gap history, and charges provider uncertainty
conservatively. Supported typed price proposals include exact evidence IDs and
still pass through Phase 6 verification. Browser replay validates the saved
cursor and response shapes. Existing single-pass research remains the default;
all Phase 8 gates remain off.

## Offline verification

Checks run on 2026-10-03 against the working tree described above:

| Check | Result |
| --- | --- |
| Backend tests (`make backend-test`) | 433 passed, 12 skipped. |
| Backend lint (`make backend-lint`) | Passed (Ruff). |
| Context, memory, memory lifecycle, Phase 5 research, Phase 6 decision, and Phase 7 domain evaluations | Passed. |
| Phase 8 paired evaluation | Passed, 18/18 deterministic synthetic pairs, including a full three-query/six-assessment run and safe follow-up decision improvement. |
| Frontend tests (`make frontend-test`) | 78 passed across 13 files. |
| Frontend lint and typecheck | Passed. |
| Frontend production build | Passed. |
| Backend package build (`uv build --no-build-isolation`) | Passed with an isolated cache under `/private/tmp`. |
| `git diff --check` | Passed. |

The Phase 8 evaluator executes the real Phase 5 and Phase 8 services against
shared synthetic sources and deterministic clocks. It makes no judge-model or
external-provider calls. It includes verified decision improvement after a
follow-up and fail-closed stale, conflicting, wrong-variant, and wrong-scope
price cases. Regressions cover pending-session Phase 5 bypass, persistent gap
provenance, elapsed overrun during synthesis, exact hostnames, nonempty event
cursors, and malformed browser progress/details.

The frontend build emitted existing Autoprefixer and Next.js ESLint-plugin
configuration warnings. The backend suite emitted a Starlette/httpx
deprecation warning. Node 22 was unavailable; frontend checks used bundled
Node 24.19.0 and pnpm 11.19.0.

## Remaining verification gaps

No Firestore emulator, deployed GCP project, search provider, or model provider
was configured or contacted. Firestore transaction/restart behavior and index
readiness remain unverified in a deployed environment. Provider quotas,
attribution and actual billing are unverified; search and synthesis cost
entries remain configured estimates because the provider boundary exposes no
billing metadata. Browser disconnect behavior in deployment, public
authentication, and retention/deletion operations remain operational work.
The fixed `local` owner is not an authenticated personal-data boundary. No
Docker build was run. All iterative and progress gates remain disabled by
default.
