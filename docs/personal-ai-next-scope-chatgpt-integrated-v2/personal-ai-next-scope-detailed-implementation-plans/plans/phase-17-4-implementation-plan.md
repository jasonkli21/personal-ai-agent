# Phase 17.4 implementation plan — ChatGPT domain integration contract

This is the detailed execution plan for integrated next-scope **Phase 17.4 — ChatGPT domain integration contract**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions. ChatGPT-specific design constraints are additionally defined in [../source/08-chatgpt-plan-and-ai-sidecar.md](../source/08-chatgpt-plan-and-ai-sidecar.md).

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

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/domains/`
- `backend/src/personal_ai/context/`
- `frontend/ shared sidecar interfaces`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`DomainModule` currently serves local Travel/Shopping comparisons, not an external application's sidecar launch contract. Define one app/workspace/entity/view launch and context-package contract over the Phase 2–7 abstractions and Phase 17.3 UI. Keep ChatGPT auth/runtime centralized, and leave each app authoritative for state and mutation validation. Domain-specific behavior remains in Phases 18–21. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make domain-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Core code routes by capabilities/metadata, not app-name conditionals.
- Domain apps remain authoritative for state and validation.
- Finance/Health can expose narrower context/control policies without forking the sidecar.
- Apply capability is declarative but remains disabled until Phase 23.

## Dependency map

**Prerequisites:** Phase 17.3

```text
P17_4.0 SidecarLaunchContext -> P17_4.1 ContextPackage/domain-hook
P17_4.1 ContextPackage/domain-hook -> P17_4.2 Provider
P17_4.2 Provider -> P17_4.3 Copy/Insert/Apply
P17_4.3 Copy/Insert/Apply -> P17_4.4 Sensitivity-aware
P17_4.4 Sensitivity-aware -> P17_4.5 Reference
P17_4.5 Reference -> P17_4.6 Contract
```

The map is sequencing guidance, not a requirement to commit once per work package. Prefer a few coherent commits that preserve reviewable boundaries.

## Required verification matrix

- Offline unit/contract tests cover success plus malformed/denied/unavailable/error paths for each new contract.
- Integration tests prove the phase composes with the existing owner/application/workspace and context boundaries.
- Regression tests prove the phase-disabled/default path preserves prior behavior.
- No automated test requires live provider credentials, a real GCP project, or personal data unless explicitly marked opt-in.
- Safe tracing/evidence records IDs, counts, versions, states, and reason codes without raw secrets or unnecessary private content.
- Documentation/release evidence states exactly which external provider/emulator/cloud checks were run, skipped, or remain open.
- Negative authorization/sensitivity tests prove protected data is not retrieved or transmitted after denial.
- ChatGPT-mode tests prove credentials never enter managed cloud persistence or browser storage and provider switching remains explicit.

## Required implementation artifacts

- Code/configuration changes required by the work packages below, limited to Phase 17.4 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 17.4 work packages

### P17_4.0 — Standardize sidecar launch context around…

**Dependencies:** Phase 17.3  

**Goal:** implement this scoped Phase 17.4 commitment without pulling later-phase behavior forward.

**Work:**

- Standardize sidecar launch context around application/workspace/entity/view/conversation scope and bounded client context.
- Reconcile the existing implementation relevant to **Standardize sidecar launch context around application/workspace/entity/view/conversation scope and bounded client context.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Thread the new data/behavior through API → service → repository/provider/context boundaries with one clear ownership path.
- Preserve existing default behavior when the new capability is absent or disabled.
- Add integration tests for success, explicit failure, cancellation/retry where relevant, and isolation boundaries.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Core code routes by capabilities/metadata, not app-name conditionals.
- Domain apps remain authoritative for state and validation.
- Finance/Health can expose narrower context/control policies without forking the sidecar.
- No hidden side channel may bypass existing authorization/context/provider boundaries.
- Existing public API/SSE behavior changes only when this phase explicitly requires it.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Existing regression tests remain green with the new path disabled/defaulted.
- The enabled path is attributable in traces/evidence without exposing sensitive payloads.
- The feature is usable without hidden provider/storage coupling and fails recoverably.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- real Travel/Shopping/Finance/Health adapters
- cross-app federation
- mutation execution
- app-specific ChatGPT authentication

### P17_4.1 — Reuse the existing planner/provider/policy/builder pipeline to produce inspectable…

**Dependencies:** P17_4.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.4 commitment without pulling later-phase behavior forward.

**Work:**

- Reuse the existing planner/provider/policy/builder pipeline to produce inspectable `ContextPackage`; do not create a parallel ChatGPT-only context system.
- Reconcile the existing implementation relevant to **Reuse the existing planner/provider/policy/builder pipeline to produce inspectable `ContextPackage`; do not create a parallel ChatGPT-only context system.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Core code routes by capabilities/metadata, not app-name conditionals.
- Domain apps remain authoritative for state and validation.
- Finance/Health can expose narrower context/control policies without forking the sidecar.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Negative tests prove protected data/provider paths are never invoked after denial.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- real Travel/Shopping/Finance/Health adapters
- cross-app federation
- mutation execution
- app-specific ChatGPT authentication

### P17_4.2 — Preserve domain ownership and mutation validation

**Dependencies:** P17_4.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.4 commitment without pulling later-phase behavior forward.

**Work:**

- Preserve domain ownership and mutation validation.
- Reconcile the existing implementation relevant to **Preserve domain ownership and mutation validation.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Core code routes by capabilities/metadata, not app-name conditionals.
- Domain apps remain authoritative for state and validation.
- Finance/Health can expose narrower context/control policies without forking the sidecar.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- real Travel/Shopping/Finance/Health adapters
- cross-app federation
- mutation execution
- app-specific ChatGPT authentication

### P17_4.3 — Standardize provider/model attribution and completed-turn persistence

**Dependencies:** P17_4.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.4 commitment without pulling later-phase behavior forward.

**Work:**

- Standardize provider/model attribution and completed-turn persistence.
- Reconcile the existing implementation relevant to **Standardize provider/model attribution and completed-turn persistence.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.

**Requirements:**

- Core code routes by capabilities/metadata, not app-name conditionals.
- Domain apps remain authoritative for state and validation.
- Finance/Health can expose narrower context/control policies without forking the sidecar.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.
- Observability is not a second source of truth and must respect the underlying data sensitivity.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.
- A developer can reconstruct the decision path from safe metadata for named fixtures.

**Out of scope:**

- real Travel/Shopping/Finance/Health adapters
- cross-app federation
- mutation execution
- app-specific ChatGPT authentication

### P17_4.4 — Standardize Copy/Insert/Apply action boundaries

**Dependencies:** P17_4.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.4 commitment without pulling later-phase behavior forward.

**Work:**

- Standardize Copy/Insert/Apply action boundaries.
- Reconcile the existing implementation relevant to **Standardize Copy/Insert/Apply action boundaries.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Core code routes by capabilities/metadata, not app-name conditionals.
- Domain apps remain authoritative for state and validation.
- Finance/Health can expose narrower context/control policies without forking the sidecar.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- real Travel/Shopping/Finance/Health adapters
- cross-app federation
- mutation execution
- app-specific ChatGPT authentication

### P17_4.5 — Sensitivity-aware domain hooks

**Dependencies:** P17_4.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.4 commitment without pulling later-phase behavior forward.

**Work:**

- Define sensitivity-aware domain hooks.
- Reconcile the existing implementation relevant to **Define sensitivity-aware domain hooks.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Core code routes by capabilities/metadata, not app-name conditionals.
- Domain apps remain authoritative for state and validation.
- Finance/Health can expose narrower context/control policies without forking the sidecar.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- real Travel/Shopping/Finance/Health adapters
- cross-app federation
- mutation execution
- app-specific ChatGPT authentication

### P17_4.6 — Keep domain-specific behavior in the later Travel/Shopping/Finance/Health phases…

**Dependencies:** P17_4.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.4 commitment without pulling later-phase behavior forward.

**Work:**

- Keep domain-specific behavior in the later Travel/Shopping/Finance/Health phases rather than core app-name branching.
- Reconcile the existing implementation relevant to **Keep domain-specific behavior in the later Travel/Shopping/Finance/Health phases rather than core app-name branching.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Core code routes by capabilities/metadata, not app-name conditionals.
- Domain apps remain authoritative for state and validation.
- Finance/Health can expose narrower context/control policies without forking the sidecar.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- real Travel/Shopping/Finance/Health adapters
- cross-app federation
- mutation execution
- app-specific ChatGPT authentication

### P17_4.7 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P17_4.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.4 commitment without pulling later-phase behavior forward.

**Work:**

- Wire the completed work packages through the narrow existing integration seam for this phase; do not add new product behavior.
- Run the phase verification matrix and all affected existing regressions from a clean checkout.
- Update the implementation guide/release evidence with actual code paths, tested revision, commands, outcomes, and explicit external verification gaps.
- Confirm every later-phase gate remains disabled/absent unless the integrated roadmap explicitly requires it now.
- Reconcile the existing implementation relevant to **Integrate the completed Phase work, run the required regression/evaluation matrix, update implementation documentation/evidence, and leave later-phase capabilities disabled or absent.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Core code routes by capabilities/metadata, not app-name conditionals.
- Domain apps remain authoritative for state and validation.
- Finance/Health can expose narrower context/control policies without forking the sidecar.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Domain apps integrate through one shared sidecar/context contract.
- No domain app needs to implement its own ChatGPT authentication or token handling.
- Domain-specific context remains bounded, authorized, attributable, and sensitivity-aware.
- The shared contract does not move authoritative domain state into Personal AI.
- Existing domain-phase scope remains intact; ChatGPT tasks are additive.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- real Travel/Shopping/Finance/Health adapters
- cross-app federation
- mutation execution
- app-specific ChatGPT authentication

---

## Phase verification and closeout

### Required local/offline checks

- `make backend-test`
- `make backend-lint`
- `make frontend-test`
- `make frontend-lint`
- `make frontend-typecheck`
- local bridge unit/contract/security test command
- frontend checks when sidecar/browser integration changes
- `git diff --check`

### Optional external checks

- Run only the provider/emulator/cloud/browser/native checks that are relevant to the phase and available in the environment.
- Use synthetic data. Never use the absence of credentials/network/cloud access as a reason to weaken offline tests.
- Record a skipped external check as **unverified**, not passed.

### Documentation/evidence closeout

- Update this plan only if implementation discovered a necessary scope-preserving clarification; do not silently rewrite the roadmap after coding.
- Create/update the phase implementation guide with actual files/classes/routes/configuration and a concise code map.
- Record release/verification evidence with date, tested revision, commands, outcomes, and explicit remaining external gaps.
- Update ADRs/API/deployment/runbook docs only where their contracts actually changed.

## Phase 17.4 completion review

- 1. Did implementation satisfy every normative Phase 17.4 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 17.4 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
