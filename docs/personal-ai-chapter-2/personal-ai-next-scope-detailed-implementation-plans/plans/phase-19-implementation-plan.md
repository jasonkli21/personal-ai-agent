# Phase 19 implementation plan — Provider usage accounting and quota ledger

Renumbered from former Phase 11 with scope preserved. Phase 10 persistence changes only the physical ownership of ledger/event records: compact queryable aggregates belong in Postgres; high-volume operational invocation events may use DynamoDB where the Phase 10 access-pattern map assigns them. No canonical ledger is duplicated.

## Scope boundary
**Goal:** Measure capacity before optimizing it.

### Normative commitments
- Record provider/model/task per invocation.
- Capture token usage where available.
- Record latency/success/429/5xx/retries.
- Add health/cooldown.
- Add quota/reset state with confidence/source.
- Expose compact developer summaries.

### Phase acceptance criteria
- Every normalized invocation is attributable.
- Unknown quota state remains unknown.

### Explicitly out of scope
- scarcity-aware route selection
- billing aggregation beyond project needs
- ChatGPT-plan opaque usage handling
- unbounded telemetry retention

## Current state and reuse
HTTP estimated reservations, iterative run ledgers and shared lookup throttles are partial reusable patterns. Full per-operation accounting/quota ledger is missing.

## Phase 10 storage dependency

Postgres owns canonical invocation reservations/settlements and compact ledger aggregates; DynamoDB owns separately retained operational events. A lifecycle execution checkpoint is not a usage ledger. Unknown provider outcomes remain uncertain under the original invocation identity. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites and work ordering
Required phase: 18, plus Phase 10 persistence foundation.

## Phase-specific invariants
- Accounting failures do not silently change inference semantics; advisory versus admission-blocking failures are explicit.
- Store safe metadata only—no prompts/responses/secrets by default.
- Exact/derived/configured/unknown confidence states remain distinguishable.

## Work packages

### P19.0 — Invocation lifecycle and scope
Add one bounded invocation/reservation identity per external operation: generation, counting, summaries, extraction, embedding, worker model work, search and lookup. Carry owner/app/workspace/task plus opaque provider account/project/tier scope. Reuse durable transaction/fence patterns. Reserve before dispatch; settle confirmed usage or conservatively retain unknown-outcome reservation. Correlation does not replace idempotency, and uncertainty never authorizes implicit retries.

**Acceptance:** All external operation families reserve once before dispatch and settle known/unknown outcomes safely.

### P19.1 — Quota windows and health
Represent unit/window/reset/source/confidence separately for each quota bucket; do not mix requests/day with tokens/minute or Cloudflare neurons. Account-level quota is shared across users/apps; track attributable local usage separately and conservative unobserved external use. Record latency, success, 429/5xx/retries, cooldown and exact/derived/configured/unknown observations. Basic search admission/zero-overflow checks belong here; Brave requires verified prepaid/no-auto-reload/no-paid-balance configuration and source rights, with postpaid overflow excluded. Scarcity scoring waits for Phase 23.

**Acceptance:** Shared-account windows and header units/reset confidence remain distinct under concurrent owner usage.

### P19.2 — Bounded persistence and developer summary
Store compact safe aggregates in Postgres and, where justified by Phase 10, high-volume append-only operational events in DynamoDB. Extend account inventory/export/deletion rules, documenting retained tombstones separately. Do not rely on paid TTL behavior for strict-$0 cleanup. Developer summaries never expose prompts, secrets or fabricated remaining quota. Account deletion/lifecycle closure remains an existing release obligation.

**Acceptance:** Safe summaries, bounded retention and account inventory work without paid TTL reliance or cross-store canonical duplication.

## Requirement coverage
| Requirement | Work packages |
| --- | --- |
| R19.1 invocation attribution | P19.0 |
| R19.2 token usage | P19.0 |
| R19.3 latency/status/retries | P19.1 |
| R19.4 health/cooldown | P19.1 |
| R19.5 quota/reset confidence/source | P19.1 |
| R19.6 compact developer summaries | P19.2 |
## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the phase-specific deterministic tests plus applicable backend/frontend test, lint, typecheck and build checks. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation evidence.
