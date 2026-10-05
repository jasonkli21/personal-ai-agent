# Phase 13 implementation plan — Deterministic task-aware routing

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Select eligible free models using transparent task rules.

### Normative commitments from the integrated roadmap

- Define a small task taxonomy.
- Add routing requirements for capability, sensitivity, context size, quality floor, and escalation.
- Apply hard eligibility filtering.
- Add fixed task-specific priorities.
- Trace rejection/selection.
- Route chat plus at least two non-chat subtasks.

### Phase acceptance criteria

- No round-robin.
- Privacy/capability precede scoring.
- Known task type does not require an LLM classifier.

### Explicitly out of scope

- quota scarcity scoring
- learned routing
- cascades
- ChatGPT-plan explicit lane

## Current state and reuse

Current dependency injection selects one Gemini client. Task routing, rejection traces and actual per-turn producing-model metadata need extension.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/llm/client.py`
- `backend/src/personal_ai/api/dependencies.py`
- `backend/src/personal_ai/services/chat_turns.py`
- `backend/src/personal_ai/entities/conversation.py`
- `backend/src/personal_ai/storage/repositories.py`
- `backend/src/personal_ai/agents/research/service.py`
- `backend/src/personal_ai/memory/services.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 8, 10, 11. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Known callers should pass task type rather than paying for classification.
- Strict-free, privacy, capability, context limits, and known exhaustion/cooldown are hard constraints.
- Route decisions must be reconstructable from registry/ledger inputs.

## Work packages

### P13.0 — Task taxonomy and requirements

**Depends on:** required phases above.

Define a small taxonomy from actual operations: chat, summary, extraction, research synthesis/planning where used, rewrite, structured validation-related generation and embedding through its separate boundary. Callers supply known task type; no LLM classifier. Requirements include capability, privacy/sensitivity, prepared context capacity and quality-floor policy, with finite retry/escalation permission.

**Acceptance:** Actual task callers supply typed requirements without an LLM classifier.

### P13.1 — Transparent deterministic router

**Depends on:** P13.0.

Apply strict-free/privacy/capability/known exhaustion/cooldown hard filters before versioned fixed task priorities. Phase 14 does not exist yet: use explicitly unmeasured configured baseline priorities and never fabricate numeric quality. If a task requires a measured floor with no profile, deny. Fit/recount for selected endpoint and record all exclusions and versions; before-visible-output fallback obeys the same filters.

**Acceptance:** Hard filters precede deterministic priorities and unmeasured quality is never represented as measured.

### P13.2 — Integrate and persist attribution

**Depends on:** P13.1.

Route chat and at least two actual non-chat tasks using the shared runtime, existing assembly and invocation ledger. Persist the actual producing provider/model and safe selection/fallback trace on automatic turns rather than static AI_MODEL. Maintain active-branch/supersession and partial-failure semantics. No round-robin, quota scarcity scoring, cascades or ChatGPT automatic route.

**Acceptance:** Chat plus two non-chat tasks route through the runtime and store actual producing-model attribution.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R13.1: Define a small task taxonomy. | P13.0 |
| R13.2: Add routing requirements for capability, sensitivity, context size, quality floor, and escalation. | P13.0 |
| R13.3: Apply hard eligibility filtering. | P13.1 |
| R13.4: Add fixed task-specific priorities. | P13.1 |
| R13.5: Trace rejection/selection. | P13.1 |
| R13.6: Route chat plus at least two non-chat subtasks. | P13.2 |

## Targeted verification and closeout

Test task-specific fixed selections, unknown task/profile, hard-filter precedence, missing measured floor, provider removal, smaller-context fallback, midstream failure and actual rather than configured provider attribution.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make research-eval`, `make itinerary-proposal-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
