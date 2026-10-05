# Phase 4 implementation plan — Context builder refactor

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Make context assembly explicit, budgeted, and sensitivity-aware.

### Normative commitments from the integrated roadmap

- Extend/refactor current context assembly.
- Combine conversation, memory, domain, research, and tools.
- Add global/per-source budgets and priorities.
- Preserve provenance/authority.
- Compute effective sensitivity.
- Add structured debug output.

### Phase acceptance criteria

- Actual-build context decisions have a safe manifest; an estimated reconstruction is explicitly labelled.
- Budgets are enforced.
- Effective sensitivity is deterministic.

### Explicitly out of scope

- LLM-assisted planning
- provider routing
- domain mutations
- unbounded profile/history injection

## Current state and reuse

Complete-turn budgeting, summary coverage and standalone evidence assembly are implemented and must be extended. Multi-source assembly and effective sensitivity need refactor; direct memory extraction budgeting is closed in Phase 8.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/context/assembler.py`
- `backend/src/personal_ai/context/contracts.py`
- `backend/src/personal_ai/context/tokens.py`
- `backend/src/personal_ai/context/deadline.py`
- `backend/src/personal_ai/llm/context.py`
- `backend/src/personal_ai/services/chat_turns.py`
- `backend/src/personal_ai/agents/research/service.py`
- `backend/src/personal_ai/itinerary_proposals/service.py`
- `backend/src/personal_ai/booking_extractions/service.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 3. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Mandatory newest-user-message and existing branch semantics remain intact.
- Effective sensitivity is monotonic: adding more restrictive context cannot lower sensitivity.
- Debug output must be safe metadata by default, not raw sensitive prompt content.

## Work packages

### P4.0 — One builder and budget contract

**Depends on:** required phases above.

Extend the existing assembler result to retain typed source manifests and exclusions. Keep mandatory newest user input, complete active-branch turns, branch-scoped lossy summaries and current optional-memory priority. Add validated global/per-source ceilings and source priorities for domain/research/tool/client items; account for instruction and wrapper overhead. Unknown/invalid budgets or unfit mandatory input reject explicitly.

**Acceptance:** All existing preparations retain complete-turn/summary/mandatory-input regressions and enforce global/per-source budgets.

### P4.1 — Authority and sensitivity preservation

**Depends on:** P4.0.

Use deterministic source ordering, immutable source refs and expiry/grant rechecks at assembly. Effective sensitivity is the monotonic join of included fields; mixed classifications must not be reduced to a lower enum. Record per-source counts/counter version, fitted/injected IDs and omission reasons. Untrusted data is labelled data, never executable instructions. Missing optional source cannot trigger broader retrieval.

**Acceptance:** Mixed sensitivity cannot decrease and all injected items remain attributable and fresh.

### P4.2 — Integrate existing generation preparations

**Depends on:** P4.1.

Extend chat and evidence/proposal/extraction preparation through the same builder; retain task-specific structured validators and existing timeout/branch/replay behavior. Emit a safe actual-build manifest. The gated inspector can reconstruct an estimated current view but cannot assert exact historical prompt reconstruction. Provider-neutral fit/recount comes in Phase 8; no new router here.

**Acceptance:** Captured manifests identify actual selection; estimated inspection is labelled and makes no provider calls.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R4.1: Extend/refactor current context assembly. | P4.0 |
| R4.2: Combine conversation, memory, domain, research, and tools. | P4.0 |
| R4.3: Add global/per-source budgets and priorities. | P4.0 |
| R4.4: Preserve provenance/authority. | P4.1 |
| R4.5: Compute effective sensitivity. | P4.1 |
| R4.6: Add structured debug output. | P4.2 |

## Targeted verification and closeout

Test complete-turn retention, mandatory overflow, wrapper overhead, per-source ceilings, stale/grant exclusions, monotonic sensitivity, preserved authority, cancellation/deadline and disabled-path compatibility.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make research-eval`, `make itinerary-proposal-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
