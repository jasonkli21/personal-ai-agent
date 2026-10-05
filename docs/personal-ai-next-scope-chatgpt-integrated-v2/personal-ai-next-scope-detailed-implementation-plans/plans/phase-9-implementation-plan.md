# Phase 9 implementation plan — Concrete provider adapters: Gemini, Groq, Cloudflare

This is the detailed execution plan for integrated next-scope **Phase 9 — Concrete provider adapters: Gemini, Groq, Cloudflare**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Prove the provider boundary against the three explicitly planned providers without adding routing policy.

### Normative commitments from the integrated roadmap

- Migrate Gemini generation and structured memory extraction behind the neutral backend while preserving Gemini embeddings.
- Add Groq backend support for the minimal generation operations needed by actual tasks, with fake/contract tests and rate-limit/usage-header capture.
- Add Cloudflare Workers AI backend support for the minimal generation operations needed by actual tasks, with fake/contract tests.
- Verify strict-free configuration only against currently eligible account/tier models.
- Use LiteLLM internally where it reduces duplication or native adapters where cleaner; keep provider-specific details below the boundary.
- Do not add benchmarking, quota-aware selection, cascades, or generalized provider discovery in this phase.

### Phase acceptance criteria

- Gemini, Groq, and Cloudflare satisfy neutral contracts in opt-in compatibility checks.
- Strict-free tests never require paid provider paths.
- No provider-specific types leak into context/domain logic.

### Explicitly out of scope

- cross-provider quality benchmarking
- quota-aware router
- cascades
- provider discovery marketplace

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/llm/`
- `backend/tests/`
- `docs/`
- `infrastructure/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

Gemini generation, token counting, summary, memory extraction, and embeddings already have adapters under `llm/`; Groq and Cloudflare inference adapters are missing. Extend the Phase 8 neutral seam and `api/dependencies.py` composition; keep provider SDKs inside `llm`. This phase proves adapters only; free eligibility, routing, evaluation, and quota allocation remain Phases 10–16. Live account/model/free-plan suitability is unverified. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make memory-eval`, `make research-eval`, `make iterative-research-eval`, `make itinerary-proposal-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Concrete model IDs and free eligibility remain configuration/operational state.
- Capture usage/rate-limit metadata when provided, but do not build selection policy yet.
- Cloudflare models requiring Workers Paid are ineligible in strict-free configuration.
- Real-provider checks are opt-in and must not be represented as passed when credentials/network are unavailable.

## Dependency map

**Prerequisites:** Phase 8

```text
P9.0 Shared -> P9.1 Gemini
P9.1 Gemini -> P9.2 Groq
P9.2 Groq -> P9.3 Cloudflare
P9.3 Cloudflare -> P9.4 Provider
P9.4 Provider -> P9.5 Offline
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

- Code/configuration changes required by the work packages below, limited to Phase 9 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 9 work packages

### P9.0 — Migrate Gemini generation and structured memory extraction behind the neutral…

**Dependencies:** Phase 8  

**Goal:** implement this scoped Phase 9 commitment without pulling later-phase behavior forward.

**Work:**

- Migrate Gemini generation and structured memory extraction behind the neutral backend while preserving Gemini embeddings.
- Reconcile the existing implementation relevant to **Migrate Gemini generation and structured memory extraction behind the neutral backend while preserving Gemini embeddings.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Concrete model IDs and free eligibility remain configuration/operational state.
- Capture usage/rate-limit metadata when provided, but do not build selection policy yet.
- Cloudflare models requiring Workers Paid are ineligible in strict-free configuration.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- cross-provider quality benchmarking
- quota-aware router
- cascades
- provider discovery marketplace

### P9.1 — Groq backend support for the minimal generation operations needed by actual tasks,…

**Dependencies:** P9.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 9 commitment without pulling later-phase behavior forward.

**Work:**

- Add Groq backend support for the minimal generation operations needed by actual tasks, with fake/contract tests and rate-limit/usage-header capture.
- Reconcile the existing implementation relevant to **Add Groq backend support for the minimal generation operations needed by actual tasks, with fake/contract tests and rate-limit/usage-header capture.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.

**Requirements:**

- Concrete model IDs and free eligibility remain configuration/operational state.
- Capture usage/rate-limit metadata when provided, but do not build selection policy yet.
- Cloudflare models requiring Workers Paid are ineligible in strict-free configuration.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Results are reproducible from a clean checkout using documented commands.

**Out of scope:**

- cross-provider quality benchmarking
- quota-aware router
- cascades
- provider discovery marketplace

### P9.2 — Cloudflare Workers AI backend support for the minimal generation operations needed…

**Dependencies:** P9.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 9 commitment without pulling later-phase behavior forward.

**Work:**

- Add Cloudflare Workers AI backend support for the minimal generation operations needed by actual tasks, with fake/contract tests.
- Reconcile the existing implementation relevant to **Add Cloudflare Workers AI backend support for the minimal generation operations needed by actual tasks, with fake/contract tests.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.

**Requirements:**

- Concrete model IDs and free eligibility remain configuration/operational state.
- Capture usage/rate-limit metadata when provided, but do not build selection policy yet.
- Cloudflare models requiring Workers Paid are ineligible in strict-free configuration.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Results are reproducible from a clean checkout using documented commands.

**Out of scope:**

- cross-provider quality benchmarking
- quota-aware router
- cascades
- provider discovery marketplace

### P9.3 — Verify strict-free configuration only against currently eligible account/tier models

**Dependencies:** P9.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 9 commitment without pulling later-phase behavior forward.

**Work:**

- Verify strict-free configuration only against currently eligible account/tier models.
- Reconcile the existing implementation relevant to **Verify strict-free configuration only against currently eligible account/tier models.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Represent volatile provider/application facts as validated configuration or persisted registry state rather than source-code constants.
- Add startup/load-time validation and developer inspection for the effective configuration.
- Cover unknown, disabled, malformed, and partially configured entries.

**Requirements:**

- Concrete model IDs and free eligibility remain configuration/operational state.
- Capture usage/rate-limit metadata when provided, but do not build selection policy yet.
- Cloudflare models requiring Workers Paid are ineligible in strict-free configuration.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Configuration cannot silently widen privacy or paid-use eligibility.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Invalid registry/configuration state fails early with a safe actionable error.

**Out of scope:**

- cross-provider quality benchmarking
- quota-aware router
- cascades
- provider discovery marketplace

### P9.4 — Use LiteLLM internally where it reduces duplication or native adapters where cleaner

**Dependencies:** P9.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 9 commitment without pulling later-phase behavior forward.

**Work:**

- Use LiteLLM internally where it reduces duplication or native adapters where cleaner; keep provider-specific details below the boundary.
- Reconcile the existing implementation relevant to **Use LiteLLM internally where it reduces duplication or native adapters where cleaner; keep provider-specific details below the boundary.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.

**Requirements:**

- Concrete model IDs and free eligibility remain configuration/operational state.
- Capture usage/rate-limit metadata when provided, but do not build selection policy yet.
- Cloudflare models requiring Workers Paid are ineligible in strict-free configuration.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.

**Out of scope:**

- cross-provider quality benchmarking
- quota-aware router
- cascades
- provider discovery marketplace

### P9.5 — Do not add benchmarking, quota-aware selection, cascades, or generalized provider…

**Dependencies:** P9.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 9 commitment without pulling later-phase behavior forward.

**Work:**

- Do not add benchmarking, quota-aware selection, cascades, or generalized provider discovery in this phase.
- Reconcile the existing implementation relevant to **Do not add benchmarking, quota-aware selection, cascades, or generalized provider discovery in this phase.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.

**Requirements:**

- Concrete model IDs and free eligibility remain configuration/operational state.
- Capture usage/rate-limit metadata when provided, but do not build selection policy yet.
- Cloudflare models requiring Workers Paid are ineligible in strict-free configuration.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Optimization logic cannot widen a hard eligibility boundary.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Results are reproducible from a clean checkout using documented commands.
- Named fixtures reproduce route decisions and rejection reasons.

**Out of scope:**

- cross-provider quality benchmarking
- quota-aware router
- cascades
- provider discovery marketplace

### P9.6 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P9.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 9 commitment without pulling later-phase behavior forward.

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

- Concrete model IDs and free eligibility remain configuration/operational state.
- Capture usage/rate-limit metadata when provided, but do not build selection policy yet.
- Cloudflare models requiring Workers Paid are ineligible in strict-free configuration.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Gemini, Groq, and Cloudflare satisfy neutral contracts in opt-in compatibility checks.
- Strict-free tests never require paid provider paths.
- No provider-specific types leak into context/domain logic.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- cross-provider quality benchmarking
- quota-aware router
- cascades
- provider discovery marketplace

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

## Phase 9 completion review

- 1. Did implementation satisfy every normative Phase 9 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can provider/model selection or failure ever cross a strict-free/privacy/capability hard boundary? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 9 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
