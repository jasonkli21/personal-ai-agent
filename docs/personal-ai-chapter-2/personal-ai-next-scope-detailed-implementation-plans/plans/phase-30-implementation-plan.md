# Phase 30 implementation plan — Cross-app context federation

Renumbered from former Phase 22 with the same four initial federation cases and revocation/sensitivity rules.

## Scope boundary

**Goal:** Enable narrow, explicit, auditable cross-domain intelligence.

### Normative commitments

- Support four initial cases: Health dietary restrictions→Travel; Health ergonomic constraints→Shopping; Travel trip→Shopping; Finance discretionary budget→Shopping.
- Make cross-app categories visible when included in a ChatGPT sidecar request.
- Preserve the most restrictive effective sensitivity in ContextPackage.
- Require explicit user/context-policy permission exactly as for automatic inference.

### Acceptance criteria

Cross-app access is narrow/auditable, revocation blocks future retrieval/reuse, and routing reflects the most restrictive supplied sensitivity.

## Current state and reuse

Cross-app grants/federation are new. Phase 15 policy dependencies plus the domain providers in Phases 26–29 are prerequisites; same-owner identity alone never grants sharing. Durable grant/policy metadata is query-rich Postgres state after Phase 10.

## Prerequisites

Required phases: 15, 26, 27, 28, 29. Sidecar visibility additionally consumes Phase 25.4.

## Invariants

Destination apps cannot directly query another domain DB; revocation never mutates source truth; most restrictive source sensitivity controls downstream provider eligibility; sharing does not imply re-delegation.

## Work packages

### P30.0 — Explicit revocable grants

Define scoped category/field/entity/purpose grants with source/destination app/workspace, expiry, version, and revocation identity. User permission and source-domain policy must both allow selection before any provider call. Persist only bounded grant metadata in Postgres; do not create a global profile dump.

**Acceptance:** a valid scoped grant plus source policy is required before cross-app retrieval.

### P30.1 — Four bounded broker cases

Implement only the four named initial cases. Broker narrow domain-owned responses through registered providers, preserving source refs/authority and most restrictive sensitivity. Destination may not re-delegate beyond the grant. Stale membership/grant denies before source calls.

**Acceptance:** exactly the initial cases preserve narrow source identity/sensitivity with no over-fetch.

### P30.2 — Audit and derived-context revocation

Record safe grant/source/selection/exclusion IDs and propagate grant dependencies through conversation history/summaries, memory, caches, and artifacts. Revalidate at prepare/dispatch/finalize and later reuse. After Phase 25.4, show cross-app categories explicitly in sidecar packages using the same grants—no separate ChatGPT permission system.

**Acceptance:** revocation blocks fresh and derived reuse; sidecar shares the same policy.

## Requirement coverage

All four former Phase 22 commitments remain represented across P30.0–P30.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
