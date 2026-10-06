# Phase 2 implementation plan — Application registry and manifest model

Status: completed. This preserved plan records the completed next-scope Phase 2 scope. Later renumbering and the Phase 10 persistence migration do not rewrite its historical implementation claims.

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

DomainModule comparison definitions and registry validation patterns are reusable. ApplicationDefinition and application registration were the missing scope addressed by this phase.

## Prerequisites and work ordering

Required phase: 1.

## Phase-specific invariants

- Core orchestration must route by manifest/capabilities rather than `if application_id == ...` branches.
- Unknown applications fail closed with stable errors.
- Initial domain entries may be stubs until their later integration phases.

## Work packages

### P2.0 — Application definition

Add a small typed, versioned ApplicationDefinition adjacent to existing domain contracts: canonical ID, supported workspace kind, bounded context-provider/tool identifiers, memory namespace, sensitivity defaults, cross-app declaration and optional budget hints. Do not make DomainModule own editable application state. Validate duplicate IDs, unknown references, contradictory policies and unsupported schema versions on registration.

**Acceptance:** Invalid/duplicate definitions fail before registration; comparison modules retain their existing contracts.

### P2.1 — Registry and initial manifests

Resolve application metadata through dependency wiring rather than orchestration app-name branching. Register standalone and explicit Travel/Shopping/Finance/Health manifests; unimplemented providers/actions are declared unavailable stubs, not fictional working capabilities. Reuse comparison-module definitions by composition where applicable. Unknown apps fail closed. Registration advertises capability but grants no access.

**Acceptance:** Registered stubs report unavailable and an unknown app is denied.

### P2.2 — Consumer contract

Thread the selected definition into scoped services/context requests with deterministic lookup and no provider/model selection. Make registration independently fake-testable; adding a synthetic app must require a definition plus provider registration, not core conditional logic.

**Acceptance:** A synthetic application can be added without core app-name branching.

## Requirement coverage

| Requirement | Work packages |
| --- | --- |
| R2.1: Define `ApplicationDefinition`. | P2.0 |
| R2.2: Add registry. | P2.1 |
| R2.3: Register providers/tools/memory/sensitivity/cross-app metadata. | P2.0 |
| R2.4: Add initial app definitions/stubs. | P2.1 |

## README maintenance

Review the repository-root `README.md` at phase close. Update it only if the completed phase changes user-visible capabilities, architecture, tech stack, setup, deployment, or current-status statements. Do not add implementation-detail churn. For historical completed phases, do not rewrite the README to imply later Phase 10 storage choices existed earlier.

## Targeted verification and closeout

Test invalid/duplicate manifests, unknown applications, stub unavailability, standalone compatibility and adding a synthetic application without changing core orchestration. Run the applicable test/lint/typecheck/build checks and finish with `git diff --check`.
