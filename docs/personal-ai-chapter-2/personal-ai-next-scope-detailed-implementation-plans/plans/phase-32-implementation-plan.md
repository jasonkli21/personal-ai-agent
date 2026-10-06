# Phase 32 implementation plan — Smarter context planning

Renumbered from former Phase 24 with baseline-before-LLM-planning requirements preserved.

## Scope boundary

**Goal:** Improve context selection only after deterministic planning has measured failure data.

### Normative commitments

- Evaluate misses/over-fetch.
- Add LLM-assisted planning only where justified.
- Route planner calls through the strict-free runtime.
- Keep permission constraints outside the model.
- Compare quality, token use, and latency.

### Acceptance criteria

Planner changes must demonstrate measurable improvement and deterministic fallback remains available.

## Current state and reuse

Phase 13 supplies deterministic planning fixtures; Phases 26–30 provide implemented domain/federation traces. No model planner is required absent measured benefit.

## Prerequisites

Required phases: 22 and 30.

## Invariants

No model call where deterministic rules suffice; model may propose selection but never authorize it; invalid/unavailable assisted planning returns the deterministic result without expanding access.

## Work packages

### P32.0 — Failure baseline and experiment criteria

Extend deterministic/evaluation fixtures with implemented domain/federation selections and held-out tasks. Quantify omitted relevant context, irrelevant/sensitive over-fetch, bytes/tokens, latency, and downstream support quality. Decide whether failures justify assisted planning and define promotion thresholds.

**Acceptance:** measured baseline identifies specific failures/thresholds; no mandatory LLM planner is assumed.

### P32.1 — Bounded assisted planner

For justified cases only, use minimized authorized planner inputs through the strict-free runtime/assembler/ledger. The model proposes a typed bounded selection; server policy validates every provider/field/window/cap. No new sources, arbitrary tools, all-app dump, or direct domain DB access.

**Acceptance:** assisted planning cannot authorize new access and invalid proposals fall back deterministically.

### P32.2 — Compare and rollback

Compare held-out quality/omission/over-fetch/tokens/latency against deterministic baseline. Version the experiment and default it off. Timeout/invalid/unavailable failures return deterministic selection. Promote only measured improvement with no authority/sensitivity regression.

**Acceptance:** paired metrics justify promotion or deterministic planning remains active.

## Requirement coverage

All five former Phase 24 commitments remain represented across P32.0–P32.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
