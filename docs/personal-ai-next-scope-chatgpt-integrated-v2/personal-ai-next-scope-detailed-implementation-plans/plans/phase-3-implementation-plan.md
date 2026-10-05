# Phase 3 implementation plan — Context source and provider abstraction

This is the detailed execution plan for integrated next-scope **Phase 3 — Context source and provider abstraction**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Normalize structured domain-context access.

### Normative commitments from the integrated roadmap

- Define context source classes.
- Define provider capabilities/interfaces.
- Normalize context item/provider response.
- Carry provenance, authority, sensitivity, timestamps, and references.
- Wrap existing memory where appropriate.
- Add fixtures.

### Phase acceptance criteria

- Core orchestration does not query domain databases.
- Context retains source identity.

### Explicitly out of scope

- real Travel/Shopping/Finance/Health providers
- context planning policy
- model selection
- direct core access to domain databases

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/context/`
- `backend/src/personal_ai/memory/`
- `backend/src/personal_ai/domains/`
- `backend/src/personal_ai/evidence/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

The actual reusable seams are `context/contracts.py`, `context/assembler.py`, `memory/contracts.py` (`MemoryRepository`, `Embedder`), `evidence/contracts.py`, and `domains/registry.py`. Existing `DomainModule` is a comparison/source-adapter contract, not a typed read of an authoritative app database. Define bounded domain context providers around domain-owned APIs and preserve source, authority, sensitivity, freshness, and owner/app/workspace references; do not turn external evidence into memory. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make memory-eval`, `make research-eval`, `make domain-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Provider results must be typed, bounded, authorized, provenance-bearing, sensitivity-bearing, and predictable on failure.
- Distinguish authoritative domain state, AI memory, external evidence, conversation, and client context.
- Do not flatten domain schemas into a universal untyped blob.
- Provider contracts must be independently testable with fakes.

## Dependency map

**Prerequisites:** Phase 2

```text
P3.0 Context -> P3.1 ContextProvider
P3.1 ContextProvider -> P3.2 Provider
P3.2 Provider -> P3.3 Existing
P3.3 Existing -> P3.4 Fixtures
```

The map is sequencing guidance, not a requirement to commit once per work package. Prefer a few coherent commits that preserve reviewable boundaries.

## Required verification matrix

- Offline unit/contract tests cover success plus malformed/denied/unavailable/error paths for each new contract.
- Integration tests prove the phase composes with the existing owner/application/workspace and context boundaries.
- Regression tests prove the phase-disabled/default path preserves prior behavior.
- No automated test requires live provider credentials, a real GCP project, or personal data unless explicitly marked opt-in.
- Safe tracing/evidence records IDs, counts, versions, states, and reason codes without raw secrets or unnecessary private content.
- Documentation/release evidence states exactly which external provider/emulator/cloud checks were run, skipped, or remain open.

## Required implementation artifacts

- Code/configuration changes required by the work packages below, limited to Phase 3 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 3 work packages

### P3.0 — Context source classes

**Dependencies:** Phase 2  

**Goal:** implement this scoped Phase 3 commitment without pulling later-phase behavior forward.

**Work:**

- Define context source classes.
- Reconcile the existing implementation relevant to **Define context source classes.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Provider results must be typed, bounded, authorized, provenance-bearing, sensitivity-bearing, and predictable on failure.
- Distinguish authoritative domain state, AI memory, external evidence, conversation, and client context.
- Do not flatten domain schemas into a universal untyped blob.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- real Travel/Shopping/Finance/Health providers
- context planning policy
- model selection
- direct core access to domain databases

### P3.1 — Provider capabilities/interfaces

**Dependencies:** P3.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 3 commitment without pulling later-phase behavior forward.

**Work:**

- Define provider capabilities/interfaces.
- Reconcile the existing implementation relevant to **Define provider capabilities/interfaces.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.

**Requirements:**

- Provider results must be typed, bounded, authorized, provenance-bearing, sensitivity-bearing, and predictable on failure.
- Distinguish authoritative domain state, AI memory, external evidence, conversation, and client context.
- Do not flatten domain schemas into a universal untyped blob.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.

**Out of scope:**

- real Travel/Shopping/Finance/Health providers
- context planning policy
- model selection
- direct core access to domain databases

### P3.2 — Normalize context item/provider response

**Dependencies:** P3.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 3 commitment without pulling later-phase behavior forward.

**Work:**

- Normalize context item/provider response.
- Reconcile the existing implementation relevant to **Normalize context item/provider response.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Provider results must be typed, bounded, authorized, provenance-bearing, sensitivity-bearing, and predictable on failure.
- Distinguish authoritative domain state, AI memory, external evidence, conversation, and client context.
- Do not flatten domain schemas into a universal untyped blob.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- real Travel/Shopping/Finance/Health providers
- context planning policy
- model selection
- direct core access to domain databases

### P3.3 — Carry provenance, authority, sensitivity, timestamps, and references

**Dependencies:** P3.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 3 commitment without pulling later-phase behavior forward.

**Work:**

- Carry provenance, authority, sensitivity, timestamps, and references.
- Reconcile the existing implementation relevant to **Carry provenance, authority, sensitivity, timestamps, and references.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.

**Requirements:**

- Provider results must be typed, bounded, authorized, provenance-bearing, sensitivity-bearing, and predictable on failure.
- Distinguish authoritative domain state, AI memory, external evidence, conversation, and client context.
- Do not flatten domain schemas into a universal untyped blob.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Observability is not a second source of truth and must respect the underlying data sensitivity.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.
- A developer can reconstruct the decision path from safe metadata for named fixtures.

**Out of scope:**

- real Travel/Shopping/Finance/Health providers
- context planning policy
- model selection
- direct core access to domain databases

### P3.4 — Wrap existing memory where appropriate

**Dependencies:** P3.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 3 commitment without pulling later-phase behavior forward.

**Work:**

- Wrap existing memory where appropriate.
- Reconcile the existing implementation relevant to **Wrap existing memory where appropriate.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Provider results must be typed, bounded, authorized, provenance-bearing, sensitivity-bearing, and predictable on failure.
- Distinguish authoritative domain state, AI memory, external evidence, conversation, and client context.
- Do not flatten domain schemas into a universal untyped blob.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- real Travel/Shopping/Finance/Health providers
- context planning policy
- model selection
- direct core access to domain databases

### P3.5 — Fixtures

**Dependencies:** P3.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 3 commitment without pulling later-phase behavior forward.

**Work:**

- Add fixtures.
- Reconcile the existing implementation relevant to **Add fixtures.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.

**Requirements:**

- Provider results must be typed, bounded, authorized, provenance-bearing, sensitivity-bearing, and predictable on failure.
- Distinguish authoritative domain state, AI memory, external evidence, conversation, and client context.
- Do not flatten domain schemas into a universal untyped blob.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.

**Acceptance criteria:**

- Results are reproducible from a clean checkout using documented commands.

**Out of scope:**

- real Travel/Shopping/Finance/Health providers
- context planning policy
- model selection
- direct core access to domain databases

### P3.6 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P3.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 3 commitment without pulling later-phase behavior forward.

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

- Provider results must be typed, bounded, authorized, provenance-bearing, sensitivity-bearing, and predictable on failure.
- Distinguish authoritative domain state, AI memory, external evidence, conversation, and client context.
- Do not flatten domain schemas into a universal untyped blob.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Core orchestration does not query domain databases.
- Context retains source identity.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- real Travel/Shopping/Finance/Health providers
- context planning policy
- model selection
- direct core access to domain databases

---

## Phase verification and closeout

### Required local/offline checks

- `make backend-test`
- `make backend-lint`
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

## Phase 3 completion review

- 1. Did implementation satisfy every normative Phase 3 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?

## Handoff to the next phase

Do not begin the next phase until the Phase 3 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
