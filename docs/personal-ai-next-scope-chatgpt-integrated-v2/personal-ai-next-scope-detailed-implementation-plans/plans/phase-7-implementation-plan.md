# Phase 7 implementation plan — Permissions and sensitivity policy

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Prevent inappropriate context/model-provider access.

### Normative commitments from the integrated roadmap

- Define sensitivity.
- Define app/provider/field policy.
- Enforce pre-retrieval authorization.
- Add deny-by-default cross-app rules.
- Pass trustworthy effective sensitivity to inference runtime.

### Phase acceptance criteria

- Sensitive Health context is deny-by-default outside Health.
- Unauthorized data is not fetched first and filtered later.

### Explicitly out of scope

- cross-app feature enablement
- provider adapter implementation
- user-facing permission-management UI
- regulatory compliance claims

## Current state and reuse

Owner checks and restrictive memory/source policies are reusable. General field/sensitivity/provider and revocable cross-app authorization are missing.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/auth/contracts.py`
- `backend/src/personal_ai/api/dependencies.py`
- `backend/src/personal_ai/context/contracts.py`
- `backend/src/personal_ai/context/assembler.py`
- `backend/src/personal_ai/memory/policy.py`
- `backend/src/personal_ai/domains/contracts.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 3, 5, 6. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Unknown provider data policy must be representable and conservatively handled.
- Never retrieve sensitive data first and rely on post-filtering.
- Cross-app authorization must be independently revocable later without changing source data.

## Work packages

### P7.0 — Policy facts and decisions

**Depends on:** required phases above.

Define server-owned app/provider/field/operation policy and a sensitivity join that supports multiple restrictions. App/workspace membership comes from verified/domain authority, not client labels. Unknown policy denies sensitive disclosure. Separate source access from external model eligibility; explicit provider choice cannot override either.

**Acceptance:** Server policy decisions deny unknown-sensitive and forged client permissions.

### P7.1 — Enforce before retrieval and disclosure

**Depends on:** P7.0.

Use decisions before provider reads, memory query embedding, summaries, remote counting/planning and generation. Recheck each item and effective sensitivity at assembly/dispatch. Policy denial returns safe reasons without fetching then filtering. Register cross-app default-deny; future grant IDs/version/revocation dependencies are represented, without enabling federation yet.

**Acceptance:** Source and auxiliary model operations are denied before retrieval/disclosure.

### P7.2 — Derived context and revocation contract

**Depends on:** P7.1.

Carry policy dependencies across conversation history, summaries, memory, caches, traces, export and artifacts. Later reuse must not bypass revoked source access. Specify denied/expired source exclusion or terminal refusal when mandatory context cannot be supplied. No deletion of authoritative domain records is implied by revocation.

**Acceptance:** Revoked dependencies cannot reappear through history, summaries, memory, caches or artifacts.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R7.1: Define sensitivity. | P7.0 |
| R7.2: Define app/provider/field policy. | P7.0 |
| R7.3: Enforce pre-retrieval authorization. | P7.1 |
| R7.4: Add deny-by-default cross-app rules. | P7.2 |
| R7.5: Pass trustworthy effective sensitivity to inference runtime. | P7.1 |

## Targeted verification and closeout

Negative matrix covers owner/app/workspace/field/provider, mixed sensitivity, hidden memory/summary disclosure, denial before calls, client capability escalation and revoked dependencies. Health outside Health is denied by default.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make research-eval`, `make domain-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Provider data-use/retention and domain membership mechanisms require explicit external review; no regulatory readiness claim.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
