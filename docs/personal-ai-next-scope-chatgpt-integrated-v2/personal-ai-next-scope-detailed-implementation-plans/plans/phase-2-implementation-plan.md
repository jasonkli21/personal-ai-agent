# Phase 2 implementation plan — Application registry and manifest model

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Move app capabilities/policy into registration.

### Normative commitments from the integrated roadmap

- Define `ApplicationDefinition`.
- Add registry.
- Register providers/tools/memory/sensitivity/cross-app metadata.
- Add initial app definitions/stubs.

### Phase acceptance criteria

- Adding an app does not require core branching.
- Invalid definitions fail clearly.

### Explicitly out of scope

- real domain context adapters
- cross-app grants
- provider routing policy
- domain mutations

## Current state and reuse

DomainModule comparison definitions and registry validation patterns are reusable. ApplicationDefinition and application registration are genuinely missing.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/domains/contracts.py`
- `backend/src/personal_ai/domains/registry.py`
- `backend/src/personal_ai/api/dependencies.py`
- `backend/src/personal_ai/settings.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 1. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Core orchestration must route by manifest/capabilities rather than `if application_id == ...` branches.
- Unknown applications fail closed with stable errors.
- Initial domain entries may be stubs until their later integration phases.

## Work packages

### P2.0 — Application definition

**Depends on:** required phases above.

Add a small typed, versioned ApplicationDefinition adjacent to existing domain contracts: canonical ID, supported workspace kind, bounded context-provider/tool identifiers, memory namespace, sensitivity defaults, cross-app declaration and optional budget hints. Do not make DomainModule own editable application state. Validate duplicate IDs, unknown references, contradictory policies and unsupported schema versions on registration.

**Acceptance:** Invalid/duplicate definitions fail before registration; comparison modules retain their existing contracts.

### P2.1 — Registry and initial manifests

**Depends on:** P2.0.

Resolve application metadata through dependency wiring rather than orchestration app-name branching. Register standalone and explicit Travel/Shopping/Finance/Health manifests; unimplemented providers/actions are declared unavailable stubs, not fictional working capabilities. Reuse comparison-module definitions by composition where applicable. Unknown apps fail closed. Registration advertises capability but grants no access.

**Acceptance:** Registered stubs report unavailable and an unknown app is denied.

### P2.2 — Consumer contract

**Depends on:** P2.1.

Thread the selected definition into scoped services/context requests with deterministic lookup and no provider/model selection. Make registration independently fake-testable; adding a synthetic app must require a definition plus provider registration, not core conditional logic.

**Acceptance:** A synthetic application can be added without core app-name branching.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R2.1: Define `ApplicationDefinition`. | P2.0 |
| R2.2: Add registry. | P2.1 |
| R2.3: Register providers/tools/memory/sensitivity/cross-app metadata. | P2.0 |
| R2.4: Add initial app definitions/stubs. | P2.1 |

## Targeted verification and closeout

Test invalid/duplicate manifests, unknown applications, stub unavailability, standalone compatibility and adding a synthetic application without changing core orchestration.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
