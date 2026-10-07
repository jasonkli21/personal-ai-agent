# Phase 35 implementation plan — Adaptive routing experiments

Renumbered from former Phase 27; deterministic hard-filter/rollback requirements are unchanged.

## Scope boundary

**Goal:** Explore learned routing only after measured deterministic, quota-aware, and cascade baselines exist.

### Normative commitments

- Experiment with complexity classifiers, RouteLLM-style concepts, or contextual bandits where data justifies them.
- Run offline/shadow first.
- Keep strict-free/privacy/capability/context/cooldown hard filters outside learning.
- Compare quality and quota use.

### Acceptance criteria

No production promotion without measurable benefit and deterministic rollback.

## Current state and reuse

No learned router exists. Reuse measured baselines from Phases 22–24 and safe compact evaluation/usage metadata; ChatGPT remains explicit-only and excluded from automatic learning candidates.

## Phase 10 storage dependency

Postgres owns compact evaluation profiles/summaries and Phase 20 GCS owns permitted raw artifacts. Preserve existing hypothesis, provenance, sensitivity and evaluation gates; storage assignment adds no experiment scope. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites

Required phases: 22, 23, and 24.

## Invariants

Learning ranks only already-eligible candidates; shadow cannot dispatch extra private/billable calls or alter user-visible routing; deterministic routing remains available.

## Work packages

### P35.0 — Offline learning dataset and candidate experiments

Build privacy-safe task/route/quality/quota/latency features from permitted versioned summaries with held-out splits/profile validity. Explore bounded candidate methods only if concrete data supports them; no mandatory external framework/provider expansion.

**Acceptance:** held-out data reproduces candidate experiments without exposing sensitive raw context.

### P35.1 — Shadow behind hard filters

Run candidates only after deterministic strict-free/privacy/capability/context/known-exhaustion filters. Shadow mode does not affect visible route or dispatch extra provider calls. ChatGPT is never an automatic candidate.

**Acceptance:** shadow cannot change visible routes or bypass any hard filter.

### P35.2 — Promotion evidence and rollback

Compare against deterministic/quota/cascade baselines for supported quality, quota conservation, latency, and uncertainty under provider/model churn. Define measurable thresholds and tested deterministic rollback. Failure cannot silently enable paid paths or alter hard policy.

**Acceptance:** any promotion has valid evidence and tested rollback.

## Requirement coverage

All four former Phase 27 commitments remain represented across P35.0–P35.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
