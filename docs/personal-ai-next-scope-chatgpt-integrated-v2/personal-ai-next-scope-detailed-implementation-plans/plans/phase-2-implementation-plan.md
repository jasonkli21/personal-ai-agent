# Phase 2 implementation plan — Application registry and manifest model

This is the detailed execution plan for integrated next-scope **Phase 2 — Application registry and manifest model**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Move app capabilities/policy into registration.

### Normative commitments from the integrated roadmap

- Define `ApplicationDefinition`.
- Add registry.
- Register providers/tools/memory/sensitivity/cross-app metadata.
- Add initial app definitions/stubs.

### Phase acceptance criteria

- Adding an app does not require core branching.
- Invalid definitions fail clearly.

### Explicitly out of scope

- real domain context adapters
- cross-app grants
- provider routing policy
- domain mutations

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/domains/`
- `backend/src/personal_ai/context/`
- `backend/src/personal_ai/api/`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`domains/registry.py` currently registers `DomainModule` for local Travel/Shopping comparisons; `DomainRegistration` in `domains/contracts.py` describes that comparison capability. Reuse or extend this registry boundary for `ApplicationDefinition`, but do not mistake it for a complete application manifest or imply that Finance/Health applications already exist. App policy metadata must be independently validated before later provider/context work. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

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
- Registry data describes capabilities and policy; it does not become authoritative domain state.
- Core orchestration must route by manifest/capabilities rather than `if application_id == ...` branches.
- Unknown applications fail closed with stable errors.
- Initial domain entries may be stubs until their later integration phases.

## Dependency map

**Prerequisites:** Phase 1

```text
P2.0 ApplicationDefinition -> P2.1 Registry
P2.1 Registry -> P2.2 Capability/policy
P2.2 Capability/policy -> P2.3 Initial
P2.3 Initial -> P2.4 Validation,
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

- Code/configuration changes required by the work packages below, limited to Phase 2 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 2 work packages

### P2.0 — `ApplicationDefinition`

**Dependencies:** Phase 1  

**Goal:** implement this scoped Phase 2 commitment without pulling later-phase behavior forward.

**Work:**

- Define `ApplicationDefinition`.
- Reconcile the existing implementation relevant to **Define `ApplicationDefinition`.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Registry data describes capabilities and policy; it does not become authoritative domain state.
- Core orchestration must route by manifest/capabilities rather than `if application_id == ...` branches.
- Unknown applications fail closed with stable errors.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- real domain context adapters
- cross-app grants
- provider routing policy
- domain mutations

### P2.1 — Registry

**Dependencies:** P2.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 2 commitment without pulling later-phase behavior forward.

**Work:**

- Add registry.
- Reconcile the existing implementation relevant to **Add registry.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Represent volatile provider/application facts as validated configuration or persisted registry state rather than source-code constants.
- Add startup/load-time validation and developer inspection for the effective configuration.
- Cover unknown, disabled, malformed, and partially configured entries.

**Requirements:**

- Registry data describes capabilities and policy; it does not become authoritative domain state.
- Core orchestration must route by manifest/capabilities rather than `if application_id == ...` branches.
- Unknown applications fail closed with stable errors.
- Configuration cannot silently widen privacy or paid-use eligibility.

**Acceptance criteria:**

- Invalid registry/configuration state fails early with a safe actionable error.

**Out of scope:**

- real domain context adapters
- cross-app grants
- provider routing policy
- domain mutations

### P2.2 — Register providers/tools/memory/sensitivity/cross-app metadata

**Dependencies:** P2.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 2 commitment without pulling later-phase behavior forward.

**Work:**

- Register providers/tools/memory/sensitivity/cross-app metadata.
- Reconcile the existing implementation relevant to **Register providers/tools/memory/sensitivity/cross-app metadata.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
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

- Registry data describes capabilities and policy; it does not become authoritative domain state.
- Core orchestration must route by manifest/capabilities rather than `if application_id == ...` branches.
- Unknown applications fail closed with stable errors.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Negative tests prove protected data/provider paths are never invoked after denial.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- real domain context adapters
- cross-app grants
- provider routing policy
- domain mutations

### P2.3 — Initial app definitions/stubs

**Dependencies:** P2.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 2 commitment without pulling later-phase behavior forward.

**Work:**

- Add initial app definitions/stubs.
- Reconcile the existing implementation relevant to **Add initial app definitions/stubs.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Registry data describes capabilities and policy; it does not become authoritative domain state.
- Core orchestration must route by manifest/capabilities rather than `if application_id == ...` branches.
- Unknown applications fail closed with stable errors.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- real domain context adapters
- cross-app grants
- provider routing policy
- domain mutations

### P2.4 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P2.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 2 commitment without pulling later-phase behavior forward.

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

- Registry data describes capabilities and policy; it does not become authoritative domain state.
- Core orchestration must route by manifest/capabilities rather than `if application_id == ...` branches.
- Unknown applications fail closed with stable errors.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Adding an app does not require core branching.
- Invalid definitions fail clearly.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- real domain context adapters
- cross-app grants
- provider routing policy
- domain mutations

---

## Phase verification and closeout

### Required local/offline checks

- `make backend-test`
- `make backend-lint`
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

## Phase 2 completion review

- 1. Did implementation satisfy every normative Phase 2 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?

## Handoff to the next phase

Do not begin the next phase until the Phase 2 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
