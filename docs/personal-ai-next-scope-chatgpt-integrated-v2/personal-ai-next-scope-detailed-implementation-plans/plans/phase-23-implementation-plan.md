# Phase 23 implementation plan — Mutation proposal framework

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Standardize AI-assisted edits without making Personal AI authoritative.

### Normative commitments from the integrated roadmap

- Define mutation proposal.
- Include target app/entity/patch/rationale/source/validation/confirmation/idempotency.
- Add domain validation callback.
- Require user confirmation before an AI-assisted authoritative write.
- Return authoritative post-state.
- Expose sidecar Apply only after conversion to a typed mutation proposal.
- Treat producing provider, including ChatGPT, as provenance rather than write authority.

### Phase acceptance criteria

- No arbitrary direct writes.
- Domain validation is mandatory.
- Mutation trace is auditable.

### Explicitly out of scope

- generic direct database writes
- transaction execution not supported by domain policy
- autonomous background mutations
- bypassing user confirmation for an AI-assisted authoritative write

## Current state and reuse

Itinerary proposals provide narrow typed operations, citations, opaque handles and fenced replay. They do not execute authoritative domain writes; a reusable proposal/confirmation/domain apply framework is missing.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/itinerary_proposals/contracts.py`
- `backend/src/personal_ai/itinerary_proposals/service.py`
- `backend/src/personal_ai/itinerary_proposals/repositories.py`
- `backend/src/personal_ai/booking_extractions/contracts.py`
- `backend/src/personal_ai/domains/contracts.py`
- `backend/src/personal_ai/auth/owner_data.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 7, 18, 19, 20, 21. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

**Conditional prerequisite:** additive sidecar integration consumes Phase 17.4. Baseline domain/backend work does not depend on live ChatGPT approval. Keep blocked sidecar work explicitly pending; do not declare the entire phase complete while any intended package is pending.

## Phase-specific invariants

- Domain validation and authorization happen after proposal creation and before authoritative write.
- Idempotency protects retries/double-clicks; post-state comes from the domain source of truth.
- Provider/model is retained as provenance, never authority.

## Work packages

### P23.0 — Typed proposal framework

**Depends on:** required phases above.

Extend proposal patterns with target app/workspace/entity, versioned domain operation/patch, rationale, source refs, producing provider/model trust, expected domain version, validation/confirmation state, expiry and idempotency identity. Preserve opaque handles and exact evidence requirements. Booking extraction yields review candidates, not a generic patch or confirmed mutation. Unsupported domain operations fail explicitly.

**Acceptance:** Only supported typed domain operations with source/version/idempotency metadata become proposals.

### P23.1 — Domain validate, confirm, execute

**Depends on:** P23.0.

Domain validates business rules/current authorization/version and preview; user explicitly confirms the exact validated proposal. Execution occurs only through the authoritative domain API, revalidating stale versions and confirmation. Return authoritative post-state/ref, not model-estimated post-state. Durable execution/reconciliation distinguishes rejected, applied and uncertain; unknown outcome queries the same domain operation key and cannot blindly resend under a new key.

**Acceptance:** Domain validation and exact user confirmation precede authoritative execution; uncertain apply reconciles under the original key.

### P23.2 — Sidecar Apply and domain adapters

**Depends on:** P23.1 and Phase 17.4 for sidecar work.

After 17.4, enable Apply only for declared domain-supported operations converted from output into typed proposals. Provider/model is provenance, never authority. Double-click/retry remains idempotent. Finance/Health can refuse sensitive operations regardless of confirmation; no generic trade/clinical mutation scope is added. Preserve narrow existing itinerary proposals and add shared UI trace/status without direct DB writes.

**Acceptance:** Shared Apply consumes typed proposals and authoritative post-state, with unsupported Finance/Health operations unavailable.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R23.1: Define mutation proposal. | P23.0 |
| R23.2: Include target app/entity/patch/rationale/source/validation/confirmation/idempotency. | P23.0 |
| R23.3: Add domain validation callback. | P23.1 |
| R23.4: Require user confirmation before an AI-assisted authoritative write. | P23.1 |
| R23.5: Return authoritative post-state. | P23.1 |
| R23.6: Expose sidecar Apply only after conversion to a typed mutation proposal. | P23.2 |
| R23.7: Treat producing provider, including ChatGPT, as provenance rather than write authority. | P23.2 |

## Targeted verification and closeout

Test forged handles/patches/citations, missing confirmation, changed preview/version, domain rule rejection, foreign scope, double clicks, network lost-after-apply reconciliation, authoritative post-state and disabled unsupported actions.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make itinerary-proposal-eval`, `make decision-eval`, `make domain-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Each domain apply API and end-to-end reconciliation must be verified externally; no real authoritative application DB is available in core tests.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
