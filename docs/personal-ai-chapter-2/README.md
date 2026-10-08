# Personal AI — Chapter 2 planning package

This package contains the reconciled architecture, Phase 10 persistence decision/contracts, preserved next-scope plans, and implementation records for Phases 10–15. Plans remain scope references, not evidence for implemented behavior. See the repository's [current state](../current-state.md) and [documentation router](../README.md) for current code and verification status.

## Current and future boundaries

Use repository [current state](../current-state.md), [P10.6 evidence](phase-10-p10.6-implementation-evidence.md), [Phase 11 evidence](phase-11-implementation-evidence.md), [Phase 12 evidence](phase-12-implementation-evidence.md), [Phase 13 evidence](phase-13-implementation-evidence.md), [Phase 14 evidence](phase-14-implementation-evidence.md), and [Phase 15 evidence](phase-15-implementation-evidence.md) for implemented status, verification, and open gates. Phase 14 remains partial because immutable Postgres policy/source-version references are missing. Phase 15 is partially implemented; its evidence records the remaining revocation-through-derived-context contract and external acceptance gaps. This package records the accepted architecture and future scope; [ADR 0021](../decisions/0021-polyglot-persistence-foundation.md) and the [Phase 10 storage contract](phase-10-storage-ownership-and-access-patterns.md) define persistence ownership, and the [Phase 10 verification plan](phase-10-migration-cutover-and-verification-plan.md) records external acceptance checks. Plans after Phase 15 remain future work. The [numbering map](NUMBERING-MAP.md) preserves original and regenerated phase identifiers.

The architecture assigns conversation/runtime timelines to DynamoDB, query-rich durable knowledge and vectors to Postgres/pgvector, and bulky immutable artifacts to GCS only in future Phase 20.

## Scope preservation and package contents

The regenerated plans preserve the substantive scope of their source planning package. Renumbering may update phase/prerequisite references, persistence assumptions superseded by Phase 10, README-maintenance requirements, and links needed for consistency; it must not discard product, security, provenance, sensitivity, export/deletion, provider, evaluation, domain, or mutation requirements.

- [Product requirements and decisions](01-product-requirements-and-decisions.md)
- [Target architecture](02-target-architecture.md)
- [Free-tier inference and routing](03-free-tier-inference-and-routing.md)
- [Storage and artifact strategy](04-storage-and-artifact-strategy.md)
- [Phased implementation plan](05-phased-implementation-plan.md)
- [Free-tier bottlenecks](06-free-tier-bottlenecks.md)
- [Final review record](07-final-review-record.md)
- [ChatGPT plan and AI sidecar](08-chatgpt-plan-and-ai-sidecar.md)
- [Phase 0 reconciliation](09-phase-0-reconciliation.md) — dated historical record
- [Detailed phase plan index](personal-ai-next-scope-detailed-implementation-plans/README.md)
- [Compatibility](COMPATIBILITY.md)

Read the detailed plan for the specifically authorized phase. Offline/fake checks do not prove provider, emulator, cloud, IAM, or cost behavior. Keep skipped external acceptance open in release evidence.

## Extensibility planning route

The 2026-10-07 additive reconciliation defines the [Application Integration Contract](02-target-architecture.md#application-integration-contract), [task/validator/evaluation seams](02-target-architecture.md#task-validator-and-evaluation-extension-seams), and [execution identity/cost modes](03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes). Product decisions state the principles; the target architecture owns detailed semantics; affected phase plans own implementation constraints and acceptance. Existing numbering, scope, and prerequisites remain intact. Phase 11 implementation status is recorded in its [guide](phase-11-implementation-guide.md) and [evidence](phase-11-implementation-evidence.md); Phase 12 builder status is recorded in its [guide](phase-12-implementation-guide.md) and [evidence](phase-12-implementation-evidence.md); Phase 13 planner status is recorded in its [guide](phase-13-implementation-guide.md) and [evidence](phase-13-implementation-evidence.md); Phase 14 partial inspection status and its open version-reference prerequisite are recorded in its [guide](phase-14-implementation-guide.md) and [evidence](phase-14-implementation-evidence.md); Phase 15 partial policy status and its revocation/evidence gaps are recorded in its [guide](phase-15-implementation-guide.md) and [evidence](phase-15-implementation-evidence.md). Phase 16 onward remains planned work. Preserved source copies and dated records remain historical.
