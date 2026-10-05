# Phase 25 implementation plan — Search and evidence retrieval optimization

This is the detailed execution plan for integrated next-scope **Phase 25 — Search and evidence retrieval optimization**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Give weaker models better evidence.

### Normative commitments from the integrated roadmap

- Run query-rewrite experiments.
- Add hybrid/source-specialized retrieval.
- Improve deduplication/freshness/reranking.
- Improve evidence compression/packing.
- Add search quota hooks when justified.
- Store bulky experiment artifacts in GCS.

### Phase acceptance criteria

- Measured end-answer/evidence improvement.
- Provenance preserved.

### Explicitly out of scope

- provider-proprietary grounding as the only search path
- unbounded crawling
- memory migration
- learned routing

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/search/`
- `backend/src/personal_ai/evidence/`
- `backend/src/personal_ai/entities/`
- `backend/src/personal_ai/ranking/`
- `backend/src/personal_ai/evaluation/`
- `experiments/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

Extend the bounded `search/`, `evidence/`, `agents/research/`, `entities/`, and `ranking/` paths and their evaluation fixtures. Brave snippet rights, freshness, TTL, attribution and Phase 8 iterative budgets remain in force. Phase 12 GCS may hold approved bulky experiment artifacts, not queryable canonical evidence or unrestricted source copies. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make research-eval`, `make iterative-research-eval`, `make decision-eval`, `make domain-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Evidence remains external, freshness-bearing observation and never becomes AI memory by accident.
- Deterministic source/provenance checks remain required.
- Search expansion is bounded by existing research budgets.
- Raw experiment output belongs in GCS when retained; compact summaries remain queryable.

## Dependency map

**Prerequisites:** Phase 24

```text
P25.0 Search/retrieval -> P25.1 Query
P25.1 Query -> P25.2 Hybrid/source-specialized
P25.2 Hybrid/source-specialized -> P25.3 Dedup/freshness/entity
P25.3 Dedup/freshness/entity -> P25.4 Evidence
P25.4 Evidence -> P25.5 Search-quota
P25.5 Search-quota -> P25.6 End-answer/provenance
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

- Code/configuration changes required by the work packages below, limited to Phase 25 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 25 work packages

### P25.0 — Run query-rewrite experiments

**Dependencies:** Phase 24  

**Goal:** implement this scoped Phase 25 commitment without pulling later-phase behavior forward.

**Work:**

- Run query-rewrite experiments.
- Reconcile the existing implementation relevant to **Run query-rewrite experiments.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Evidence remains external, freshness-bearing observation and never becomes AI memory by accident.
- Deterministic source/provenance checks remain required.
- Search expansion is bounded by existing research budgets.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- provider-proprietary grounding as the only search path
- unbounded crawling
- memory migration
- learned routing

### P25.1 — Hybrid/source-specialized retrieval

**Dependencies:** P25.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 25 commitment without pulling later-phase behavior forward.

**Work:**

- Add hybrid/source-specialized retrieval.
- Reconcile the existing implementation relevant to **Add hybrid/source-specialized retrieval.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Evidence remains external, freshness-bearing observation and never becomes AI memory by accident.
- Deterministic source/provenance checks remain required.
- Search expansion is bounded by existing research budgets.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- provider-proprietary grounding as the only search path
- unbounded crawling
- memory migration
- learned routing

### P25.2 — Improve deduplication/freshness/reranking

**Dependencies:** P25.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 25 commitment without pulling later-phase behavior forward.

**Work:**

- Improve deduplication/freshness/reranking.
- Reconcile the existing implementation relevant to **Improve deduplication/freshness/reranking.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Evidence remains external, freshness-bearing observation and never becomes AI memory by accident.
- Deterministic source/provenance checks remain required.
- Search expansion is bounded by existing research budgets.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- provider-proprietary grounding as the only search path
- unbounded crawling
- memory migration
- learned routing

### P25.3 — Improve evidence compression/packing

**Dependencies:** P25.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 25 commitment without pulling later-phase behavior forward.

**Work:**

- Improve evidence compression/packing.
- Reconcile the existing implementation relevant to **Improve evidence compression/packing.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Evidence remains external, freshness-bearing observation and never becomes AI memory by accident.
- Deterministic source/provenance checks remain required.
- Search expansion is bounded by existing research budgets.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- provider-proprietary grounding as the only search path
- unbounded crawling
- memory migration
- learned routing

### P25.4 — Search quota hooks when justified

**Dependencies:** P25.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 25 commitment without pulling later-phase behavior forward.

**Work:**

- Add search quota hooks when justified.
- Reconcile the existing implementation relevant to **Add search quota hooks when justified.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Evidence remains external, freshness-bearing observation and never becomes AI memory by accident.
- Deterministic source/provenance checks remain required.
- Search expansion is bounded by existing research budgets.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- provider-proprietary grounding as the only search path
- unbounded crawling
- memory migration
- learned routing

### P25.5 — Store bulky experiment artifacts in GCS

**Dependencies:** P25.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 25 commitment without pulling later-phase behavior forward.

**Work:**

- Store bulky experiment artifacts in GCS.
- Reconcile the existing implementation relevant to **Store bulky experiment artifacts in GCS.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.

**Requirements:**

- Evidence remains external, freshness-bearing observation and never becomes AI memory by accident.
- Deterministic source/provenance checks remain required.
- Search expansion is bounded by existing research budgets.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.

**Acceptance criteria:**

- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.

**Out of scope:**

- provider-proprietary grounding as the only search path
- unbounded crawling
- memory migration
- learned routing

### P25.6 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P25.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 25 commitment without pulling later-phase behavior forward.

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

- Evidence remains external, freshness-bearing observation and never becomes AI memory by accident.
- Deterministic source/provenance checks remain required.
- Search expansion is bounded by existing research budgets.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Measured end-answer/evidence improvement.
- Provenance preserved.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- provider-proprietary grounding as the only search path
- unbounded crawling
- memory migration
- learned routing

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

## Phase 25 completion review

- 1. Did implementation satisfy every normative Phase 25 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?

## Handoff to the next phase

Do not begin the next phase until the Phase 25 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
