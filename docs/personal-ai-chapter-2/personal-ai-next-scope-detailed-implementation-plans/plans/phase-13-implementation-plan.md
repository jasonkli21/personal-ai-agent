# Phase 13 implementation plan — Deterministic context planner

Renumbered on 2026-10-06 from former next-scope Phase 5. This plan preserves the former detailed plan’s normative commitments, work packages, invariants, acceptance criteria, and verification scope. Only phase numbering/prerequisites, persistence references superseded by Phase 10, and README-maintenance requirements are changed. Read the source roadmap, Phase 10 persistence plan, and shared execution contract first. This plan defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Retrieve only relevant bounded context.

### Normative commitments from the integrated roadmap

- Define planner.
- Implement deterministic categories/rules.
- Select provider/fields/history window/result limit/budget.
- Define unavailable-provider fallback.
- Avoid an LLM planner initially.

### Phase acceptance criteria

- Representative requests fetch narrow relevant slices.
- Unrelated sensitive fields are not requested.

### Explicitly out of scope

- LLM planner
- adaptive planning
- model routing
- new domain provider implementations

## Current state and reuse

Deterministic research query planning exists, but it is not a general context planner. Reuse bounded-rule and fake patterns; do not replace search query semantics.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/context/contracts.py`
- `backend/src/personal_ai/context/assembler.py`
- `backend/src/personal_ai/api/dependencies.py`
- `backend/src/personal_ai/search/contracts.py`
- `backend/src/personal_ai/search/policy.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends the post-Phase-10 GCP/Neon/DynamoDB deployment assets, `Makefile`, and `.github/workflows/quality.yml` only when required; do not reintroduce Firestore as a canonical runtime dependency. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 12, 10. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Permission checks happen before provider retrieval; planner output is not authorization.
- Rules should be explainable and configuration-driven where practical.
- Missing optional context degrades explicitly without causing unrelated source expansion.

## Work packages

### P13.0 — Deterministic planning contract

**Depends on:** required phases above.

Add a future ContextPlan/ContextPlanner at the context seam: authorized providers, fields/entity refs, history/time windows, result limits, token/byte allocations and required/optional sources. Categories/rules are versioned and explainable, based on registered capabilities and bounded user intent. This planner chooses information, not a model.

**Acceptance:** Repeated requests produce the same bounded source/field/window plan with versioned reasons.

### P13.1 — Execute narrow selections

**Depends on:** P13.0.

Plan before retrieval; execute only the selected authorized operations using Phase 11 providers and Phase 12 builder. Missing optional providers yield explicit degraded context; missing required provider stops. Do not retry with an all-field/all-app slice. Keep global profile and memory inclusion explicit and bounded.

**Acceptance:** Only selected authorized providers are called, and missing context cannot widen access.

### P13.2 — Baseline fixtures and metrics

**Depends on:** P13.1.

Create named context-plan fixtures for standalone and synthetic Travel/Shopping/Finance/Health requests. Record expected fields, exclusions, relevance/omission, bytes/tokens, latency and answer-support needs. These establish the baseline used by Phase 32; do not add LLM classification or planning now.

**Acceptance:** Named baseline fixtures record relevant selections, exclusions and omission/over-fetch metrics for Phase 32.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R13.1: Define planner. | P13.0 |
| R13.2: Implement deterministic categories/rules. | P13.0 |
| R13.3: Select provider/fields/history window/result limit/budget. | P13.1 |
| R13.4: Define unavailable-provider fallback. | P13.1 |
| R13.5: Avoid an LLM planner initially. | P13.2 |

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Assert exact provider/field/window calls and no unrelated sensitive retrieval; test ambiguity, absent optional/required sources, over-budget plans and deterministic results.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make research-eval`, `make domain-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
