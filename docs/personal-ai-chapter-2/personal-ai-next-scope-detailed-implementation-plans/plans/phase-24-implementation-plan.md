# Phase 24 implementation plan — Bounded cascades and deterministic validation

Renumbered from former Phase 16 with scope preserved.

## Scope boundary
**Goal:** Use abundant weaker models where safe and escalate only when useful.

### Normative commitments
- Define cascade contract with max depth.
- Add deterministic validators for selected tasks: schema, provenance, hard constraints, required fields/citations.
- Escalate to stronger eligible free model.
- Evaluate cascade versus direct stronger-model use.

### Phase acceptance criteria
- Cascades are bounded.
- Sensitivity cannot widen.
- Adopted cascades improve quality or quota efficiency.

### Explicitly out of scope
- open-ended reflection loops
- privacy widening
- paid escalation
- adaptive routing

## Current state and reuse
Strict service-specific JSON/provenance/constraint validators are reusable. A general bounded eligible cascade policy is missing.

## Prerequisites and work ordering
Required phase: 23.

## Phase-specific invariants
- Each escalation reruns hard eligibility under the same-or-stricter sensitivity.
- Depth/attempt budgets are explicit and finite.
- Only tasks with meaningful deterministic validation use cascades.

## Work packages
### P24.0 — Task-specific bounded cascade
Define attempt/depth/token/time/quota limits and eligible escalation order for tasks with meaningful deterministic validation. Reuse schema/span/citation/hard-constraint validators rather than a generic model self-grade. Each attempt has invocation identity and usage settlement; unknown outcomes remain fenced.

**Acceptance:** Attempt/depth/time/token/quota ceilings are finite and enforced with existing validators.

### P24.1 — Validate before exposure
Buffer bounded internal task output, validate against exact prepared sources and only then expose success or escalate to a stronger eligible free endpoint. Reassemble/recount from the same permitted source set for each endpoint; no privacy widening, hidden evidence changes or paid path. User-visible chat after a first delta cannot restart/concatenate another model.

**Acceptance:** Invalid buffered output cannot escape validation; escalation preserves identical source/privacy constraints.

### P24.2 — Direct versus cascade baseline
Compare weaker-first cascade against direct stronger-model execution using Phase 22 fixtures and Phase 23 quota policy. Include total latency/attempt costs and rejects. Keep direct deterministic rollback unless bounded cascades measurably improve quality or quota efficiency.

**Acceptance:** Paired direct/cascade results justify promotion or leave deterministic direct routing in place.

## Requirement coverage
Former R16.1–R16.4 are preserved as R24.1–R24.4.
## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the phase-specific deterministic tests plus applicable backend/frontend test, lint, typecheck and build checks. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation evidence.
