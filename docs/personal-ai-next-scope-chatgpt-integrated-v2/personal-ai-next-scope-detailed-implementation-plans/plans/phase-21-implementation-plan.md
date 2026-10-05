# Phase 21 implementation plan — Health integration

This is the detailed execution plan for integrated next-scope **Phase 21 — Health integration**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

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

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/domains/`
- `backend/src/personal_ai/context/`
- `backend/src/personal_ai/llm/ policy registry`
- Health application integration boundary
- `frontend/ shared sidecar hooks`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

No Health application/module exists locally. Add read-only, bounded Health context-provider contracts with field-level authorization before retrieval, most-restrictive provider eligibility and minimal retention. A ChatGPT sidecar must expose only authorized categories; native-mobile SIWC availability remains a separate capability check. Health state stays in the Health application, never flattened into memory. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

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
- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Medication/condition/clinical truth cannot be changed by generic model text.

## Dependency map

**Prerequisites:** Phase 20

```text
P21.0 Health -> P21.1 Field/category
P21.1 Field/category -> P21.2 Bounded
P21.2 Bounded -> P21.3 Strict
P21.3 Strict -> P21.4 Health
P21.4 Health -> P21.5 Read-only/mutation-boundary/privacy
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

- Code/configuration changes required by the work packages below, limited to Phase 21 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 21 work packages

### P21.0 — Read-only Health providers

**Dependencies:** Phase 20  

**Goal:** implement this scoped Phase 21 commitment without pulling later-phase behavior forward.

**Work:**

- Start with read-only Health providers.
- Reconcile the existing implementation relevant to **Start with read-only Health providers.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

### P21.1 — Flexible structured profile and bounded time queries

**Dependencies:** P21.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 21 commitment without pulling later-phase behavior forward.

**Work:**

- Support flexible structured profile and bounded time queries.
- Reconcile the existing implementation relevant to **Support flexible structured profile and bounded time queries.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.

**Requirements:**

- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.

**Out of scope:**

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

### P21.2 — Apply field sensitivity and strict provider eligibility

**Dependencies:** P21.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 21 commitment without pulling later-phase behavior forward.

**Work:**

- Apply field sensitivity and strict provider eligibility.
- Reconcile the existing implementation relevant to **Apply field sensitivity and strict provider eligibility.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.

**Requirements:**

- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Negative tests prove protected data/provider paths are never invoked after denial.

**Out of scope:**

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

### P21.3 — Use minimal context

**Dependencies:** P21.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 21 commitment without pulling later-phase behavior forward.

**Work:**

- Use minimal context.
- Reconcile the existing implementation relevant to **Use minimal context.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

### P21.4 — Allow mutation proposals only with domain rules

**Dependencies:** P21.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 21 commitment without pulling later-phase behavior forward.

**Work:**

- Allow mutation proposals only with domain rules.
- Reconcile the existing implementation relevant to **Allow mutation proposals only with domain rules.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

### P21.5 — Read-only sidecar with human-readable sensitive context categories and narrowing…

**Dependencies:** P21.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 21 commitment without pulling later-phase behavior forward.

**Work:**

- Add read-only sidecar with human-readable sensitive context categories and narrowing controls where practical.
- Reconcile the existing implementation relevant to **Add read-only sidecar with human-readable sensitive context categories and narrowing controls where practical.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- The feature is usable without hidden provider/storage coupling and fails recoverably.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

### P21.6 — Require Health authorization before a category can be offered

**Dependencies:** P21.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 21 commitment without pulling later-phase behavior forward.

**Work:**

- Require Health authorization before a category can be offered.
- Reconcile the existing implementation relevant to **Require Health authorization before a category can be offered.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

### P21.7 — Prevent generic sidecar output from directly editing medications, conditions,…

**Dependencies:** P21.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 21 commitment without pulling later-phase behavior forward.

**Work:**

- Prevent generic sidecar output from directly editing medications, conditions, measurements, or clinical records.
- Reconcile the existing implementation relevant to **Prevent generic sidecar output from directly editing medications, conditions, measurements, or clinical records.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.

**Requirements:**

- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- The feature is usable without hidden provider/storage coupling and fails recoverably.

**Out of scope:**

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

### P21.8 — Verify native-mobile SIWC support before mobile credential logic

**Dependencies:** P21.7 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 21 commitment without pulling later-phase behavior forward.

**Work:**

- Verify native-mobile SIWC support before mobile credential logic; preserve the Health roadmap regardless.
- Reconcile the existing implementation relevant to **Verify native-mobile SIWC support before mobile credential logic; preserve the Health roadmap regardless.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Core orchestration must not query the domain database directly.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

### P21.9 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P21.8 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 21 commitment without pulling later-phase behavior forward.

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

- Health domain state remains distinct from AI memory.
- Unauthorized categories must not be fetched merely to hide them later.
- Minimal/no verbose trace retention is the default for sensitive requests.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Health is not flattened into memory.
- Cross-app Health access is deny-by-default.
- Routing cannot weaken Health sensitivity.
- Verbose artifacts default to minimal/no retention for sensitive traces.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- clinical-record mutation execution
- medical device behavior
- regulatory compliance claims
- cross-app Health sharing before Phase 22

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

## Phase 21 completion review

- 1. Did implementation satisfy every normative Phase 21 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Is sensitive/cross-domain data denied before retrieval/transmission when policy does not allow it?
- 8. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 21 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
