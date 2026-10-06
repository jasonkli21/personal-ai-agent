# Phase 29 implementation plan — Health integration

Renumbered from former Phase 21 with all sensitive-domain requirements preserved.

## Scope boundary

**Goal:** Integrate the most sensitive/flexible domain without weakening memory, provider, artifact, or mutation policy.

### Normative commitments

- Start with read-only Health providers.
- Support flexible structured profile and bounded time queries.
- Apply field sensitivity and strict provider eligibility using minimal context.
- Allow mutation proposals only under domain rules.
- Add read-only sidecar with human-readable sensitive context categories and narrowing controls where practical.
- Require Health authorization before a category can be offered.
- Prevent generic sidecar output from directly editing medications, conditions, measurements, or clinical records.
- Verify native-mobile SIWC support before mobile credential logic; preserve the Health roadmap regardless.

### Acceptance criteria

Health is not flattened into memory; cross-app Health is deny-by-default; routing cannot weaken sensitivity; sensitive verbose artifacts default to minimal/no retention.

## Current state and reuse

No Health app/provider exists in core. Existing memory policy deliberately rejects sensitive medical extraction; Health integration must not weaken it.

## Prerequisites

Required phases: 15, 21, 24; sidecar work additionally requires Phase 25.4. Phase 10 remains the persistence foundation.

## Invariants

Unauthorized categories are not fetched then hidden; most restrictive field sensitivity governs downstream; medications/conditions/measurements/clinical records remain domain-owned and cannot be edited by generic output.

## Work packages

### P29.0 — Read-only typed Health providers

Pin external Health contract/revision/membership. Expose flexible domain-typed profile/categories and bounded time-query data, preserving source/effective time, units, uncertainty, and field sensitivity. Do not create an untyped global profile or memory dump. Deny cross-app use by default.

**Acceptance:** Health responses are domain-typed, bounded, and never flattened into memory.

### P29.1 — Minimal sensitive context

Authorize category before offering/fetching it. Apply field/window/result limits and sensitivity join; enforce eligible generation/count/embedding/summary paths and minimal/no verbose artifact retention. Refuse if no endpoint can safely handle selected data. Keep memory extraction restrictions and source attribution intact.

**Acceptance:** sensitive categories are denied before calls and verbose retention stays minimal/off by default.

### P29.2 — Sidecar and proposal hooks

After Phase 25.4, show only authorized human-readable categories with narrowing controls. Copy/permitted drafts only. Medication/condition/clinical edits require a typed Phase 31 proposal plus Health validation/confirmation and may remain forbidden. Verify native-mobile SIWC mechanics before native credentials; a blocked optional lane must not block baseline Health read architecture.

**Acceptance:** sidecar offers no unauthorized category or generic clinical edit; mobile capability remains separately gated.

## Requirement coverage

All nine former Phase 21 commitments remain represented across P29.0–P29.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
