# Phase 24 implementation evidence

Date: 2026-10-09 (America/Los_Angeles). Tested base revision: `347f25523e48f6205aac6fb7790263e5592e9420` plus the Phase 24 working-tree changes. This record establishes local contract behavior only. See the [guide](phase-24-implementation-guide.md) for interfaces, implementation map and architecture audit.

## Delivered locally

- Extended the P21 task contract with `CascadePolicy`, preserving default task-quality digests when no cascade policy is present. Existing decision schemas remain readable.
- Added a bounded buffered coordinator, exact-endpoint preparer, frozen shared-context assembler and retained-chain replay.
- Extended the existing routing service with explicit auxiliary physical sends and shared reservation/claim/settlement helpers. P19 remains canonical for root physical attempts and quota; cumulative per-bucket/token checks read its existing tables under the existing request lock, including larger known actual use. No migration or duplicate mutable cascade state was added.
- Added typed versioned validators and source/constraint contracts, bounded terminal validation observations with attempt attribution, and shared structural/constraint checks reused by Phase 22 evaluation.
- Added synthetic full-path tests and opt-in Postgres linked-decision/cumulative-budget tests, plus the paired Phase 22 fixture baseline through P23/P24 and admitted count/generation attempts.

## Verification

The repository backend virtualenv supplies Python 3.11.15 and the pinned dependencies. The frontend uses the bundled Node runtime because `node` was absent from the initial shell PATH. Backend build uses `UV_CACHE_DIR=/private/tmp/personal-ai-phase24-uv-cache` because the normal uv cache is outside the sandbox's writable roots. These are command environment adjustments, not repository setup changes.

| Check | Result |
| --- | --- |
| Phase 24 targeted tests and paired evaluation | Passed: 20 phase-specific tests and one paired baseline; all task/transport fixtures are synthetic. |
| `make backend-test` | Passed: 1,094 tests; 76 opt-in/manual checks skipped, unverified. |
| `make backend-lint` | Passed. |
| `make backend-build` with writable temporary uv cache | Passed: wheel and source distribution. |
| `make frontend-test` | Passed: 98 tests in 19 files. |
| `make frontend-lint frontend-typecheck frontend-build` with bundled Node in PATH | Passed. Existing Next.js ESLint-plugin warning remains nonfatal. |
| `make cascade-eval` | Passed; direct default retained. |
| `make quota-scarcity-eval context-plan-eval` | Passed synthetic suites. |
| Postgres cascade integration tests | Two tests present and skipped without isolated DSN. Docker is not installed; locking, races, JSONB, cumulative SQL and migration application remain unverified. |
| Live provider, account/tier/privacy, cloud, deployed identity/revocation | Not run; unverified. |
| `git diff --check` and documentation link review | Passed; new/changed local documentation links resolve. |

The paired baseline accepts 20/20 cases in each arm, quality 1.0. Direct: 40 physical sends, 20 auxiliary counts, 17,188 reserved input tokens, 320 output tokens, 40 shared quota units, modeled 300 ms. Cascade: 54 sends, 27 auxiliary counts, 23,171 input tokens, 432 output tokens, 54 shared units, modeled 405 ms, seven rejected intermediate responses. Counts and latency are synthetic fixtures; this establishes neither real tokenizer accuracy nor real provider performance. It does not justify promotion.

## Intentional interpretations and retained gates

The implemented execution-plan seam is the existing preparation identity and dispatch permit; an additional stateful `ExecutionPlan` would duplicate P21 ownership. Cascade depth uses the existing linked-reselection budget and the bounded configured order. Same-endpoint retries are intentionally not enabled, so no extra retry identity or SDK retry layer is needed. A missing/denied preparation aborts, and uncertain sends are never replayed under a new identity.

Fixture-only preparation is explicitly marked synthetic and requires a synthetic-test-attested endpoint; live preparation requires an authoritative endpoint counter identity.

Application workflows remain Gemini-only, no production task registers a cascade by default, and Phase 15 membership/revocation acceptance remains a prerequisite. Groq/Cloudflare still lack authoritative matching counters. No live promotion, private-domain disclosure, itinerary mutation, paid escalation or ChatGPT spillover occurred. Optional artifact gates remain off and replay does not require GCS.

Root README was reviewed and its architecture/status paragraph was updated to describe the internal bounded coordinator and existing authorization gate. Adjacent Phase 23 quota ownership, Phase 25 separate execution mode, Phase 26 domain authority and Phase 35 future strategy replacement remain intact.

## Independent-review focus

Review the request/root lock ordering and cumulative P19 SQL against real PostgreSQL; physical count/claim identities and failed/unknown recovery; the trusted runtime-resolver contract (one send, zero hidden retries, no nested accounting); exact-source/permission projection and source-rights retention inputs; validation-event bounds and historical digest compatibility; and the distinction between synthetic paired evidence and live adoption. Current Phase 14/15 source-version and revocation gaps remain unresolved prerequisites, not exceptions granted by this phase.
