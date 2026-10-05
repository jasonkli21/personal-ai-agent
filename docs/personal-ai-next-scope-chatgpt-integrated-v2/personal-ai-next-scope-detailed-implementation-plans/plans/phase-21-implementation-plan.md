# Phase 21 implementation plan — Health integration

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Integrate the most sensitive/flexible domain.

### Normative commitments from the integrated roadmap

- Start with read-only Health providers.
- Support flexible structured profile and bounded time queries.
- Apply field sensitivity and strict provider eligibility.
- Use minimal context.
- Allow mutation proposals only with domain rules.
- Add read-only sidecar with human-readable sensitive context categories and narrowing controls where practical.
- Require Health authorization before a category can be offered.
- Prevent generic sidecar output from directly editing medications, conditions, measurements, or clinical records.
- Verify native-mobile SIWC support before mobile credential logic; preserve the Health roadmap regardless.

### Phase acceptance criteria

- Health is not flattened into memory.
- Cross-app Health access is deny-by-default.
- Routing cannot weaken Health sensitivity.
- Verbose artifacts default to minimal/no retention for sensitive traces.

### Explicitly out of scope

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

## Current state and reuse

No Health app/provider exists here. Current memory extraction deliberately rejects sensitive medical content; adding Health context does not weaken that memory policy.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/domains/contracts.py`
- `backend/src/personal_ai/domains/registry.py`
- `backend/src/personal_ai/context/contracts.py`
- `backend/src/personal_ai/memory/policy.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 7, 13, 16. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

**Conditional prerequisite:** additive sidecar integration consumes Phase 17.4. Baseline domain/backend work does not depend on live ChatGPT approval. Keep blocked sidecar work explicitly pending; do not declare the entire phase complete while any intended package is pending.

## Phase-specific invariants

- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Medication/condition/clinical truth cannot be changed by generic model text.

## Work packages

### P21.0 — Read-only typed Health providers

**Depends on:** required phases above.

Pin Health application/revision and owner/membership read contracts. Expose flexible domain-typed profile/categories and bounded time-query data, not an untyped global profile or memory dump. Preserve source/effective time, units, uncertainty and field sensitivity. Medications, conditions, measurements and clinical records remain domain-owned; deny cross-app use by default.

**Acceptance:** Health source responses remain domain-typed/bounded and are never flattened into memory.

### P21.1 — Minimal sensitive context

**Depends on:** P21.0.

Authorize category before it can be offered/fetched, use field/window/result bounds and the most restrictive combined sensitivity. Enforce eligible generation/count/embedding/summary paths and minimal/no verbose artifact retention. If no authorized endpoint can handle selected data, refuse explicitly. Keep memory extraction restrictions and immutable source attribution intact.

**Acceptance:** Sensitive categories are denied before calls and artifacts default to minimal/no verbose retention.

### P21.2 — Sidecar and later proposal hooks

**Depends on:** P21.1 and Phase 17.4 for sidecar work.

After 17.4, provide read-only sidecar with human-readable included categories and narrowing controls. Copy/permitted non-authoritative drafts only; clinical or medication edits require the Phase 23 typed proposal plus Health rules and confirmation and may remain forbidden by policy. Verify mobile SIWC mechanics before native credential implementation; mobile Health roadmap and baseline read contracts remain preserved if the optional lane is blocked.

**Acceptance:** Shared Health sidecar exposes only authorized categories and no generic clinical edits; mobile enablement remains separately gated.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R21.1: Start with read-only Health providers. | P21.0 |
| R21.2: Support flexible structured profile and bounded time queries. | P21.0 |
| R21.3: Apply field sensitivity and strict provider eligibility. | P21.1 |
| R21.4: Use minimal context. | P21.1 |
| R21.5: Allow mutation proposals only with domain rules. | P21.2 |
| R21.6: Add read-only sidecar with human-readable sensitive context categories and narrowing controls where practical. | P21.2 |
| R21.7: Require Health authorization before a category can be offered. | P21.2 |
| R21.8: Prevent generic sidecar output from directly editing medications, conditions, measurements, or clinical records. | P21.2 |
| R21.9: Verify native-mobile SIWC support before mobile credential logic; preserve the Health roadmap regardless. | P21.2 |

## Targeted verification and closeout

Test category denial before read, narrow time windows, mixed sensitivity, historical/derived context rechecks, no Health-to-other-app retrieval, no memory flattening, no clinical writes and minimal artifacts. Mobile fake UI is not live SIWC evidence.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make domain-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Health repository/auth/provider-data and mobile transport need independent verification; no clinical/device/regulatory claims.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
