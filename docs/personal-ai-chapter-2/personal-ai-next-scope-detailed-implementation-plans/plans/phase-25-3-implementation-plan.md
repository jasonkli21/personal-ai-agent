# Phase 25.3 implementation plan — Shared AI sidecar UI

Renumbered on 2026-10-06 from former next-scope Phase 17.3 with its full UI/context/action scope preserved, plus additive cross-provider continuation and manual external-model copy/import flows.

## Scope boundary

**Goal:** Provide one reusable in-application UX for automatic Personal AI routing, the user’s explicitly connected ChatGPT plan, or a user-mediated external model workflow that can re-enter the same Personal AI conversation.

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

### Additive user-flow commitments

- Add a first-class `Continue with…` action on completed turns that starts a new request through the shared conversation/context pipeline and lets the user choose another eligible provider/execution mode.
- Cross-provider continuation must preserve the producing turn’s original attribution and must re-run current context authorization, sensitivity, and budgeting before dispatch.
- Add a generic `Manual external model` execution mode that does not require credentials or provider-specific browser automation.
- Manual external mode must let the user generate/inspect a bounded prepared prompt from the same authorized `ContextPackage`, copy that prompt, use it in an external model of their choice, and explicitly import/paste the resulting response back into Personal AI.
- Imported manual responses must be labelled as `manual_external`; optional provider/model labels are user-declared/unverified unless a supported integration independently observed them.
- After import, the response must behave like any other completed conversation turn for later authorized context, Copy, draft Insert, and future Phase 31 Apply/proposal conversion.
- The UI must never suggest that Personal AI programmatically controlled, authenticated, scraped, or verified the external consumer product used in the manual flow.
- Manual mode must not expose or require consumer-session cookies, passwords, hidden browser state, unofficial endpoints, or reusable provider credentials.
- Copy prepared prompt/import response must be usable even when the ChatGPT bridge is absent or disconnected.
- Switching among automatic routing, connected ChatGPT, and manual external mode is explicit and never rewrites prior-turn provenance.

### Acceptance criteria

- One sidecar works with automatic Personal AI routing and explicit ChatGPT-plan mode.
- ChatGPT mode never claims to be the user’s chatgpt.com session/history.
- Context sent to ChatGPT is inspectable and bounded.
- Copy works without domain mutation.
- No ChatGPT credential crosses into managed cloud persistence.
- A completed turn can be continued through another provider/execution mode with prior attribution preserved and current policy re-evaluated.
- Manual external mode supports the end-to-end copy prepared prompt → external use → import response flow without browser automation or provider credentials.
- Imported external responses are clearly marked as manual/user-supplied, persist through the shared conversation service, and can participate in later authorized workflows.
- The sidecar remains one shared UX rather than introducing provider- or domain-specific conversation surfaces.

## Current state and reuse

Reuse existing chat state/SSE/proxy/auth helpers, the Phase 25.2 external-turn prepare/finalize path, and the shared context planner/policy/builder. The sidecar, context selector, paired local bridge browser client, `Continue with…` interaction, and manual external copy/import interaction are new.

The manual path is deliberately not a second conversation implementation. It reuses the Phase 25.2 prepared-turn/finalization/provenance contracts and the same shared conversation state used by automatic and connected-provider turns.

## Phase 10 storage dependency

Consume shared DynamoDB turn/finalization and Postgres safe control metadata rather than creating sidecar persistence. Local bridge registration/reusable credentials stay user-local and are excluded from managed artifacts and exports. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

Manual imported responses persist only through the shared canonical turn repository with `manual_external` provenance and safe user-declared metadata; they do not create a new sidecar/manual history store.

## Prerequisites

Required phases: 14 and 25.2. Phase 10 is a standing storage boundary.

## Phase-specific invariants

- Always display which provider/model is producing an answer.
- For manual external imports, display execution mode and distinguish optional user-declared provider/model labels from verified/connected metadata.
- Context inspection shows bounded source/category summaries without hidden credentials or unnecessary raw sensitive values.
- Provider switching is explicit and never rewrites prior-turn attribution.
- Browser code never handles reusable ChatGPT credentials.
- `Continue with…` always creates a new turn and re-runs context policy; it never edits the prior answer in place.
- Manual external copy/import remains user-mediated and does not automate a consumer model website/app.
- Imported text does not mutate authoritative domain state merely because it has re-entered the conversation.

## Work packages

### P25_3.0 — ContextPackage endpoint and selector

Add the scoped ContextPackage endpoint/model using Phase 13 planner, Phase 11 context providers, Phase 15 policy, Phase 12 builder, and Phase 25.2 turn preparation. Do not create a ChatGPT-only context system. This authenticated execution/preview endpoint is separate from the gated developer inspector. Carry only authorized content plus redacted manifest, bounded actual selection/exclusions, safe source summaries, authority/sensitivity, count kind, grant versions, expiry, and fingerprint. Unauthorized categories cannot be offered; user selection only narrows an already-authorized set.

Ensure the endpoint can prepare both:
1. connected-provider dispatch packages; and
2. manual-external portable prompt packages that expose only the already-authorized/bounded user-visible content needed for explicit copy.

A continuation request may nominate prior completed turns as candidate context, but the planner must treat them like any other source and re-apply current authorization/sensitivity/budget rules.

**Acceptance:** packages retain shared source/policy/budget semantics and expose only authorized categories; manual portable prompts do not reveal hidden manifest fields or credentials; continuation cannot bypass context policy.

### P25_3.1 — Shared responsive shell and bridge client

Build alongside existing frontend chat state/SSE/API/proxy seams. Use same-origin cloud API calls and a distinct paired local bridge client; keep credential JavaScript absent. Add automatic-versus-explicit selector, account/model/status, manage-usage/reconnect controls, desktop drawer and mobile bottom-sheet/full-screen behavior, accessibility/focus, and loading/streaming/cancelled/completed/error states. Account/model/scope changes cancel old output and discard stale packages.

Extend the execution selector with `Manual external model`. This mode must:
- show the same bounded context summary before preparation;
- generate a copyable prepared prompt using Phase 25.2 manual prepared-turn semantics;
- provide a clear `Copy prepared prompt` action;
- provide a paste/import surface for the returned response;
- optionally capture provider/model labels as user-declared metadata;
- clearly label that Personal AI did not verify the external model/session;
- support cancel/discard/reprepare when context changes.

The manual path must remain available when the local ChatGPT bridge is unavailable, while connected ChatGPT controls remain independently disabled/recoverable.

**Acceptance:** responsive accessible shell handles bridge/auth/model/account transitions without credential exposure; manual copy/import works without bridge availability and has explicit provenance labelling.

### P25_3.2 — Conversation view and safe actions

Stream normalized deltas into the shared view and use Phase 25.2 finalize rather than duplicating persistence. Copy is universal. Insert targets only non-authoritative draft/edit callbacks and must not auto-save authoritative state. Apply is absent/disabled until Phase 31. Show selected context before send; no claim of consumer ChatGPT history/session. Partial ChatGPT output stays transient unless explicitly saved as a draft.

For manual external mode, finalize only after explicit user import/confirmation against the matching active prepared-turn reservation. Imported text is stored as a completed `manual_external` turn with safe user-declared/unverified provider/model metadata. Do not invent streaming, latency, usage, plan, account, or billing facts.

After either a connected, automatic, or manual completion, the same Copy and eligible draft Insert actions are available subject to domain policy.

**Acceptance:** completed turns finalize through the shared service; Copy/draft Insert work; authoritative Apply remains disabled; manual imports use the same completed-turn service and remain correctly labelled.

### P25_3.3 — Cross-provider continuation UX

Add a provider-neutral `Continue with…` action for completed turns. The action starts a new turn with the current conversation/branch and lets the user choose among currently eligible execution modes, such as:
- Personal AI automatic strict-free routing;
- connected ChatGPT plan and an account-visible model;
- other registered providers when available in the broader architecture;
- `Manual external model`.

The previous answer is not blindly concatenated into a raw prompt. Instead, continuation requests feed the shared planner/context pipeline, which decides what prior turns and other context are authorized and fit within the current budget. The context inspector must show the resulting bounded selection before dispatch where the existing UX requires/permits inspection.

Preserve historical attribution exactly. The new turn records its own producing provider/model/execution mode and may reference prior source turns, but it must never rewrite the earlier turn to make it look as though another model produced or verified it.

Account/model/provider changes after preparation invalidate stale packages and require re-preparation. Manual continuation uses the same copy/import path as P25_3.1/P25_3.2.

**Acceptance:** users can complete representative ChatGPT→automatic, automatic→ChatGPT, manual→connected, connected→manual, and same-provider continuations; each produces a new correctly attributed turn and re-runs current context/policy/budget checks.

### P25_3.4 — Manual-flow and continuation failure coverage

Add deterministic UI/integration coverage for:
- copying a prepared manual prompt;
- importing a response into the correct active reservation;
- stale/superseded/expired manual reservations;
- context changes between copy and import;
- missing/optional user-declared provider/model labels;
- explicit discard/reprepare;
- bridge absence while manual mode remains usable;
- continuation after provider/model disappearance;
- continuation when a prior turn is no longer authorized as context;
- cancellation during connected streaming followed by a new manual or automatic turn;
- switching providers without rewriting historical attribution.

No test should require a real external consumer UI; use fakes/fixtures around the Personal AI boundaries.

**Acceptance:** failure-state tests prove user-mediated external execution cannot bypass branch ownership, context freshness, provenance labelling, or domain-action boundaries.

## Requirement coverage

All twelve former Phase 17.3 commitments remain represented by P25_3.0–P25_3.2. P25_3.3–P25_3.4 and the additive clauses add first-class cross-provider continuation and a generic manual external-model fallback without replacing the connected ChatGPT plan path.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
