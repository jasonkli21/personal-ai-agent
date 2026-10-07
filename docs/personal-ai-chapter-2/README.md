# Personal AI — Chapter 2 integrated next-scope plan

Status: regenerated after review, 2026-10-06

This package supersedes the deleted `docs/personal-ai-next-scope-chatgpt-integrated-v2` planning package for **future work** while preserving its implemented Phase 1–2 history and all of its planned scope.

## Current status

- Next-scope Phase 0 reconciliation: complete.
- Next-scope Phase 1 application/workspace identity: implemented and locally verified, with the previously recorded external/deployed gaps still open.
- Next-scope Phase 2 application registry/manifest model: implemented and locally verified, with the previously recorded external/deployed gaps still open.
- **Next implementation phase: Phase 10 — Polyglot persistence foundation and Firestore migration.** P10.0 documentation decisions are complete; P10.1–P10.6 remain unimplemented and externally unverified.
- Phases 3–9 are intentionally unused in this chapter. This keeps Phase 10 as the clear architecture boundary without renumbering the completed Phases 0–2.
- Former Phases 3–16 are preserved as Phases 11–24.
- Former ChatGPT Phases 17.1–17.4 are preserved as Phases 25.1–25.4.
- Former Phases 18–28 are preserved as Phases 26–36.

See [NUMBERING-MAP.md](NUMBERING-MAP.md) for the complete mapping.

## Target architecture after Phase 10 is implemented

```text
Clients / domain applications
          |
          v
Personal AI API / Cloud Run
          |
          +--------------------+---------------------+
          |                    |                     |
          v                    v                     v
       DynamoDB          Neon Postgres            GCS
 operational timeline     + pgvector        bulky artifacts
 conversations/messages   memory/profile     raw evals/traces
 runtime/checkpoints      provenance/research exports/replay
 summaries/idempotency    decisions/metadata
```

Local development mirrors the logical stores:

```text
local Postgres + pgvector  <->  Neon Postgres + pgvector
DynamoDB Local             <->  AWS DynamoDB
local/fake artifact store  <->  private GCS (Phase 20+)
```

Firestore remains the **current implementation until Phase 10 is actually completed**. Phase 10 performs the bounded migration/cutover and then retires Firestore from normal runtime. Planning this migration does not make the repository README describe the future architecture prematurely.

## Storage ownership after Phase 10

- **DynamoDB:** conversations, messages/branch timeline, working summaries, runtime/model/tool events, and checkpoint/idempotency/job state where key/range access patterns justify it.
- **Neon Postgres + pgvector:** bounded global profile, memory/vector/provenance/lifecycle, research/evidence/entities/claims, decisions, account/control metadata, compact quota/evaluation data, and later artifact references.
- **GCS:** large immutable artifact bodies once Phase 20 is implemented.
- Every durable record class has one canonical store; there is no permanent dual-write design or assumed distributed transaction.

## Scope-preservation rule

The reviewed renumbered draft incorrectly shortened the former Phase 3–28 detailed plans and lost substantive work packages/acceptance criteria. This regeneration treats the **pre-renumbering detailed plans as authoritative for scope**. Renumbered plans may change only:

1. phase number and prerequisite references;
2. storage references made obsolete by Phase 10;
3. README-maintenance responsibilities;
4. references required to keep the package internally consistent.

Unrelated product, security, provenance, sensitivity, export/deletion, provider, evaluation, domain, mutation, and ChatGPT requirements remain intact.

## Root README maintenance rule

Every implementation phase must review the repository-root `README.md` before closeout. Update it only if that phase changes a fact a user/developer relies on: implemented capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Do not put low-level implementation mechanics into the root README.

Phase 10 is explicitly required to update the root README after its storage migration/cutover because it changes architecture, storage, local setup, and cloud topology. The README must not be changed to claim that architecture before implementation is complete.

## Package contents

- [01-product-requirements-and-decisions.md](01-product-requirements-and-decisions.md)
- [02-target-architecture.md](02-target-architecture.md)
- [03-free-tier-inference-and-routing.md](03-free-tier-inference-and-routing.md)
- [04-storage-and-artifact-strategy.md](04-storage-and-artifact-strategy.md)
- [05-phased-implementation-plan.md](05-phased-implementation-plan.md)
- [06-free-tier-bottlenecks.md](06-free-tier-bottlenecks.md)
- [07-final-review-record.md](07-final-review-record.md)
- [08-chatgpt-plan-and-ai-sidecar.md](08-chatgpt-plan-and-ai-sidecar.md)
- [09-phase-0-reconciliation.md](09-phase-0-reconciliation.md)
- [Phase 10 storage ownership/access-pattern contract](phase-10-storage-ownership-and-access-patterns.md)
- [Phase 10 migration/cutover/verification plan](phase-10-migration-cutover-and-verification-plan.md)
- [ADR 0021 — polyglot persistence](../decisions/0021-polyglot-persistence-foundation.md)

- [NUMBERING-MAP.md](NUMBERING-MAP.md)
- [COMPATIBILITY.md](COMPATIBILITY.md)
- [personal-ai-next-scope-detailed-implementation-plans/](personal-ai-next-scope-detailed-implementation-plans/README.md)
- [repository-updates/](repository-updates/README.md) — living-doc link/status corrections for applying this package to the repository.

## Implementation discipline

Follow the detailed plan for the active phase and the shared execution contract. Do not start a later phase merely because its plan exists. Offline/fake verification never proves live provider/cloud/domain compatibility; skipped external checks remain unverified.
