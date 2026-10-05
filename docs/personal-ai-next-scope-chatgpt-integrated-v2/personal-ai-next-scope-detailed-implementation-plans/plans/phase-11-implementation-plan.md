# Phase 11 implementation plan — Provider usage accounting and quota ledger

This is the detailed execution plan for integrated next-scope **Phase 11 — Provider usage accounting and quota ledger**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Measure capacity before optimizing it.

### Normative commitments from the integrated roadmap

- Record provider/model/task per invocation.
- Capture token usage where available.
- Record latency/success/429/5xx/retries.
- Add health/cooldown.
- Add quota/reset state with confidence/source.
- Expose compact developer summaries.

### Phase acceptance criteria

- Every normalized invocation is attributable.
- Unknown quota state remains unknown.

### Explicitly out of scope

- scarcity-aware route selection
- billing aggregation beyond project needs
- ChatGPT-plan opaque usage handling
- unbounded telemetry retention

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/llm/`
- `backend/src/personal_ai/evaluation/`
- `backend/src/personal_ai/storage/`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`auth/safeguards.py` and middleware currently reserve request-level provider/token estimates; iterative research has a per-run resource ledger. The repository review records uncounted countTokens, summaries, embeddings, worker and repeated operations (R1). Extend per-operation accounting across the existing `llm`, search and worker call paths, with explicit settlement/unknown states; do not relabel current estimates as a strict-free quota guarantee. This work also informs the still-open existing Phase 9 accounting gate. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make memory-eval`, `make memory-lifecycle-eval`, `make research-eval`, `make iterative-research-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Never fabricate token counts, remaining capacity, or reset timestamps.
- Accounting failures should not silently change inference semantics; define which failures are advisory versus admission-blocking.
- Store safe metadata only—no prompts/responses/secrets by default.
- The ledger must support exact/derived/configured/unknown confidence states.

## Dependency map

**Prerequisites:** Phase 10

```text
P11.0 UsageEvent -> P11.1 Invocation
P11.1 Invocation -> P11.2 Provider
P11.2 Provider -> P11.3 Quota/reset
P11.3 Quota/reset -> P11.4 Compact
P11.4 Compact -> P11.5 Failure/idempotency/accounting
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

- Code/configuration changes required by the work packages below, limited to Phase 11 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 11 work packages

### P11.0 — Provider/model/task per invocation

**Dependencies:** Phase 10  

**Goal:** implement this scoped Phase 11 commitment without pulling later-phase behavior forward.

**Work:**

- Record provider/model/task per invocation.
- Reconcile the existing implementation relevant to **Record provider/model/task per invocation.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.

**Requirements:**

- Never fabricate token counts, remaining capacity, or reset timestamps.
- Accounting failures should not silently change inference semantics; define which failures are advisory versus admission-blocking.
- Store safe metadata only—no prompts/responses/secrets by default.
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

- scarcity-aware route selection
- billing aggregation beyond project needs
- ChatGPT-plan opaque usage handling
- unbounded telemetry retention

### P11.1 — Token usage where available

**Dependencies:** P11.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 11 commitment without pulling later-phase behavior forward.

**Work:**

- Capture token usage where available.
- Reconcile the existing implementation relevant to **Capture token usage where available.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Never fabricate token counts, remaining capacity, or reset timestamps.
- Accounting failures should not silently change inference semantics; define which failures are advisory versus admission-blocking.
- Store safe metadata only—no prompts/responses/secrets by default.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- scarcity-aware route selection
- billing aggregation beyond project needs
- ChatGPT-plan opaque usage handling
- unbounded telemetry retention

### P11.2 — Latency/success/429/5xx/retries

**Dependencies:** P11.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 11 commitment without pulling later-phase behavior forward.

**Work:**

- Record latency/success/429/5xx/retries.
- Reconcile the existing implementation relevant to **Record latency/success/429/5xx/retries.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Never fabricate token counts, remaining capacity, or reset timestamps.
- Accounting failures should not silently change inference semantics; define which failures are advisory versus admission-blocking.
- Store safe metadata only—no prompts/responses/secrets by default.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- scarcity-aware route selection
- billing aggregation beyond project needs
- ChatGPT-plan opaque usage handling
- unbounded telemetry retention

### P11.3 — Health/cooldown

**Dependencies:** P11.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 11 commitment without pulling later-phase behavior forward.

**Work:**

- Add health/cooldown.
- Reconcile the existing implementation relevant to **Add health/cooldown.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Never fabricate token counts, remaining capacity, or reset timestamps.
- Accounting failures should not silently change inference semantics; define which failures are advisory versus admission-blocking.
- Store safe metadata only—no prompts/responses/secrets by default.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- scarcity-aware route selection
- billing aggregation beyond project needs
- ChatGPT-plan opaque usage handling
- unbounded telemetry retention

### P11.4 — Quota/reset state with confidence/source

**Dependencies:** P11.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 11 commitment without pulling later-phase behavior forward.

**Work:**

- Add quota/reset state with confidence/source.
- Reconcile the existing implementation relevant to **Add quota/reset state with confidence/source.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Never fabricate token counts, remaining capacity, or reset timestamps.
- Accounting failures should not silently change inference semantics; define which failures are advisory versus admission-blocking.
- Store safe metadata only—no prompts/responses/secrets by default.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- scarcity-aware route selection
- billing aggregation beyond project needs
- ChatGPT-plan opaque usage handling
- unbounded telemetry retention

### P11.5 — Expose compact developer summaries

**Dependencies:** P11.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 11 commitment without pulling later-phase behavior forward.

**Work:**

- Expose compact developer summaries.
- Reconcile the existing implementation relevant to **Expose compact developer summaries.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Never fabricate token counts, remaining capacity, or reset timestamps.
- Accounting failures should not silently change inference semantics; define which failures are advisory versus admission-blocking.
- Store safe metadata only—no prompts/responses/secrets by default.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- scarcity-aware route selection
- billing aggregation beyond project needs
- ChatGPT-plan opaque usage handling
- unbounded telemetry retention

### P11.6 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P11.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 11 commitment without pulling later-phase behavior forward.

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

- Never fabricate token counts, remaining capacity, or reset timestamps.
- Accounting failures should not silently change inference semantics; define which failures are advisory versus admission-blocking.
- Store safe metadata only—no prompts/responses/secrets by default.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Every normalized invocation is attributable.
- Unknown quota state remains unknown.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- scarcity-aware route selection
- billing aggregation beyond project needs
- ChatGPT-plan opaque usage handling
- unbounded telemetry retention

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

## Phase 11 completion review

- 1. Did implementation satisfy every normative Phase 11 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can provider/model selection or failure ever cross a strict-free/privacy/capability hard boundary? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 11 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
