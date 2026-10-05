# Phase 4 implementation plan — Context builder refactor

This is the detailed execution plan for integrated next-scope **Phase 4 — Context builder refactor**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Make context assembly explicit, budgeted, and sensitivity-aware.

### Normative commitments from the integrated roadmap

- Extend/refactor current context assembly.
- Combine conversation, memory, domain, research, and tools.
- Add global/per-source budgets and priorities.
- Preserve provenance/authority.
- Compute effective sensitivity.
- Add structured debug output.

### Phase acceptance criteria

- Final context can be reconstructed.
- Budgets are enforced.
- Effective sensitivity is deterministic.

### Explicitly out of scope

- LLM-assisted planning
- provider routing
- domain mutations
- unbounded profile/history injection

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/context/`
- `backend/src/personal_ai/llm/context.py`
- `backend/src/personal_ai/api/`
- `backend/src/personal_ai/evaluation/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`ContextAssembler` already selects complete active-branch turns, compatible summaries, and optional memories; research and proposal paths also use it. Refactor this assembler and its contracts rather than creating a second builder. Preserve parent/supersedes history and the current provider-authoritative token count; new domain/tool/evidence blocks must share one final budget and carry exclusion reasons. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make memory-eval`, `make research-eval`, `make itinerary-proposal-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Preserve the existing token-budgeted context assembler behavior while broadening its sources.
- Mandatory newest-user-message and existing branch semantics remain intact.
- Effective sensitivity is monotonic: adding more restrictive context cannot lower sensitivity.
- Debug output must be safe metadata by default, not raw sensitive prompt content.

## Dependency map

**Prerequisites:** Phase 3

```text
P4.0 Builder -> P4.1 Source
P4.1 Source -> P4.2 Global
P4.2 Global -> P4.3 Authority/provenance/sensitivity
P4.3 Authority/provenance/sensitivity -> P4.4 Structured
P4.4 Structured -> P4.5 Chat-path
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

- Code/configuration changes required by the work packages below, limited to Phase 4 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 4 work packages

### P4.0 — Extend/refactor current context assembly

**Dependencies:** Phase 3  

**Goal:** implement this scoped Phase 4 commitment without pulling later-phase behavior forward.

**Work:**

- Extend/refactor current context assembly.
- Reconcile the existing implementation relevant to **Extend/refactor current context assembly.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Preserve the existing token-budgeted context assembler behavior while broadening its sources.
- Mandatory newest-user-message and existing branch semantics remain intact.
- Effective sensitivity is monotonic: adding more restrictive context cannot lower sensitivity.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- LLM-assisted planning
- provider routing
- domain mutations
- unbounded profile/history injection

### P4.1 — Combine conversation, memory, domain, research, and tools

**Dependencies:** P4.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 4 commitment without pulling later-phase behavior forward.

**Work:**

- Combine conversation, memory, domain, research, and tools.
- Reconcile the existing implementation relevant to **Combine conversation, memory, domain, research, and tools.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Preserve the existing token-budgeted context assembler behavior while broadening its sources.
- Mandatory newest-user-message and existing branch semantics remain intact.
- Effective sensitivity is monotonic: adding more restrictive context cannot lower sensitivity.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- LLM-assisted planning
- provider routing
- domain mutations
- unbounded profile/history injection

### P4.2 — Global/per-source budgets and priorities

**Dependencies:** P4.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 4 commitment without pulling later-phase behavior forward.

**Work:**

- Add global/per-source budgets and priorities.
- Reconcile the existing implementation relevant to **Add global/per-source budgets and priorities.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Preserve the existing token-budgeted context assembler behavior while broadening its sources.
- Mandatory newest-user-message and existing branch semantics remain intact.
- Effective sensitivity is monotonic: adding more restrictive context cannot lower sensitivity.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- LLM-assisted planning
- provider routing
- domain mutations
- unbounded profile/history injection

### P4.3 — Preserve provenance/authority

**Dependencies:** P4.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 4 commitment without pulling later-phase behavior forward.

**Work:**

- Preserve provenance/authority.
- Reconcile the existing implementation relevant to **Preserve provenance/authority.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.

**Requirements:**

- Preserve the existing token-budgeted context assembler behavior while broadening its sources.
- Mandatory newest-user-message and existing branch semantics remain intact.
- Effective sensitivity is monotonic: adding more restrictive context cannot lower sensitivity.
- Observability is not a second source of truth and must respect the underlying data sensitivity.

**Acceptance criteria:**

- A developer can reconstruct the decision path from safe metadata for named fixtures.

**Out of scope:**

- LLM-assisted planning
- provider routing
- domain mutations
- unbounded profile/history injection

### P4.4 — Compute effective sensitivity

**Dependencies:** P4.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 4 commitment without pulling later-phase behavior forward.

**Work:**

- Compute effective sensitivity.
- Reconcile the existing implementation relevant to **Compute effective sensitivity.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.

**Requirements:**

- Preserve the existing token-budgeted context assembler behavior while broadening its sources.
- Mandatory newest-user-message and existing branch semantics remain intact.
- Effective sensitivity is monotonic: adding more restrictive context cannot lower sensitivity.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.

**Out of scope:**

- LLM-assisted planning
- provider routing
- domain mutations
- unbounded profile/history injection

### P4.5 — Structured debug output

**Dependencies:** P4.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 4 commitment without pulling later-phase behavior forward.

**Work:**

- Add structured debug output.
- Reconcile the existing implementation relevant to **Add structured debug output.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Preserve the existing token-budgeted context assembler behavior while broadening its sources.
- Mandatory newest-user-message and existing branch semantics remain intact.
- Effective sensitivity is monotonic: adding more restrictive context cannot lower sensitivity.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- LLM-assisted planning
- provider routing
- domain mutations
- unbounded profile/history injection

### P4.6 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P4.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 4 commitment without pulling later-phase behavior forward.

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

- Preserve the existing token-budgeted context assembler behavior while broadening its sources.
- Mandatory newest-user-message and existing branch semantics remain intact.
- Effective sensitivity is monotonic: adding more restrictive context cannot lower sensitivity.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Final context can be reconstructed.
- Budgets are enforced.
- Effective sensitivity is deterministic.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- LLM-assisted planning
- provider routing
- domain mutations
- unbounded profile/history injection

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

## Phase 4 completion review

- 1. Did implementation satisfy every normative Phase 4 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?

## Handoff to the next phase

Do not begin the next phase until the Phase 4 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
