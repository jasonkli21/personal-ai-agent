# Phase 17.3 implementation plan — Shared AI sidecar UI

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

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

## Current state and reuse

Existing chat state/SSE/proxy/auth helpers are reusable. A reusable sidecar, context selector and bridge browser client are missing.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/api/schemas.py`
- `backend/src/personal_ai/api/routes.py`
- `backend/src/personal_ai/context/assembler.py`
- `backend/src/personal_ai/context/inspection.py`
- `backend/src/personal_ai/services/chat_turns.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 6, 17.2. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- The sidecar must display which provider/model is producing the answer.
- Context inspection should expose categories/source summaries without leaking hidden credentials or unnecessary raw sensitive values.
- Switching provider is explicit and does not rewrite prior turn attribution.

## Work packages

### P17_3.0 — ContextPackage endpoint and selector

**Depends on:** required phases above.

Add the future scoped ContextPackage endpoint/model using the Phase 5 planner, 3 providers, 7 policy, 4 builder and 17.2 turn preparation. Do not create a new context source class or ChatGPT-only builder. This authenticated execution/preview endpoint is separate from the gated development debug inspector; it carries authorized content plus a redacted manifest, serialized once by the bridge adapter. Include bounded actual selection/exclusions, safe source summaries, authority/sensitivity, count kind, grant versions, expiry/fingerprint and no credentials. Unauthorized categories cannot be offered; user selection narrows already-authorized fields only.

**Acceptance:** Packages retain shared source/policy/budget semantics and show only authorized categories.

### P17_3.1 — Shared responsive shell and bridge client

**Depends on:** P17_3.0.

Build adjacent to frontend features/chat/chat-state.ts and lib/sse.ts, using same-origin lib/api.ts/proxy for cloud calls and a separate paired local bridge client. Keep credential JS absent. Add automatic versus explicit-plan selector, account/model/status, manage-usage/reconnect controls and desktop drawer/mobile bottom-sheet or full-screen adaptation. Accessibility, keyboard focus and loading/streaming/cancelled/completed/error states are required. Account/model/scope change cancels old output and discards stale context.

**Acceptance:** Responsive accessible shell and paired bridge client handle cancellation/account/model/connection changes without credential JS.

### P17_3.2 — Conversation view and response actions

**Depends on:** P17_3.1.

Stream normalized deltas into shared chat view; use 17.2 prepare/finalize, do not reimplement completion persistence in UI. Copy is universal, Insert only targets explicitly non-authoritative draft/edit callbacks and may not auto-save authoritative state. Apply is absent/disabled until Phase 23. Show context before send and make explicit switch to automatic available; no claim to chatgpt.com history/session. Partial ChatGPT text stays transient unless explicitly saved as draft.

**Acceptance:** Completed turns use 17.2 finalization; Copy/draft Insert work and authoritative Apply remains disabled.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R17.3.1: Build reusable desktop/web sidecar/drawer shell and define mobile bottom-sheet/full-screen adaptation. | P17_3.1 |
| R17.3.2: Add provider selector for Personal AI automatic strict-free routing and ChatGPT plan when connected. | P17_3.1 |
| R17.3.3: Add ChatGPT account/model controls and visible plan status. | P17_3.1 |
| R17.3.4: Add bounded context summary/inspector/selector. | P17_3.0 |
| R17.3.5: Add Personal AI `ContextPackage` endpoint/model reusing planner/provider/policy/builder semantics. | P17_3.0 |
| R17.3.6: Add bridge client that sends authorized context package to the local/user-controlled runtime. | P17_3.1 |
| R17.3.7: Stream normalized ChatGPT output into the shared conversation view. | P17_3.2 |
| R17.3.8: Add Copy universally. | P17_3.2 |
| R17.3.9: Add Insert only for explicitly non-authoritative draft/edit surfaces. | P17_3.2 |
| R17.3.10: Defer authoritative Apply to Phase 23. | P17_3.2 |
| R17.3.11: Persist completed turns with provider/model attribution; keep interrupted output transient unless explicitly saved as a draft. | P17_3.2 |
| R17.3.12: Test bridge absence, revoked auth, model disappearance, usage-limit errors, and explicit switch back to automatic routing. | P17_3.2 |

## Targeted verification and closeout

Component/integration tests cover no bridge, policy-empty context, mobile layout, keyboard/focus, account/model disappearance, expired/revoked auth/grants, limits, cancelled/interrupted streams, stale completions, explicit mode switch and Copy/Insert/disabled Apply. Provider labels persist correctly.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Supported web-to-local browser transport, native mobile SIWC and deployed UI cancellation are opt-in checks; responsive mock rendering proves no auth capability.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
