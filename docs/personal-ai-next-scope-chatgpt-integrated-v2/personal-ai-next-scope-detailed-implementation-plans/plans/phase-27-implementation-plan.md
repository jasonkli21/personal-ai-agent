# Phase 27 implementation plan — Adaptive routing experiments

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Explore learned routing only after deterministic baselines.

### Normative commitments from the integrated roadmap

- Experiment with complexity classifiers, RouteLLM-style concepts, or contextual bandits.
- Run shadow/offline first.
- Keep hard strict-free/privacy/capability filters outside learning.
- Compare quality/quota use.

### Phase acceptance criteria

- No deployment without measurable benefit.
- Deterministic rollback remains.

### Explicitly out of scope

- production rollout without evidence
- hard-filter learning
- paid-provider optimization
- autonomous policy mutation

## Current state and reuse

Adaptive routing is intentionally deferred until measured deterministic/quota/cascade baselines exist. No learned router currently exists.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/evaluation/context.py`
- `backend/src/personal_ai/llm/client.py`
- `backend/src/personal_ai/api/dependencies.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 14, 15, 16. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- No model/learner can override strict-free, privacy, capability, context-limit, or cooldown hard filters.
- Shadow mode must not affect user-visible route selection.
- A deterministic router remains available as rollback.

## Work packages

### P27.0 — Offline learning dataset and candidates

**Depends on:** required phases above.

Build privacy-safe task/route/quality/quota/latency features from permitted versioned summaries, with held-out splits and profile validity. Explore bounded complexity classifiers, RouteLLM-style concepts or contextual bandits only if concrete data supports the experiment; no required external framework or extra provider scope.

**Acceptance:** Privacy-safe held-out data can reproduce candidate experiment results without a required new framework.

### P27.1 — Shadow behind hard filters

**Depends on:** P27.0.

Run offline/shadow candidates after deterministic strict-free/privacy/capability/context/known-exhaustion eligibility. Shadow cannot dispatch extra billable/private calls or change user-visible route. Models may suggest ranking within eligible candidates only; ChatGPT remains excluded from automatic sets.

**Acceptance:** Shadow mode cannot change visible routes or bypass hard filters, including ChatGPT exclusion.

### P27.2 — Evaluate promotion and rollback

**Depends on:** P27.1.

Compare against Phase 13/15/16 baselines for supported quality, quota conservation, latency and uncertainty under model churn. Define measurable benefit thresholds, deterministic fallback and release gates. No production promotion without valid evidence; adaptive failure never changes hard policy or silently enables paid endpoints.

**Acceptance:** Any promotion has measured benefit/profile validity and tested deterministic rollback.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R27.1: Experiment with complexity classifiers, RouteLLM-style concepts, or contextual bandits. | P27.0 |
| R27.2: Run shadow/offline first. | P27.1 |
| R27.3: Keep hard strict-free/privacy/capability filters outside learning. | P27.1 |
| R27.4: Compare quality/quota use. | P27.2 |

## Targeted verification and closeout

Test shadow non-interference, feature redaction, held-out leakage, invalid/stale profiles, sensitive/paid candidate exclusion and deterministic rollback; record results reproducibly.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
