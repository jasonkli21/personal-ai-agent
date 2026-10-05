# Phase 25 implementation plan — Search and evidence retrieval optimization

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Give weaker models better evidence.

### Normative commitments from the integrated roadmap

- Run query-rewrite experiments.
- Add hybrid/source-specialized retrieval.
- Improve deduplication/freshness/reranking.
- Improve evidence compression/packing.
- Reuse required Phase 11 search quota admission; add optimization hooks when justified.
- Store bulky experiment artifacts in GCS.

### Phase acceptance criteria

- Measured end-answer/evidence improvement.
- Provenance preserved.

### Explicitly out of scope

- provider-proprietary grounding as the only search path
- unbounded crawling
- memory migration
- learned routing

## Current state and reuse

Deterministic constraint-preserving query planning, snippets, freshness/dedupe and literal grounded synthesis are implemented. Retrieval optimization is deferred; basic quota admission is owned by 11, not duplicated here.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/search/contracts.py`
- `backend/src/personal_ai/search/policy.py`
- `backend/src/personal_ai/search/providers/brave.py`
- `backend/src/personal_ai/evidence/contracts.py`
- `backend/src/personal_ai/evidence/pipeline.py`
- `backend/src/personal_ai/agents/research/service.py`
- `backend/src/personal_ai/agents/research/iterative_service.py`
- `backend/src/personal_ai/entities/research.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 11, 12, 14. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Deterministic source/provenance checks remain required.
- Search expansion is bounded by existing research budgets.
- Raw experiment output belongs in GCS when retained; compact summaries remain queryable.

## Work packages

### P25.0 — Constraint-preserving query/retrieval experiments

**Depends on:** required phases above.

Benchmark current query planner and bounded snippet retrieval before query-rewrite/hybrid/source-specialized retrieval. Preserve explicit constraints, negation, units, numbers and domain allowlists; new sources require their existing source-policy/privacy/rights gates. Stay within immutable per-run search/source/time/usage budgets and Phase 11 admission. No unbounded crawling or proprietary grounding-only dependency.

**Acceptance:** Queries retain literal constraints/allowlists and all retrieval stays within existing admitted budgets.

### P25.1 — Evidence identity, freshness and packing

**Depends on:** P25.0.

Improve conservative dedupe/diversity/reranking/packing with complete observation/claim/source refs and conflict visibility. Derived compression is a separately labelled transformation with exact support mappings, never a rewritten original passage. Current ADR 0011 literal selected-passage synthesis and ADR 0016 constraints remain baseline; any semantic synthesis/compression contract change requires an explicit evaluated ADR amendment before promotion.

**Acceptance:** Dedupe/compression retains exact support/conflict/source mappings; broader semantics require evaluated ADR acceptance.

### P25.2 — Paired end-answer evaluation

**Depends on:** P25.1.

Measure supported end answers, evidence recall/precision/freshness, constraint retention, budget and quota use against current research/iterative baseline. Reuse ledger hooks, add only optimized demand signals as justified. Store permitted bulky experiment artifacts in GCS, summaries in Firestore; unverified rights or skipped live sources cannot count as validated improvements.

**Acceptance:** Paired evidence/answer/budget metrics demonstrate benefit without unsupported claims or skipped-source quality claims.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R25.1: Run query-rewrite experiments. | P25.0 |
| R25.2: Add hybrid/source-specialized retrieval. | P25.0 |
| R25.3: Improve deduplication/freshness/reranking. | P25.1 |
| R25.4: Improve evidence compression/packing. | P25.1 |
| R25.5: Reuse required Phase 11 search quota admission; add optimization hooks when justified. | P25.2 |
| R25.6: Store bulky experiment artifacts in GCS. | P25.2 |

## Targeted verification and closeout

Test query constraint loss, near duplicates with conflicting numbers/negation, stale sources, fake citations, unsupported compressed claims, search exhaustion and deterministic fallback.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make research-eval`, `make decision-eval`, `make domain-eval`, `make iterative-research-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Brave storage/AI-use rights, live ranking freshness and any new source compatibility remain opt-in external gates.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
