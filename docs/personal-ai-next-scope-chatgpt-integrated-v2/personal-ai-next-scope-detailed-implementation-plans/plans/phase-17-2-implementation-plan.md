# Phase 17.2 implementation plan — ChatGPT provider/runtime integration, policy, and usage handling

This is the detailed execution plan for integrated next-scope **Phase 17.2 — ChatGPT provider/runtime integration, policy, and usage handling**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions. ChatGPT-specific design constraints are additionally defined in [../source/08-chatgpt-plan-and-ai-sidecar.md](../source/08-chatgpt-plan-and-ai-sidecar.md).

## Scope boundary

**Goal:** Represent ChatGPT-plan usage inside Personal AI while keeping it outside automatic strict-free routing and ordinary free-provider quota semantics.

### Normative commitments from the integrated roadmap

- Add/verify provider metadata for auth mode, selection mode, credential runtime, account-specific model discovery, automation eligibility, and hosted conversation-state availability.
- Define `openai_chatgpt_plan` as explicit-user and not an automatic candidate.
- Add request-envelope fields for explicit provider/model choice.
- Ensure explicit provider selection does not bypass context/sensitivity authorization.
- Persist only safe provider/model attribution on completed turns.
- Prove ChatGPT models can never enter a strict-free automatic candidate set.
- Track safe connection and normalized usage state.
- Record per-turn provider/model/latency/status/error metadata.
- Add manage-usage/reconnect/switch-account hooks.
- Never infer reset timestamps from generic usage-limit errors.
- Add redaction tests for auth/account material.

### Phase acceptance criteria

- Automatic strict-free routing remains Gemini/Groq/Cloudflare only.
- ChatGPT requests require explicit user/session/request selection.
- No silent fallback occurs in either direction.
- Provider/model attribution is preserved on conversation turns.
- ChatGPT failures produce actionable normalized states.
- The strict-free quota ledger remains semantically separate.
- No auth secret is emitted into tracing/evaluation artifacts.

### Explicitly out of scope

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `backend/src/personal_ai/llm/`
- `backend/src/personal_ai/context/`
- `backend/src/personal_ai/api/`
- `frontend/`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

Phase 10's registry and Phase 13's router are the real extension seams once implemented. Add ChatGPT as an explicit-user lane only, never a strict-free automatic candidate or silent fallback. Existing `Message.model` is only a model string; safe provider/model/status attribution needs an explicit schema/repository migration plan, and existing request-estimate counters are not ChatGPT plan allowance. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make research-eval`, `make domain-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Provider sensitivity policy still applies after explicit selection.

## Dependency map

**Prerequisites:** Phase 17.1

```text
P17_2.0 Explicit-provider -> P17_2.1 ChatGPT
P17_2.1 ChatGPT -> P17_2.2 Conversation/provider
P17_2.2 Conversation/provider -> P17_2.3 Connection/usage
P17_2.3 Connection/usage -> P17_2.4 Sidecar-facing
P17_2.4 Sidecar-facing -> P17_2.5 Strict-free
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
- ChatGPT-mode tests prove credentials never enter managed cloud persistence or browser storage and provider switching remains explicit.

## Required implementation artifacts

- Code/configuration changes required by the work packages below, limited to Phase 17.2 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 17.2 work packages

### P17_2.0 — Provider metadata for auth mode, selection mode, credential runtime,…

**Dependencies:** Phase 17.1  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Add/verify provider metadata for auth mode, selection mode, credential runtime, account-specific model discovery, automation eligibility, and hosted conversation-state availability.
- Reconcile the existing implementation relevant to **Add/verify provider metadata for auth mode, selection mode, credential runtime, account-specific model discovery, automation eligibility, and hosted conversation-state availability.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Thread the new data/behavior through API → service → repository/provider/context boundaries with one clear ownership path.
- Preserve existing default behavior when the new capability is absent or disabled.
- Add integration tests for success, explicit failure, cancellation/retry where relevant, and isolation boundaries.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- No hidden side channel may bypass existing authorization/context/provider boundaries.
- Existing public API/SSE behavior changes only when this phase explicitly requires it.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Existing regression tests remain green with the new path disabled/defaulted.
- The enabled path is attributable in traces/evidence without exposing sensitive payloads.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Negative tests prove protected data/provider paths are never invoked after denial.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.1 — `openai_chatgpt_plan` as explicit-user and not an automatic candidate

**Dependencies:** P17_2.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Define `openai_chatgpt_plan` as explicit-user and not an automatic candidate.
- Reconcile the existing implementation relevant to **Define `openai_chatgpt_plan` as explicit-user and not an automatic candidate.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Optimization logic cannot widen a hard eligibility boundary.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Named fixtures reproduce route decisions and rejection reasons.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.2 — Request-envelope fields for explicit provider/model choice

**Dependencies:** P17_2.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Add request-envelope fields for explicit provider/model choice.
- Reconcile the existing implementation relevant to **Add request-envelope fields for explicit provider/model choice.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
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

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.3 — Ensure explicit provider selection does not bypass context/sensitivity authorization

**Dependencies:** P17_2.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Ensure explicit provider selection does not bypass context/sensitivity authorization.
- Reconcile the existing implementation relevant to **Ensure explicit provider selection does not bypass context/sensitivity authorization.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Negative tests prove protected data/provider paths are never invoked after denial.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.4 — Persist only safe provider/model attribution on completed turns

**Dependencies:** P17_2.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Persist only safe provider/model attribution on completed turns.
- Reconcile the existing implementation relevant to **Persist only safe provider/model attribution on completed turns.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Record safe IDs, policy/profile versions, counts, decisions, and reason codes needed to reconstruct behavior.
- Apply allowlist/redaction before persistence or display; raw private content remains absent by default.
- Add read-only inspection/tests proving no write/provider side effects.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Observability is not a second source of truth and must respect the underlying data sensitivity.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- A developer can reconstruct the decision path from safe metadata for named fixtures.

**Out of scope:**

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.5 — Prove ChatGPT models can never enter a strict-free automatic candidate set

**Dependencies:** P17_2.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Prove ChatGPT models can never enter a strict-free automatic candidate set.
- Reconcile the existing implementation relevant to **Prove ChatGPT models can never enter a strict-free automatic candidate set.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Optimization logic cannot widen a hard eligibility boundary.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Named fixtures reproduce route decisions and rejection reasons.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.6 — Safe connection and normalized usage state

**Dependencies:** P17_2.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Track safe connection and normalized usage state.
- Reconcile the existing implementation relevant to **Track safe connection and normalized usage state.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.7 — Per-turn provider/model/latency/status/error metadata

**Dependencies:** P17_2.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Record per-turn provider/model/latency/status/error metadata.
- Reconcile the existing implementation relevant to **Record per-turn provider/model/latency/status/error metadata.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
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

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.8 — Manage-usage/reconnect/switch-account hooks

**Dependencies:** P17_2.7 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Add manage-usage/reconnect/switch-account hooks.
- Reconcile the existing implementation relevant to **Add manage-usage/reconnect/switch-account hooks.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.9 — Never infer reset timestamps from generic usage-limit errors

**Dependencies:** P17_2.8 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Never infer reset timestamps from generic usage-limit errors.
- Reconcile the existing implementation relevant to **Never infer reset timestamps from generic usage-limit errors.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.10 — Redaction tests for auth/account material

**Dependencies:** P17_2.9 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

**Work:**

- Add redaction tests for auth/account material.
- Reconcile the existing implementation relevant to **Add redaction tests for auth/account material.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Create/reuse named synthetic fixtures with explicit expected selections, exclusions, errors, and invariants.
- Run deterministic offline comparisons first; make live/cloud checks explicit opt-in steps.
- Define promotion/completion gates before interpreting results and record failures without hiding them.

**Requirements:**

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.

**Acceptance criteria:**

- Results are reproducible from a clean checkout using documented commands.

**Out of scope:**

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

### P17_2.11 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P17_2.10 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.2 commitment without pulling later-phase behavior forward.

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

- Explicit choice is required for every transition into ChatGPT mode.
- A ChatGPT error never silently selects API-key billing, credits, another account, or an automatic free provider.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Automatic strict-free routing remains Gemini/Groq/Cloudflare only.
- ChatGPT requests require explicit user/session/request selection.
- No silent fallback occurs in either direction.
- Provider/model attribution is preserved on conversation turns.
- ChatGPT failures produce actionable normalized states.
- The strict-free quota ledger remains semantically separate.
- No auth secret is emitted into tracing/evaluation artifacts.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- sidecar UI implementation
- automatic ChatGPT routing
- quota reset prediction
- domain-specific sidecar behavior

---

## Phase verification and closeout

### Required local/offline checks

- `make backend-test`
- `make backend-lint`
- `make frontend-test`
- `make frontend-lint`
- `make frontend-typecheck`
- local bridge unit/contract/security test command
- frontend checks when sidecar/browser integration changes
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

## Phase 17.2 completion review

- 1. Did implementation satisfy every normative Phase 17.2 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 17.2 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
