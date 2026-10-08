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

Postgres owns canonical logical invocation and physical-attempt reservations/settlements, quota-bucket admission controls, and compact ledger aggregates; DynamoDB owns separately retained operational events and turn attribution. A lifecycle execution checkpoint is not a usage ledger. Unknown provider outcomes remain uncertain under their original attempt and reservation identities. Compact routing-decision observations are also Postgres-owned under the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md), but they are advisory history, not admission controls.

## Prerequisites and work ordering
Required phase: 18, plus Phase 10 persistence foundation.

## Phase-specific invariants
- Accounting failures do not silently change inference semantics; advisory versus admission-blocking failures are explicit.
- Store safe metadata only—no prompts/responses/secrets by default.
- Exact/derived/configured/unknown confidence states remain distinguishable.
- LiteLLM usage telemetry may supply observations but does not define Personal AI quota units, authority, or remaining-capacity certainty.
- One logical invocation may contain multiple physical dispatch attempts only when each actual send has its own attempt identity and admission/reservation; SDK/client-hidden sends are prohibited.
- `routing_decision_id` identifies the semantic endpoint selection. Same-endpoint physical retries retain it; a changed endpoint selection uses a new linked decision ID. Invocation/attempt accounting does not merge endpoint or credential attribution merely because quota buckets are shared.
- Operational records are stable and joinable; do not add learned-routing features, feature vectors, reward functions, or model-specific training data.

## Work packages

### P19.0 — Invocation lifecycle and scope
Give each logical external operation (generation, counting, summaries, extraction, embedding, worker model work, search, and lookup) a stable root `invocation_id`; give each physical provider/account send a distinct `attempt_id` linked to that root, its routing decision (where applicable), selected endpoint-profile version, and parent attempt. Carry owner/app/workspace/task plus opaque provider account/project/tier scope. Every actual send—including an explicitly permitted retry—requires its own pre-dispatch attempt admission/reservation and records actual send count. Reserve before dispatch; settle confirmed usage or conservatively retain unknown-outcome reservation. Correlation does not replace idempotency, and uncertainty never authorizes replay under a new identity. Disable implicit SDK/provider/HTTP retries so they cannot bypass attempt accounting.

**Acceptance:** All external operation families reserve each physical attempt before dispatch and settle known/unknown outcomes safely. Intercepted synthetic 429/known-failure, timeout/unknown-outcome, and nested SDK/client retry cases count actual sends; no send occurs after the cumulative attempt, deadline, token, or quota budget is exhausted.

Attribution consumes [distinct execution identities](../../03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes): provider, endpoint/profile version, account/project/tier, safe credential scope/class, execution/cost class, app/workspace/task, quota bucket, usage, status, and latency. Separate credential/account scopes for the same provider/model must not merge quota or billing attribution. Store references/classification only, never secrets. Representing explicit BYOK attribution adds no BYOK dispatch, invoices, monthly billing, cost dashboard, or automatic spending budgets.

Keep stable lineage fields equivalent to `invocation_id`, `attempt_id`, `parent_attempt_id`, `task_id`/profile version, `endpoint_profile_id`/version, nullable `routing_decision_id`, nullable `routing_strategy_id`/version until Phase 21, request/run correlation ID, registry/policy versions, and start/completion times. A known-safe retry of the identical endpoint plan has a new attempt ID and reuses the same decision ID. A different endpoint after quota reselection or cascade has a new routing-decision ID linked to the prior decision and remains under the same root operation/budgets. Record input/output count confidence and source alongside usage, latency, status, normalized error, retry/reselection lineage, rate-limit/quota attribution, and owner/application/workspace/task scope. Unknown quota and ambiguous outcomes remain explicitly unknown and fenced; no new attempt is dispatched from an unresolved unknown outcome.

### P19.1 — Quota windows and health
Represent unit/window/reset/source/confidence separately for each quota bucket; do not mix requests/day with tokens/minute or Cloudflare neurons. Bucket IDs represent provider/account quota authority, not endpoint or credential identity: endpoints/keys/models under one shared limit aggregate to the same bucket, and key rotation preserves that bucket's usage. Independently scoped free and paid accounts/modes never share capacity. Each dispatch resolves every applicable bucket and reserves all of them atomically under bounded concurrency; failure to reserve any bucket means no send and no partial authorization. Unknown/ambiguous bucket relationships follow the conservative admission rule in the shared [quota-bucket contract](../../03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes). Keep endpoint/account/credential attribution distinct even when usage rolls up to common buckets. Account-level quota is shared across users/apps; track attributable local usage separately and conservative unobserved external use. Record latency, success, 429/5xx/retries, cooldown and exact/derived/configured/unknown observations. Basic search admission/zero-overflow checks belong here; Brave requires verified prepaid/no-auto-reload/no-paid-balance configuration and source rights, with postpaid overflow excluded. Scarcity scoring waits for Phase 23.

**Acceptance:** Shared-account windows and header units/reset confidence remain distinct under concurrent owner usage. Two models/keys sharing an account exhaust a common bucket, credential rotation does not reset usage, independent paid/free accounts remain isolated, all required buckets reserve all-or-none, and snapshots preserve bucket IDs/units/confidence for replay.

**Provider extension acceptance:** Synthetic request/token/neuron/other-unit buckets use the same accounting operations without provider-name branches; compatible shared-account scopes aggregate correctly while distinct account/credential buckets remain separate. Existing Brave checks stay adapter/account-specific admission facts; they do not bind research to one search provider.

The routing observation store joins by decision ID, root invocation ID, physical attempt ID, and request/run correlation. Quota-bucket snapshots are advisory replay inputs; the Postgres reservation/settlement rows are the authoritative admission ledger. If an observation or turn reference is only partially published across Postgres and DynamoDB, reconcile by IDs and mark it incomplete/unknown; do not reconstruct the missing record from current profiles.

### P19.2 — Bounded persistence and developer summary
Store compact safe aggregates in Postgres and, where justified by Phase 10, high-volume append-only operational events in DynamoDB. Extend account inventory/export/deletion rules, documenting retained tombstones separately. Do not rely on paid TTL behavior for strict-$0 cleanup. Developer summaries never expose prompts, secrets or fabricated remaining quota. Account deletion/lifecycle closure remains an existing release obligation.

**Acceptance:** Safe summaries, bounded retention and account inventory work without paid TTL reliance or cross-store canonical duplication.

The [Routing Observation Contract](../../03-free-tier-inference-and-routing.md#routing-observation-contract) defines how invocation outcomes join later to a decision and strategy version. Persist stable semantic observations only; Phase 35 derives features from them.

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
