# Phase 13 implementation plan — Deterministic task-aware routing

This is the detailed execution plan for integrated next-scope **Phase 13 — Deterministic task-aware routing**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Select eligible free models using transparent task rules.

### Normative commitments from the integrated roadmap

- Define a small task taxonomy.
- Add routing requirements for capability, sensitivity, context size, quality floor, and escalation.
- Apply hard eligibility filtering.
- Add fixed task-specific priorities.
- Trace rejection/selection.
- Route chat plus at least two non-chat subtasks.

### Phase acceptance criteria

- No round-robin.
- Privacy/capability precede scoring.
- Known task type does not require an LLM classifier.

### Explicitly out of scope

- quota scarcity scoring
- learned routing
- cascades
- ChatGPT-plan explicit lane

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/llm/`
- `backend/src/personal_ai/evaluation/`
- `backend/src/personal_ai/context/`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`api/dependencies.py` currently constructs Gemini directly and no task-aware model router exists. Add deterministic selection only after Phases 7–12 have policy, eligible models, accounting and storage; continue using the single context assembler and `LLMClient` family. Existing domain ranking in `ranking/policy.py` ranks evidence-backed candidates, not model routes. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make research-eval`, `make domain-eval`, `make iterative-research-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Hard filters run before any preference/scoring.
- Known callers should pass task type rather than paying for classification.
- Strict-free, privacy, capability, context limits, and known exhaustion/cooldown are hard constraints.
- Route decisions must be reconstructable from registry/ledger inputs.

## Dependency map

**Prerequisites:** Phase 12 / Checkpoint C

```text
P13.0 TaskType -> P13.1 Hard
P13.1 Hard -> P13.2 Static
P13.2 Static -> P13.3 Router
P13.3 Router -> P13.4 Route-decision
P13.4 Route-decision -> P13.5 Representative
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

- Code/configuration changes required by the work packages below, limited to Phase 13 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 13 work packages

### P13.0 — A small task taxonomy

**Dependencies:** Phase 12 / Checkpoint C  

**Goal:** implement this scoped Phase 13 commitment without pulling later-phase behavior forward.

**Work:**

- Define a small task taxonomy.
- Reconcile the existing implementation relevant to **Define a small task taxonomy.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.

**Requirements:**

- Hard filters run before any preference/scoring.
- Known callers should pass task type rather than paying for classification.
- Strict-free, privacy, capability, context limits, and known exhaustion/cooldown are hard constraints.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.

**Out of scope:**

- quota scarcity scoring
- learned routing
- cascades
- ChatGPT-plan explicit lane

### P13.1 — Routing requirements for capability, sensitivity, context size, quality floor, and…

**Dependencies:** P13.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 13 commitment without pulling later-phase behavior forward.

**Work:**

- Add routing requirements for capability, sensitivity, context size, quality floor, and escalation.
- Reconcile the existing implementation relevant to **Add routing requirements for capability, sensitivity, context size, quality floor, and escalation.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.

**Requirements:**

- Hard filters run before any preference/scoring.
- Known callers should pass task type rather than paying for classification.
- Strict-free, privacy, capability, context limits, and known exhaustion/cooldown are hard constraints.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- Optimization logic cannot widen a hard eligibility boundary.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Named fixtures reproduce route decisions and rejection reasons.

**Out of scope:**

- quota scarcity scoring
- learned routing
- cascades
- ChatGPT-plan explicit lane

### P13.2 — Apply hard eligibility filtering

**Dependencies:** P13.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 13 commitment without pulling later-phase behavior forward.

**Work:**

- Apply hard eligibility filtering.
- Reconcile the existing implementation relevant to **Apply hard eligibility filtering.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.

**Requirements:**

- Hard filters run before any preference/scoring.
- Known callers should pass task type rather than paying for classification.
- Strict-free, privacy, capability, context limits, and known exhaustion/cooldown are hard constraints.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.

**Out of scope:**

- quota scarcity scoring
- learned routing
- cascades
- ChatGPT-plan explicit lane

### P13.3 — Fixed task-specific priorities

**Dependencies:** P13.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 13 commitment without pulling later-phase behavior forward.

**Work:**

- Add fixed task-specific priorities.
- Reconcile the existing implementation relevant to **Add fixed task-specific priorities.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Hard filters run before any preference/scoring.
- Known callers should pass task type rather than paying for classification.
- Strict-free, privacy, capability, context limits, and known exhaustion/cooldown are hard constraints.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- quota scarcity scoring
- learned routing
- cascades
- ChatGPT-plan explicit lane

### P13.4 — Trace rejection/selection

**Dependencies:** P13.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 13 commitment without pulling later-phase behavior forward.

**Work:**

- Trace rejection/selection.
- Reconcile the existing implementation relevant to **Trace rejection/selection.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.

**Requirements:**

- Hard filters run before any preference/scoring.
- Known callers should pass task type rather than paying for classification.
- Strict-free, privacy, capability, context limits, and known exhaustion/cooldown are hard constraints.
- Observability is not a second source of truth and must respect the underlying data sensitivity.

**Acceptance criteria:**

- A developer can reconstruct the decision path from safe metadata for named fixtures.

**Out of scope:**

- quota scarcity scoring
- learned routing
- cascades
- ChatGPT-plan explicit lane

### P13.5 — Route chat plus at least two non-chat subtasks

**Dependencies:** P13.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 13 commitment without pulling later-phase behavior forward.

**Work:**

- Route chat plus at least two non-chat subtasks.
- Reconcile the existing implementation relevant to **Route chat plus at least two non-chat subtasks.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.

**Requirements:**

- Hard filters run before any preference/scoring.
- Known callers should pass task type rather than paying for classification.
- Strict-free, privacy, capability, context limits, and known exhaustion/cooldown are hard constraints.
- Optimization logic cannot widen a hard eligibility boundary.

**Acceptance criteria:**

- Named fixtures reproduce route decisions and rejection reasons.

**Out of scope:**

- quota scarcity scoring
- learned routing
- cascades
- ChatGPT-plan explicit lane

### P13.6 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P13.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 13 commitment without pulling later-phase behavior forward.

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

- Hard filters run before any preference/scoring.
- Known callers should pass task type rather than paying for classification.
- Strict-free, privacy, capability, context limits, and known exhaustion/cooldown are hard constraints.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- No round-robin.
- Privacy/capability precede scoring.
- Known task type does not require an LLM classifier.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- quota scarcity scoring
- learned routing
- cascades
- ChatGPT-plan explicit lane

---

## Phase verification and closeout

### Required local/offline checks

- `make backend-test`
- `make backend-lint`
- phase-specific inference/routing evaluation command added by the implementation if no existing command covers it
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

## Phase 13 completion review

- 1. Did implementation satisfy every normative Phase 13 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can provider/model selection or failure ever cross a strict-free/privacy/capability hard boundary? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 13 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
