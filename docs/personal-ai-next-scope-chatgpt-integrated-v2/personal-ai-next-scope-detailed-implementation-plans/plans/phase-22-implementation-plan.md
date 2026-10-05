# Phase 22 implementation plan — Cross-app context federation

This is the detailed execution plan for integrated next-scope **Phase 22 — Cross-app context federation**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Enable safe cross-domain intelligence.

### Normative commitments from the integrated roadmap

- Support initial cases: Health dietary restrictions -> Travel; Health ergonomic constraints -> Shopping; Travel trip -> Shopping; Finance discretionary budget -> Shopping.
- Make cross-app context categories visible when a ChatGPT sidecar request includes them.
- Preserve the most restrictive effective sensitivity in ContextPackage.
- Require explicit user/context-policy permission exactly as for automatic inference.

### Phase acceptance criteria

- Cross-app access is narrow and auditable.
- Revocation blocks future retrieval.
- Router reflects the most restrictive context sensitivity.

### Explicitly out of scope

- global profile dumping
- implicit all-app sharing
- domain mutation
- new federation cases beyond the four initial cases unless needed for plumbing tests

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/context/`
- `backend/src/personal_ai/domains/`
- `backend/src/personal_ai/auth/`
- `frontend/ context manifest`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

Cross-app context access does not exist today; owner-only OIDC is insufficient consent. Compose Phase 2 registry, Phase 3 context providers, Phase 7 deny-by-default policy, and Phase 17 ContextPackage visibility. Revocation must prevent future retrieval and effective sensitivity must be the most restrictive included source; neither automatic nor ChatGPT mode bypasses this check. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make memory-eval`, `make domain-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Cross-app context is not globally enabled.
- The destination app cannot directly query another app database through core shortcuts.
- Revocation affects future retrieval without mutating source state.
- The most restrictive supplied context governs downstream provider eligibility.

## Dependency map

**Prerequisites:** Phase 21

```text
P22.0 CrossAppContextGrant/access-policy -> P22.1 Brokered
P22.1 Brokered -> P22.2 Initial
P22.2 Initial -> P22.3 Sensitivity/provenance
P22.3 Sensitivity/provenance -> P22.4 Revocation
P22.4 Revocation -> P22.5 Sidecar
P22.5 Sidecar -> P22.6 Authorization/isolation/e2e
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

- Code/configuration changes required by the work packages below, limited to Phase 22 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 22 work packages

### P22.0 — Initial cases: Health dietary restrictions -> Travel

**Dependencies:** Phase 21  

**Goal:** implement this scoped Phase 22 commitment without pulling later-phase behavior forward.

**Work:**

- Support initial cases: Health dietary restrictions -> Travel; Health ergonomic constraints -> Shopping; Travel trip -> Shopping; Finance discretionary budget -> Shopping.
- Reconcile the existing implementation relevant to **Support initial cases: Health dietary restrictions -> Travel; Health ergonomic constraints -> Shopping; Travel trip -> Shopping; Finance discretionary budget -> Shopping.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Cross-app context is not globally enabled.
- The destination app cannot directly query another app database through core shortcuts.
- Revocation affects future retrieval without mutating source state.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- global profile dumping
- implicit all-app sharing
- domain mutation
- new federation cases beyond the four initial cases unless needed for plumbing tests

### P22.1 — Make cross-app context categories visible when a ChatGPT sidecar request includes them

**Dependencies:** P22.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 22 commitment without pulling later-phase behavior forward.

**Work:**

- Make cross-app context categories visible when a ChatGPT sidecar request includes them.
- Reconcile the existing implementation relevant to **Make cross-app context categories visible when a ChatGPT sidecar request includes them.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Cross-app context is not globally enabled.
- The destination app cannot directly query another app database through core shortcuts.
- Revocation affects future retrieval without mutating source state.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- Core orchestration must not query the domain database directly.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- The feature is usable without hidden provider/storage coupling and fails recoverably.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- global profile dumping
- implicit all-app sharing
- domain mutation
- new federation cases beyond the four initial cases unless needed for plumbing tests

### P22.2 — Preserve the most restrictive effective sensitivity in ContextPackage

**Dependencies:** P22.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 22 commitment without pulling later-phase behavior forward.

**Work:**

- Preserve the most restrictive effective sensitivity in ContextPackage.
- Reconcile the existing implementation relevant to **Preserve the most restrictive effective sensitivity in ContextPackage.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Cross-app context is not globally enabled.
- The destination app cannot directly query another app database through core shortcuts.
- Revocation affects future retrieval without mutating source state.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- global profile dumping
- implicit all-app sharing
- domain mutation
- new federation cases beyond the four initial cases unless needed for plumbing tests

### P22.3 — Require explicit user/context-policy permission exactly as for automatic inference

**Dependencies:** P22.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 22 commitment without pulling later-phase behavior forward.

**Work:**

- Require explicit user/context-policy permission exactly as for automatic inference.
- Reconcile the existing implementation relevant to **Require explicit user/context-policy permission exactly as for automatic inference.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Cross-app context is not globally enabled.
- The destination app cannot directly query another app database through core shortcuts.
- Revocation affects future retrieval without mutating source state.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- global profile dumping
- implicit all-app sharing
- domain mutation
- new federation cases beyond the four initial cases unless needed for plumbing tests

### P22.4 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P22.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 22 commitment without pulling later-phase behavior forward.

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

- Cross-app context is not globally enabled.
- The destination app cannot directly query another app database through core shortcuts.
- Revocation affects future retrieval without mutating source state.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Cross-app access is narrow and auditable.
- Revocation blocks future retrieval.
- Router reflects the most restrictive context sensitivity.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- global profile dumping
- implicit all-app sharing
- domain mutation
- new federation cases beyond the four initial cases unless needed for plumbing tests

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

## Phase 22 completion review

- 1. Did implementation satisfy every normative Phase 22 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Is sensitive/cross-domain data denied before retrieval/transmission when policy does not allow it?
- 8. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 22 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
