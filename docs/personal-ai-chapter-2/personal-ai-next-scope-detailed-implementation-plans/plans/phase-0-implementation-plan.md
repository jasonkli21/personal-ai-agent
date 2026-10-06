# Phase 0 implementation plan — Repository, architecture and planning reconciliation

Phase 0 is completed historical scope. No future phase may rewrite its evidence to imply later architecture choices already existed. The [comprehensive review](../../09-phase-0-reconciliation.md) remains the current reconciliation outcome; later planning amendments must be additive and explicitly supersede forward-looking decisions only.

## P0.0 — Verify the baseline

Read AGENTS.md, project brief, architecture and existing phase guides/plans/evidence/ADRs. Inspect git status and preserve unrelated changes. Trace real API/auth/scope, context, memory/vector/lifecycle, search/evidence/decisions/domains, generation/count/embed/fakes, repositories/indexes/export/deletion, UI/proxies/SSE and infrastructure/CI seams. Classify actual behavior separately from similarly named abstractions and external readiness. Verify the earlier review's assertions rather than accepting them.

## P0.1 — Reconcile all source designs and phases

Review every product, architecture, provider, storage, operational, ChatGPT, roadmap and detailed-plan document. Resolve contradictions at their source and propagate corrections. Preserve every intended requirement; distinguish already implemented, partial, reusable, needs extension/refactor, duplicated, missing, intentionally deferred and external-verification-only work. Remove generic duplicate implementation tasks while retaining acceptance duties. Document exact phase prerequisites, baseline-before-optimization rules, scope/authority/privacy/storage/mutation guarantees and future types versus verified file seams. Use current official provider documentation only to verify operational facts, not to claim live compatibility.

## P0.2 — Record and verify the handoff

Maintain substantive issue/correction/rationale/scope/sequencing records and requirement-to-phase/package coverage. Keep one authoritative source per design; compatibility source pointers must resolve. Verify all detailed plans, manifest sizes/order/dependencies, local links/cross-references, known paths, acyclic prerequisite graph and realistic commands. Run relevant cheap offline repository checks where useful and `git diff --check`; report skipped external checks as unverified. Final report identifies existing reuse, important corrections, gaps, preserved scope, implementation sequence and first genuinely ready phase.

## README maintenance

Phase 0 does not rewrite the repository-root README to describe future architecture as implemented. It may correct objectively stale current-state facts only when verified against the repository.

## Acceptance

Every handoff file and capability area has been reviewed against code/ADRs and the rest of the package. All scope remains represented, dependencies are acyclic, plans are grounded in real seams, source pointers resolve, documented commands exist or are explicitly future, and external verification is not overstated. Historical evidence remains historical truth.
