# Phase 0 reconciliation — historical handoff record

> This is the dated Phase 0/Chapter 2 reconciliation, not the current project
> status. Its Phase 10 “next” statements predate P10.6 implementation. See
> [repository current state](../current-state.md) and [P10.6 evidence](phase-10-p10.6-implementation-evidence.md).

This is the replacement package’s compatibility reconciliation record. It preserves the completed Phase 0 conclusion from the 2026-10-05 review and records the subsequent completed Phase 1–2 state plus the 2026-10-06 persistence/renumbering amendment.

## Verified baseline

The repository already implements substantial conversation, source-attributed memory, research/evidence, decision/domain seams, owner authentication, tracing/evaluation, and Firestore persistence. Existing original repository Phases 1–9 remain a separate historical numbering system.

## Next-scope status

- Phase 0: completed documentation/reconciliation.
- Phase 1: application/workspace identity implemented and locally verified; previously documented deployed/workspace/index/owner-migration gaps remain external/open.
- Phase 2: application registry/manifest implemented and locally verified; real domain providers/actions remain later scope.
- Phase 10: next implementation phase, introducing the Postgres/DynamoDB migration.
- Phase 11 onward: future scope preserved from the former detailed roadmap under the numbering map.

## 2026-10-06 storage decision amendment

The future-facing Firestore/GCS-only target is superseded before Phase 11 begins. Phase 10 migrates to DynamoDB operational state + Neon Postgres/pgvector query-rich state, with local equivalents and later GCS artifacts. This is additive architectural scope and does not delete former requirements.

## Scope-preservation amendment

The first renumbered draft incorrectly summarized old phases and lost details. That draft is rejected as authoritative scope. The regenerated detailed plans restore former work packages/acceptance criteria and make only necessary number/storage/README edits.

## Implementation authorization

The package does not itself authorize implementation beyond the user-selected active phase. Phase 10 is the first ready future phase after completed Phases 0–2. External gates that were previously open remain open until independently verified.
