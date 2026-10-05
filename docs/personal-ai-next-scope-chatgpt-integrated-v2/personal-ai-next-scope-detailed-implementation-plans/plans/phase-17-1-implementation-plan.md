# Phase 17.1 implementation plan — ChatGPT authentication and local bridge

This is the detailed execution plan for integrated next-scope **Phase 17.1 — ChatGPT authentication and local bridge**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions. ChatGPT-specific design constraints are additionally defined in [../source/08-chatgpt-plan-and-ai-sidecar.md](../source/08-chatgpt-plan-and-ai-sidecar.md).

## Scope boundary

**Goal:** Add the user-controlled execution boundary required for ChatGPT-plan usage without storing ChatGPT credentials in the managed Personal AI cloud backend.

### Normative commitments from the integrated roadmap

- Re-verify current Sign in with ChatGPT open-source/local-runtime requirements before implementation.
- Define `ChatGPTPlanBridge` / local-client contract using normalized Personal AI request/output types where practical.
- Implement supported OAuth/OIDC/PKCE registration/sign-in flow.
- Persist stable host/client registration metadata and credentials only in protected local/user-controlled storage.
- Validate ID token identity and required ChatGPT-plan usage scope.
- Implement token refresh, sign-out/disconnect, and revocation/recovery behavior.
- Implement account-specific model discovery.
- Implement direct Responses API streaming behind the bridge using current required request semantics.
- Normalize completed/incomplete/auth/eligibility/usage-limit errors.
- Add fake bridge and contract tests.
- Ensure the bridge never returns reusable OAuth tokens to browser/cloud callers.
- For hosted web integration, define loopback/local-IPC transport with origin allowlisting and anti-CSRF/request authorization.
- Treat native-mobile support as capability to verify rather than assuming desktop loopback mechanics.

### Phase acceptance criteria

- Eligible signed-in user can complete a streamed ChatGPT-plan request through the local/user-controlled runtime.
- No persistent ChatGPT credential appears in Firestore, GCS, Secret Manager, browser storage, logs, traces, analytics, or exports.
- Managed Cloud Run services can operate with zero knowledge of ChatGPT access/refresh tokens.
- Account model list is discovered rather than hard-coded.
- Existing Gemini behavior and Phase 8 neutral contracts remain functional.

### Explicitly out of scope

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- new local/user-controlled bridge runtime
- `frontend/ bridge client seam`
- `backend/src/personal_ai/llm/ normalized contracts`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

No ChatGPT bridge, SIWC credential store, local IPC transport, or account-model discovery exists. `frontend/src/lib/auth.ts` holds only a Google ID token in memory for Personal AI OIDC; it must not be reused as ChatGPT-plan authorization. Re-verify current account/API eligibility and platform support before implementation. A local/user-controlled bridge must keep reusable credentials out of Cloud Run, Firestore, GCS, browser storage, logs and exports. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- Treat preview/operational OpenAI requirements as revalidated configuration/compatibility facts, not permanent assumptions.

## Dependency map

**Prerequisites:** Phase 16 / Checkpoint D

```text
P17_1.0 External-requirements -> P17_1.1 Local
P17_1.1 Local -> P17_1.2 SIWC
P17_1.2 SIWC -> P17_1.3 Authenticated
P17_1.3 Authenticated -> P17_1.4 Responses
P17_1.4 Responses -> P17_1.5 Browser/local
P17_1.5 Browser/local -> P17_1.6 Fake
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
- ChatGPT-mode tests prove credentials never enter managed cloud persistence or browser storage and provider switching remains explicit.

## Required implementation artifacts

- Code/configuration changes required by the work packages below, limited to Phase 17.1 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 17.1 work packages

### P17_1.0 — Re-verify current Sign in with ChatGPT open-source/local-runtime requirements before…

**Dependencies:** Phase 16 / Checkpoint D  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Re-verify current Sign in with ChatGPT open-source/local-runtime requirements before implementation.
- Reconcile the existing implementation relevant to **Re-verify current Sign in with ChatGPT open-source/local-runtime requirements before implementation.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Thread the new data/behavior through API → service → repository/provider/context boundaries with one clear ownership path.
- Preserve existing default behavior when the new capability is absent or disabled.
- Add integration tests for success, explicit failure, cancellation/retry where relevant, and isolation boundaries.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- No hidden side channel may bypass existing authorization/context/provider boundaries.
- Existing public API/SSE behavior changes only when this phase explicitly requires it.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Existing regression tests remain green with the new path disabled/defaulted.
- The enabled path is attributable in traces/evidence without exposing sensitive payloads.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.1 — `ChatGPTPlanBridge` / local-client contract using normalized Personal AI…

**Dependencies:** P17_1.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Define `ChatGPTPlanBridge` / local-client contract using normalized Personal AI request/output types where practical.
- Reconcile the existing implementation relevant to **Define `ChatGPTPlanBridge` / local-client contract using normalized Personal AI request/output types where practical.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.2 — Supported OAuth/OIDC/PKCE registration/sign-in flow

**Dependencies:** P17_1.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Implement supported OAuth/OIDC/PKCE registration/sign-in flow.
- Reconcile the existing implementation relevant to **Implement supported OAuth/OIDC/PKCE registration/sign-in flow.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.3 — Persist stable host/client registration metadata and credentials only in protected…

**Dependencies:** P17_1.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Persist stable host/client registration metadata and credentials only in protected local/user-controlled storage.
- Reconcile the existing implementation relevant to **Persist stable host/client registration metadata and credentials only in protected local/user-controlled storage.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep persistence behind repository/store protocols and provide an in-memory fake for automated tests.
- Define idempotency/concurrency/failure semantics for partial writes or retries.
- Document required indexes/object layout/retention behavior without exposing storage details to higher layers.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- Storage failures must have explicit user-visible versus best-effort semantics.
- No collection/bucket scan may become a normal request-path dependency unless explicitly designed.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Persistence tests cover create/read/update or append semantics, isolation, missing records, and injected failure.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.4 — Validate ID token identity and required ChatGPT-plan usage scope

**Dependencies:** P17_1.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Validate ID token identity and required ChatGPT-plan usage scope.
- Reconcile the existing implementation relevant to **Validate ID token identity and required ChatGPT-plan usage scope.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.5 — Token refresh, sign-out/disconnect, and revocation/recovery behavior

**Dependencies:** P17_1.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Implement token refresh, sign-out/disconnect, and revocation/recovery behavior.
- Reconcile the existing implementation relevant to **Implement token refresh, sign-out/disconnect, and revocation/recovery behavior.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.6 — Account-specific model discovery

**Dependencies:** P17_1.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Implement account-specific model discovery.
- Reconcile the existing implementation relevant to **Implement account-specific model discovery.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.7 — Direct Responses API streaming behind the bridge using current required request…

**Dependencies:** P17_1.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Implement direct Responses API streaming behind the bridge using current required request semantics.
- Reconcile the existing implementation relevant to **Implement direct Responses API streaming behind the bridge using current required request semantics.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.8 — Normalize completed/incomplete/auth/eligibility/usage-limit errors

**Dependencies:** P17_1.7 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Normalize completed/incomplete/auth/eligibility/usage-limit errors.
- Reconcile the existing implementation relevant to **Normalize completed/incomplete/auth/eligibility/usage-limit errors.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.

**Acceptance criteria:**

- Negative tests prove protected data/provider paths are never invoked after denial.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.9 — Fake bridge and contract tests

**Dependencies:** P17_1.8 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Add fake bridge and contract tests.
- Reconcile the existing implementation relevant to **Add fake bridge and contract tests.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
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

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
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

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.10 — Ensure the bridge never returns reusable OAuth tokens to browser/cloud callers

**Dependencies:** P17_1.9 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Ensure the bridge never returns reusable OAuth tokens to browser/cloud callers.
- Reconcile the existing implementation relevant to **Ensure the bridge never returns reusable OAuth tokens to browser/cloud callers.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.11 — For hosted web integration, define loopback/local-IPC transport with origin…

**Dependencies:** P17_1.10 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- For hosted web integration, define loopback/local-IPC transport with origin allowlisting and anti-CSRF/request authorization.
- Reconcile the existing implementation relevant to **For hosted web integration, define loopback/local-IPC transport with origin allowlisting and anti-CSRF/request authorization.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Thread the new data/behavior through API → service → repository/provider/context boundaries with one clear ownership path.
- Preserve existing default behavior when the new capability is absent or disabled.
- Add integration tests for success, explicit failure, cancellation/retry where relevant, and isolation boundaries.
- Implement hard allow/deny evaluation before protected data retrieval or model invocation, as appropriate.
- Return structured denial/rejection reasons suitable for safe tracing and tests.
- Build an explicit negative matrix covering cross-owner/app/workspace/provider cases.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- No hidden side channel may bypass existing authorization/context/provider boundaries.
- Existing public API/SSE behavior changes only when this phase explicitly requires it.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Existing regression tests remain green with the new path disabled/defaulted.
- The enabled path is attributable in traces/evidence without exposing sensitive payloads.
- Negative tests prove protected data/provider paths are never invoked after denial.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.12 — Treat native-mobile support as capability to verify rather than assuming desktop…

**Dependencies:** P17_1.11 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

**Work:**

- Treat native-mobile support as capability to verify rather than assuming desktop loopback mechanics.
- Reconcile the existing implementation relevant to **Treat native-mobile support as capability to verify rather than assuming desktop loopback mechanics.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

### P17_1.13 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P17_1.12 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.1 commitment without pulling later-phase behavior forward.

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

- Never scrape, automate, or iframe chatgpt.com as the integration mechanism.
- Reusable credentials stay exclusively in protected user-controlled storage.
- Browser JavaScript and managed cloud services never receive access/refresh tokens.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Eligible signed-in user can complete a streamed ChatGPT-plan request through the local/user-controlled runtime.
- No persistent ChatGPT credential appears in Firestore, GCS, Secret Manager, browser storage, logs, traces, analytics, or exports.
- Managed Cloud Run services can operate with zero knowledge of ChatGPT access/refresh tokens.
- Account model list is discovered rather than hard-coded.
- Existing Gemini behavior and Phase 8 neutral contracts remain functional.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- automatic strict-free routing through ChatGPT
- OpenAI API-key billing fallback
- ChatGPT conversation-history import
- native-mobile credential design before capability verification

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

## Phase 17.1 completion review

- 1. Did implementation satisfy every normative Phase 17.1 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 17.1 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
