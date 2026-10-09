# Phase 24 implementation evidence

Date: 2026-10-09 (America/Los_Angeles). Tested revision: `10df3b31eb02b1093f27849d1d0f9a653b006e71` plus the focused review-fix working tree. This record establishes local contract behavior only. See the [guide](phase-24-implementation-guide.md) for interfaces, implementation map and architecture audit.

## Delivered locally

- Extended the P21 task contract with `CascadePolicy`, preserving default task-quality digests when no cascade policy is present. Existing decision schemas remain readable.
- Added a bounded buffered coordinator, exact-endpoint preparer, frozen shared-context assembler and retained-chain replay.
- Extended the existing routing service with explicit auxiliary physical sends and shared reservation/claim/settlement helpers. P19 remains canonical for root physical attempts and quota; cumulative per-bucket/token checks read its existing tables under the existing request lock, including larger known actual use. No migration or duplicate mutable cascade state was added.
- Added typed versioned validators and source/constraint contracts, bounded terminal validation observations with attempt attribution, and shared structural/constraint checks reused by Phase 22 evaluation.
- Added synthetic full-path tests and opt-in Postgres linked-decision/cumulative-budget tests, plus the paired Phase 22 fixture baseline through P23/P24 and admitted count/generation attempts.
- Bound Phase 24 generator/counter adapters to the complete selected endpoint profile and registered counter ID; reject nested P19 accounting, transport retries, and multi-request calls before provider IO.
- Derived frozen-source authorization hashes from canonical context-item identity, provenance, permissions, expiry, and content digest; support multiple items per source and abort on revocation.
- Added safe P21 linked reselection for classified known endpoint-local pre-dispatch failures, total input/output window checks at final authority, database-clock deadline/expiry handling, and incomplete-chain replay rejection.
- Extended the opt-in Postgres test to use the canonical `EndpointInputPreparer` count-plus-generation path with real P19/P21 persistence and synthetic transport callbacks.
- Added an in-memory P19/P21 integration through the real LiteLLM Gemini counter and generator over fake HTTP. It verifies one outer attempt per request, rejects an accounting-enabled gateway before sending, and preserves the original unknown generation attempt without a retry.

## Verification

The repository backend virtualenv supplies Python 3.11.15 and the pinned dependencies. The frontend uses the bundled Node runtime because `node` was absent from the initial shell PATH. Backend build uses `UV_CACHE_DIR=/private/tmp/personal-ai-phase24-uv-cache` because the normal uv cache is outside the sandbox's writable roots. These are command environment adjustments, not repository setup changes.

| Check | Result |
| --- | --- |
| Phase 24 targeted tests and paired evaluation | Passed, including the real LiteLLM gateway/P19 integration; all HTTP responses are synthetic fixtures. |
| Full backend suite (`.venv/bin/python -m pytest -q`) | Passed: 1,109 tests; 76 opt-in/manual checks skipped, unverified. Two existing dependency warnings (Starlette/httpx deprecation and Pydantic `ReadOnly` notice). |
| Backend lint (`.venv/bin/ruff check .`) | Passed. |
| `make backend-build` with writable temporary uv cache | Passed: wheel and source distribution. |
| `make frontend-test` | Passed: 98 tests in 19 files. |
| `make frontend-lint frontend-typecheck frontend-build` with bundled Node in PATH | Passed. Existing Next.js ESLint-plugin warning remains nonfatal. |
| `make cascade-eval` | Passed; direct default retained. |
| `make quota-scarcity-eval context-plan-eval` | Passed synthetic suites. |
| Postgres cascade integration tests | Two tests present; skipped without isolated DSN. The test code now uses the canonical count-plus-generation path with synthetic transport callbacks, but locking, races, JSONB, cumulative SQL and migration application remain unverified. |
| Live provider, account/tier/privacy, cloud, deployed identity/revocation | Not run; unverified. |
| `git diff --check` and documentation link review | Passed; new/changed local documentation links resolve. |

The paired baseline accepts 20/20 cases in each arm, quality 1.0. Direct: 40 physical sends, 20 auxiliary counts, 17,188 reserved input tokens, 320 output tokens, 40 shared quota units, modeled 300 ms. Cascade: 54 sends, 27 auxiliary counts, 23,171 input tokens, 432 output tokens, 54 shared units, modeled 405 ms, seven rejected intermediate responses. Counts and latency are synthetic fixtures; this establishes neither real tokenizer accuracy nor real provider performance. It does not justify promotion.

## Review fixes and retained gates

The implemented execution-plan seam remains the existing preparation identity and dispatch permit; an additional stateful `ExecutionPlan` would duplicate P21 ownership. Cascade depth uses the existing linked-reselection budget and the bounded configured order. Each configured stage reserves capacity for one exact count and one generation. Known endpoint-local pre-dispatch failures can use a linked child after the parent is terminal; privacy/source-policy failures, root budget/deadline exhaustion, runtime-binding errors, and uncertain sends abort. Uncertain sends are never replayed under a new identity. Replay reports interrupted or unclassified terminal chains as unavailable.

Fixture-only preparation is explicitly marked synthetic and requires a synthetic-test-attested endpoint; live preparation requires an authoritative endpoint counter identity bound to the exact selected profile, account/credential scopes, runtime, serializer, and cost lane. Nested gateway accounting and HTTP retries are rejected.

Frozen context authorization digests are derived from each context item rather than accepted as independent caller assertions. The digest covers source and item IDs, provider/version, source references, permission dependencies, expiry, and a content hash. Multiple context items can share a source ID. Source revocation/expiry aborts rather than being treated as optional source narrowing. Persisted lifecycle timestamps and deadline/expiry decisions use the routing store clock; provider timeout duration is derived from that clock at each physical-send boundary.

Application workflows remain Gemini-only, no production task registers a cascade by default, and Phase 15 membership/revocation acceptance remains a prerequisite. Groq/Cloudflare still lack authoritative matching counters. No live promotion, private-domain disclosure, itinerary mutation, paid escalation or ChatGPT spillover occurred. Optional artifact gates remain off and replay does not require GCS. Live provider/account/privacy checks, source-rights revocation acceptance, and the real Postgres integration run remain unverified.

Root README was reviewed and its architecture/status paragraph was updated to describe the internal bounded coordinator and existing authorization gate. Adjacent Phase 23 quota ownership, Phase 25 separate execution mode, Phase 26 domain authority and Phase 35 future strategy replacement remain intact.

## Independent-review focus

Review the request/root lock ordering and cumulative P19 SQL against real PostgreSQL; physical count/claim identities and failed/unknown recovery; the trusted runtime-resolver contract (one send, zero hidden retries, no nested accounting); exact-source/permission projection and source-rights retention inputs; validation-event bounds and historical digest compatibility; and the distinction between synthetic paired evidence and live adoption. Current Phase 14/15 source-version and revocation gaps remain unresolved prerequisites, not exceptions granted by this phase.
