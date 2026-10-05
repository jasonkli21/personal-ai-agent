# Phase 0 implementation plan — Repository, architecture and planning reconciliation

Phase 0 is the active documentation-only scope. No substantive implementation of Phase 1 or later is authorized in this session. The [comprehensive review](../../09-phase-0-reconciliation.md) is the current outcome; the [earlier Phase 0 record](../phase-0-reconciliation-2026-10-05.md) is retained and explicitly audited as incomplete historical evidence.

## P0.0 — Verify the baseline

Read AGENTS.md, project brief, architecture and existing phase guides/plans/evidence/ADRs. Inspect git status and preserve unrelated changes. Trace real API/auth/scope, context, memory/vector/lifecycle, search/evidence/decisions/domains, generation/count/embed/fakes, repositories/indexes/export/deletion, UI/proxies/SSE and infrastructure/CI seams. Classify actual behavior separately from similarly named abstractions and external readiness. Verify the earlier review's assertions rather than accepting them.

## P0.1 — Reconcile all source designs and phases

Review every product, architecture, provider, storage, operational, ChatGPT, roadmap and detailed-plan document. Resolve contradictions at their source and propagate corrections. Preserve every intended requirement; distinguish already implemented, partial, reusable, needs extension/refactor, duplicated, missing, intentionally deferred and external-verification-only work. Remove generic duplicate implementation tasks while retaining acceptance duties. Document exact phase prerequisites, baseline-before-optimization rules, scope/authority/privacy/storage/mutation guarantees and future types versus verified file seams. Use current official provider documentation only to verify operational facts, not to claim live compatibility.

## P0.2 — Record and verify the handoff

Maintain substantive issue/correction/rationale/scope/sequencing records and requirement-to-phase/package coverage. Keep one authoritative source per design; compatibility source pointers must resolve. Verify all 32 plans, manifest sizes/order/dependencies, local links/cross-references, known paths, acyclic prerequisite graph and realistic commands. Run relevant cheap offline repository checks where useful and git diff --check; report skipped external checks as unverified. Final report identifies existing reuse, important corrections, gaps, preserved scope, implementation sequence and first genuinely ready phase. Stop before implementation.

## Acceptance

Every handoff file and capability area has been reviewed against code/ADRs and the rest of the package. All scope remains represented, dependencies are acyclic, plans are grounded in real seams, source pointers resolve, documented commands exist or are explicitly future, and external verification is not overstated. The old review is included but superseded where evidence contradicts it. Next-scope Phase 1 may start offline only after this reconciliation; this does not authorize production or private-data promotion.
