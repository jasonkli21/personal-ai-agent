# Phase 14 implementation plan — Cross-provider task evaluation matrix

This is the detailed execution plan for integrated next-scope **Phase 14 — Cross-provider task evaluation matrix**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Measure actual task quality.

### Normative commitments from the integrated roadmap

- Reuse/extend existing fixtures.
- Compare enabled strict-free Gemini, Groq, and Cloudflare models.
- Store raw outputs in GCS and summaries in Firestore.
- Version quality profiles.
- Define task quality floors.

### Phase acceptance criteria

- Router quality assumptions have project-specific evidence.
- Evaluations are bounded/reproducible.
- Strict-free eval mode cannot call paid endpoints.

### Explicitly out of scope

- automatic model promotion without thresholds
- paid-provider experiments in strict-free mode
- model judge as the sole scorer
- learned router

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/evaluation/`
- `experiments/`
- `backend/tests/`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`evaluation/` and CI already contain synthetic context/memory/research/decision/domain/iterative cases, but no cross-provider task quality matrix. Extend those fixture conventions and record model/policy/fixture versions. Phase 12 artifact storage is available in this sequence; retained raw outputs need sensitivity, access and retention policy and must not require real personal data in offline CI. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make memory-eval`, `make memory-lifecycle-eval`, `make research-eval`, `make decision-eval`, `make domain-eval`, `make iterative-research-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Project-specific task results outrank generic leaderboard assumptions.
- Separate deterministic offline fixtures from opt-in live-provider evaluations.
- Never claim a provider was evaluated if the live check was skipped.
- Evaluation must preserve sensitive-data policy; synthetic fixtures are the default.

## Dependency map

**Prerequisites:** Phase 13

```text
P14.0 Evaluation -> P14.1 Provider/model
P14.1 Provider/model -> P14.2 Task-specific
P14.2 Task-specific -> P14.3 Raw
P14.3 Raw -> P14.4 Quality-floor
P14.4 Quality-floor -> P14.5 Reproducibility/reporting/release
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

- Code/configuration changes required by the work packages below, limited to Phase 14 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 14 work packages

### P14.0 — Reuse/extend existing fixtures

**Dependencies:** Phase 13  

**Goal:** implement this scoped Phase 14 commitment without pulling later-phase behavior forward.

**Work:**

- Reuse/extend existing fixtures.
- Reconcile the existing implementation relevant to **Reuse/extend existing fixtures.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.

**Requirements:**

- Project-specific task results outrank generic leaderboard assumptions.
- Separate deterministic offline fixtures from opt-in live-provider evaluations.
- Never claim a provider was evaluated if the live check was skipped.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.

**Acceptance criteria:**

- Results are reproducible from a clean checkout using documented commands.

**Out of scope:**

- automatic model promotion without thresholds
- paid-provider experiments in strict-free mode
- model judge as the sole scorer
- learned router

### P14.1 — Compare enabled strict-free Gemini, Groq, and Cloudflare models

**Dependencies:** P14.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 14 commitment without pulling later-phase behavior forward.

**Work:**

- Compare enabled strict-free Gemini, Groq, and Cloudflare models.
- Reconcile the existing implementation relevant to **Compare enabled strict-free Gemini, Groq, and Cloudflare models.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.

**Requirements:**

- Project-specific task results outrank generic leaderboard assumptions.
- Separate deterministic offline fixtures from opt-in live-provider evaluations.
- Never claim a provider was evaluated if the live check was skipped.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.

**Out of scope:**

- automatic model promotion without thresholds
- paid-provider experiments in strict-free mode
- model judge as the sole scorer
- learned router

### P14.2 — Store raw outputs in GCS and summaries in Firestore

**Dependencies:** P14.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 14 commitment without pulling later-phase behavior forward.

**Work:**

- Store raw outputs in GCS and summaries in Firestore.
- Reconcile the existing implementation relevant to **Store raw outputs in GCS and summaries in Firestore.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.

**Requirements:**

- Project-specific task results outrank generic leaderboard assumptions.
- Separate deterministic offline fixtures from opt-in live-provider evaluations.
- Never claim a provider was evaluated if the live check was skipped.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.

**Acceptance criteria:**

- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.

**Out of scope:**

- automatic model promotion without thresholds
- paid-provider experiments in strict-free mode
- model judge as the sole scorer
- learned router

### P14.3 — Version quality profiles

**Dependencies:** P14.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 14 commitment without pulling later-phase behavior forward.

**Work:**

- Version quality profiles.
- Reconcile the existing implementation relevant to **Version quality profiles.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.

**Requirements:**

- Project-specific task results outrank generic leaderboard assumptions.
- Separate deterministic offline fixtures from opt-in live-provider evaluations.
- Never claim a provider was evaluated if the live check was skipped.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.

**Out of scope:**

- automatic model promotion without thresholds
- paid-provider experiments in strict-free mode
- model judge as the sole scorer
- learned router

### P14.4 — Task quality floors

**Dependencies:** P14.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 14 commitment without pulling later-phase behavior forward.

**Work:**

- Define task quality floors.
- Reconcile the existing implementation relevant to **Define task quality floors.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Project-specific task results outrank generic leaderboard assumptions.
- Separate deterministic offline fixtures from opt-in live-provider evaluations.
- Never claim a provider was evaluated if the live check was skipped.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- automatic model promotion without thresholds
- paid-provider experiments in strict-free mode
- model judge as the sole scorer
- learned router

### P14.5 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P14.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 14 commitment without pulling later-phase behavior forward.

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

- Project-specific task results outrank generic leaderboard assumptions.
- Separate deterministic offline fixtures from opt-in live-provider evaluations.
- Never claim a provider was evaluated if the live check was skipped.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Router quality assumptions have project-specific evidence.
- Evaluations are bounded/reproducible.
- Strict-free eval mode cannot call paid endpoints.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- automatic model promotion without thresholds
- paid-provider experiments in strict-free mode
- model judge as the sole scorer
- learned router

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

## Phase 14 completion review

- 1. Did implementation satisfy every normative Phase 14 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can provider/model selection or failure ever cross a strict-free/privacy/capability hard boundary? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 14 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
