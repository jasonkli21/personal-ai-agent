# Phase 31 implementation plan — Mutation proposal framework

Renumbered from former Phase 23 with all typed proposal, confirmation, idempotency, and domain-authority requirements preserved.

## Scope boundary

**Goal:** Standardize AI-assisted edits without making Personal AI authoritative.

### Normative commitments

- Define a typed mutation proposal carrying target app/entity/operation/patch/rationale/source/validation/confirmation/idempotency.
- Add domain validation callbacks.
- Require explicit user confirmation before AI-assisted authoritative writes.
- Return authoritative post-state.
- Expose sidecar Apply only after output becomes a validated typed proposal.
- Treat producing provider, including ChatGPT, as provenance rather than write authority.

### Acceptance criteria

No arbitrary direct writes; domain validation is mandatory; mutation trace is auditable and retries are idempotent.

## Current state and reuse

Reuse existing narrow itinerary-proposal opaque-handle/fenced-replay patterns without turning them into generic direct writes. Durable proposal/evaluation metadata is Postgres-owned after Phase 10; domain state stays external/authoritative.

## Phase 10 storage dependency

Postgres owns proposal/evaluation/result/reconciliation metadata; domain APIs remain authoritative for mutations. Reuse stable identities and uncertain-outcome fencing without treating a runtime checkpoint as proof of an external domain commit. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites

Required phases: 15, 26, 27, 28, 29. Sidecar Apply consumes Phase 25.4.

## Invariants

Domain validates/authorizes after proposal creation and before write; confirmation binds the exact validated version; unknown outcomes reconcile with the same domain operation key; provider/model is provenance only.

## Work packages

### P31.0 — Typed proposal framework

Define target app/workspace/entity, versioned domain operation/patch, rationale/source refs, producing-provider provenance, expected domain version, validation/confirmation state, expiry, and idempotency identity. Preserve opaque handles/exact evidence. Unsupported operations fail explicitly; extraction candidates are not confirmed mutations.

Mutation support is an optional typed [Application Integration Contract](../../02-target-architecture.md#application-integration-contract) capability. Generic orchestration owns proposal identity, target scope, operation ID/version, typed payload, expected version, provenance, validation/confirmation/idempotency, and reconciliation state. Domain capabilities own authorization, business validation, authoritative write, and authoritative post-state. Domain operation names belong in registration/adapters/validators, not generic mutation control-flow branches.

**Acceptance:** only supported typed operations with source/version/idempotency metadata become proposals.

### P31.1 — Domain validate, confirm, execute

Domain validates current authorization/business rules/version and preview. User confirms the exact validated proposal. Execute only through authoritative domain API and return authoritative post-state/ref. Distinguish rejected/applied/uncertain and reconcile unknown outcome under original idempotency key rather than blindly resending.

**Acceptance:** validation and exact confirmation precede write; uncertain apply reconciles safely.

**Extension acceptance:** A synthetic safe versioned operation uses registered domain validation/execution/reconciliation through the same proposal controller without domain-specific orchestration edits. Exact confirmation, authorization, idempotency, and uncertain-outcome fencing remain mandatory.

### P31.2 — Shared sidecar Apply and adapters

After Phase 25.4, expose Apply only for domain-declared operations that convert output into typed proposals. Prevent double-click/retry duplication. Finance/Health can refuse sensitive operations regardless of confirmation. Preserve narrow existing proposal flows and add shared status/trace without direct DB access.

**Acceptance:** Apply consumes typed proposals/authoritative post-state and unsupported sensitive operations remain unavailable.

## Requirement coverage

All seven former Phase 23 commitments remain represented across P31.0–P31.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
