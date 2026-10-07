# Phase 27 implementation plan — Shopping integration

Renumbered from former Phase 19 with project-state, evidence, constraint, routing, and sidecar scope preserved.

## Scope boundary

**Goal:** Validate project state, external evidence, deterministic constraints, and routed AI assistance.

### Normative commitments

- Implement Shopping providers.
- Feed structured requirements to product research.
- Preserve hard/soft constraints and saved/rejected products.
- Evaluate routing for extraction/rewrite/synthesis.
- Add shared sidecar to project/search/comparison/product views with explicitly selected products and active requirements.
- Show selected context before ChatGPT send.
- Support Copy and non-authoritative draft insertion.
- Keep shortlist/requirement mutations behind Phase 31.

### Acceptance criteria

Recommendations reflect project state; deterministic constraints remain authoritative; Personal AI does not own Shopping state.

## Current state and reuse

Reuse current catalog-comparison/identity/evidence/ranking seams. Shopping project/requirements/shortlist authoritative state remains external and arrives through domain providers.

## Prerequisites

Required phases: 15, 21, 24; shared sidecar work additionally requires Phase 25.4. Phase 10 remains the persistence foundation.

## Invariants

Saved/rejected state is authoritative domain state, current prices/availability/reviews remain freshness-bearing evidence, and generic sidecar output cannot mutate shortlist/requirements in this phase.

## Work packages

### P27.0 — Shopping-owned project providers

Pin authoritative app read/membership contracts; expose typed bounded requirements, hard/soft constraints, active project, selected/saved/rejected products, and history. Core owns none of the project/shortlist DB. Preserve exact catalog/entity identity; public catalog data does not become current merchant offer/review/availability authority. Sensitive/private budget preferences raise sensitivity.

**Acceptance:** bounded project/product context preserves domain ownership and exact identity.

### P27.1 — Research and routed task baseline

Feed structured requirements into bounded product research. Unknown/conflicting/stale required attributes remain failures rather than guessed values. Route actual extraction/rewrite/synthesis tasks through runtime/ledger while deterministic filters remain authoritative. Record evidence freshness/rights and task-quality baselines; no unbounded merchant crawling or checkout.

**Acceptance:** hard constraints/rejections/current evidence remain authoritative through routed fixtures.

**Reference integration acceptance:** Shopping validates deterministic constraints, evidence-heavy comparisons, and saved/rejected project state through the [Application Integration Contract](../../02-target-architecture.md#application-integration-contract). Work primarily implements/registers domain capabilities and validators. Generic orchestration changes must repair a demonstrated shared deficiency without app-name branches and retain synthetic-app compatibility; all existing research/routing/sidecar scope remains required.

### P27.2 — Additive sidecar hooks

After Phase 25.4, attach shared sidecar to project/search/comparison/product views with selected products and active requirements visible before send. Enable Copy/permitted non-authoritative drafts only; authoritative shortlist/requirement writes wait for Phase 31.

**Acceptance:** selected context is visible and sidecar cannot mutate authoritative Shopping state before Phase 31.

## Requirement coverage

All nine former Phase 19 commitments remain represented across P27.0–P27.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
