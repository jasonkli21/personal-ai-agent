# Phase 34 implementation plan — Memory retrieval optimization

Renumbered from former Phase 26. The former retrieval/lifecycle/provenance scope is preserved; the only architectural substitution is Postgres/pgvector for the retired Firestore vector path.

## Scope boundary

**Goal:** Improve durable personal context relevance without weakening source attribution, lifecycle, scope, or authority.

### Normative commitments

- Benchmark current versus hybrid/entity-aware retrieval.
- Add task-conditioned memory selection/budgets where justified.
- Run packing/compression experiments.
- Measure irrelevant/missed/stale context.

### Acceptance criteria

Relevance improves without false-memory, attribution, authority, sensitivity, or scope regression.

## Current state and reuse

Reuse validated fixed/scored/consolidated memory retrieval and lifecycle experiments. Phase 10 migrates canonical memory/vector state to Postgres/pgvector while preserving logical source/lifecycle semantics. This phase optimizes retrieval; it does not redo migration or extraction semantics.

## Prerequisites

Required phases: 1, 10, 12, 16, and 22.

## Invariants

Existing lifecycle exclusions/supersession/forgetting remain binding; owner/app/workspace filters and embedding-space compatibility are hard prerequisites; authoritative domain state never becomes generic memory; no silent embedding-provider migration.

## Work packages

### P34.0 — Postgres/pgvector retrieval benchmark

Compare existing validated retrieval behavior against hybrid/entity-aware candidate selection on source-attributed held-out fixtures. Measure missed/irrelevant/stale/false memories, tokens/latency, and downstream answer support. Require owner/app/workspace scope, embedding model/dimension/normalization/task compatibility, active-source/lifecycle state, and provenance filters before candidate ranking.

**Acceptance:** held-out fixtures quantify baseline relevance/staleness while proving scope/source integrity.

### P34.1 — Task budgets and extractive packing

Add only justified task-conditioned budgets/selection and packing/compression within the shared builder. Original/derived IDs and exact source coverage stay intact. Derived packing is not new memory extraction or domain truth. Preserve vector-space metadata and pgvector retrieval/index semantics; incompatible embeddings fail explicitly and require a separate migration/re-index plan.

**Acceptance:** task packing preserves exact source coverage and vector/lifecycle/scope filters.

### P34.2 — Promotion and fallback

Require measured improvement without false-memory/provenance/sensitivity regression. Keep the existing retrieval variant as deterministic fallback and version experiment policy. Recheck revoked context dependencies and source branch/lifecycle at injection; do not leak through caches or treat source deletion as ordinary forgetting.

**Acceptance:** promoted retrieval improves paired metrics with safe deterministic fallback.

## Requirement coverage

All four former Phase 26 commitments remain represented across P34.0–P34.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
