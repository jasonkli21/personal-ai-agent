# Phase 22 implementation plan — Cross-app context federation

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Enable safe cross-domain intelligence.

### Normative commitments from the integrated roadmap

- Support initial cases: Health dietary restrictions -> Travel; Health ergonomic constraints -> Shopping; Travel trip -> Shopping; Finance discretionary budget -> Shopping.
- Make cross-app context categories visible when a ChatGPT sidecar request includes them.
- Preserve the most restrictive effective sensitivity in ContextPackage.
- Require explicit user/context-policy permission exactly as for automatic inference.

### Phase acceptance criteria

- Cross-app access is narrow and auditable.
- Revocation blocks future retrieval.
- Router reflects the most restrictive context sensitivity.

### Explicitly out of scope

- global profile dumping
- implicit all-app sharing
- domain mutation
- new federation cases beyond the four initial cases unless needed for plumbing tests

## Current state and reuse

Cross-app federation and user grants are missing. Phase 7 policy dependencies and Phase 18–21 read providers are prerequisites; same-owner identity alone never grants sharing.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/context/contracts.py`
- `backend/src/personal_ai/context/assembler.py`
- `backend/src/personal_ai/domains/contracts.py`
- `backend/src/personal_ai/auth/owner_data.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 7, 18, 19, 20, 21. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

**Conditional prerequisite:** additive sidecar integration consumes Phase 17.4. Baseline domain/backend work does not depend on live ChatGPT approval. Keep blocked sidecar work explicitly pending; do not declare the entire phase complete while any intended package is pending.

## Phase-specific invariants

- The destination app cannot directly query another app database through core shortcuts.
- Revocation affects future retrieval without mutating source state.
- The most restrictive supplied context governs downstream provider eligibility.

## Work packages

### P22.0 — Explicit revocable grants

**Depends on:** required phases above.

Define scoped category/field/entity/purpose grants with source and destination app/workspace, expiry and version/revocation identity. User permission and source-domain policy must both allow the selection before retrieval. Do not create a global profile dump or modify authoritative source data when revoking access.

**Acceptance:** Sharing requires a valid source/destination category/purpose grant and source policy before calls.

### P22.1 — Four bounded broker cases

**Depends on:** P22.0.

Implement only Health dietary restrictions→Travel, Health ergonomic constraints→Shopping, Travel trip→Shopping and Finance discretionary budget→Shopping. Broker narrow domain-owned responses through registered providers, preserving source refs/authority and most restrictive sensitivity. Destination cannot re-delegate data beyond grant scope; stale membership/grant denies before source calls.

**Acceptance:** Exactly the four initial cases preserve narrow source identity and most restrictive sensitivity.

### P22.2 — Audit and derived-context revocation

**Depends on:** P22.1.

Record safe grant/source/selection/exclusion IDs and propagate dependencies to history, summaries, memory, caches and artifacts. Revalidate at prepare/dispatch/finalize and subsequent reuse, not just fresh source fetch. After 17.4, show cross-app categories explicitly in sidecar packages with the same permission/sensitivity rules; no separate ChatGPT grant path.

**Acceptance:** Revocation blocks retrieval and derived reuse; sidecar categories use the same policy after 17.4.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R22.1: Support initial cases: Health dietary restrictions -> Travel; Health ergonomic constraints -> Shopping; Travel trip -> Shopping; Finance discretionary budget -> Shopping. | P22.1 |
| R22.2: Make cross-app context categories visible when a ChatGPT sidecar request includes them. | P22.2 |
| R22.3: Preserve the most restrictive effective sensitivity in ContextPackage. | P22.1 |
| R22.4: Require explicit user/context-policy permission exactly as for automatic inference. | P22.0 |

## Targeted verification and closeout

Test all four cases, missing/expired/revoked grants, narrower source policy, re-delegation, mixed sensitivity, no over-fetch and reuse after revocation. Sidecar visibility tests additionally require 17.4.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make domain-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
