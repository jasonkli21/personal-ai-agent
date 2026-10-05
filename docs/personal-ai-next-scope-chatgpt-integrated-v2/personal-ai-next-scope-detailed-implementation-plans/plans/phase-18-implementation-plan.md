# Phase 18 implementation plan — Travel integration

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Validate the complete context + routing architecture on a lower-sensitivity app.

### Normative commitments from the integrated roadmap

- Implement Travel context providers.
- Exercise profile/current state/research/conversation/memory.
- Route through inference runtime.
- Add end-to-end tests/traces.
- Add sidecar to trip/day/place views with active trip/day/entity plus relevant preferences/research.
- Make included trip context visible.
- Support Copy and safe draft insertion where appropriate.
- Keep itinerary writes out of the generic response path until Phase 23.

### Phase acceptance criteria

- Travel stays authoritative.
- Core has no Travel branching.
- Provider route is inspectable.

### Explicitly out of scope

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

## Current state and reuse

Gated Nominatim place comparisons and itinerary proposals/booking extraction exist. Authoritative trip/day/booking app context is missing from this repository; local extraction acceptance is recorded, external release gates remain closed.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/domains/travel/models.py`
- `backend/src/personal_ai/domains/travel/module.py`
- `backend/src/personal_ai/domains/providers.py`
- `backend/src/personal_ai/domains/service.py`
- `backend/src/personal_ai/itinerary_proposals/contracts.py`
- `backend/src/personal_ai/itinerary_proposals/service.py`
- `backend/src/personal_ai/booking_extractions/contracts.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 7, 13, 16. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

**Conditional prerequisite:** additive sidecar integration consumes Phase 17.4. Baseline domain/backend work does not depend on live ChatGPT approval. Keep blocked sidecar work explicitly pending; do not declare the entire phase complete while any intended package is pending.

## Phase-specific invariants

- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.
- Generic sidecar output cannot write itinerary state in this phase.

## Work packages

### P18.0 — Travel-owned read adapters

**Depends on:** required phases above.

Pin the external Travel application contract/revision and verified owner/workspace membership mechanism before integration. Add domain-side typed bounded providers for profile/preferences, active trip/day/place/entity, current itinerary/booking state, selected history/research and attributed memory. Reuse shared evidence/comparison contracts; Nominatim is public place identity only, not lodging availability or private itinerary retrieval. Private booking context raises sensitivity despite public-place examples.

**Acceptance:** Bounded Travel reads expose only authorized typed profile/trip/day/entity context; public place providers are not booking authority.

### P18.1 — Core runtime integration and baseline

**Depends on:** P18.0.

Register Travel providers through ApplicationDefinition, prepare via shared planner/policy/builder and route through runtime. Trace source authority, expiry/permissions and actual provider. Extend end-to-end synthetic fixtures and Phase 14 baselines. Existing narrow proposal/extraction capabilities retain separate gates and validation; generic response does not write itinerary or confirm bookings.

**Acceptance:** Synthetic end-to-end traces preserve source freshness/privacy and never write itineraries through generic output.

### P18.2 — Additive sidecar hooks

**Depends on:** P18.1 and Phase 17.4 for sidecar work.

After Phase 17.4, attach the shared sidecar to trip/day/place views with relevant trip/day/entity/preferences/research categories visible and narrowable. Copy and non-authoritative draft insertion only. This work package is pending if live ChatGPT integration is externally blocked; Travel backend scope remains implementable and preserved. No duplicated sign-in or app-specific core branches.

**Acceptance:** Shared trip/day/place sidecar shows selected context and supports only Copy/permitted drafts after 17.4.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R18.1: Implement Travel context providers. | P18.0 |
| R18.2: Exercise profile/current state/research/conversation/memory. | P18.0 |
| R18.3: Route through inference runtime. | P18.1 |
| R18.4: Add end-to-end tests/traces. | P18.1 |
| R18.5: Add sidecar to trip/day/place views with active trip/day/entity plus relevant preferences/research. | P18.2 |
| R18.6: Make included trip context visible. | P18.2 |
| R18.7: Support Copy and safe draft insertion where appropriate. | P18.2 |
| R18.8: Keep itinerary writes out of the generic response path until Phase 23. | P18.1 |

## Targeted verification and closeout

Test scope membership, active trip/day bounds, stale evidence, sensitive booking denial, complete source provenance, narrow planner calls and no itinerary write. Sidecar tests use shared fake bridge, no private bookings.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make research-eval`, `make decision-eval`, `make domain-eval`, `make itinerary-proposal-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** External Travel repository/API ownership/auth compatibility and live mounted app UI/provider checks require pinned evidence; local fakes do not verify that application.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
