# Phase 25.4 implementation plan — ChatGPT and shared external-model domain integration contract

Renumbered on 2026-10-06 from former Phase 17.4; domain-ownership and additive-scope requirements are preserved, with additive shared hooks for cross-provider continuation and manual external-model turns.

## Scope boundary

**Goal:** Extend the [Application Integration Contract](../../02-target-architecture.md#application-integration-contract) with shared sidecar/host hooks, validated by Travel, Shopping, Finance, and Health reference integrations, so ChatGPT-specific UI/auth/provider logic and generic manual-external/cross-provider logic are not duplicated per application.

### Normative commitments

- Standardize sidecar launch context around application/workspace/entity/view/conversation scope plus bounded client context.
- Reuse the existing planner/provider/policy/builder pipeline for inspectable `ContextPackage`; no parallel ChatGPT-only context system.
- Preserve domain authority and mutation validation.
- Standardize provider/model attribution and completed-turn persistence.
- Standardize Copy/Insert/Apply boundaries.
- Define sensitivity-aware domain hooks.
- Keep domain-specific behavior in later domain phases rather than core app-name branching.

### Additive integration commitments

- Standardize host behavior for `Continue with…` so cross-provider continuation remains a shared sidecar capability rather than a domain-specific implementation.
- Standardize a generic manual-external launch/copy/import contract that domains can opt into without implementing provider auth, browser automation, or a separate conversation store.
- Domain apps may narrow or disable manual external disclosure based on sensitivity policy, just as they may narrow connected-provider context.
- Manual imported responses must enter the same shared conversation callbacks/persistence path with `manual_external` and user-declared/unverified provenance.
- Copy, manual import, continuation, draft Insert, and future Apply operate on the same domain-authority boundaries regardless of which provider/execution mode produced the text.
- A domain must not special-case ChatGPT versus manual/other providers for authoritative mutation rights; producing provider is provenance, not authority.
- Reference integrations must demonstrate that a prior response can be continued through another eligible provider without direct domain database access or app-specific provider branches.

### Acceptance criteria

- Domain apps integrate through one shared sidecar/context contract.
- No app implements its own ChatGPT token/auth stack.
- Domain context remains bounded, authorized, attributable, and sensitivity-aware.
- No authoritative domain state moves into Personal AI.
- Existing domain-phase scope remains intact; ChatGPT tasks are additive.
- No app needs a custom manual-external history, custom provider-switching controller, or consumer-site automation.
- Cross-provider continuation and manual import work through the shared contract while preserving original turn attribution and domain authority.

## Current state and reuse

Phase 25.2/25.3 supply shared sidecar/context/external-turn contracts. Domain launch adapters and sensitivity/action hooks are new integration contracts only.

The additive manual-external and cross-provider flows also come from shared Phase 25.2/25.3 contracts. Phase 25.4 only exposes the domain-owned launch/context/action hooks needed to use them safely; it must not recreate those flows inside each app.

## Phase 10 storage dependency

Domain host adapters consume the shared DynamoDB conversation and Postgres policy/control contracts. They must not persist reusable credentials or local bridge registration in managed stores, nor copy authoritative domain records into AI storage. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

Manual imported responses remain shared conversation turns, not domain-owned copies. Domain state stays authoritative and is only changed through later validated mutation flows.

## Prerequisites

Required phase: 25.3. Phase 10 remains the persistence boundary.

## Phase-specific invariants

- Domain apps remain authoritative for state and validation.
- Finance/Health may expose stricter/narrower context/action policy without forking the sidecar.
- Apply is declarative but remains disabled until Phase 31.
- Provider/execution-mode changes never change domain authority.
- Manual external mode may be disabled or narrowed by domain sensitivity policy without requiring a forked sidecar.
- A continuation action always creates a new shared conversation turn; domains do not rewrite prior-turn provenance.
- Domain adapters never automate an external consumer model UI or collect its credentials/session state.

## Work packages

### P25_4.0 — Domain launch and read contract

Define versioned launch metadata for app/workspace/entity/view/conversation plus bounded advisory client context. Domain-owned adapters supply authorized typed source refs and consume the shared package; core never directly queries domain databases. Keep Personal AI workspace separate from ChatGPT account registration. Supply fake integration examples for all four apps without claiming real external app files.

Compose existing scope, definition/workspace semantics, provider registrations, typed policy, planner, builder, provenance, and authority boundaries. This is an optional host extension of the same integration model, not a separate ChatGPT-domain framework or a mandatory client SDK. ChatGPT remains a distinct explicit subscription lane under shared disclosure policy.

The launch contract must be provider/execution neutral enough that the same sidecar instance can later run automatic routing, connected ChatGPT, another registered provider, or manual external mode without the domain adapter branching on provider names.

**Acceptance:** four fake domain launches compose with one shared package/turn contract and no core domain-DB access; launch adapters do not need provider-specific control flow.

### P25_4.1 — Sensitivity and action hooks

Expose narrow allowed context categories and policy-approved Copy/draft Insert. Finance/Health may further restrict fields/artifacts without forking credentials/UI. Apply remains disabled until Phase 31; domain validation and mandatory user confirmation remain required. Auth/model discovery/usage/producing-provider metadata come only from shared contracts.

Extend domain policy hooks so a domain can separately allow/narrow/deny:
- connected-provider disclosure;
- manual-external prepared-prompt disclosure;
- imported-response reuse as later context;
- draft Insert;
- future typed Apply operations.

A domain may therefore permit local/automatic reasoning while disallowing manual external copy for selected sensitive categories, without adding a provider-specific fork.

**Acceptance:** domain policy can narrow context/actions without custom auth; Apply remains disabled; manual external disclosure obeys the same shared policy framework.

### P25_4.2 — Integration handoff and boundary tests

Document domain-owned read/mutation API responsibilities and required repository/revision/transport verification before each live integration. Standardize post-completion callbacks without duplicating prepare/finalize. Prove a synthetic domain adds no core app-name branch, app-specific provider auth, or authoritative state in Personal AI.

Add reference contract tests showing:
- a completed domain-scoped turn can be continued through a different provider/execution mode using the shared sidecar;
- historical attribution remains unchanged;
- manual imported output returns through the shared completion callback;
- Copy/manual import never mutate domain state;
- draft Insert only targets declared non-authoritative edit surfaces;
- unsupported/sensitive domains can disable manual external disclosure without changing shared sidecar code.

**Acceptance:** integration boundaries preserve shared attribution/completion and domain authority across connected, automatic, and manual-external turns.

**Extension acceptance:** A synthetic application launches through registered host/provider/policy hooks without changes to the shared sidecar, preparation pipeline, authentication, continuation controller, or manual-external controller. The four reference launches remain required examples, not the only supported application identities.

## Requirement coverage

All seven former Phase 17.4 commitments remain represented by P25_4.0–P25_4.2. The additive clauses extend the same host/domain contracts to cross-provider continuation and manual external-model turns without changing domain ownership or moving mutation scope forward from Phase 31.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
