# Phase 28 implementation plan — Integrated evaluation and hardening

This is the detailed execution plan for integrated next-scope **Phase 28 — Integrated evaluation and hardening**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions.

## Scope boundary

**Goal:** Validate the complete multi-app, multi-provider, two-tier-storage platform.

### Normative commitments from the integrated roadmap

- Evaluate app/workspace isolation, context relevance/omission, provenance, authority confusion, mutation safety, strict-free enforcement, provider failure handling, quota exhaustion, cascade correctness, sensitive routing, Firestore/GCS growth and retention, artifact authorization, deletion/export propagation, and provider removal/change.
- Add ChatGPT hardening for credential absence, bridge caller security, revoked/expired auth, account switching, model disappearance, consent/ineligibility/usage limits, interrupted streams, explicit-only routing, explicit provider switching, domain context minimization, provider attribution, and Copy/Insert/Apply boundaries.

### Phase acceptance criteria

- No known cross-app isolation failure.
- No known paid-overflow path.
- No sensitivity-unsafe fallback.
- No public/unauthorized artifact path.
- Firestore does not retain avoidable bulky raw evaluation/trace data.
- Provider failures degrade explicitly.
- Regression suites cover quality and resource behavior.

### Explicitly out of scope

- new domain features
- new provider families
- major architecture rewrites
- claims of regulatory compliance

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/`
- `frontend/`
- `infrastructure/`
- `experiments/`
- `docs/`
- `Firestore/GCS/provider opt-in verification paths`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

Integrate the existing `.github/workflows/quality.yml`, evaluation suites, `docs/phase-9-release-checklist.md`, and `infrastructure/gcp/deploy.sh` with all new phase checks. Existing Phase 9 physical deletion, full migration, provider accounting and cloud release gates are not complete. Prove strict-free infrastructure/provider limits, Firestore/GCS retention and artifact access, domain authority, and the separate ChatGPT credential/sidecar failure matrix before any production claim. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make memory-eval`, `make memory-lifecycle-eval`, `make research-eval`, `make decision-eval`, `make domain-eval`, `make iterative-research-eval`, `make itinerary-proposal-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- This phase validates the built system; it is not permission to add missing product features.
- Cloud/provider/emulator checks remain opt-in and must be reported separately from offline deterministic results.
- Strict-$0 guardrails cover supporting GCP infrastructure as well as model inference.
- Security/privacy failures block release rather than being papered over with a feature flag.

## Dependency map

**Prerequisites:** Phase 27 plus all prior domain/integration phases

```text
P28.0 Integrated -> P28.1 Isolation/context/provenance/authority
P28.1 Isolation/context/provenance/authority -> P28.2 Provider/routing/quota/cascade
P28.2 Provider/routing/quota/cascade -> P28.3 Storage/artifact/retention/resource-growth
P28.3 Storage/artifact/retention/resource-growth -> P28.4 Mutation/export/deletion
P28.4 Mutation/export/deletion -> P28.5 ChatGPT
P28.5 ChatGPT -> P28.6 Deployment/rollback/kill-switch/provider-removal
P28.6 Deployment/rollback/kill-switch/provider-removal -> P28.7 Final
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
- Negative authorization/sensitivity tests prove protected data is not retrieved or transmitted after denial.
- Storage failure/orphan/retention/authorization behavior is exercised without relying on public buckets or production data.
- ChatGPT-mode tests prove credentials never enter managed cloud persistence or browser storage and provider switching remains explicit.

## Required implementation artifacts

- Code/configuration changes required by the work packages below, limited to Phase 28 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 28 work packages

### P28.0 — Evaluate app/workspace isolation, context relevance/omission, provenance, authority…

**Dependencies:** Phase 27 plus all prior domain/integration phases  

**Goal:** implement this scoped Phase 28 commitment without pulling later-phase behavior forward.

**Work:**

- Evaluate app/workspace isolation, context relevance/omission, provenance, authority confusion, mutation safety, strict-free enforcement, provider failure handling, quota exhaustion, cascade correctness, sensitive routing, Firestore/GCS growth and retention, artifact authorization, deletion/export propagation, and provider removal/change.
- Reconcile the existing implementation relevant to **Evaluate app/workspace isolation, context relevance/omission, provenance, authority confusion, mutation safety, strict-free enforcement, provider failure handling, quota exhaustion, cascade correctness, sensitive routing, Firestore/GCS growth and retention, artifact authorization, deletion/export propagation, and provider removal/change.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Thread the new data/behavior through API → service → repository/provider/context boundaries with one clear ownership path.
- Preserve existing default behavior when the new capability is absent or disabled.
- Add integration tests for success, explicit failure, cancellation/retry where relevant, and isolation boundaries.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.

**Requirements:**

- This phase validates the built system; it is not permission to add missing product features.
- Cloud/provider/emulator checks remain opt-in and must be reported separately from offline deterministic results.
- Strict-$0 guardrails cover supporting GCP infrastructure as well as model inference.
- No hidden side channel may bypass existing authorization/context/provider boundaries.
- Existing public API/SSE behavior changes only when this phase explicitly requires it.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.
- Observability is not a second source of truth and must respect the underlying data sensitivity.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- Optimization logic cannot widen a hard eligibility boundary.
- Core orchestration must not query the domain database directly.

**Acceptance criteria:**

- Existing regression tests remain green with the new path disabled/defaulted.
- The enabled path is attributable in traces/evidence without exposing sensitive payloads.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Negative tests prove protected data/provider paths are never invoked after denial.
- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.
- A developer can reconstruct the decision path from safe metadata for named fixtures.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Named fixtures reproduce route decisions and rejection reasons.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.

**Out of scope:**

- new domain features
- new provider families
- major architecture rewrites
- claims of regulatory compliance

### P28.1 — ChatGPT hardening for credential absence, bridge caller security, revoked/expired…

**Dependencies:** P28.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 28 commitment without pulling later-phase behavior forward.

**Work:**

- Add ChatGPT hardening for credential absence, bridge caller security, revoked/expired auth, account switching, model disappearance, consent/ineligibility/usage limits, interrupted streams, explicit-only routing, explicit provider switching, domain context minimization, provider attribution, and Copy/Insert/Apply boundaries.
- Reconcile the existing implementation relevant to **Add ChatGPT hardening for credential absence, bridge caller security, revoked/expired auth, account switching, model disappearance, consent/ineligibility/usage limits, interrupted streams, explicit-only routing, explicit provider switching, domain context minimization, provider attribution, and Copy/Insert/Apply boundaries.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.
- Keep the domain application authoritative; Personal AI reads/reasons/proposes through typed contracts only.
- Carry application/workspace/entity references and sensitivity/provenance without copying authoritative records into core storage.
- Add domain isolation tests and at least one end-to-end synthetic scenario using the shared core contracts.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- This phase validates the built system; it is not permission to add missing product features.
- Cloud/provider/emulator checks remain opt-in and must be reported separately from offline deterministic results.
- Strict-$0 guardrails cover supporting GCP infrastructure as well as model inference.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Observability is not a second source of truth and must respect the underlying data sensitivity.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.
- Optimization logic cannot widen a hard eligibility boundary.
- Core orchestration must not query the domain database directly.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Negative tests prove protected data/provider paths are never invoked after denial.
- A developer can reconstruct the decision path from safe metadata for named fixtures.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.
- Named fixtures reproduce route decisions and rejection reasons.
- Domain state remains authoritative after the scenario; Personal AI stores only AI-owned conversation/memory/metadata as designed.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- new domain features
- new provider families
- major architecture rewrites
- claims of regulatory compliance

### P28.2 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P28.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 28 commitment without pulling later-phase behavior forward.

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

- This phase validates the built system; it is not permission to add missing product features.
- Cloud/provider/emulator checks remain opt-in and must be reported separately from offline deterministic results.
- Strict-$0 guardrails cover supporting GCP infrastructure as well as model inference.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- No known cross-app isolation failure.
- No known paid-overflow path.
- No sensitivity-unsafe fallback.
- No public/unauthorized artifact path.
- Firestore does not retain avoidable bulky raw evaluation/trace data.
- Provider failures degrade explicitly.
- Regression suites cover quality and resource behavior.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- new domain features
- new provider families
- major architecture rewrites
- claims of regulatory compliance

---

## Phase verification and closeout

### Required local/offline checks

- `make backend-test`
- `make backend-lint`
- `make frontend-test`
- `make frontend-lint`
- `make frontend-typecheck`
- phase-specific inference/routing evaluation command added by the implementation if no existing command covers it
- storage/artifact fake integration suite
- `bash -n infrastructure/gcp/deploy.sh` when deployment scripts change
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

## Phase 28 completion review

- 1. Did implementation satisfy every normative Phase 28 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.
- 8. Can optional artifact persistence failure break successful user inference, or can required exports fail silently? Both required answers are no.

## Handoff to the next phase

Do not begin the next phase until the Phase 28 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
