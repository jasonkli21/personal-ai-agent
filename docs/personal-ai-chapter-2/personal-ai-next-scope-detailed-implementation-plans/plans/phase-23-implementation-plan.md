# Phase 23 implementation plan — Quota-aware routing

Renumbered from former Phase 15 with scope preserved.

## Scope boundary
**Goal:** Treat free quota as scarce, expiring compute.

### Normative commitments
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

## Prerequisites and work ordering
Required phase: 22, with Phase 19 ledger and Phase 10 persistence transitively available.

## Phase-specific invariants
- Unknown quota state stays unknown and uses documented conservative/default policy.
- Scarcity policy cannot weaken privacy or capability eligibility.
- Use deterministic formulas/configuration before learned optimization.

## Work packages
### P23.0 — Deterministic scarcity formula
Extend Phase 21 router with versioned configurable penalties based on qualified remaining-capacity estimates, window-specific reset horizon, cooldown and reliability. Compare only eligible substitutes meeting Phase 22 task floors. Preserve stronger scarce routes when safe; reducing penalty near reset uses known reset facts, not guessed timestamps.

**Acceptance:** Scarcity penalties are reproducible from qualified bucket/reset facts and eligible measured substitutes.

### P23.1 — Ledger and dispatch integration
Read a consistent ledger/profile snapshot and reserve selected operation before dispatch. Concurrent capacity loss rejects/reselects within bounded attempts under identical hard filters. Unknown capacity remains explicit uncertainty, never fake precision or permission for paid overflow.

**Acceptance:** Concurrent admission cannot over-reserve or weaken hard filters; unknown quota remains labelled.

### P23.2 — Paired evaluation
Replay recorded synthetic demand/window scenarios against fixed-routing baseline. Measure task quality, conservation, exhaustion, latency and uncertainty outcomes. Promote only with configured thresholds and deterministic rollback; no learned policy or ChatGPT spillover.

**Acceptance:** Paired demand fixtures demonstrate conservation while satisfying quality thresholds and rollback.

## Requirement coverage
Former R15.1–R15.6 are preserved as R23.1–R23.6.
## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the phase-specific deterministic tests plus applicable backend/frontend test, lint, typecheck and build checks. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation evidence.
