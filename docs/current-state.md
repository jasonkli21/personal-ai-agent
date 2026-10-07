# Current implementation state

Updated: 2026-10-07. This is the single living status snapshot. Code, tests, and dated evidence remain authoritative for delivered behavior.

## Implemented boundary

The repository contains a Next.js frontend and FastAPI API/worker. Chat, context assembly, gated memory and lifecycle, bounded research, evidence-backed decisions, travel/shopping modules, application manifests, and partial authentication/account safeguards are implemented locally. Experimental product gates remain off by default. See the [root README](../README.md) for current runtime and setup details.

## Persistence

P10.6 switched normal API and worker wiring to Postgres/pgvector plus DynamoDB and removed Firestore SDK, repositories, migration tooling, and runtime fallback. Local/test configurations require explicit Postgres and DynamoDB Local endpoints; deployed configuration targets Neon and federated AWS DynamoDB. This is an implemented code/runtime cutover, not evidence of a live cloud cutover or data migration. The user-reported no-source disposition has not been checked against a cloud account.

## Security and release readiness

Google OIDC, owner mapping, private service invocation, request safeguards, and account workflows are implemented in part. The fixed `local` owner remains a development identity. Staging/production identity, IAM, provider data rights, target-store behavior, and recovery have not received full acceptance. Physical account deletion, deletion-aware restore, full legacy-owner migration, complete provider usage accounting, and operational release gates remain open.

## Planned work and external gates

Chapter 2 Phases 0–2 are completed history and Phase 10 runtime code work is implemented locally. The next planned architecture boundary is [Phase 11, context source/provider abstraction](personal-ai-chapter-2/personal-ai-next-scope-detailed-implementation-plans/plans/phase-11-implementation-plan.md); its plan is not authorization to begin implementation. Phase 10 release acceptance still needs Docker-backed local Postgres/DynamoDB contract checks, live Neon/AWS/GCP verification, and strict-$0 eligibility evidence. If a Firestore source is discovered, the reported no-source disposition must be revisited before data is abandoned or deleted.

## Evidence and plans

- Latest persistence implementation and review record: [P10.6 evidence](personal-ai-chapter-2/phase-10-p10.6-implementation-evidence.md).
- Current account/security gaps: [Phase 9 evidence](phase-9-implementation-evidence.md) and [repository review](repository-review-2026-10-03.md).
- Latest implemented research capability record: [Phase 8 release evidence](releases/phase-8-iterative-research.md).
- Chapter 2 status, numbering, and future scope: [Chapter 2 overview](personal-ai-chapter-2/README.md), [numbering map](personal-ai-chapter-2/NUMBERING-MAP.md), and [detailed plans](personal-ai-chapter-2/personal-ai-next-scope-detailed-implementation-plans/README.md).
