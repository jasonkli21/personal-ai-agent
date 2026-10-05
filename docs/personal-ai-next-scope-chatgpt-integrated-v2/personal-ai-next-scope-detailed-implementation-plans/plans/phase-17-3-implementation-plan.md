# Phase 17.3 implementation plan — Shared AI sidecar UI

This is the detailed execution plan for integrated next-scope **Phase 17.3 — Shared AI sidecar UI**. It elaborates the normative scope in [../source/05-phased-implementation-plan.md](../source/05-phased-implementation-plan.md) using the structure and verification style of the repository’s existing phase implementation plans. It is an execution backlog, not permission to broaden product scope. Phase 0/current-repository evidence wins over hypothetical file/module assumptions. ChatGPT-specific design constraints are additionally defined in [../source/08-chatgpt-plan-and-ai-sidecar.md](../source/08-chatgpt-plan-and-ai-sidecar.md).

## Scope boundary

**Goal:** Provide one reusable in-application UX for automatic Personal AI routing or the user’s connected ChatGPT plan.

### Normative commitments from the integrated roadmap

- Build reusable desktop/web sidecar/drawer shell and define mobile bottom-sheet/full-screen adaptation.
- Add provider selector for Personal AI automatic strict-free routing and ChatGPT plan when connected.
- Add ChatGPT account/model controls and visible plan status.
- Add bounded context summary/inspector/selector.
- Add Personal AI `ContextPackage` endpoint/model reusing planner/provider/policy/builder semantics.
- Add bridge client that sends authorized context package to the local/user-controlled runtime.
- Stream normalized ChatGPT output into the shared conversation view.
- Add Copy universally.
- Add Insert only for explicitly non-authoritative draft/edit surfaces.
- Defer authoritative Apply to Phase 23.
- Persist completed turns with provider/model attribution; keep interrupted output transient unless explicitly saved as a draft.
- Test bridge absence, revoked auth, model disappearance, usage-limit errors, and explicit switch back to automatic routing.

### Phase acceptance criteria

- One sidecar works with automatic Personal AI routing and explicit ChatGPT plan mode.
- ChatGPT mode does not claim to be the user’s chatgpt.com session/history.
- Context sent to ChatGPT is inspectable and bounded.
- Copy works without domain mutations.
- No ChatGPT credential crosses into managed cloud persistence.

### Explicitly out of scope

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

## Repository baseline and candidate code areas

The current repository already separates backend API/auth/context/domain/evaluation/evidence/LLM/memory/ranking/search concerns, plus frontend and infrastructure. Candidate areas for this phase are intentionally advisory until Phase 0/current-code inspection confirms the exact seam:

- `frontend/`
- `backend/src/personal_ai/api/`
- `backend/src/personal_ai/context/`
- `local bridge client seam`
- `docs/`

Do not create a new parallel subsystem when an existing contract can be extended cleanly. Do not rename/reorganize unrelated code merely to make the phase look cleaner.

## Phase 0 repository reconciliation

The current browser surface is first-party Next.js chat/research/domain workbenches with bounded SSE and same-origin API proxies; no reusable domain sidecar or `ContextPackage` endpoint exists. Extend the Phase 4–7 builder/planner/policy and existing conversation/stream path for an inspectable package; pass it through the authorized local bridge without exposing reusable tokens. Copy is safe; Insert is draft-only; Apply waits for Phase 23. See the [dated Phase 0 code and dependency map](../phase-0-reconciliation-2026-10-05.md).

**Existing regression evaluations:** `make context-eval`, `make domain-eval`. Run those touched by this phase in addition to its backend/frontend test, lint, and type checks; add phase-specific fixtures for new behavior.

## Delivery conventions and invariants

- Begin by reading `AGENTS.md`, `docs/project-brief.md`, `docs/architecture.md`, the current authoritative roadmap, and this phase plan.
- Inspect `git status` before editing; preserve unrelated user changes and existing accepted decisions unless this phase explicitly supersedes them.
- Keep routes/UI thin and keep provider/storage SDK details behind existing service/repository boundaries.
- Use deterministic fakes for automated tests; credentialed provider, emulator, and cloud checks are opt-in and must be reported separately.
- Preserve owner/application/workspace isolation and safe error semantics across every new path.
- Do not add later-phase features merely because they would make the current phase easier.
- Update docs when contracts/behavior change and record tested revision, commands, outcomes, and remaining external verification gaps.
- Finish repository changes with relevant tests/lint/type-check/build checks plus `git diff --check`; documentation-only changes still require link/content review and `git diff --check`.
- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- Switching provider is explicit and does not rewrite prior turn attribution.

## Dependency map

**Prerequisites:** Phase 17.2

```text
P17_3.0 Sidecar -> P17_3.1 Provider/account/model
P17_3.1 Provider/account/model -> P17_3.2 ContextPackage
P17_3.2 ContextPackage -> P17_3.3 Local
P17_3.3 Local -> P17_3.4 Conversation
P17_3.4 Conversation -> P17_3.5 Copy/Insert
P17_3.5 Copy/Insert -> P17_3.6 Failure/reconnect/switch-provider
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

- Code/configuration changes required by the work packages below, limited to Phase 17.3 scope.
- Deterministic fixtures/fakes and tests for every new public/internal contract and failure class.
- Updated architecture/API/operations documentation only where the implemented behavior changes those contracts.
- A phase implementation guide/release-evidence update after implementation, including tested revision, commands, results, and remaining verification gaps.
- Any ADR required to resolve a durable architectural decision that is not already accepted; routine implementation details do not need separate ADRs.

---

## Phase 17.3 work packages

### P17_3.0 — Build reusable desktop/web sidecar/drawer shell and define mobile…

**Dependencies:** Phase 17.2  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Build reusable desktop/web sidecar/drawer shell and define mobile bottom-sheet/full-screen adaptation.
- Reconcile the existing implementation relevant to **Build reusable desktop/web sidecar/drawer shell and define mobile bottom-sheet/full-screen adaptation.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.

**Requirements:**

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.

**Acceptance criteria:**

- The feature is usable without hidden provider/storage coupling and fails recoverably.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.1 — Provider selector for Personal AI automatic strict-free routing and ChatGPT plan…

**Dependencies:** P17_3.0 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Add provider selector for Personal AI automatic strict-free routing and ChatGPT plan when connected.
- Reconcile the existing implementation relevant to **Add provider selector for Personal AI automatic strict-free routing and ChatGPT plan when connected.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Optimization logic cannot widen a hard eligibility boundary.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Named fixtures reproduce route decisions and rejection reasons.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.2 — ChatGPT account/model controls and visible plan status

**Dependencies:** P17_3.1 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Add ChatGPT account/model controls and visible plan status.
- Reconcile the existing implementation relevant to **Add ChatGPT account/model controls and visible plan status.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Implement typed client state with loading/streaming/completed/error/reconnect states and keyboard/accessibility behavior.
- Keep the UI on documented APIs/contracts; do not call Firestore or provider SDKs directly.
- Add component/integration tests for empty, success, cancellation, failure, and disabled-capability states.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- UI must make provider/context/action state explicit when that state affects user control or sensitivity.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- The feature is usable without hidden provider/storage coupling and fails recoverably.
- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.3 — Bounded context summary/inspector/selector

**Dependencies:** P17_3.2 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Add bounded context summary/inspector/selector.
- Reconcile the existing implementation relevant to **Add bounded context summary/inspector/selector.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.4 — Personal AI `ContextPackage` endpoint/model reusing planner/provider/policy/builder…

**Dependencies:** P17_3.3 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Add Personal AI `ContextPackage` endpoint/model reusing planner/provider/policy/builder semantics.
- Reconcile the existing implementation relevant to **Add Personal AI `ContextPackage` endpoint/model reusing planner/provider/policy/builder semantics.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
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

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Deny by default when required policy facts are missing or unverified.
- Policy is enforced in code; prompt instructions are not authorization.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Negative tests prove protected data/provider paths are never invoked after denial.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.5 — Bridge client that sends authorized context package to the local/user-controlled runtime

**Dependencies:** P17_3.4 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Add bridge client that sends authorized context package to the local/user-controlled runtime.
- Reconcile the existing implementation relevant to **Add bridge client that sends authorized context package to the local/user-controlled runtime.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Thread the new data/behavior through API → service → repository/provider/context boundaries with one clear ownership path.
- Preserve existing default behavior when the new capability is absent or disabled.
- Add integration tests for success, explicit failure, cancellation/retry where relevant, and isolation boundaries.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Preserve source class, authority, freshness/provenance, sensitivity, and boundedness through the full path.
- Define deterministic behavior for unavailable/empty/invalid sources instead of broadening retrieval silently.
- Add fixtures for relevant, irrelevant, stale, conflicting, sensitive, and over-budget inputs as applicable.

**Requirements:**

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- No hidden side channel may bypass existing authorization/context/provider boundaries.
- Existing public API/SSE behavior changes only when this phase explicitly requires it.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- Existing regression tests remain green with the new path disabled/defaulted.
- The enabled path is attributable in traces/evidence without exposing sensitive payloads.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.6 — Stream normalized ChatGPT output into the shared conversation view

**Dependencies:** P17_3.5 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Stream normalized ChatGPT output into the shared conversation view.
- Reconcile the existing implementation relevant to **Stream normalized ChatGPT output into the shared conversation view.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Keep reusable authentication material inside the user-controlled runtime and expose only normalized connection/model/request results to browser or cloud callers.
- Define explicit lifecycle states for sign-in/refresh/revocation/disconnect or the relevant subset, with deterministic error mapping and recovery tests.
- Add secret-scanning/redaction assertions proving credentials and authorization material cannot enter logs, traces, analytics, exports, Firestore, GCS, or browser storage.

**Requirements:**

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- No automatic fallback may convert ChatGPT-plan use into API-key billing, credits, another account, or strict-free routing.
- Current external SIWC/Responses constraints must be re-verified at implementation/release time rather than frozen as permanent assumptions.

**Acceptance criteria:**

- Credential-bound tests prove the managed cloud backend can operate without access/refresh tokens and browser callers never receive reusable tokens.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.7 — Copy universally

**Dependencies:** P17_3.6 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Add Copy universally.
- Reconcile the existing implementation relevant to **Add Copy universally.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.8 — Insert only for explicitly non-authoritative draft/edit surfaces

**Dependencies:** P17_3.7 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Add Insert only for explicitly non-authoritative draft/edit surfaces.
- Reconcile the existing implementation relevant to **Add Insert only for explicitly non-authoritative draft/edit surfaces.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.9 — Defer authoritative Apply to Phase 23

**Dependencies:** P17_3.8 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Defer authoritative Apply to Phase 23.
- Reconcile the existing implementation relevant to **Defer authoritative Apply to Phase 23.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.

**Requirements:**

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.

**Acceptance criteria:**

- The workstream is covered by deterministic tests and composes with prior-phase behavior.
- Failure is explicit and does not silently broaden data/provider access.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.10 — Persist completed turns with provider/model attribution

**Dependencies:** P17_3.9 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Persist completed turns with provider/model attribution; keep interrupted output transient unless explicitly saved as a draft.
- Reconcile the existing implementation relevant to **Persist completed turns with provider/model attribution; keep interrupted output transient unless explicitly saved as a draft.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
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

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
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

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.11 — Test bridge absence, revoked auth, model disappearance, usage-limit errors, and…

**Dependencies:** P17_3.10 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

**Work:**

- Test bridge absence, revoked auth, model disappearance, usage-limit errors, and explicit switch back to automatic routing.
- Reconcile the existing implementation relevant to **Test bridge absence, revoked auth, model disappearance, usage-limit errors, and explicit switch back to automatic routing.** in the candidate code areas; extend existing contracts rather than creating a parallel subsystem.
- Define typed/provider-neutral records or protocols with explicit versioning/validation where persistence or cross-process exchange is involved.
- Specify required/optional fields, stable enums/reason codes, serialization behavior, and invalid-input semantics.
- Add deterministic contract/schema tests for valid, missing, malformed, and forward-compatibility cases.
- Normalize request/response/error/usage metadata into Personal AI types and keep vendor/client objects inside the adapter boundary.
- Implement a deterministic fake with the same contract for unit/integration tests.
- Define opt-in real-provider compatibility checks that skip cleanly without credentials/network.
- Make route/candidate decisions deterministic and inspectable from explicit inputs for this phase.
- Preserve hard strict-free/privacy/capability/context-limit constraints before optimization logic.
- Record selected/rejected candidates and reason codes in safe trace metadata.

**Requirements:**

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- Contracts must not expose provider SDK or Firestore implementation types above their boundary.
- Unknown/unsupported values fail explicitly rather than being silently coerced.
- Secrets and authorization headers are never logged or persisted in test artifacts.
- Provider failures map to stable application error categories.
- Optimization logic cannot widen a hard eligibility boundary.

**Acceptance criteria:**

- Representative valid and invalid contract fixtures are covered offline.
- Callers can depend on the new contract without importing implementation-specific SDK types.
- Fake-based tests exercise all required operations and failure classes.
- External checks, when run, are recorded separately from offline completion.
- Named fixtures reproduce route decisions and rejection reasons.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

### P17_3.12 — Phase integration, regression verification, and evidence closeout

**Dependencies:** P17_3.11 plus any earlier work packages whose contracts it consumes  

**Goal:** implement this scoped Phase 17.3 commitment without pulling later-phase behavior forward.

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

- The domain page remains visible/usable on desktop where practical.
- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- Evaluation must distinguish skipped external checks from passing checks.
- No personal/private data is required in committed fixtures.
- Context/evidence/memory boundaries remain distinct; no source class silently becomes another.

**Acceptance criteria:**

- One sidecar works with automatic Personal AI routing and explicit ChatGPT plan mode.
- ChatGPT mode does not claim to be the user’s chatgpt.com session/history.
- Context sent to ChatGPT is inspectable and bounded.
- Copy works without domain mutations.
- No ChatGPT credential crosses into managed cloud persistence.
- Results are reproducible from a clean checkout using documented commands.
- Tests prove excluded/unauthorized/over-budget material is not supplied downstream.

**Out of scope:**

- authoritative Apply actions
- domain-specific data retrieval beyond the shared ContextPackage
- ChatGPT consumer-history sync
- duplicated provider auth per app

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

## Phase 17.3 completion review

- 1. Did implementation satisfy every normative Phase 17.3 commitment without adding later-phase product behavior?
- 2. Can a reviewer identify the authoritative source of each new piece of state and the boundary that owns it?
- 3. Do negative/isolation/failure tests prove the new behavior fails safely instead of silently broadening access or provider use?
- 4. Are offline verification and external/provider/cloud verification clearly distinguished?
- 5. Can the new behavior be disabled/absent without regressing the previously working path where backward compatibility is required?
- 6. Are docs, implementation evidence, and remaining gaps accurate at the tested revision?
- 7. Can any reusable ChatGPT credential reach managed cloud persistence, logs, traces, analytics, exports, or browser storage? The required answer is no.

## Handoff to the next phase

Do not begin the next phase until the Phase 17.3 acceptance criteria are met locally or any deliberately deferred external checks are documented as verification gaps. The next session should read the implementation guide/release evidence produced here in addition to the next phase plan.
