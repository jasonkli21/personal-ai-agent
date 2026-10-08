# Documentation router

Start with [current state](current-state.md) for the short implementation and release snapshot. Then read only the route for the task at hand. The [root README](../README.md) describes user/developer setup and the current runtime; [project brief](project-brief.md) and [architecture](architecture.md) hold durable intent and boundaries.

## Authority and document classes

When sources disagree, follow this order:

1. Code, executable schemas/contracts, migrations, and tests describe current delivered behavior.
2. Release, review, and verification evidence state what was actually exercised and what remains open.
3. Accepted ADRs record durable decisions and supersession history.
4. Architecture and product documents describe intended boundaries and scope.
5. Active implementation plans describe authorized future sequencing; plans do not prove delivery.
6. Historical plans, prior reviews, and copied source documents provide context only.

The implemented runtime is the one in the root README, current code, and [current state](current-state.md). Chapter 2 Phase 10 persistence, Phase 11 context-source/provider boundaries, Phase 12 model-input building, Phase 13 deterministic context planning, and Phase 16 provider-neutral inference/embedding contracts are implemented locally. Phase 14 bounded provenance/context inspection remains partial because immutable Postgres policy/source-version references are open. Phase 15 permission/sensitivity policy is partially implemented locally; end-to-end revocation through derived context and external acceptance gates remain open. Phase 16's live Gemini compatibility checks remain opt-in; the application still configures Gemini only. See [ADR 0021](decisions/0021-polyglot-persistence-foundation.md) for the accepted persistence decision, [P10.6 evidence](personal-ai-chapter-2/phase-10-p10.6-implementation-evidence.md), [Phase 11 evidence](personal-ai-chapter-2/phase-11-implementation-evidence.md), [Phase 12 evidence](personal-ai-chapter-2/phase-12-implementation-evidence.md), [Phase 13 evidence](personal-ai-chapter-2/phase-13-implementation-evidence.md), [Phase 14 evidence](personal-ai-chapter-2/phase-14-implementation-evidence.md), [Phase 15 evidence](personal-ai-chapter-2/phase-15-implementation-evidence.md), and [Phase 16 evidence](personal-ai-chapter-2/phase-16-implementation-evidence.md). Original Phase 1–9 guides and evidence may describe the storage/provider implementation as it existed at that phase; consult current state and the storage README for current adapters.

## Route by task

| Task | Read first | Authority note |
| --- | --- | --- |
| Chat, conversations, context, summaries | [Phase 2 guide](phase-2-implementation-guide.md), [API contract](api-contract.md), relevant [ADRs](#decisions) | Code/tests define behavior; guides explain the delivered contract. |
| Memory and memory lifecycle | [Phase 3 guide](phase-3-implementation-guide.md), [Phase 4 guide](phase-4-implementation-guide.md) | Keep memory distinct from evidence; see their release/evaluation records below. |
| Research, evidence, decisions, domains | [Research agent notes](research-agent.md), [Phase 5–8 guides](#research-evidence-and-domain-guides) | Guides/release evidence describe bounded, gated capabilities; plans are not delivery evidence. |
| Application registry and integration | [applications README](../backend/src/personal_ai/applications/README.md), [Chapter 2 Phase 2 guide](personal-ai-chapter-2/phase-2-implementation-guide.md) | Registration metadata does not itself grant cross-app access. |
| Context sources, model-input building, inference contracts, inspection, and disclosure policy | [Phase 11 guide](personal-ai-chapter-2/phase-11-implementation-guide.md), [Phase 12 guide](personal-ai-chapter-2/phase-12-implementation-guide.md), [Phase 13 guide](personal-ai-chapter-2/phase-13-implementation-guide.md), [Phase 14 guide](personal-ai-chapter-2/phase-14-implementation-guide.md), [Phase 15 guide](personal-ai-chapter-2/phase-15-implementation-guide.md), [Phase 16 guide](personal-ai-chapter-2/phase-16-implementation-guide.md), and their evidence | Typed preparation, the budgeted builder, deterministic planning, neutral generation/count/embedding contracts, a bounded actual-build inspector, and local server-owned disclosure checks are implemented in part. Phase 14 still needs immutable Postgres policy/source references; Phase 15 still needs end-to-end revocation through derived context; Phase 16's live Gemini compatibility remains unverified. Real domain providers remain future work. |
| Authentication, account data, security | [Phase 9 plan](phase-9-implementation-plan.md), [evidence](phase-9-implementation-evidence.md), [threat model](phase-9-threat-model.md), [release checklist](phase-9-release-checklist.md) | Local behavior and fake tests do not establish deployed security readiness. |
| Persistence and storage changes | [storage README](../backend/src/personal_ai/storage/README.md), [ADR 0021](decisions/0021-polyglot-persistence-foundation.md), [Phase 10 storage contract](personal-ai-chapter-2/phase-10-storage-ownership-and-access-patterns.md) | Current adapters are Postgres/DynamoDB; Firestore material is historical. |
| Phase 10 local persistence or acceptance | [local persistence guide](phase-10-local-persistence.md), [P10.6 evidence](personal-ai-chapter-2/phase-10-p10.6-implementation-evidence.md), [verification plan](personal-ai-chapter-2/phase-10-migration-cutover-and-verification-plan.md) | Evidence is current for implemented work; the verification plan records gates, not passed checks. |
| API or persisted data contracts | [API contract](api-contract.md), then the owning subsystem contract | Contracts describe boundaries; verify implementation in code and tests. |
| Deployment and GCP | [GCP deployment](gcp-deployment.md), then relevant [Phase 9 operational docs](#authentication-and-operations) | Static configuration is not live deployment evidence. |
| Evaluations | [Makefile](../Makefile), relevant `docs/releases/*evaluation*` records, and subsystem release notes | Synthetic/fake evaluations cover only their stated fixtures. |
| Active Chapter 2 planning | [Chapter 2 overview](personal-ai-chapter-2/README.md), [detailed plan index](personal-ai-chapter-2/personal-ai-next-scope-detailed-implementation-plans/README.md), [numbering map](personal-ai-chapter-2/NUMBERING-MAP.md) | Phases 10–13 and Phase 16 are implemented locally; Phase 14 and Phase 15 are partial with documented acceptance gaps; Phase 17 onward remains future work and still requires authorization. |
| Release/review evidence | [Release records](#release-and-review-evidence), [repository review](repository-review-2026-10-03.md) | Evidence is date/revision bounded; do not generalize beyond its checks. |
| Architectural decisions | [ADRs](#decisions) | Read status and supersession notes; older records may be historical. |

## Authentication and operations

- [Phase 9 authorization matrix](phase-9-authorization-matrix.md)
- [Phase 9 threat model](phase-9-threat-model.md)
- [Phase 9 operations runbook](phase-9-operations-runbook.md)
- [Phase 9 provider-data register](phase-9-provider-data-register.md)
- [Phase 9 owner migration](phase-9-owner-migration.md)
- [GCP deployment](gcp-deployment.md)

## Research, evidence, and domain guides

- [Phase 5 guide](phase-5-implementation-guide.md) and [release evidence](releases/phase-5-source-grounded-research.md)
- [Phase 6 guide](phase-6-implementation-guide.md) and [release evidence](releases/phase-6-decision-support.md)
- [Phase 7 guide](phase-7-implementation-guide.md) and [release evidence](releases/phase-7-travel-shopping.md)
- [Phase 8 guide](phase-8-implementation-guide.md) and [release evidence](releases/phase-8-iterative-research.md)

## Release and review evidence

Release records under [`releases/`](releases/) report dated implementation and checks. Evaluation JSON files report only their named synthetic cases. Reviews are snapshots, not living status; the [2026-10-03 repository review](repository-review-2026-10-03.md) retains open Phase 9 and earlier findings. The latest persistence record is [P10.6 evidence](personal-ai-chapter-2/phase-10-p10.6-implementation-evidence.md); the latest context-source, model-input, planning, inspection, disclosure-policy, and inference-contract records are [Phase 11 evidence](personal-ai-chapter-2/phase-11-implementation-evidence.md), [Phase 12 evidence](personal-ai-chapter-2/phase-12-implementation-evidence.md), [Phase 13 evidence](personal-ai-chapter-2/phase-13-implementation-evidence.md), [Phase 14 evidence](personal-ai-chapter-2/phase-14-implementation-evidence.md), [Phase 15 evidence](personal-ai-chapter-2/phase-15-implementation-evidence.md), and [Phase 16 evidence](personal-ai-chapter-2/phase-16-implementation-evidence.md).

## Decisions

The accepted records are in [`decisions/`](decisions/). [ADR 0021](decisions/0021-polyglot-persistence-foundation.md) supersedes [ADR 0002](decisions/0002-firestore-native-persistence.md) for current persistence architecture. ADR 0002 and earlier implementation evidence remain historical; consult their supersession notes before applying old Firestore-era guidance.

## Historical material

Phase guides and old ADRs remain available for their original implementation and decision context. The [detailed plan index](personal-ai-chapter-2/personal-ai-next-scope-detailed-implementation-plans/README.md) identifies preserved source copies from the earlier planning package, and dated reconciliation/review records describe the state at their review date. Neither historical text nor a future plan overrides current code and evidence.
