# Codex Assessment Brief — Reconciled With Current Repository

Status: handoff prompt  
Date: 2026-10-02

## Objective

Assess the current `personal-ai-system` repository against this reconciled long-term direction.

Do not redesign the project from scratch.

Do not implement later phases unless explicitly authorized.

The key question is:

> Does the architecture already preserve the right seams for becoming a shared AI/research substrate for future rich travel, shopping, and eventually health applications, while keeping the current research roadmap small and testable?

## Required reading order

Before making recommendations, read the repository's current versions of:

1. root `AGENTS.md`;
2. `project-brief.md`;
3. `architecture.md`;
4. `implementation-plan.md`;
5. `api-contract.md`;
6. `gcp-deployment.md`;
7. `research-agent.md`;
8. ADRs 0001–0011;
9. current phase implementation/release guides relevant to the active task.

Treat code and newer accepted ADR/release evidence as authoritative when stale handoff text conflicts.

## Known reconciliation issue

The supplied project brief still describes Phase 4 as active and says not to advance to Phase 5, while ADR 0011 says Phase 5 was explicitly authorized.

Determine the live repository's actual Phase 5 implementation/release status.

Recommend a minimal documentation correction so future sessions do not misread the active phase.

Do not infer implementation merely from authorization.

## Current architectural facts to preserve unless evidence says otherwise

- Next.js/React/TypeScript web.
- FastAPI API.
- Firestore Native deployed persistence.
- SSE browser streaming.
- provider-neutral LLM boundary.
- append-only branchable messages.
- shared provider-authoritative context assembler.
- working summaries distinct from memory.
- source-grounded attributable memory.
- Firestore vector retrieval with model/dimension compatibility.
- experimental memory lifecycle with deterministic policies.
- private worker and Pub/Sub for bounded durable Phase 4 jobs.
- unauthenticated logical `local` owner is not a security boundary.

## Long-term target

The platform may later support independent rich applications:

```text
travel-app
shopping-app
health-app (later)
```

These may have separate repositories and authoritative domain stores/UIs.

The core should provide reusable AI capabilities such as:

- model access,
- context,
- memory,
- research/evidence,
- entity/ranking support,
- structured extraction,
- typed actions/tools when justified,
- evaluation.

The in-core `domains/travel` and `domains/shopping` direction may remain as shared AI-side domain logic.

Do not recommend moving all app state/UI into `personal-ai-system`.

Do not recommend building a generic plugin/app framework before a real external app creates repeated requirements.

## Assessment questions

### 1. Documentation consistency

Identify stale/conflicting statements across:

- project brief,
- implementation plan,
- architecture,
- deployment,
- accepted ADRs.

Focus especially on Phase 5 authorization/status and current Pub/Sub use.

Propose exact minimal edits.

### 2. Domain-app readiness

Assess whether the current module/API boundaries can later serve a separate rich travel app without major rewrites.

Look for dependencies where:

- UI assumptions leak into services,
- domain state would be forced into chat storage,
- research/memory APIs are inseparable from the current frontend,
- provider-specific data leaks across boundaries.

Do not design the full travel API yet.

### 3. Core-vs-domain ownership

Assess the proposed split:

```text
personal-ai-system:
  shared AI/research + reusable domain intelligence

domain app:
  authoritative domain records + business rules + rich UI
```

Identify any current architecture choice that conflicts with this.

### 4. Firestore portability

The repo already uses repository interfaces, but memory retrieval depends on Firestore vector KNN.

Assess separately:

- canonical-record portability;
- vector-retrieval portability.

Do not claim DynamoDB is a drop-in replacement for Firestore vector search.

Recommend only small interface changes if a real coupling would otherwise force a future rewrite.

### 5. Free-tier posture

Assess current GCP configuration for personal $0-oriented use.

Keep GCP as the current deployment target.

Do not introduce AWS now.

Identify measurable migration triggers, such as:

- Firestore stored/index bytes,
- operation counts,
- vector/index growth.

DynamoDB's 25 GB Always Free storage may be considered a future structured-record option.

Cloud Storage should remain future blob storage unless the current repository already has a real blob requirement.

### 6. Gemini model modernization

The repository correctly uses runtime `AI_MODEL`.

Assess what tests/config changes are required to move the deployment default from the current example (`gemini-2.5-flash`) to a newer stable free-tier Flash model such as `gemini-3.8-flash`.

Do not hard-code the new model.

Separately assess embedding migration from `gemini-embedding-001` to Gemini Embedding 2.

Because embeddings affect dimensions, Firestore vector indexes, and stored records, treat this as a migration decision rather than a routine config switch.

### 7. Phase 5 alignment

Compare the live implementation, if any, with ADR 0011:

- standalone opt-in request,
- request-owned SSE execution,
- idempotent transactional creation,
- bounded source observations/evidence,
- Brave snippets only,
- no publisher-page fetching,
- no full raw response retention,
- grounded structured quotation synthesis,
- persisted citation provenance,
- no implicit retry after process loss.

Flag divergences before proposing broader iterative research.

### 8. Cloud Storage timing

Determine whether any existing feature actually needs object/blob storage.

If not, recommend leaving it absent.

Identify the first plausible feature that would justify a `BlobStore` boundary (for example user-uploaded PDF or booking attachment).

### 9. Pub/Sub scope

Verify that:

- chat streaming remains SSE/direct model streaming;
- Pub/Sub is limited to durable asynchronous workloads;
- current lifecycle jobs preserve idempotency/fencing/recovery.

Do not remove Pub/Sub just because the original v1 discussion deferred it.

Do not expand it into general background orchestration without a demonstrated requirement.

### 10. Security sequencing

The current logical owner is unauthenticated.

Assess whether planned travel/shopping features would cross the current safety boundary before nominal Phase 9.

If real personal email/bookings or other private data are introduced earlier, recommend the smallest authentication/security prerequisite rather than waiting mechanically for Phase 9.

Health should remain out of implementation scope until a deliberate sensitive-data architecture exists.

## Desired output from Codex

Produce:

1. **Current-state correction:** what the repository actually implements/authorizes today.
2. **Conflicts/stale docs:** exact documents/sections needing updates.
3. **Architecture assessment:** seams that are already sufficient.
4. **Minimal recommended changes:** only changes justified now.
5. **Deferred abstractions:** things that should explicitly not be built yet.
6. **Free-tier assessment:** current GCP risks and measurable AWS migration triggers.
7. **Model migration assessment:** generation vs embedding migration.
8. **Domain-app readiness assessment:** whether a future separate travel UI can use the core cleanly.
9. **Next-step recommendation:** scoped to the currently authorized phase; no implementation unless separately authorized.

Favor preserving tested behavior and accepted ADRs over speculative platform refactors.
