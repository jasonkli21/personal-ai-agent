# Phase 16 implementation plan — Bounded cascades and deterministic validation

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Use abundant weaker models where safe and escalate only when useful.

### Normative commitments from the integrated roadmap

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

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/llm/client.py`
- `backend/src/personal_ai/evidence/pipeline.py`
- `backend/src/personal_ai/itinerary_proposals/service.py`
- `backend/src/personal_ai/booking_extractions/service.py`
- `backend/src/personal_ai/ranking/policy.py`
- `backend/src/personal_ai/evaluation/research.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 15. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Each escalation reruns hard eligibility under the same-or-stricter sensitivity.
- Depth/attempt budgets are explicit and finite.
- Only tasks with meaningful deterministic validation should use cascades.

## Work packages

### P16.0 — Task-specific bounded cascade

**Depends on:** required phases above.

Define attempt/depth/token/time/quota limits and eligible escalation order for tasks with meaningful deterministic validation. Reuse schema/span/citation/hard-constraint validators rather than a generic model self-grade. Each attempt has invocation identity and usage settlement; unknown outcomes remain fenced.

**Acceptance:** Attempt/depth/time/token/quota ceilings are finite and enforced with existing validators.

### P16.1 — Validate before exposure

**Depends on:** P16.0.

Buffer bounded internal task output, validate against the exact prepared sources and only then expose success or escalate to a stronger eligible free endpoint. Reassemble/recount from the same permitted source set for each endpoint; no privacy widening, hidden evidence changes or paid path. User-visible chat after a first delta cannot restart/concatenate another model.

**Acceptance:** Invalid buffered output cannot escape validation; escalation preserves identical source/privacy constraints.

### P16.2 — Direct versus cascade baseline

**Depends on:** P16.1.

Compare weaker-first cascade against direct stronger-model execution using Phase 14 fixtures and Phase 15 quota policy. Include total latency/attempt costs and rejects. Keep direct deterministic rollback unless bounded cascades measurably improve quality or quota efficiency.

**Acceptance:** Paired direct/cascade results justify promotion or leave deterministic direct routing in place.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R16.1: Define cascade contract with max depth. | P16.0 |
| R16.2: Add deterministic validators for selected tasks: schema, provenance, hard constraints, required fields/citations. | P16.1 |
| R16.3: Escalate to stronger eligible free model. | P16.1 |
| R16.4: Evaluate cascade versus direct stronger-model use. | P16.2 |

## Targeted verification and closeout

Test invalid schemas, fake citations/spans, hard-constraint failure, max depth, deadline, exhaustion, revoked context, unknown-outcome replay and no after-delta continuation across providers.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make research-eval`, `make itinerary-proposal-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
