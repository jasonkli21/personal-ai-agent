# Phase 26 implementation plan — Memory retrieval optimization

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Improve durable personal context without weakening attribution.

### Normative commitments from the integrated roadmap

- Benchmark current versus hybrid/entity-aware retrieval.
- Add task-conditioned memory selection/budgets.
- Run packing/compression experiments.
- Measure irrelevant/missed/stale context.

### Phase acceptance criteria

- Relevance improves without attribution/authority regression.

### Explicitly out of scope

- new memory extraction semantics
- authoritative domain-state storage in memory
- embedding-provider migration without explicit plan
- learned routing

## Current state and reuse

Fixed/scored/consolidated validated retrieval and lifecycle experiments are implemented. Hybrid/entity/task-conditioned optimization needs evaluation and extension, not reimplementation of those variants.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/memory/services.py`
- `backend/src/personal_ai/memory/contracts.py`
- `backend/src/personal_ai/memory/repositories.py`
- `backend/src/personal_ai/memory/lifecycle_policy.py`
- `backend/src/personal_ai/memory/lifecycle_repositories.py`
- `backend/src/personal_ai/memory/inspection.py`
- `backend/src/personal_ai/evaluation/memory.py`
- `backend/src/personal_ai/evaluation/memory_lifecycle.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 1, 4, 8, 14. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Existing lifecycle exclusions/supersession/forgetting remain binding.
- Embedding compatibility and Firestore vector path remain explicit.
- No optimization may increase false-memory or cross-owner/context leakage.

## Work packages

### P26.0 — Retrieval benchmark

**Depends on:** required phases above.

Compare existing validated fixed/scored/consolidated paths against hybrid/entity-aware candidate selection on source-attributed held-out fixtures. Measure missed, irrelevant, stale and false memories, tokens/latency and downstream answer support. Keep owner/app/workspace/vector compatibility and active-source/lifecycle checks as hard prerequisites.

**Acceptance:** Named held-out memory fixtures quantify baseline recall/irrelevance/staleness and source integrity.

### P26.1 — Task budgets and extractive packing

**Depends on:** P26.0.

Add only justified task-conditioned selection/budgets and packing/compression experiments inside shared builder. Original/derived IDs and exact source coverage remain intact; derived packing is not new extraction semantics or domain truth. Preserve model/dimension/normalization/task space and Firestore vector search; no silent incompatible embeddings or re-index migration.

**Acceptance:** Task packing preserves exact source coverage and current embedding space/lifecycle/scope filters.

### P26.2 — Promotion and fallback

**Depends on:** P26.1.

Require improvement without false-memory/provenance/sensitivity regression. Keep existing retrieval variant as deterministic fallback and version experiment policies. Recheck revoked context dependencies and source branch/lifecycle at injection; no cross-scope cache leakage or source deletion disguised as forgetting.

**Acceptance:** Promoted retrieval improves paired metrics with no false-memory/sensitivity regression and safe fallback.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R26.1: Benchmark current versus hybrid/entity-aware retrieval. | P26.0 |
| R26.2: Add task-conditioned memory selection/budgets. | P26.1 |
| R26.3: Run packing/compression experiments. | P26.1 |
| R26.4: Measure irrelevant/missed/stale context. | P26.2 |

## Targeted verification and closeout

Test entity ambiguity, invalid vector space, forgotten/superseded sources, stale branch/source fingerprints, revoked grants, compression coverage and hybrid failure fallback; paired relevance/omission metrics are required.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make memory-lifecycle-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Only relevant provider/emulator/cloud/domain/browser checks run opt-in with explicit environment and synthetic data. Local fakes do not establish deployed compatibility.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
