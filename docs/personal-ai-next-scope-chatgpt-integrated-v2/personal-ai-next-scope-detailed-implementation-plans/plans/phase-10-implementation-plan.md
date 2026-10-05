# Phase 10 implementation plan — Provider/model registry and strict-free eligibility

This is the detailed execution plan for integrated next-scope **Phase 10 — Provider/model registry and strict-free eligibility**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Describe endpoint capability/privacy/free eligibility independently of routing.

### Normative commitments from the integrated roadmap

- Define model profile schema.
- Represent enabled/strict-free flags.
- Represent capabilities and context/output limits.
- Represent provider data-policy metadata.
- Represent quota/reset metadata.
- Add initial profiles for configured Gemini free-tier, Groq Free-plan, and Cloudflare Workers Free models.
- Add strict-free admission guard.

### Phase acceptance criteria

- Paid/ineligible endpoints cannot enter strict-free candidate sets.
- Unknown data policy can conservatively exclude sensitive use.
- Current quota numbers are not application constants.

### Explicitly out of scope

- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/llm/`
- `backend/src/personal_ai/evaluation/`
- `backend/src/personal_ai/api/`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

`settings.py` has one `ai_provider`/`ai_model` configuration and feature gates; no versioned multi-provider capability/free-tier registry exists. Build eligibility over the Phase 9 adapters and Phase 7 sensitivity policy. Treat provider/model/free-tier facts as volatile configuration requiring account-specific verification; do not infer free eligibility from an adapter's existence or include ChatGPT plan models in automatic candidates. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make memory-eval`, `make research-eval`, `make domain-eval`, `make iterative-research-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Unknown facts remain explicitly unknown.
- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.
- Registry describes facts; the router in Phase 13 owns selection policy.

## Dependency map

**Prerequisites:** Phase 9

```text
P10.0 ModelProfile -> P10.1 Configuration
P10.1 Configuration -> P10.2 Data-policy
P10.2 Data-policy -> P10.3 Strict-free
P10.3 Strict-free -> P10.4 Initial
P10.4 Initial -> P10.5 Developer
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

- Code/configuration changes required by the work packages below, limited to Phase 10 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 10 work packages

### P10.0 — Model profile schema

**Dependencies:** Phase 9  

**Goal:** implement this scoped Phase 10 commitment without pulling later-phase behavior forward.

**Work:**

- Define model profile schema.
- Reconcile the existing implementation relevant to **Define model profile schema.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.

**Requirements:**

- Unknown facts remain explicitly unknown.
- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.

**Out of scope:**

- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

### P10.1 — Represent enabled/strict-free flags

**Dependencies:** P10.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 10 commitment without pulling later-phase behavior forward.

**Work:**

- Represent enabled/strict-free flags.
- Reconcile the existing implementation relevant to **Represent enabled/strict-free flags.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Unknown facts remain explicitly unknown.
- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

### P10.2 — Represent capabilities and context/output limits

**Dependencies:** P10.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 10 commitment without pulling later-phase behavior forward.

**Work:**

- Represent capabilities and context/output limits.
- Reconcile the existing implementation relevant to **Represent capabilities and context/output limits.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Unknown facts remain explicitly unknown.
- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

### P10.3 — Represent provider data-policy metadata

**Dependencies:** P10.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 10 commitment without pulling later-phase behavior forward.

**Work:**

- Represent provider data-policy metadata.
- Reconcile the existing implementation relevant to **Represent provider data-policy metadata.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.

**Requirements:**

- Unknown facts remain explicitly unknown.
- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Negative tests prove protected data/provider paths are never invoked after denial.

**Out of scope:**

- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

### P10.4 — Represent quota/reset metadata

**Dependencies:** P10.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 10 commitment without pulling later-phase behavior forward.

**Work:**

- Represent quota/reset metadata.
- Reconcile the existing implementation relevant to **Represent quota/reset metadata.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Unknown facts remain explicitly unknown.
- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

### P10.5 — Initial profiles for configured Gemini free-tier, Groq Free-plan, and Cloudflare…

**Dependencies:** P10.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 10 commitment without pulling later-phase behavior forward.

**Work:**

- Add initial profiles for configured Gemini free-tier, Groq Free-plan, and Cloudflare Workers Free models.
- Reconcile the existing implementation relevant to **Add initial profiles for configured Gemini free-tier, Groq Free-plan, and Cloudflare Workers Free models.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.

**Requirements:**

- Unknown facts remain explicitly unknown.
- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.
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

- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

### P10.6 — Strict-free admission guard

**Dependencies:** P10.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 10 commitment without pulling later-phase behavior forward.

**Work:**

- Add strict-free admission guard.
- Reconcile the existing implementation relevant to **Add strict-free admission guard.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.

**Requirements:**

- Unknown facts remain explicitly unknown.
- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.

**Out of scope:**

- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

### P10.7 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P10.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 10 commitment without pulling later-phase behavior forward.

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

- Unknown facts remain explicitly unknown.
- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Paid/ineligible endpoints cannot enter strict-free candidate sets.
- Unknown data policy can conservatively exclude sensitive use.
- Current quota numbers are not application constants.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

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

## Phase 10 completion review

- 1. Did implementation satisfy every normative Phase 10 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can provider/model selection or failure ever cross a strict-free/privacy/capability hard boundary? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 10 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
