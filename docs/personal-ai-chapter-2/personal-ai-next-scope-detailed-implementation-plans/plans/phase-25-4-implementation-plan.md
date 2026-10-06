# Phase 25.4 implementation plan — ChatGPT domain integration contract

Renumbered on 2026-10-06 from former next-scope Phase 17.4; domain-ownership and additive-scope requirements are preserved.

## Scope boundary

**Goal:** Define one reusable contract for Travel, Shopping, Finance, and Health so ChatGPT-specific UI/auth/provider logic is not duplicated per application.

### Normative commitments

- Standardize sidecar launch context around application/workspace/entity/view/conversation scope plus bounded client context.
- Reuse the existing planner/provider/policy/builder pipeline for inspectable `ContextPackage`; no parallel ChatGPT-only context system.
- Preserve domain authority and mutation validation.
- Standardize provider/model attribution and completed-turn persistence.
- Standardize Copy/Insert/Apply boundaries.
- Define sensitivity-aware domain hooks.
- Keep domain-specific behavior in later domain phases rather than core app-name branching.

### Acceptance criteria

- Domain apps integrate through one shared sidecar/context contract.
- No app implements its own ChatGPT token/auth stack.
- Domain context remains bounded, authorized, attributable, and sensitivity-aware.
- No authoritative domain state moves into Personal AI.
- Existing domain-phase scope remains intact; ChatGPT tasks are additive.

## Current state and reuse

Phase 25.2/25.3 supply shared sidecar/context/external-turn contracts. Domain launch adapters and sensitivity/action hooks are new integration contracts only.

## Prerequisites

Required phase: 25.3. Phase 10 remains the persistence boundary.

## Phase-specific invariants

- Domain apps remain authoritative for state and validation.
- Finance/Health may expose stricter/narrower context/action policy without forking the sidecar.
- Apply is declarative but remains disabled until Phase 31.

## Work packages

### P25_4.0 — Domain launch and read contract

Define versioned launch metadata for app/workspace/entity/view/conversation plus bounded advisory client context. Domain-owned adapters supply authorized typed source refs and consume the shared package; core never directly queries domain databases. Keep Personal AI workspace separate from ChatGPT account registration. Supply fake integration examples for all four apps without claiming real external app files.

**Acceptance:** four fake domain launches compose with one shared package/turn contract and no core domain-DB access.

### P25_4.1 — Sensitivity and action hooks

Expose narrow allowed context categories and policy-approved Copy/draft Insert. Finance/Health may further restrict fields/artifacts without forking credentials/UI. Apply remains disabled until Phase 31; domain validation and mandatory user confirmation remain required. Auth/model discovery/usage/producing-provider metadata come only from shared contracts.

**Acceptance:** domain policy can narrow context/actions without custom auth; Apply remains disabled.

### P25_4.2 — Integration handoff and boundary tests

Document domain-owned read/mutation API responsibilities and required repository/revision/transport verification before each live integration. Standardize post-completion callbacks without duplicating prepare/finalize. Prove a synthetic domain adds no core app-name branch, app-specific provider auth, or authoritative state in Personal AI.

**Acceptance:** integration boundaries preserve shared attribution/completion and domain authority.

## Requirement coverage

All seven former Phase 17.4 commitments remain represented by P25_4.0–P25_4.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
