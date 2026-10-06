# Phase 33 implementation plan — Search and evidence retrieval optimization

Renumbered from former Phase 25 with evidence identity, source-rights, budget, and baseline obligations preserved.

## Scope boundary

**Goal:** Give weaker models better evidence without weakening provenance or bounded research.

### Normative commitments

- Run query-rewrite experiments.
- Add hybrid/source-specialized retrieval where justified.
- Improve deduplication/freshness/reranking and evidence compression/packing.
- Reuse required Phase 19 search-quota admission and add optimization hooks only when justified.
- Store bulky permitted experiment artifacts in GCS.

### Acceptance criteria

End-answer/evidence quality measurably improves and provenance remains exact.

## Current state and reuse

Reuse deterministic constraint-preserving query planning, snippets, freshness/dedupe, literal grounded synthesis, and bounded research budgets. Basic search admission remains Phase 19 responsibility.

## Prerequisites

Required phases: 19, 20, 22. Phase 10 supplies the data-plane ownership: queryable summaries/metadata in Postgres, bulky artifacts in GCS.

## Invariants

Explicit constraints/negation/units/numbers/allowlists survive rewriting; all expansion stays within immutable budgets; derived compression is labelled and exactly support-mapped; source rights/privacy remain mandatory.

## Work packages

### P33.0 — Constraint-preserving query/retrieval experiments

Benchmark current planner/snippet path before rewrite/hybrid/source-specific alternatives. Preserve all literal constraints and domain allowlists; new sources require existing source-policy/rights gates. Stay within search/source/time/usage budgets and Phase 19 admission; no unbounded crawl or proprietary-grounding-only dependency.

**Acceptance:** rewritten/retrieved queries preserve constraints and admitted budgets.

### P33.1 — Evidence identity, freshness, reranking, packing

Improve conservative dedupe/diversity/reranking/packing with observation/claim/source refs and conflict visibility. Derived compression is separately labelled with exact support mapping, never a rewritten original passage. Preserve current literal-passage synthesis/constraint ADR semantics unless a separately evaluated ADR change is accepted.

**Acceptance:** packing/compression preserves exact support/conflict/source mappings.

### P33.2 — Paired end-answer evaluation

Measure supported answers, evidence recall/precision/freshness, constraint retention, quota/budget use, and latency against current baseline. Store permitted bulky outputs in GCS and compact searchable summaries in Postgres. Unverified rights or skipped live sources cannot count as validated quality gains.

**Acceptance:** paired evidence/answer/resource metrics demonstrate benefit without unsupported or skipped-source claims.

## Requirement coverage

All six former Phase 25 commitments remain represented across P33.0–P33.2.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
