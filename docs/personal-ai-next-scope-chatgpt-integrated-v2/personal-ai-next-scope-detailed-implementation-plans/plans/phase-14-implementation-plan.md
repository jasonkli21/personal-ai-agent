# Phase 14 implementation plan — Cross-provider task evaluation matrix

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Measure actual task quality.

### Normative commitments from the integrated roadmap

- Reuse/extend existing fixtures.
- Compare enabled strict-free Gemini, Groq, and Cloudflare models.
- Store raw outputs in GCS and summaries in Firestore.
- Version quality profiles.
- Define task quality floors.

### Phase acceptance criteria

- Router quality assumptions have project-specific evidence.
- Evaluations are bounded/reproducible.
- Strict-free eval mode cannot call paid endpoints.

### Explicitly out of scope

- automatic model promotion without thresholds
- paid-provider experiments in strict-free mode
- model judge as the sole scorer
- learned router

## Current state and reuse

Deterministic domain/task fixtures and evaluation runners are reusable. Cross-provider quality matrix and versioned measured profiles are missing.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/evaluation/context.py`
- `backend/src/personal_ai/evaluation/memory.py`
- `backend/src/personal_ai/evaluation/research.py`
- `backend/src/personal_ai/evaluation/decision.py`
- `backend/src/personal_ai/evaluation/domain.py`
- `backend/src/personal_ai/evaluation/iterative_research.py`
- `backend/src/personal_ai/evaluation/itinerary_proposals.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 12, 13. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Separate deterministic offline fixtures from opt-in live-provider evaluations.
- Never claim a provider was evaluated if the live check was skipped.
- Evaluation must preserve sensitive-data policy; synthetic fixtures are the default.

## Work packages

### P14.0 — Baseline matrix and scoring

**Depends on:** required phases above.

Extend fixture/run formats to record task/model/config/serializer/counter/policy/revision/seed where supported. Define held-out fixtures and deterministic schema/citation/provenance/hard-constraint/privacy scoring, with answer support/relevance, token/quota and latency metrics. Model judges may supplement, never be sole scorer. Capture current single-provider and Phase 13 deterministic baselines before comparison.

**Acceptance:** Held-out task fixtures and thresholds produce reproducible deterministic baseline metrics.

### P14.1 — Bounded provider runs and artifacts

**Depends on:** P14.0.

Run identical synthetic task inputs through enabled eligible Gemini/Groq/Cloudflare profiles with Phase 11 admission and bounded attempts/concurrency. Offline fakes validate harness mechanics; live model output is separate evidence. Store retained raw outputs in Phase 12 GCS and compact searchable summaries in Firestore; no private fixtures or unlicensed retained provider evidence.

**Acceptance:** Bounded eligible runs store permitted raw artifacts separately from compact summaries; skipped live models have no quality score.

### P14.2 — Versioned quality profiles and promotion

**Depends on:** P14.1.

Define task quality floors, confidence/sample coverage and profile invalidation when model/config changes. Unrun/skipped endpoints have no measured quality. Require reproducible benefit and no hard-boundary regression; export/publish only permitted artifacts. Domain phases later extend fixtures with their implemented read contracts before optimization consumes those results.

**Acceptance:** Versioned profiles include coverage/config evidence and cannot promote stale or unrun models.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R14.1: Reuse/extend existing fixtures. | P14.0 |
| R14.2: Compare enabled strict-free Gemini, Groq, and Cloudflare models. | P14.1 |
| R14.3: Store raw outputs in GCS and summaries in Firestore. | P14.1 |
| R14.4: Version quality profiles. | P14.2 |
| R14.5: Define task quality floors. | P14.2 |

## Targeted verification and closeout

Test harness reproducibility, split isolation, missing/skipped live result, invalid artifacts, model-version drift, hard-filter violations and rejection of unmeasured profiles. Record live runs distinctly.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Actual task quality/latency/quota requires opt-in provider runs; fake results never prove cross-provider quality.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
