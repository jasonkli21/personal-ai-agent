# Phase 25.2 implementation plan — ChatGPT provider/runtime integration, policy, usage handling, and external-turn provenance

Renumbered on 2026-10-06 from former next-scope Phase 17.2 with all former scope preserved. Only numbering/prerequisites, post-Phase-10 storage references, README maintenance, and additive foundations for cross-provider continuation/manual external turns change.

## Scope boundary

**Goal:** Represent ChatGPT-plan usage inside Personal AI while keeping it outside automatic strict-free routing and ordinary free-provider quota semantics, and define the shared persistence/provenance semantics required for later manual external-model copy/import and cross-provider continuation.

### Normative commitments

- Add/verify provider metadata for auth mode, selection mode, credential runtime, account-specific model discovery, automation eligibility, and hosted-conversation-state availability.
- Define `openai_chatgpt_plan` as explicit-user only and never an automatic candidate.
- Add request-envelope fields for explicit provider/model choice.
- Ensure explicit selection does not bypass context/sensitivity authorization.
- Persist only safe provider/model attribution on completed turns.
- Prove ChatGPT models can never enter strict-free automatic candidate sets.
- Track safe connection and normalized coarse usage state.
- Record per-turn provider/model/latency/status/error metadata.
- Add manage-usage/reconnect/switch-account hooks.
- Never infer reset timestamps from generic usage-limit errors.
- Add redaction tests for auth/account material.

### Additive cross-provider/manual-external commitments

- Represent execution provenance separately from provider identity, including at minimum connected/provider-executed versus `manual_external`.
- Allow a completed turn from any provider/execution mode to be considered as input to a later request to another provider only through the ordinary authorized context planner/policy/budget pipeline.
- Preserve the original provider/model/execution attribution when a later provider consumes or transforms the prior response; continuation must never rewrite historical attribution.
- Define a manual external-turn lifecycle that can bind a copied prepared prompt/context package to a later user-imported response without requiring any provider credential or browser automation.
- Manual external provider/model labels are optional user declarations and must be marked unverified/user-declared unless independently observed by a supported integration.
- Manual external imports must not create usage/billing/account/eligibility claims and must not contaminate strict-free quota or connected ChatGPT-plan usage state.
- Imported manual responses re-enter the same completed-turn/conversation pipeline so they can participate in later authorized context, Copy, draft Insert, and future typed Apply flows.
- Keep copy/import as a user-mediated fallback; this phase must not implement scraping, session-cookie reuse, password capture, unofficial consumer-web automation, or implicit dispatch to an external consumer UI.

### Acceptance criteria

- Automatic strict-free routing remains the configured free-provider lane only.
- ChatGPT requires explicit user/session/request selection; no silent fallback occurs in either direction.
- Provider/model attribution is preserved on conversation turns.
- ChatGPT failures produce actionable normalized states without contaminating strict-free quota semantics.
- No auth secret enters telemetry/evaluation/artifacts.
- Connected-provider and manual-external turns have distinct trust/provenance semantics.
- A completed turn can be reused as later provider context only after normal context authorization/budgeting, with prior attribution unchanged.
- A manually imported external response can be finalized as a normal completed conversation turn with user-declared/unverified attribution and no fabricated usage/account facts.

## Current state and reuse

Phase 16/21 provide neutral inference and automatic-provider attribution; Phase 25.1 provides the local bridge/credential boundary. Completed conversations/messages are DynamoDB-owned after Phase 10; query-rich provider/control metadata may be Postgres-owned, but no reusable ChatGPT credential may be persisted in either.

The additive manual-external path must reuse the same conversation branch, context, policy, provenance, and finalization machinery rather than creating a second chat history. It differs only in dispatch/observation trust: the system prepares/copies context, the user performs the external interaction, and the user explicitly imports the resulting text.

## Phase 10 storage dependency

External-turn preparation/finalization/replay uses the DynamoDB conversation/branch boundary, with versioned Postgres policy/registry/ledger references. Phase 10 source validation and uncertain-effect rules apply; reusable credentials and interrupted output retain their existing exclusions. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

Manual-external imports use the same canonical conversation repository. They may persist safe user-declared provider/model labels and a manual-external execution marker, but never fabricated account, billing, token, quota, or server-observed claims.

## Prerequisites

Required phases: 19, 21, and 25.1. Phase 10 remains the storage/security foundation.

## Phase-specific invariants

- ChatGPT errors never silently select credits/API-key billing, another account, or automatic free routing.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Full context/source/provider sensitivity policy applies after explicit selection.
- Prior completed turns are ordinary candidate context sources, not automatically trusted or automatically included; normal source authorization, sensitivity rules, user narrowing, and token budgets still apply.
- Manual-external outputs are user-supplied content with declared provenance, never authenticated-provider evidence.
- No manual path may claim that an external consumer product session, account, model, plan, or usage state was programmatically verified when it was not.
- Manual external execution never bypasses branch ownership, stale-context checks, or finalization idempotency.

## Work packages

### P25_2.0 — Explicit provider policy and usage state

Extend Phase 18 profiles with auth mode, explicit-selection mode, local credential runtime, account-model visibility, automation exclusion, and no hosted ChatGPT-history inheritance. Add non-secret provider/model/context choice fields. `openai_chatgpt_plan` never enters automatic candidate/fallback/evaluation automation. Apply all source/provider sensitivity checks after user choice. Model connection as connected/disconnected/reauth/unavailable and usage as available/limit/unavailable/unknown; keep this separate from strict-free quota buckets.

Add execution-provenance metadata that is orthogonal to provider identity. At minimum, connected ChatGPT-plan execution must be distinguishable from `manual_external`. Manual external mode has no connection or usage state and may carry only optional user-declared provider/model labels marked as such.

**Acceptance:** automatic-candidate tests always exclude ChatGPT; explicit choice cannot bypass privacy or silently switch routes; manual-external records cannot populate connected-provider usage/account state.

### P25_2.1 — Scoped external-turn prepare/finalize

Extend the existing conversation/branch transaction model with one prepared external turn, active-branch/source-grant snapshot, package fingerprint/expiry, output bound, selected provider/model, and durable idempotency. Finalize only the reserved owner/app/workspace/conversation branch after rechecking grants and terminal intent. Issue a short-lived verifiable dispatch grant bound to paired caller, package content hash, provider/model, sensitivity/policy versions, and expiry; use the proof/verifier contract from Phase 25.1 so the bridge rejects forged/edited browser manifests without receiving cloud credentials.

Because Phase 10 makes conversations/messages canonical in DynamoDB, prepare/finalize and branch/idempotency semantics must use the DynamoDB conversation repository boundary; query-rich policy/profile data continues to come from Postgres. Context/model changes require a fresh preparation. Duplicate completion replays; foreign/stale/expired/superseded output fails safely. Interrupted text stays transient unless explicitly saved as a labelled draft.

For the later manual-external UX, define a sibling prepared-turn mode that reuses the same branch/context/package fingerprint and output-bound semantics but does not issue or require a bridge dispatch grant. Instead, it produces a user-visible/copyable prepared prompt plus a safe import reservation/nonce or equivalent bounded identifier. Finalization accepts only explicit user import against the matching active reservation and records `manual_external` provenance. The import path must safely reject stale/superseded/foreign reservations and must not infer what external service actually executed the prompt.

**Acceptance:** only a valid scoped active reservation can finalize, with idempotent replay and explicit stale/expired/superseded failures; connected dispatch and manual import use distinct authorization/provenance paths while sharing conversation consistency rules.

### P25_2.2 — Safe attribution and recovery hooks

Persist safe turn provider/model/task/latency/error/usage attribution with provenance distinguishing client-reported from server-observed facts; do not create a second attribution store or treat browser completion as verified billing proof. Normalize usage-limit state without invented resets. Expose reconnect/manage-usage/switch-account hooks for Phase 25.3. Account/scope changes clear transient state and never rewrite prior attribution.

Extend trust provenance so manual external imports can record:
- execution mode `manual_external`;
- optional user-declared provider name;
- optional user-declared model name;
- import timestamp and originating prepared-package fingerprint/reservation;
- explicit unverified/user-declared trust labels.

Do not synthesize latency, token usage, account identity, plan, quota, billing, or provider-confirmed model identity for manual imports.

**Acceptance:** turn metadata preserves trust provenance and recovery remains explicit/coarse with no guessed reset time; manual imports remain clearly distinguishable from connected provider completions.

### P25_2.3 — Cross-provider continuation semantics

Define continuation as a new request over the shared conversation, not a mutation of the previous turn. A completed result from ChatGPT, an automatic/free provider, another integrated provider, or `manual_external` may be selected by the ordinary planner as context for a later provider subject to:
- current workspace/app/conversation ownership;
- current source grants and sensitivity policy;
- user-visible context selection/narrowing where applicable;
- current token/context budget;
- provider-specific disclosure restrictions;
- branch/version freshness.

Preserve immutable producing-provider/model/execution provenance on every historical turn. The consuming turn records only its own provider/model plus source/context references; it must not overwrite the producer's attribution or imply that the consuming provider independently verified the earlier content.

Support a future Phase 25.3 `Continue with…` action by exposing a provider-neutral continuation request shape that can select automatic routing, connected ChatGPT, other registered providers, or manual external mode without special-casing prior-turn origin.

**Acceptance:** tests cover ChatGPT→automatic, automatic→ChatGPT, manual→connected, connected→manual, and same-provider continuations; every path re-runs authorization/budgeting and preserves historical attribution.

## Requirement coverage

All eleven former Phase 17.2 normative commitments remain in P25_2.0–P25_2.2; none is replaced by generic provider handling. P25_2.3 and the additive clauses establish only the shared provenance/continuation/manual-import semantics required by later UI/domain phases.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
