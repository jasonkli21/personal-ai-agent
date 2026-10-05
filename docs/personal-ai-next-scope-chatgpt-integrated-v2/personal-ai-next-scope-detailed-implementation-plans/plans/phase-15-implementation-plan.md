# Phase 15 implementation plan — Quota-aware routing

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Treat free quota as scarce, expiring compute.

### Normative commitments from the integrated roadmap

- Add deterministic scarcity policy.
- Consider known/estimated remaining capacity and time-to-reset.
- Preserve scarce stronger free routes when substitutes meet quality floors.
- Reduce scarcity penalty near reset.
- Incorporate cooldown/reliability.
- Trace route reasons.

### Phase acceptance criteria

- Hard eligibility is never violated to save quota.
- Unknown quota does not create fake precision.
- Quota conservation is measurable.

### Explicitly out of scope

- learned quota policy
- paid overflow
- cross-mode ChatGPT fallback
- unbounded retries

## Current state and reuse

Scarcity-aware routing is missing and intentionally follows the ledger and measured matrix.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/llm/client.py`
- `backend/src/personal_ai/evaluation/context.py`
- `backend/src/personal_ai/api/dependencies.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 14. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Unknown quota state must stay unknown and use a documented conservative/default policy.
- Scarcity policy cannot weaken privacy or capability eligibility.
- Use deterministic formulas/configuration before any learned optimization.

## Work packages

### P15.0 — Deterministic scarcity formula

**Depends on:** required phases above.

Extend the Phase 13 router with versioned configurable penalties based on qualified remaining-capacity estimates, window-specific reset horizon, cooldown and reliability. Compare only eligible substitutes meeting Phase 14 task floors. Preserve stronger scarce routes when safe; reducing penalty near reset uses known reset facts, not guessed timestamps.

**Acceptance:** Scarcity penalties are reproducible from qualified bucket/reset facts and eligible measured substitutes.

### P15.1 — Ledger and dispatch integration

**Depends on:** P15.0.

Read a consistent ledger/profile snapshot and reserve selected operation before dispatch. Concurrent capacity loss rejects/reselects within bounded attempts under identical hard filters. Unknown capacity remains an explicit uncertainty policy, never fake precision or permission for paid overflow.

**Acceptance:** Concurrent admission cannot over-reserve or weaken hard filters; unknown quota remains labelled.

### P15.2 — Paired evaluation

**Depends on:** P15.1.

Replay recorded synthetic demand/window scenarios against fixed-routing baseline. Measure task quality, conservation, exhaustion, latency and uncertainty outcomes. Promote only with configured thresholds and deterministic rollback; no learned policy or ChatGPT spillover.

**Acceptance:** Paired demand fixtures demonstrate conservation while satisfying quality thresholds and rollback.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R15.1: Add deterministic scarcity policy. | P15.0 |
| R15.2: Consider known/estimated remaining capacity and time-to-reset. | P15.0 |
| R15.3: Preserve scarce stronger free routes when substitutes meet quality floors. | P15.0 |
| R15.4: Reduce scarcity penalty near reset. | P15.0 |
| R15.5: Incorporate cooldown/reliability. | P15.1 |
| R15.6: Trace route reasons. | P15.2 |

## Targeted verification and closeout

Test known/unknown/reset windows, simultaneous admissions, unavailable substitutes, sensitivity/capability dominance, exhausted routes and measurable paired conservation without quality regression.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
