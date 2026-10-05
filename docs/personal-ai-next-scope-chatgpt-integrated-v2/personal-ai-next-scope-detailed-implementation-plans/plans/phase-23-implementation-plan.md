# Phase 23 implementation plan — Mutation proposal framework

This is the detailed execution plan for integrated next-scope **Phase 23 — Mutation proposal framework**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Standardize AI-assisted edits without making Personal AI authoritative.

### Normative commitments from the integrated roadmap

- Define mutation proposal.
- Include target app/entity/patch/rationale/source/validation/confirmation/idempotency.
- Add domain validation callback.
- Require user confirmation before an AI-assisted authoritative write.
- Return authoritative post-state.
- Expose sidecar Apply only after conversion to a typed mutation proposal.
- Treat producing provider, including ChatGPT, as provenance rather than write authority.

### Phase acceptance criteria

- No arbitrary direct writes.
- Domain validation is mandatory.
- Mutation trace is auditable.

### Explicitly out of scope

- generic direct database writes
- transaction execution not supported by domain policy
- autonomous background mutations
- bypassing user confirmation for an AI-assisted authoritative write

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/domains/`
- `backend/src/personal_ai/api/`
- `backend/src/personal_ai/auth/`
- `frontend/ shared sidecar`
- `domain application integration boundaries`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`itinerary_proposals/` already offers a separately gated, bounded typed proposal and Travel-side preview example, while `booking_extractions/` validates extracted candidates. Neither supplies the general cross-domain proposal/confirmation/authoritative-post-state contract. Extend those patterns only where they fit; final validation, confirmation and mutation stay with the target domain app, including ChatGPT-produced proposals. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make decision-eval`, `make domain-eval`, `make itinerary-proposal-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Model output is never executed as an arbitrary patch.
- Domain validation and authorization happen after proposal creation and before authoritative write.
- Idempotency protects retries/double-clicks; post-state comes from the domain source of truth.
- Provider/model is retained as provenance, never authority.

## Dependency map

**Prerequisites:** Phase 22

```text
P23.0 MutationProposal -> P23.1 Domain
P23.1 Domain -> P23.2 Confirmation/idempotency/state-machine
P23.2 Confirmation/idempotency/state-machine -> P23.3 Execution
P23.3 Execution -> P23.4 Sidecar
P23.4 Sidecar -> P23.5 Audit/error/replay/concurrency
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

- Code/configuration changes required by the work packages below, limited to Phase 23 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 23 work packages

### P23.0 — Mutation proposal

**Dependencies:** Phase 22  

**Goal:** implement this scoped Phase 23 commitment without pulling later-phase behavior forward.

**Work:**

- Define mutation proposal.
- Reconcile the existing implementation relevant to **Define mutation proposal.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Model output is never executed as an arbitrary patch.
- Domain validation and authorization happen after proposal creation and before authoritative write.
- Idempotency protects retries/double-clicks; post-state comes from the domain source of truth.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- generic direct database writes
- transaction execution not supported by domain policy
- autonomous background mutations
- bypassing user confirmation for an AI-assisted authoritative write

### P23.1 — Include target app/entity/patch/rationale/source/validation/confirmation/idempotency

**Dependencies:** P23.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 23 commitment without pulling later-phase behavior forward.

**Work:**

- Include target app/entity/patch/rationale/source/validation/confirmation/idempotency.
- Reconcile the existing implementation relevant to **Include target app/entity/patch/rationale/source/validation/confirmation/idempotency.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Model output is never executed as an arbitrary patch.
- Domain validation and authorization happen after proposal creation and before authoritative write.
- Idempotency protects retries/double-clicks; post-state comes from the domain source of truth.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- generic direct database writes
- transaction execution not supported by domain policy
- autonomous background mutations
- bypassing user confirmation for an AI-assisted authoritative write

### P23.2 — Domain validation callback

**Dependencies:** P23.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 23 commitment without pulling later-phase behavior forward.

**Work:**

- Add domain validation callback.
- Reconcile the existing implementation relevant to **Add domain validation callback.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Model output is never executed as an arbitrary patch.
- Domain validation and authorization happen after proposal creation and before authoritative write.
- Idempotency protects retries/double-clicks; post-state comes from the domain source of truth.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- generic direct database writes
- transaction execution not supported by domain policy
- autonomous background mutations
- bypassing user confirmation for an AI-assisted authoritative write

### P23.3 — Require user confirmation before an AI-assisted authoritative write

**Dependencies:** P23.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 23 commitment without pulling later-phase behavior forward.

**Work:**

- Require user confirmation before an AI-assisted authoritative write.
- Reconcile the existing implementation relevant to **Require user confirmation before an AI-assisted authoritative write.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Model output is never executed as an arbitrary patch.
- Domain validation and authorization happen after proposal creation and before authoritative write.
- Idempotency protects retries/double-clicks; post-state comes from the domain source of truth.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- generic direct database writes
- transaction execution not supported by domain policy
- autonomous background mutations
- bypassing user confirmation for an AI-assisted authoritative write

### P23.4 — Return authoritative post-state

**Dependencies:** P23.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 23 commitment without pulling later-phase behavior forward.

**Work:**

- Return authoritative post-state.
- Reconcile the existing implementation relevant to **Return authoritative post-state.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Model output is never executed as an arbitrary patch.
- Domain validation and authorization happen after proposal creation and before authoritative write.
- Idempotency protects retries/double-clicks; post-state comes from the domain source of truth.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- generic direct database writes
- transaction execution not supported by domain policy
- autonomous background mutations
- bypassing user confirmation for an AI-assisted authoritative write

### P23.5 — Expose sidecar Apply only after conversion to a typed mutation proposal

**Dependencies:** P23.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 23 commitment without pulling later-phase behavior forward.

**Work:**

- Expose sidecar Apply only after conversion to a typed mutation proposal.
- Reconcile the existing implementation relevant to **Expose sidecar Apply only after conversion to a typed mutation proposal.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Model output is never executed as an arbitrary patch.
- Domain validation and authorization happen after proposal creation and before authoritative write.
- Idempotency protects retries/double-clicks; post-state comes from the domain source of truth.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- The feature is usable without hidden provider/storage coupling and fails recoverably.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- generic direct database writes
- transaction execution not supported by domain policy
- autonomous background mutations
- bypassing user confirmation for an AI-assisted authoritative write

### P23.6 — Treat producing provider, including ChatGPT, as provenance rather than write authority

**Dependencies:** P23.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 23 commitment without pulling later-phase behavior forward.

**Work:**

- Treat producing provider, including ChatGPT, as provenance rather than write authority.
- Reconcile the existing implementation relevant to **Treat producing provider, including ChatGPT, as provenance rather than write authority.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Model output is never executed as an arbitrary patch.
- Domain validation and authorization happen after proposal creation and before authoritative write.
- Idempotency protects retries/double-clicks; post-state comes from the domain source of truth.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Observability is not a second source of truth and must respect the underlying data sensitivity.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- A developer can reconstruct the decision path from safe metadata for named fixtures.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- generic direct database writes
- transaction execution not supported by domain policy
- autonomous background mutations
- bypassing user confirmation for an AI-assisted authoritative write

### P23.7 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P23.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 23 commitment without pulling later-phase behavior forward.

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

- Model output is never executed as an arbitrary patch.
- Domain validation and authorization happen after proposal creation and before authoritative write.
- Idempotency protects retries/double-clicks; post-state comes from the domain source of truth.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- No arbitrary direct writes.
- Domain validation is mandatory.
- Mutation trace is auditable.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- generic direct database writes
- transaction execution not supported by domain policy
- autonomous background mutations
- bypassing user confirmation for an AI-assisted authoritative write

---

## Phase verification and closeout

### Required local/offline checks

- `make backend-test`
- `make backend-lint`
- `make frontend-test`
- `make frontend-lint`
- `make frontend-typecheck`
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

## Phase 23 completion review

- 1. Did implementation satisfy every normative Phase 23 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Is sensitive/cross-domain data denied before retrieval/transmission when policy does not allow it?
- 8. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 23 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
