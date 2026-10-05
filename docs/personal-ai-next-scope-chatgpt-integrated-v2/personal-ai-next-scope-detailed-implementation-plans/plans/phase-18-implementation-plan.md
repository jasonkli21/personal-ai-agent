# Phase 18 implementation plan — Travel integration

This is the detailed execution plan for integrated next-scope **Phase 18 — Travel integration**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Validate the complete context + routing architecture on a lower-sensitivity app.

### Normative commitments from the integrated roadmap

- Implement Travel context providers.
- Exercise profile/current state/research/conversation/memory.
- Route through inference runtime.
- Add end-to-end tests/traces.
- Add sidecar to trip/day/place views with active trip/day/entity plus relevant preferences/research.
- Make included trip context visible.
- Support Copy and safe draft insertion where appropriate.
- Keep itinerary writes out of the generic response path until Phase 23.

### Phase acceptance criteria

- Travel stays authoritative.
- Core has no Travel branching.
- Provider route is inspectable.

### Explicitly out of scope

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/domains/`
- `backend/src/personal_ai/context/`
- `backend/src/personal_ai/search/`
- `frontend/ shared sidecar hooks`
- Travel application integration boundary

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`domains/travel/` is an existing gated place/comparison module with Nominatim and decision snapshots, not an authoritative trip/day/place application store. Reuse its evidence and constraints while adding typed context reads from a Travel-owned application boundary. `itinerary_proposals/` is a gated AI-owned proposal example; it neither applies trip mutations nor completes Phase 23. Sidecar writes remain drafts until the domain validates a typed proposal. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make research-eval`, `make decision-eval`, `make domain-eval`, `make itinerary-proposal-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Personal AI never becomes the itinerary/reservation source of truth.
- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.
- Generic sidecar output cannot write itinerary state in this phase.

## Dependency map

**Prerequisites:** Phase 17.4

```text
P18.0 Travel -> P18.1 Profile/active-trip/itinerary/current-state
P18.1 Profile/active-trip/itinerary/current-state -> P18.2 Research/memory/conversation
P18.2 Research/memory/conversation -> P18.3 Inference-runtime
P18.3 Inference-runtime -> P18.4 Travel
P18.4 Travel -> P18.5 End-to-end
```

The map is sequencing guidance, not a requirement to commit once per work package. Prefer a few coherent commits that preserve reviewable boundaries.

## Required verification matrix

- Offline unit/contract tests cover success plus malformed/denied/unavailable/error paths for each new contract.
- Integration tests prove the phase composes with the existing owner/application/workspace and context boundaries.
- Regression tests prove the phase-disabled/default path preserves prior behavior.
- No automated test requires live provider credentials, a real GCP project, or personal data unless explicitly marked opt-in.
- Safe tracing/evidence records IDs, counts, versions, states, and reason codes without raw secrets or unnecessary private content.
- Documentation/release evidence states exactly which external provider/emulator/cloud checks were run, skipped, or remain open.
- ChatGPT-mode tests prove credentials never enter managed cloud persistence or browser storage and provider switching remains explicit.

## Required implementation artifacts

- Code/configuration changes required by the work packages below, limited to Phase 18 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 18 work packages

### P18.0 — Travel context providers

**Dependencies:** Phase 17.4  

**Goal:** implement this scoped Phase 18 commitment without pulling later-phase behavior forward.

**Work:**

- Implement Travel context providers.
- Reconcile the existing implementation relevant to **Implement Travel context providers.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- Personal AI never becomes the itinerary/reservation source of truth.
- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

### P18.1 — Exercise profile/current state/research/conversation/memory

**Dependencies:** P18.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 18 commitment without pulling later-phase behavior forward.

**Work:**

- Exercise profile/current state/research/conversation/memory.
- Reconcile the existing implementation relevant to **Exercise profile/current state/research/conversation/memory.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Personal AI never becomes the itinerary/reservation source of truth.
- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

### P18.2 — Route through inference runtime

**Dependencies:** P18.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 18 commitment without pulling later-phase behavior forward.

**Work:**

- Route through inference runtime.
- Reconcile the existing implementation relevant to **Route through inference runtime.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Thread the new data/behavior through API → service → repository/provider/context boundaries with one clear ownership path.
- Preserve existing default behavior when the new capability is absent or disabled.
- Add integration tests for success, explicit failure, cancellation/retry where relevant, and isolation boundaries.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.

**Requirements:**

- Personal AI never becomes the itinerary/reservation source of truth.
- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.
- No hidden side channel may bypass existing authorization/context/provider boundaries.
- Existing public API/SSE behavior changes only when this phase explicitly requires it.
- Optimization logic cannot widen a hard eligibility boundary.

**Acceptance criteria:**

- Existing regression tests remain green with the new path disabled/defaulted.
- The enabled path is attributable in traces/evidence without exposing sensitive payloads.
- Named fixtures reproduce route decisions and rejection reasons.

**Out of scope:**

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

### P18.3 — End-to-end tests/traces

**Dependencies:** P18.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 18 commitment without pulling later-phase behavior forward.

**Work:**

- Add end-to-end tests/traces.
- Reconcile the existing implementation relevant to **Add end-to-end tests/traces.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.

**Requirements:**

- Personal AI never becomes the itinerary/reservation source of truth.
- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.
- Observability is not a second source of truth and must respect the underlying data sensitivity.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.

**Acceptance criteria:**

- A developer can reconstruct the decision path from safe metadata for named fixtures.
- Results are reproducible from a clean checkout using documented commands.

**Out of scope:**

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

### P18.4 — Sidecar to trip/day/place views with active trip/day/entity plus relevant…

**Dependencies:** P18.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 18 commitment without pulling later-phase behavior forward.

**Work:**

- Add sidecar to trip/day/place views with active trip/day/entity plus relevant preferences/research.
- Reconcile the existing implementation relevant to **Add sidecar to trip/day/place views with active trip/day/entity plus relevant preferences/research.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Personal AI never becomes the itinerary/reservation source of truth.
- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- The feature is usable without hidden provider/storage coupling and fails recoverably.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

### P18.5 — Make included trip context visible

**Dependencies:** P18.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 18 commitment without pulling later-phase behavior forward.

**Work:**

- Make included trip context visible.
- Reconcile the existing implementation relevant to **Make included trip context visible.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Personal AI never becomes the itinerary/reservation source of truth.
- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

### P18.6 — Copy and safe draft insertion where appropriate

**Dependencies:** P18.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 18 commitment without pulling later-phase behavior forward.

**Work:**

- Support Copy and safe draft insertion where appropriate.
- Reconcile the existing implementation relevant to **Support Copy and safe draft insertion where appropriate.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Personal AI never becomes the itinerary/reservation source of truth.
- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

### P18.7 — Keep itinerary writes out of the generic response path until Phase 23

**Dependencies:** P18.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 18 commitment without pulling later-phase behavior forward.

**Work:**

- Keep itinerary writes out of the generic response path until Phase 23.
- Reconcile the existing implementation relevant to **Keep itinerary writes out of the generic response path until Phase 23.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Personal AI never becomes the itinerary/reservation source of truth.
- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

### P18.8 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P18.7 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 18 commitment without pulling later-phase behavior forward.

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

- Personal AI never becomes the itinerary/reservation source of truth.
- Context providers should return bounded typed records with Travel-owned references.
- Research evidence remains freshness/provenance-bearing and distinct from itinerary state.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Travel stays authoritative.
- Core has no Travel branching.
- Provider route is inspectable.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- itinerary mutation execution
- cross-app Health/Finance context
- Travel database migration into Personal AI
- new Travel product features

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

## Phase 18 completion review

- 1. Did implementation satisfy every normative Phase 18 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 18 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
