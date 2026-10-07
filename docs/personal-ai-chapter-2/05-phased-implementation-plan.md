# Phased implementation plan

Status: integrated renumbered next-scope plan, regenerated 2026-10-06

## Overview

This roadmap preserves the full former integrated scope, adds the Postgres/DynamoDB migration as Phase 10, and keeps completed next-scope Phases 0–2 unchanged. Phases 3–9 are intentionally unused. Detailed plans are authoritative for work packages and acceptance criteria.

### Completed checkpoint

- Phase 0 — reconciliation: complete.
- Phase 1 — application/workspace identity: implemented and locally verified; recorded external gaps remain open.
- Phase 2 — application registry/manifest model: implemented and locally verified; real domain providers/actions remain later scope.

### Immediate next phase

**Phase 10 — Polyglot persistence foundation and Firestore migration.** It establishes local Postgres/pgvector + DynamoDB Local, cloud Neon Postgres + AWS DynamoDB, canonical store ownership, migration/reconciliation, bounded cutover/rollback, and Firestore retirement before the former Phase 3 roadmap resumes.

P10.0 documentation decisions and P10.1–P10.3 local implementation are recorded as of 2026-10-06. See the [storage contract](phase-10-storage-ownership-and-access-patterns.md), [migration/verification plan](phase-10-migration-cutover-and-verification-plan.md), and [implementation evidence](phase-10-p10.1-p10.3-implementation-evidence.md). Firestore remains selected at runtime; P10.4–P10.6 and cloud/cutover acceptance remain open.

## Roadmap

### Phase 0 — Repository, architecture and planning reconciliation **[completed]**

Prerequisites: none.

### Phase 1 — Application and workspace identity **[completed]**

Prerequisites: 0.

### Phase 2 — Application registry and manifest model **[completed]**

Prerequisites: 1.

### Phase 10 — Polyglot persistence foundation and Firestore migration

Prerequisites: 1, 2.

Goal: migrate durable AI-owned persistence to the DynamoDB/Postgres split without reducing existing product scope; local equivalents are required and the root README must be updated after implementation to describe the new architecture.

### Phase 11 — Context source and provider abstraction

Prerequisites: 1, 2, 10.

Scope is preserved from former Phase 3; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 12 — Context builder refactor

Prerequisites: 11, 10.

Scope is preserved from former Phase 4; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 13 — Deterministic context planner

Prerequisites: 12, 10.

Scope is preserved from former Phase 5; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 14 — Provenance and context inspection

Prerequisites: 13, 10.

Scope is preserved from former Phase 6; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 15 — Permissions and sensitivity policy

Prerequisites: 11, 13, 14, 10.

Scope is preserved from former Phase 7; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 16 — Provider-neutral inference and embedding contracts

Prerequisites: 12, 15, 10.

Scope is preserved from former Phase 8; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 17 — Concrete provider adapters: Gemini, Groq, Cloudflare

Prerequisites: 16, 10.

Scope is preserved from former Phase 9; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 18 — Provider/model registry and strict-free eligibility

Prerequisites: 15, 17, 10.

Scope is preserved from former Phase 10; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 19 — Provider usage accounting and quota ledger

Prerequisites: 18, 10.

Scope is preserved from former Phase 11; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 20 — Cloud Storage artifact tier and retention

Prerequisites: 1, 10, 14, 19.

Scope is preserved from former Phase 12; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 21 — Deterministic task-aware routing

Prerequisites: 16, 18, 19, 10.

Scope is preserved from former Phase 13; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 22 — Cross-provider task evaluation matrix

Prerequisites: 20, 21, 10.

Scope is preserved from former Phase 14; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 23 — Quota-aware routing

Prerequisites: 22, 10.

Scope is preserved from former Phase 15; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 24 — Bounded cascades and deterministic validation

Prerequisites: 23, 10.

Scope is preserved from former Phase 16; see the detailed plan for the restored work packages and acceptance criteria.

### Phase 25.1 — ChatGPT authentication and local bridge

Prerequisites: 16, 18, 10.

Scope is preserved from former Phase 17.1; ChatGPT integration remains additive and explicit-user controlled.

### Phase 25.2 — ChatGPT provider/runtime integration, policy, and usage handling

Prerequisites: 19, 21, 25.1, 10.

Scope is preserved from former Phase 17.2; ChatGPT integration remains additive and explicit-user controlled.

### Phase 25.3 — Shared AI sidecar UI

Prerequisites: 14, 25.2, 10.

Scope is preserved from former Phase 17.3; ChatGPT integration remains additive and explicit-user controlled.

### Phase 25.4 — ChatGPT domain integration contract

Prerequisites: 25.3, 10.

Scope is preserved from former Phase 17.4; ChatGPT integration remains additive and explicit-user controlled.

### Phase 26 — Travel integration

Prerequisites: 15, 21, 24, 10.

Scope is preserved from former Phase 18; storage references are updated only where Phase 10 supersedes Firestore.

### Phase 27 — Shopping integration

Prerequisites: 15, 21, 24, 10.

Scope is preserved from former Phase 19; storage references are updated only where Phase 10 supersedes Firestore.

### Phase 28 — Finance integration

Prerequisites: 15, 21, 24, 10.

Scope is preserved from former Phase 20; storage references are updated only where Phase 10 supersedes Firestore.

### Phase 29 — Health integration

Prerequisites: 15, 21, 24, 10.

Scope is preserved from former Phase 21; storage references are updated only where Phase 10 supersedes Firestore.

### Phase 30 — Cross-app context federation

Prerequisites: 15, 26, 27, 28, 29, 10.

Scope is preserved from former Phase 22; storage references are updated only where Phase 10 supersedes Firestore.

### Phase 31 — Mutation proposal framework

Prerequisites: 15, 26, 27, 28, 29, 10.

Scope is preserved from former Phase 23; storage references are updated only where Phase 10 supersedes Firestore.

### Phase 32 — Smarter context planning

Prerequisites: 22, 30, 10.

Scope is preserved from former Phase 24; storage references are updated only where Phase 10 supersedes Firestore.

### Phase 33 — Search and evidence retrieval optimization

Prerequisites: 19, 20, 22, 10.

Scope is preserved from former Phase 25; storage references are updated only where Phase 10 supersedes Firestore.

### Phase 34 — Memory retrieval optimization

Prerequisites: 1, 10, 12, 16, 22.

Scope is preserved from former Phase 26; storage references are updated only where Phase 10 supersedes Firestore.

### Phase 35 — Adaptive routing experiments

Prerequisites: 22, 23, 24, 10.

Scope is preserved from former Phase 27; storage references are updated only where Phase 10 supersedes Firestore.

### Phase 36 — Integrated evaluation and hardening

Prerequisites: 20, 25.4, 30, 31, 32, 33, 34, 35, 10.

Scope is preserved from former Phase 28; storage references are updated only where Phase 10 supersedes Firestore.

## Execution order

`0 [done] -> 1 [done] -> 2 [done] -> 10 -> 11 -> 12 -> ... -> 24 -> 25.1 -> 25.2 -> 25.3 -> 25.4 -> 26 -> ... -> 36`

Later phases with independent prerequisites may be implemented only when their detailed prerequisite set is satisfied and the user authorizes that phase.

## README maintenance rule

Every detailed phase includes a root-README accuracy check. Update the README only when implemented current-state facts change; do not copy detailed work-package mechanics into it. Phase 10 explicitly requires a root README architecture/tech-stack/local-setup/deployment update after the migration is actually complete.

## DynamoDB guardrail

DynamoDB is intentionally limited to named operational key/range access patterns. Postgres remains the default for relational/ad-hoc/query-rich/vector state. Do not add additional AWS services merely because DynamoDB is present.

## Scope preservation

No former normative requirement may disappear merely because of renumbering. If a future reconciliation intentionally changes scope, it must identify the former requirement and rationale explicitly rather than silently shortening the plan.
