# Phase 20 implementation plan — Finance integration

This is the detailed execution plan for integrated next-scope **Phase 20 — Finance integration**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Validate high-value structured state with stricter privacy/provider policy.

### Normative commitments from the integrated roadmap

- Start with read-only Finance providers.
- Distinguish observed/calculated/assumed/AI-interpreted data.
- Use stricter provenance.
- Apply Finance-specific provider eligibility.
- Allow no implicit mutation.
- Add read-only sidecar to portfolio/security/research views with narrow default scope.
- Make broader portfolio/account context an explicit visible inclusion choice.
- Preserve semantic labels in ContextPackage.
- Support Copy/save-as-draft/research-note only where domain policy permits.
- Do not execute trades or transactions from generic sidecar output.

### Phase acceptance criteria

- Finance remains authoritative.
- Ineligible free providers never receive sensitive Finance context.

### Explicitly out of scope

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/domains/`
- `backend/src/personal_ai/context/`
- `backend/src/personal_ai/llm/ policy registry`
- Finance application integration boundary
- `frontend/ shared sidecar hooks`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

No Finance application/module exists locally. Build read-only typed Finance providers over a Finance-owned authority, using Phase 7 sensitivity policy and Phase 17 shared sidecar. Preserve observed/calculated/assumed/AI-interpreted distinctions and narrow context defaults; do not turn financial state into memory or allow implicit trade/transaction writes. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make decision-eval`, `make domain-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- Sensitive provider eligibility fails closed.

## Dependency map

**Prerequisites:** Phase 19 / Checkpoint E

```text
P20.0 Finance -> P20.1 Portfolio/account/security/research
P20.1 Portfolio/account/security/research -> P20.2 Finance
P20.2 Finance -> P20.3 Provider-eligibility
P20.3 Provider-eligibility -> P20.4 Finance
P20.4 Finance -> P20.5 Negative
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

- Code/configuration changes required by the work packages below, limited to Phase 20 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 20 work packages

### P20.0 — Read-only Finance providers

**Dependencies:** Phase 19 / Checkpoint E  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

**Work:**

- Start with read-only Finance providers.
- Reconcile the existing implementation relevant to **Start with read-only Finance providers.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

### P20.1 — Distinguish observed/calculated/assumed/AI-interpreted data

**Dependencies:** P20.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

**Work:**

- Distinguish observed/calculated/assumed/AI-interpreted data.
- Reconcile the existing implementation relevant to **Distinguish observed/calculated/assumed/AI-interpreted data.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

### P20.2 — Use stricter provenance

**Dependencies:** P20.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

**Work:**

- Use stricter provenance.
- Reconcile the existing implementation relevant to **Use stricter provenance.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.

**Requirements:**

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- Observability is not a second source of truth and must respect the underlying data sensitivity.

**Acceptance criteria:**

- A developer can reconstruct the decision path from safe metadata for named fixtures.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

### P20.3 — Apply Finance-specific provider eligibility

**Dependencies:** P20.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

**Work:**

- Apply Finance-specific provider eligibility.
- Reconcile the existing implementation relevant to **Apply Finance-specific provider eligibility.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Negative tests prove protected data/provider paths are never invoked after denial.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

### P20.4 — Allow no implicit mutation

**Dependencies:** P20.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

**Work:**

- Allow no implicit mutation.
- Reconcile the existing implementation relevant to **Allow no implicit mutation.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

### P20.5 — Read-only sidecar to portfolio/security/research views with narrow default scope

**Dependencies:** P20.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

**Work:**

- Add read-only sidecar to portfolio/security/research views with narrow default scope.
- Reconcile the existing implementation relevant to **Add read-only sidecar to portfolio/security/research views with narrow default scope.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- The feature is usable without hidden provider/storage coupling and fails recoverably.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

### P20.6 — Make broader portfolio/account context an explicit visible inclusion choice

**Dependencies:** P20.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

**Work:**

- Make broader portfolio/account context an explicit visible inclusion choice.
- Reconcile the existing implementation relevant to **Make broader portfolio/account context an explicit visible inclusion choice.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

### P20.7 — Preserve semantic labels in ContextPackage

**Dependencies:** P20.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

**Work:**

- Preserve semantic labels in ContextPackage.
- Reconcile the existing implementation relevant to **Preserve semantic labels in ContextPackage.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

### P20.8 — Copy/save-as-draft/research-note only where domain policy permits

**Dependencies:** P20.7 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

**Work:**

- Support Copy/save-as-draft/research-note only where domain policy permits.
- Reconcile the existing implementation relevant to **Support Copy/save-as-draft/research-note only where domain policy permits.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

### P20.9 — Do not execute trades or transactions from generic sidecar output

**Dependencies:** P20.8 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

**Work:**

- Do not execute trades or transactions from generic sidecar output.
- Reconcile the existing implementation relevant to **Do not execute trades or transactions from generic sidecar output.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.

**Requirements:**

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.

**Acceptance criteria:**

- The feature is usable without hidden provider/storage coupling and fails recoverably.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

### P20.10 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P20.9 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 20 commitment without pulling later-phase behavior forward.

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

- Observed/calculated/assumed/AI-interpreted labels survive retrieval, context building, and display.
- Narrow selected-security/account scope is the default.
- No trade/transfer/order mutation path may be reachable from generic inference.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Finance remains authoritative.
- Ineligible free providers never receive sensitive Finance context.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- transaction execution
- portfolio ownership in Personal AI
- implicit whole-portfolio disclosure
- new financial advice product scope

---

## Phase verification and closeout

### Required local/offline checks

- `make backend-test`
- `make backend-lint`
- `make frontend-test`
- `make frontend-lint`
- `make frontend-typecheck`
- existing context/memory/research evaluation commands affected by the change
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

## Phase 20 completion review

- 1. Did implementation satisfy every normative Phase 20 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Is sensitive/cross-domain data denied before retrieval/transmission when policy does not allow it?
- 8. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 20 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
