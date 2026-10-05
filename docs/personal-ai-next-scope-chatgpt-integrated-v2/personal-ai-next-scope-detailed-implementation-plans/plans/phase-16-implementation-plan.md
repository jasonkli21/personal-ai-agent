# Phase 16 implementation plan — Bounded cascades and deterministic validation

This is the detailed execution plan for integrated next-scope **Phase 16 — Bounded cascades and deterministic validation**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Use abundant weaker models where safe and escalate only when useful.

### Normative commitments from the integrated roadmap

- Define cascade contract with max depth.
- Add deterministic validators for selected tasks: schema, provenance, hard constraints, required fields/citations.
- Escalate to stronger eligible free model.
- Evaluate cascade versus direct stronger-model use.

### Phase acceptance criteria

- Cascades are bounded.
- Sensitivity cannot widen.
- Adopted cascades improve quality or quota efficiency.

### Explicitly out of scope

- open-ended reflection loops
- privacy widening
- paid escalation
- adaptive routing

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/llm/`
- `backend/src/personal_ai/evaluation/`
- `backend/src/personal_ai/decisions/`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

Existing deterministic validators live in `evidence/pipeline.py`, `decisions/`, `ranking/policy.py`, `booking_extractions/service.py`, and `itinerary_proposals/service.py`; none is a general multi-provider cascade. Reuse task-specific validation patterns after Phase 13 routing and Phase 14 baselines, bound every extra provider call through Phase 11 accounting, and keep all turns on the shared context budget. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make research-eval`, `make decision-eval`, `make domain-eval`, `make iterative-research-eval`, `make itinerary-proposal-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- No model may self-grade confidence as the only validator.
- Each escalation reruns hard eligibility under the same-or-stricter sensitivity.
- Depth/attempt budgets are explicit and finite.
- Only tasks with meaningful deterministic validation should use cascades.

## Dependency map

**Prerequisites:** Phase 15

```text
P16.0 Cascade -> P16.1 Deterministic
P16.1 Deterministic -> P16.2 Bounded
P16.2 Bounded -> P16.3 Eligibility/sensitivity
P16.3 Eligibility/sensitivity -> P16.4 Trace/accounting
P16.4 Trace/accounting -> P16.5 Cascade-versus-direct
```

The map is sequencing guidance, not a requirement to commit once per work package. Prefer a few coherent commits that preserve reviewable boundaries.

## Required verification matrix

- Offline unit/contract tests cover success plus malformed/denied/unavailable/error paths for each new contract.
- Integration tests prove the phase composes with the existing owner/application/workspace and context boundaries.
- Regression tests prove the phase-disabled/default path preserves prior behavior.
- No automated test requires live provider credentials, a real GCP project, or personal data unless explicitly marked opt-in.
- Safe tracing/evidence records IDs, counts, versions, states, and reason codes without raw secrets or unnecessary private content.
- Documentation/release evidence states exactly which external provider/emulator/cloud checks were run, skipped, or remain open.
- Provider/model compatibility and quota/eligibility assertions are tested with fakes/config fixtures; real-provider behavior is an opt-in compatibility check.

## Required implementation artifacts

- Code/configuration changes required by the work packages below, limited to Phase 16 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 16 work packages

### P16.0 — Cascade contract with max depth

**Dependencies:** Phase 15  

**Goal:** implement this scoped Phase 16 commitment without pulling later-phase behavior forward.

**Work:**

- Define cascade contract with max depth.
- Reconcile the existing implementation relevant to **Define cascade contract with max depth.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.

**Requirements:**

- No model may self-grade confidence as the only validator.
- Each escalation reruns hard eligibility under the same-or-stricter sensitivity.
- Depth/attempt budgets are explicit and finite.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Optimization logic cannot widen a hard eligibility boundary.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Named fixtures reproduce route decisions and rejection reasons.

**Out of scope:**

- open-ended reflection loops
- privacy widening
- paid escalation
- adaptive routing

### P16.1 — Deterministic validators for selected tasks: schema, provenance, hard constraints,…

**Dependencies:** P16.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 16 commitment without pulling later-phase behavior forward.

**Work:**

- Add deterministic validators for selected tasks: schema, provenance, hard constraints, required fields/citations.
- Reconcile the existing implementation relevant to **Add deterministic validators for selected tasks: schema, provenance, hard constraints, required fields/citations.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.

**Requirements:**

- No model may self-grade confidence as the only validator.
- Each escalation reruns hard eligibility under the same-or-stricter sensitivity.
- Depth/attempt budgets are explicit and finite.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Observability is not a second source of truth and must respect the underlying data sensitivity.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- A developer can reconstruct the decision path from safe metadata for named fixtures.

**Out of scope:**

- open-ended reflection loops
- privacy widening
- paid escalation
- adaptive routing

### P16.2 — Escalate to stronger eligible free model

**Dependencies:** P16.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 16 commitment without pulling later-phase behavior forward.

**Work:**

- Escalate to stronger eligible free model.
- Reconcile the existing implementation relevant to **Escalate to stronger eligible free model.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.

**Requirements:**

- No model may self-grade confidence as the only validator.
- Each escalation reruns hard eligibility under the same-or-stricter sensitivity.
- Depth/attempt budgets are explicit and finite.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.

**Out of scope:**

- open-ended reflection loops
- privacy widening
- paid escalation
- adaptive routing

### P16.3 — Evaluate cascade versus direct stronger-model use

**Dependencies:** P16.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 16 commitment without pulling later-phase behavior forward.

**Work:**

- Evaluate cascade versus direct stronger-model use.
- Reconcile the existing implementation relevant to **Evaluate cascade versus direct stronger-model use.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.

**Requirements:**

- No model may self-grade confidence as the only validator.
- Each escalation reruns hard eligibility under the same-or-stricter sensitivity.
- Depth/attempt budgets are explicit and finite.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Optimization logic cannot widen a hard eligibility boundary.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Named fixtures reproduce route decisions and rejection reasons.

**Out of scope:**

- open-ended reflection loops
- privacy widening
- paid escalation
- adaptive routing

### P16.4 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P16.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 16 commitment without pulling later-phase behavior forward.

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

- No model may self-grade confidence as the only validator.
- Each escalation reruns hard eligibility under the same-or-stricter sensitivity.
- Depth/attempt budgets are explicit and finite.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Cascades are bounded.
- Sensitivity cannot widen.
- Adopted cascades improve quality or quota efficiency.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- open-ended reflection loops
- privacy widening
- paid escalation
- adaptive routing

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

## Phase 16 completion review

- 1. Did implementation satisfy every normative Phase 16 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can provider/model selection or failure ever cross a strict-free/privacy/capability hard boundary? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 16 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
