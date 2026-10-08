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
- Personal AI's authoritative quota ledger supplies typed facts; telemetry from LiteLLM is only an observation source.

## Work packages
### P23.0 — Deterministic scarcity strategy
Extend the Phase 21 deterministic `RoutingStrategy` baseline or add a compatible deterministic scarcity-aware strategy with versioned configurable penalties based on qualified remaining-capacity estimates, window-specific reset horizon, cooldown and reliability. Compare only eligible substitutes meeting Phase 22 task floors. Preserve stronger scarce routes when safe; reducing penalty near reset uses known reset facts, not guessed timestamps. Do not move hard admission or provider selection into LiteLLM.

Consume typed quota buckets by their authoritative bucket IDs, preserving unit, window, observed/remaining state, reset, source, and confidence. Endpoint or credential identities do not create distinct capacity when they map to the same bucket. Request/token/neuron/other units use declared semantics rather than provider-name branches or direct comparison of incompatible units. [Execution-mode eligibility](../../03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes) remains a hard gate; BYOK is never a scarcity fallback.

**Acceptance:** Scarcity penalties are reproducible from qualified bucket/reset facts and eligible measured substitutes.

Record the bounded decision-time quota/scarcity snapshot (or immutable versioned observation) used by the strategy, including bucket unit/window, remaining-capacity value and confidence/source, time-to-reset when known, cooldown/reliability, policy result, eligible substitutes, and selected endpoint. A pointer to mutable current ledger state alone is insufficient for replay. See the [Routing Observation Contract](../../03-free-tier-inference-and-routing.md#routing-observation-contract).

### P23.1 — Ledger and dispatch integration
Read a consistent ledger/profile snapshot and reserve every bucket consumed by each physical send atomically before dispatch, using the Phase 19 attempt ID. Failure to reserve any bucket means no send and no partial authorization. Concurrent capacity loss rejects/reselects within bounded attempt/deadline budgets and creates a linked route decision if the endpoint changes, under identical hard filters. Unknown capacity remains explicit uncertainty, never fake precision or permission for paid overflow.

**Acceptance:** Concurrent admission cannot over-reserve a shared bucket across endpoints/credential rotations, partially reserve a multi-bucket dispatch, or weaken hard filters; unknown quota remains labelled.

### P23.2 — Paired evaluation
Replay recorded synthetic demand/window scenarios against fixed-routing baseline. Measure task quality, conservation, exhaustion, latency and uncertainty outcomes. Promote only with configured thresholds and deterministic rollback; no learned policy or ChatGPT spillover.

**Acceptance:** Paired demand fixtures demonstrate conservation while satisfying quality thresholds and rollback.

Scarcity facts and outcomes join to routing-decision, strategy-version, and invocation identities. Exhausting eligible free capacity never opens a paid/BYOK or subscription lane.

**Extension acceptance:** Synthetic endpoint buckets with distinct units/windows run through the same policy with explicit uncertainty. Exhausting every free bucket yields exhaustion/unavailability, never paid/BYOK or subscription overflow.

## Requirement coverage
Former R15.1–R15.6 are preserved as R23.1–R23.6.
## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the phase-specific deterministic tests plus applicable backend/frontend test, lint, typecheck and build checks. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation evidence.
