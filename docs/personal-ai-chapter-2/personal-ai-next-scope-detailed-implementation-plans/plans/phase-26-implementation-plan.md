# Phase 26 implementation plan — Travel integration

Renumbered from former Phase 18 with its complete context/routing/sidecar boundary preserved.

## Scope boundary

**Goal:** Validate the complete context + routing architecture on a lower-sensitivity domain application.

### Normative commitments

- Implement Travel context providers.
- Exercise profile/current state/research/conversation/memory.
- Route through the shared inference runtime and add end-to-end tests/traces.
- Add the shared sidecar to trip/day/place views with active trip/day/entity plus relevant preferences/research.
- Make included trip context visible.
- Support Copy and safe draft insertion where appropriate.
- Keep itinerary writes out of the generic response path until Phase 31.

### Acceptance criteria

- Travel stays authoritative; core has no Travel-specific orchestration branch; provider route is inspectable.

### Explicitly out of scope

- itinerary mutation execution;
- cross-app Health/Finance context;
- Travel database migration into Personal AI;
- unrelated new Travel product scope.

## Current state and reuse

Reuse current gated place comparisons and itinerary proposal/booking-extraction capability boundaries. Authoritative trip/day/booking state comes from the external Travel app contract, not Personal AI storage. Research evidence remains separate from itinerary truth.

## Prerequisites

Required phases: 15, 21, and 24. Sidecar work additionally requires Phase 25.4. Phase 10 remains the persistence foundation. Baseline domain/backend work may proceed if optional ChatGPT external gates are still pending, but the phase is not fully complete while intended sidecar work remains pending.

## Phase-specific invariants

- Providers return bounded typed Travel-owned references.
- Public place evidence is never private booking authority.
- Generic model output cannot mutate itinerary state in this phase.

## Work packages

### P26.0 — Travel-owned read adapters

Pin external Travel contract/revision and owner/workspace membership. Add bounded typed providers for profile/preferences, active trip/day/place/entity, itinerary/booking state, selected history/research, and attributed memory. Reuse shared evidence/comparison semantics. Private booking context raises sensitivity even when surrounding place data is public.

**Acceptance:** only authorized typed Travel state is returned; public place sources are not treated as booking authority.

### P26.1 — Shared runtime integration and baseline

Register providers through `ApplicationDefinition`, prepare via shared planner/policy/builder, and route through runtime/ledger. Trace source authority, expiry/grants, and actual model/provider. Extend synthetic end-to-end and evaluation baselines. Existing proposal/extraction gates remain separate; generic response performs no itinerary/booking write.

**Acceptance:** synthetic traces preserve source freshness/privacy and never write itinerary state through generic output.

### P26.2 — Additive shared-sidecar hooks

After Phase 25.4, attach the shared sidecar to trip/day/place views with relevant trip/day/entity/preferences/research categories visible and narrowable. Copy and non-authoritative draft insertion only. No duplicated sign-in or app-specific core branch.

**Acceptance:** shared sidecar previews included trip context and supports only safe actions before Phase 31.

## Requirement coverage

All eight former Phase 18 commitments remain represented across P26.0–P26.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
