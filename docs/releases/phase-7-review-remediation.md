# Phase 7 combined review and remediation

Date: 2026-10-02 (America/Los_Angeles).

Reviewed together, with a clean starting worktree:

- `e83f89e299a7a3da98a33a743758b3248847b6aa` — backend domain modules.
- `40ed00d444d3878337ad5a4799570f2da7f6bff7` — browser workbench.
- `f4dfc3a6f2bc1164d14e5d583df5977597ff636e` — implementation/evidence docs.

Review base: `d75e7f8`.

Remediation was implemented in the working tree based on starting HEAD
`f4dfc3a6f2bc1164d14e5d583df5977597ff636e`; no commit was created.

## Findings

1. **P1: availability policy can be weakened by a caller — addressed.** Both
   domain modules now retain caller constraints and independently add a
   marker-owned system constraint on every preparation. Regression coverage
   verifies `allow_unknown` remains present while the required system
   constraint stays fail-closed and preparation is idempotent.

2. **P1: lookup retries repeat provider work and conflict with themselves —
   addressed.** The repository contract now reserves an owner/domain/key
   fingerprint with a fence, stores completion as a comparison pointer, and
   records safe failures. Memory and Firestore implementations enforce the
   fence and owner/domain mapping. Completed retries return the saved
   comparison without even resolving an adapter; changed inputs conflict
   before provider dispatch. Concurrent work remains in-progress, known
   failures replay their error, and uncertain outcomes never dispatch again.
   Regression tests cover replay, changed input, concurrency, uncertain
   outcomes, stale fences, cross-owner mapping, and Firestore completion
   equivalence.

3. **P1: domain feature scoring bypasses conflict resolution — addressed.**
   Features now select only claim IDs admitted by shared `AttributeStatus`,
   exact scope, and current verification/freshness policy. Unresolved
   preference values are omitted from their denominator. Regression tests
   cover verified/unverified disagreement, stale/retracted claims, and scoped
   matches.

4. **P2: travel value scoring compares incompatible quantities — addressed.**
   With one applicable budget constraint, travel uses its exact price
   attribute, scope, and currency. Without a budget, it compares only
   candidates sharing one price basis, scope, and currency; insufficient or
   incomparable values produce no feature score. Shopping offer scoring also
   requires a comparable currency and scope.

5. **P2: provider timeout excludes queueing and whole-response duration —
   addressed.** Both HTTP adapters start one deadline before rate limiting,
   bound the transactional slot reservation and wait, wrap the request plus
   streamed body in that deadline, and reject queued work that cannot begin
   before it expires. Mock-transport tests cover queued and slowly streamed
   responses.

6. **P2: browser result validation misses rendered fields and policy links —
   addressed.** The client checks registration fields, comparison policy/state,
   candidate ranking and exclusion fields, cells, features, provider metadata,
   timestamps, and every source/policy link. HTTP and HTTPS public URLs are
   accepted. Malformed responses are shown as recoverable errors. UI tests
   cover valid HTTP links, absent rendered fields, and unsafe policy links.

## Verification and remaining gaps

Date: 2026-10-02 (America/Los_Angeles). Tested code: starting HEAD
`f4dfc3a6f2bc1164d14e5d583df5977597ff636e` plus the uncommitted working-tree
remediation. Offline regression checks remained credential-free.

- Focused domain and Firestore suite: 29 passed.
- `make backend-test`: 401 passed, 12 opt-in checks skipped, one upstream
  Starlette/httpx deprecation warning.
- `make backend-lint`: passed.
- `make context-eval`, `make memory-eval`, `make memory-lifecycle-eval`,
  `make research-eval`, `make decision-eval`, and `make domain-eval`: passed.
- `make frontend-test`: 64 passed across 12 files; `make frontend-lint` and
  `make frontend-typecheck`: passed.
- Python 3.11.15, bundled Node 24.19.0, and pnpm 11.19.0 were used; Node 22
  was not available on `PATH`. Frontend tests emitted Vite's existing CJS API
  deprecation notice.
- `git diff --check`: passed.

Real provider policies and smoke tests, Firestore emulator transactions,
cross-instance rate limiting, Gemini, deployed proxy/GCP, and earlier-phase
external checks remain unverified. No offline result is represented as external
verification. See the
[Phase 7 release record](phase-7-travel-shopping.md) for the complete check
list and test counts.

## Parent completeness pass

The parent additionally preserved caller constraints even when their source-record
marker matches a policy marker, and made registration storage keys include field,
feature, and source policy versions. Existing v1 registration records remain
auditable and cannot block v2 registrations. Three focused regression cases cover
these edges. Final parent checks: backend tests (404 passed, 12 opt-in skips),
backend lint, domain evaluation (10/10), and `git diff --check` passed. The earlier
frontend and other platform evaluation results remain applicable because this pass
changed only registration persistence and domain constraint preparation.
