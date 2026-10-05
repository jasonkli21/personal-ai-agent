# Phase 19 implementation plan — Shopping integration

This is the detailed execution plan for integrated next-scope **Phase 19 — Shopping integration**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Validate project state, external evidence, constraints, and routing.

### Normative commitments from the integrated roadmap

- Implement Shopping providers.
- Feed structured requirements to product research.
- Preserve hard/soft constraints.
- Use saved/rejected products.
- Evaluate routing for extraction/rewrite/synthesis.
- Add sidecar to project/search/comparison/product views with explicitly selected products and active requirements.
- Show selected context before ChatGPT send.
- Support Copy and non-authoritative draft insertion.
- Keep shortlist/requirement mutations behind Phase 23.

### Phase acceptance criteria

- Recommendations reflect project state.
- Deterministic constraints remain authoritative.
- Personal AI does not own Shopping state.

### Explicitly out of scope

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/domains/`
- `backend/src/personal_ai/search/`
- `backend/src/personal_ai/ranking/`
- `backend/src/personal_ai/context/`
- Shopping application integration boundary
- `frontend/ shared sidecar hooks`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`domains/shopping/` is an existing gated barcode/catalog comparison module with Open Food Facts; it has no authoritative shopping project, shortlist or purchase store. Reuse typed claims, constraints, ranking and evidence, then obtain project/current-state context from the Shopping-owned application. Sidecar Insert remains non-authoritative and shortlist/requirement changes await Phase 23. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make research-eval`, `make decision-eval`, `make domain-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.
- Generic sidecar output cannot mutate shortlist/requirements in this phase.

## Dependency map

**Prerequisites:** Phase 18

```text
P19.0 Shopping -> P19.1 Project
P19.1 Project -> P19.2 Research/evidence
P19.2 Research/evidence -> P19.3 Task-routing
P19.3 Task-routing -> P19.4 Shopping
P19.4 Shopping -> P19.5 End-to-end
```

The map is sequencing guidance, not a requirement to commit once per work package. Prefer a few coherent commits that preserve reviewable boundaries.

## Required verification matrix

- Offline unit/contract tests cover success plus malformed/denied/unavailable/error paths for each new contract.
- Integration tests prove the phase composes with the existing owner/application/workspace and context boundaries.
- Regression tests prove the phase-disabled/default path preserves prior behavior.
- No automated test requires live provider credentials, a real GCP project, or personal data unless explicitly marked opt-in.
- Safe tracing/evidence records IDs, counts, versions, states, and reason codes without raw secrets or unnecessary private content.
- Documentation/release evidence states exactly which external provider/emulator/cloud checks were run, skipped, or remain open.
- ChatGPT-mode tests prove credentials never enter managed cloud persistence or browser storage and provider switching remains explicit.

## Required implementation artifacts

- Code/configuration changes required by the work packages below, limited to Phase 19 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 19 work packages

### P19.0 — Shopping providers

**Dependencies:** Phase 18  

**Goal:** implement this scoped Phase 19 commitment without pulling later-phase behavior forward.

**Work:**

- Implement Shopping providers.
- Reconcile the existing implementation relevant to **Implement Shopping providers.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

### P19.1 — Feed structured requirements to product research

**Dependencies:** P19.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 19 commitment without pulling later-phase behavior forward.

**Work:**

- Feed structured requirements to product research.
- Reconcile the existing implementation relevant to **Feed structured requirements to product research.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

### P19.2 — Preserve hard/soft constraints

**Dependencies:** P19.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 19 commitment without pulling later-phase behavior forward.

**Work:**

- Preserve hard/soft constraints.
- Reconcile the existing implementation relevant to **Preserve hard/soft constraints.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

### P19.3 — Use saved/rejected products

**Dependencies:** P19.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 19 commitment without pulling later-phase behavior forward.

**Work:**

- Use saved/rejected products.
- Reconcile the existing implementation relevant to **Use saved/rejected products.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

### P19.4 — Evaluate routing for extraction/rewrite/synthesis

**Dependencies:** P19.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 19 commitment without pulling later-phase behavior forward.

**Work:**

- Evaluate routing for extraction/rewrite/synthesis.
- Reconcile the existing implementation relevant to **Evaluate routing for extraction/rewrite/synthesis.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.

**Requirements:**

- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.
- Optimization logic cannot widen a hard eligibility boundary.

**Acceptance criteria:**

- Named fixtures reproduce route decisions and rejection reasons.

**Out of scope:**

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

### P19.5 — Sidecar to project/search/comparison/product views with explicitly selected products…

**Dependencies:** P19.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 19 commitment without pulling later-phase behavior forward.

**Work:**

- Add sidecar to project/search/comparison/product views with explicitly selected products and active requirements.
- Reconcile the existing implementation relevant to **Add sidecar to project/search/comparison/product views with explicitly selected products and active requirements.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.

**Requirements:**

- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.

**Acceptance criteria:**

- Results are reproducible from a clean checkout using documented commands.
- The feature is usable without hidden provider/storage coupling and fails recoverably.

**Out of scope:**

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

### P19.6 — Show selected context before ChatGPT send

**Dependencies:** P19.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 19 commitment without pulling later-phase behavior forward.

**Work:**

- Show selected context before ChatGPT send.
- Reconcile the existing implementation relevant to **Show selected context before ChatGPT send.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

### P19.7 — Copy and non-authoritative draft insertion

**Dependencies:** P19.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 19 commitment without pulling later-phase behavior forward.

**Work:**

- Support Copy and non-authoritative draft insertion.
- Reconcile the existing implementation relevant to **Support Copy and non-authoritative draft insertion.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

### P19.8 — Keep shortlist/requirement mutations behind Phase 23

**Dependencies:** P19.7 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 19 commitment without pulling later-phase behavior forward.

**Work:**

- Keep shortlist/requirement mutations behind Phase 23.
- Reconcile the existing implementation relevant to **Keep shortlist/requirement mutations behind Phase 23.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

### P19.9 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P19.8 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 19 commitment without pulling later-phase behavior forward.

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

- Hard constraints are code/data policy, not model suggestions.
- Rejected/saved state is authoritative Shopping state supplied through providers.
- External prices/availability/reviews remain evidence with freshness.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Recommendations reflect project state.
- Deterministic constraints remain authoritative.
- Personal AI does not own Shopping state.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- checkout/purchase execution
- shortlist mutations before Phase 23
- Shopping state duplication in core
- cross-app budget federation

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

## Phase 19 completion review

- 1. Did implementation satisfy every normative Phase 19 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 19 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
