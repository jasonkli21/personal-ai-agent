# Phase 25.2 implementation plan — ChatGPT provider/runtime integration, policy, and usage handling

Renumbered on 2026-10-06 from former next-scope Phase 17.2 with all former scope preserved. Only numbering/prerequisites, post-Phase-10 storage references, and README maintenance change.

## Scope boundary

**Goal:** Represent ChatGPT-plan usage inside Personal AI while keeping it outside automatic strict-free routing and ordinary free-provider quota semantics.

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

### Acceptance criteria

- Automatic strict-free routing remains the configured free-provider lane only.
- ChatGPT requires explicit user/session/request selection; no silent fallback occurs in either direction.
- Provider/model attribution is preserved on conversation turns.
- ChatGPT failures produce actionable normalized states without contaminating strict-free quota semantics.
- No auth secret enters telemetry/evaluation/artifacts.

## Current state and reuse

Phase 16/21 provide neutral inference and automatic-provider attribution; Phase 25.1 provides the local bridge/credential boundary. Completed conversations/messages are DynamoDB-owned after Phase 10; query-rich provider/control metadata may be Postgres-owned, but no reusable ChatGPT credential may be persisted in either.

## Phase 10 storage dependency

External-turn preparation/finalization/replay uses the DynamoDB conversation/branch boundary, with versioned Postgres policy/registry/ledger references. Phase 10 source validation and uncertain-effect rules apply; reusable credentials and interrupted output retain their existing exclusions. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites

Required phases: 19, 21, and 25.1. Phase 10 remains the storage/security foundation.

## Phase-specific invariants

- ChatGPT errors never silently select credits/API-key billing, another account, or automatic free routing.
- Connection/usage state is deliberately coarser than the strict-free quota ledger.
- Full context/source/provider sensitivity policy applies after explicit selection.

## Work packages

### P25_2.0 — Explicit provider policy and usage state

Extend Phase 18 profiles with auth mode, explicit-selection mode, local credential runtime, account-model visibility, automation exclusion, and no hosted ChatGPT-history inheritance. Add non-secret provider/model/context choice fields. `openai_chatgpt_plan` never enters automatic candidate/fallback/evaluation automation. Apply all source/provider sensitivity checks after user choice. Model connection as connected/disconnected/reauth/unavailable and usage as available/limit/unavailable/unknown; keep this separate from strict-free quota buckets.

**Acceptance:** automatic-candidate tests always exclude ChatGPT; explicit choice cannot bypass privacy or silently switch routes.

### P25_2.1 — Scoped external-turn prepare/finalize

Extend the existing conversation/branch transaction model with one prepared external turn, active-branch/source-grant snapshot, package fingerprint/expiry, output bound, selected provider/model, and durable idempotency. Finalize only the reserved owner/app/workspace/conversation branch after rechecking grants and terminal intent. Issue a short-lived verifiable dispatch grant bound to paired caller, package content hash, provider/model, sensitivity/policy versions, and expiry; use the proof/verifier contract from Phase 25.1 so the bridge rejects forged/edited browser manifests without receiving cloud credentials.

Because Phase 10 makes conversations/messages canonical in DynamoDB, prepare/finalize and branch/idempotency semantics must use the DynamoDB conversation repository boundary; query-rich policy/profile data continues to come from Postgres. Context/model changes require a fresh preparation. Duplicate completion replays; foreign/stale/expired/superseded output fails safely. Interrupted text stays transient unless explicitly saved as a labelled draft.

**Acceptance:** only a valid scoped active reservation can finalize, with idempotent replay and explicit stale/expired/superseded failures.

### P25_2.2 — Safe attribution and recovery hooks

Persist safe turn provider/model/task/latency/error/usage attribution with provenance distinguishing client-reported from server-observed facts; do not create a second attribution store or treat browser completion as verified billing proof. Normalize usage-limit state without invented resets. Expose reconnect/manage-usage/switch-account hooks for Phase 25.3. Account/scope changes clear transient state and never rewrite prior attribution.

**Acceptance:** turn metadata preserves trust provenance and recovery remains explicit/coarse with no guessed reset time.

## Requirement coverage

All eleven former Phase 17.2 normative commitments remain in P25_2.0–P25_2.2; none is replaced by generic provider handling.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
