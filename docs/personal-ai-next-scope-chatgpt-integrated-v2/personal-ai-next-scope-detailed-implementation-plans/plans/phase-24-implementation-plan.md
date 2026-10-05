# Phase 24 implementation plan — Smarter context planning

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Improve selection after deterministic planning has failure data.

### Normative commitments from the integrated roadmap

- Evaluate misses/over-fetch.
- Add LLM-assisted planning only where justified.
- Route planner calls through strict-free runtime.
- Keep permission constraints outside model.
- Compare quality/token/latency.

### Phase acceptance criteria

- Planner changes show measurable improvement.
- Deterministic fallback remains.

### Explicitly out of scope

- removing deterministic planner
- model-authored authorization
- learned end-to-end routing
- new context sources

## Current state and reuse

Smarter planning is intentionally deferred. Phase 5 deterministic fixtures plus domain/federation traces must supply actual omission/over-fetch data.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/context/contracts.py`
- `backend/src/personal_ai/context/assembler.py`
- `backend/src/personal_ai/evaluation/context.py`
- `backend/src/personal_ai/llm/client.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 14, 22. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- No LLM planner call for requests where deterministic rules are sufficient.
- Fallback to deterministic planner on model/provider failure.
- Measure omission, over-fetch, tokens, latency, and downstream answer quality.

## Work packages

### P24.0 — Failure baseline and experiment criteria

**Depends on:** required phases above.

Extend Phase 5/14 fixtures with implemented domain/federation selections and held-out tasks. Quantify omissions, irrelevant/sensitive over-fetch, bytes/tokens, latency and downstream support quality. Decide whether any failure warrants LLM-assisted planning; no model planner is mandatory absent measured benefit.

**Acceptance:** Recorded domain/federation baselines identify actual omissions/over-fetch and define held-out promotion thresholds.

### P24.1 — Bounded assisted planner

**Depends on:** P24.0.

For justified cases, use authorized minimized planner inputs through strict-free runtime/assembler/ledger. Model proposes a typed bounded selection only; server policy validates every field/provider/window/cap and cannot be changed by model. No new sources, arbitrary tools, all-app dump or direct domain DB reads.

**Acceptance:** Assisted plans cannot authorize new sources/fields and failed validation falls back deterministically.

### P24.2 — Compare and rollback

**Depends on:** P24.1.

Compare against deterministic baseline using fixed promotion thresholds and safe artifacts. Timeout, invalid selection, unavailable model or failed validation returns the deterministic plan without expanding access. Keep versioned policy, reason traces and default-off experiment; promote only measured improvement without sensitivity/authority regression.

**Acceptance:** Paired metrics justify improvement or the experiment remains off with the deterministic planner intact.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R24.1: Evaluate misses/over-fetch. | P24.0 |
| R24.2: Add LLM-assisted planning only where justified. | P24.1 |
| R24.3: Route planner calls through strict-free runtime. | P24.1 |
| R24.4: Keep permission constraints outside model. | P24.1 |
| R24.5: Compare quality/token/latency. | P24.2 |

## Targeted verification and closeout

Test malicious planner suggestions, denied fields/sources, oversized plans, invalid schema/deadline and exact deterministic fallback; compare omission/over-fetch/tokens/latency/downstream quality.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make domain-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
