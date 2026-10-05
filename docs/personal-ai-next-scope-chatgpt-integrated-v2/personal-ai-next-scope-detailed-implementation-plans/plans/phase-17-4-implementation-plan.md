# Phase 17.4 implementation plan — ChatGPT domain integration contract

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Define the reusable contract Travel, Shopping, Finance, and Health consume so ChatGPT-specific UI/auth/provider logic is not duplicated.

### Normative commitments from the integrated roadmap

- Standardize sidecar launch context around application/workspace/entity/view/conversation scope and bounded client context.
- Reuse the existing planner/provider/policy/builder pipeline to produce inspectable `ContextPackage`; do not create a parallel ChatGPT-only context system.
- Preserve domain ownership and mutation validation.
- Standardize provider/model attribution and completed-turn persistence.
- Standardize Copy/Insert/Apply action boundaries.
- Define sensitivity-aware domain hooks.
- Keep domain-specific behavior in the later Travel/Shopping/Finance/Health phases rather than core app-name branching.

### Phase acceptance criteria

- Domain apps integrate through one shared sidecar/context contract.
- No domain app needs to implement its own ChatGPT authentication or token handling.
- Domain-specific context remains bounded, authorized, attributable, and sensitivity-aware.
- The shared contract does not move authoritative domain state into Personal AI.
- Existing domain-phase scope remains intact; ChatGPT tasks are additive.

### Explicitly out of scope

- real Travel/Shopping/Finance/Health adapters
- cross-app federation
- mutation execution
- app-specific ChatGPT authentication

## Current state and reuse

Shared sidecar/context/external-turn contracts now come from 17.2/17.3. Domain launch adapters and sensitivity/action hooks are new integration contracts, not another auth/persistence implementation.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/domains/contracts.py`
- `backend/src/personal_ai/domains/registry.py`
- `backend/src/personal_ai/context/contracts.py`
- `backend/src/personal_ai/api/schemas.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 17.3. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Domain apps remain authoritative for state and validation.
- Finance/Health can expose narrower context/control policies without forking the sidecar.
- Apply capability is declarative but remains disabled until Phase 23.

## Work packages

### P17_4.0 — Domain launch and read contract

**Depends on:** required phases above.

Define versioned launch metadata for app/workspace/entity/view/conversation plus bounded advisory client context. Domain-owned adapters supply authorized typed source refs; consume the shared ContextPackage without querying domain DBs in core. Separate Personal AI workspace from provider account registration. Provide fake integration examples for all four applications, not claimed real app files.

**Acceptance:** All four fake domain launches compose with one shared package/turn contract and no core DB calls.

### P17_4.1 — Sensitivity and action hooks

**Depends on:** P17_4.0.

Expose narrow allowed context categories and policy-approved Copy/draft Insert capabilities. Finance/Health can restrict fields/artifacts without forking UI or credentials. Apply is declarative and disabled until 23; domain validation and mandatory user confirmation remain required. Auth, model discovery, usage and producing-provider metadata are consumed from shared contracts only.

**Acceptance:** Domain policies narrow fields/actions without forking auth; Apply remains disabled.

### P17_4.2 — Integration handoff and boundary tests

**Depends on:** P17_4.1.

Document domain-owned read/mutation API responsibilities and repository/revision/transport verification required before each live integration. Standardize post-completion callbacks without duplicating prepare/finalize. Prove adding synthetic domain hooks does not add app-name branches to orchestration, provider auth in apps or authoritative state in AI storage.

**Acceptance:** Pinned integration responsibilities and boundary fixtures preserve shared attribution/completion and domain authority.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R17.4.1: Standardize sidecar launch context around application/workspace/entity/view/conversation scope and bounded client context. | P17_4.0 |
| R17.4.2: Reuse the existing planner/provider/policy/builder pipeline to produce inspectable `ContextPackage`; do not create a parallel ChatGPT-only context system. | P17_4.0 |
| R17.4.3: Preserve domain ownership and mutation validation. | P17_4.1 |
| R17.4.4: Standardize provider/model attribution and completed-turn persistence. | P17_4.2 |
| R17.4.5: Standardize Copy/Insert/Apply action boundaries. | P17_4.1 |
| R17.4.6: Define sensitivity-aware domain hooks. | P17_4.1 |
| R17.4.7: Keep domain-specific behavior in the later Travel/Shopping/Finance/Health phases rather than core app-name branching. | P17_4.2 |

## Targeted verification and closeout

Test all four launch fixtures, foreign workspace/entity, unsupported actions, sensitive-category omission, preserved provider attribution and no direct writes/token handling. Real domain adapters are later work.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
