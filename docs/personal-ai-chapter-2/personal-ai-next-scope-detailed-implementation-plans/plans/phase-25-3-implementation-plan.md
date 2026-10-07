# Phase 25.3 implementation plan — Shared AI sidecar UI

Renumbered on 2026-10-06 from former next-scope Phase 17.3 with its full UI/context/action scope preserved.

## Scope boundary

**Goal:** Provide one reusable in-application UX for automatic Personal AI routing or the user’s explicitly connected ChatGPT plan.

### Normative commitments

- Build a reusable desktop/web sidecar/drawer and defined mobile bottom-sheet/full-screen adaptation.
- Add a provider selector for Personal AI automatic strict-free routing and ChatGPT plan when connected.
- Add ChatGPT account/model controls and visible plan state.
- Add bounded context summary/inspector/selector.
- Add a Personal AI `ContextPackage` endpoint/model reusing planner/provider/policy/builder semantics.
- Add a bridge client that sends authorized packages to the local/user-controlled runtime.
- Stream normalized ChatGPT output into the shared conversation view.
- Add Copy universally.
- Add Insert only for explicitly non-authoritative draft/edit surfaces.
- Defer authoritative Apply to Phase 31.
- Persist completed turns with provider/model attribution; interrupted output stays transient unless explicitly saved as draft.
- Test bridge absence, revoked auth, model disappearance, usage limits, and explicit switching back to automatic routing.

### Acceptance criteria

- One sidecar works with automatic Personal AI routing and explicit ChatGPT-plan mode.
- ChatGPT mode never claims to be the user’s chatgpt.com session/history.
- Context sent to ChatGPT is inspectable and bounded.
- Copy works without domain mutation.
- No ChatGPT credential crosses into managed cloud persistence.

## Current state and reuse

Reuse existing chat state/SSE/proxy/auth helpers, the Phase 25.2 external-turn prepare/finalize path, and the shared context planner/policy/builder. The sidecar, context selector, and paired local bridge browser client are new.

## Phase 10 storage dependency

Consume shared DynamoDB turn/finalization and Postgres safe control metadata rather than creating sidecar persistence. Local bridge registration/reusable credentials stay user-local and are excluded from managed artifacts and exports. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites

Required phases: 14 and 25.2. Phase 10 is a standing storage boundary.

## Phase-specific invariants

- Always display which provider/model is producing an answer.
- Context inspection shows bounded source/category summaries without hidden credentials or unnecessary raw sensitive values.
- Provider switching is explicit and never rewrites prior-turn attribution.
- Browser code never handles reusable ChatGPT credentials.

## Work packages

### P25_3.0 — ContextPackage endpoint and selector

Add the scoped ContextPackage endpoint/model using Phase 13 planner, Phase 11 context providers, Phase 15 policy, Phase 12 builder, and Phase 25.2 turn preparation. Do not create a ChatGPT-only context system. This authenticated execution/preview endpoint is separate from the gated developer inspector. Carry only authorized content plus redacted manifest, bounded actual selection/exclusions, safe source summaries, authority/sensitivity, count kind, grant versions, expiry, and fingerprint. Unauthorized categories cannot be offered; user selection only narrows an already-authorized set.

**Acceptance:** packages retain shared source/policy/budget semantics and expose only authorized categories.

### P25_3.1 — Shared responsive shell and bridge client

Build alongside existing frontend chat state/SSE/API/proxy seams. Use same-origin cloud API calls and a distinct paired local bridge client; keep credential JavaScript absent. Add automatic-versus-explicit selector, account/model/status, manage-usage/reconnect controls, desktop drawer and mobile bottom-sheet/full-screen behavior, accessibility/focus, and loading/streaming/cancelled/completed/error states. Account/model/scope changes cancel old output and discard stale packages.

**Acceptance:** responsive accessible shell handles bridge/auth/model/account transitions without credential exposure.

### P25_3.2 — Conversation view and safe actions

Stream normalized deltas into the shared view and use Phase 25.2 finalize rather than duplicating persistence. Copy is universal. Insert targets only non-authoritative draft/edit callbacks and must not auto-save authoritative state. Apply is absent/disabled until Phase 31. Show selected context before send; no claim of consumer ChatGPT history/session. Partial ChatGPT output stays transient unless explicitly saved as a draft.

**Acceptance:** completed turns finalize through the shared service; Copy/draft Insert work; authoritative Apply remains disabled.

## Requirement coverage

All twelve former Phase 17.3 commitments remain represented by P25_3.0–P25_3.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
