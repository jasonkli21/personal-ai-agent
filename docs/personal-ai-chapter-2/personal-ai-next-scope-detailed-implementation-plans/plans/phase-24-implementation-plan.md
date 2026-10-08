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
- Depth, physical-send attempt, request-deadline, auxiliary-call, token, and quota budgets are explicit and finite across the whole cascade, including client/SDK retries.
- Only tasks with meaningful deterministic validation use cascades.
- Personal AI owns cascade selection and any explicitly authorized retry; LiteLLM executes one selected-endpoint attempt at a time and cannot choose the next provider/model or hide retries. Every additional send uses Phase 19 attempt admission.

## Work packages
### P24.0 — Task-specific bounded cascade
Define attempt/depth/token/time/auxiliary-call/quota limits and eligible escalation order for tasks with meaningful deterministic validation. The `ExecutionPlan` and Personal AI orchestrator govern attempts; LiteLLM executes the selected endpoint. Reuse schema/span/citation/hard-constraint validators rather than a generic model self-grade. Each physical provider send has a Phase 19 attempt identity and usage/quota reservation, including any explicitly enabled same-endpoint retry; SDK/provider/HTTP hidden retries are disabled. Unknown outcomes remain fenced under the original attempt and cannot be replayed under a new identity. Retries and cascades share cumulative root-operation attempt, time, token, and quota bounds.

Implement registered deterministic `TaskValidator` capabilities as defined in the [target seam](../../02-target-architecture.md#task-validator-and-evaluation-extension-seams). Typed task/domain configuration associates validator ID/version and input/output contracts for schema, citations, required fields, source spans, hard constraints, and domain-specific checks. Generic cascade control flow invokes registered validators; itinerary and Shopping semantics stay in domain validators rather than task-name branches. Missing required validators fail closed.

**Acceptance:** Attempt/depth/time/auxiliary-call/token/quota ceilings are finite and enforced across actual sends, nested client/SDK layers, retries, and cascades; no send occurs after exhaustion.

Correlate each physical attempt with root/decision ID, attempt number, endpoint/profile version, validator ID/version, validation result, escalation reason, usage, latency, status/error, and final accepted attempt under the [Routing Observation Contract](../../03-free-tier-inference-and-routing.md#routing-observation-contract). Each escalation selecting another endpoint creates a distinct decision linked to the previous decision; a physical retry of the identical endpoint plan retains its decision and has a distinct attempt ID. Do not add learned escalation policy here.

**Replay acceptance:** A cascade replay distinguishes its initial and final endpoint selections and their linked decision IDs after registry updates and optional GCS artifact loss; a replay whose required inputs expired or were deleted reports unavailable rather than using current profiles.

**Extension acceptance:** A synthetic task/domain validator can register and govern escalation without generic cascade changes. Unsupported/missing validation cannot expose buffered output or relax free-only, source, sensitivity, or attempt bounds.

### P24.1 — Validate before exposure
Buffer bounded internal task output, validate against exact prepared sources and only then expose success or escalate to a stronger eligible free endpoint. Reassemble and recount using each endpoint's serializer/counter and limits under the same frozen authorization/source policy; a narrower source subset is allowed only by explicit policy, while broader disclosure is denied. Different endpoint truncation is not represented as identical prepared input. Revalidate policy/source/profile and atomically reserve all quota buckets before each endpoint dispatch. User-visible chat after a first delta cannot restart/concatenate another model.

**Acceptance:** Invalid buffered output cannot escape validation; escalation preserves the frozen source/privacy policy, endpoint-specific recounting, and producing-endpoint attribution. A denied reassembly cannot disclose additional sources.

### P24.2 — Direct versus cascade baseline
Compare weaker-first cascade against direct stronger-model execution using Phase 22 fixtures and Phase 23 quota policy. Include total end-to-end latency, every physical attempt and auxiliary count/summary call, total quota/token use, and rejects. Keep direct deterministic rollback unless bounded cascades measurably improve quality or quota efficiency.

**Acceptance:** Paired direct/cascade results justify promotion or leave deterministic direct routing in place.

## Requirement coverage
Former R16.1–R16.4 are preserved as R24.1–R24.4.
## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the phase-specific deterministic tests plus applicable backend/frontend test, lint, typecheck and build checks. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation evidence.
