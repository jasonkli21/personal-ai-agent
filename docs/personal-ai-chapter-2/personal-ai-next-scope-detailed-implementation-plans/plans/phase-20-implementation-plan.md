# Phase 20 implementation plan — Cloud Storage artifact tier and retention

Renumbered from former Phase 12 with **all former sensitivity, retention, export, reconciliation and actual-build requirements preserved**. The only architectural substitution is Phase 10's storage ownership: Postgres stores compact queryable artifact metadata/references; DynamoDB stores only operational references/events when an access pattern requires them; GCS stores large immutable artifact bodies. Firestore is not reintroduced.

## Scope boundary
**Goal:** Keep bulky immutable observability/evaluation/export artifacts out of the operational and relational databases.

### Normative commitments
- Define `ArtifactStore` and `ArtifactRef`.
- Add fake/in-memory and private GCS implementations.
- Add compressed JSON/JSONL support.
- Persist compact artifact metadata/reference in Postgres.
- Use the tier for detailed routing/context traces, raw evaluation output, exports, and debug/replay artifacts.
- Add retention/deletion behavior and Postgres/DynamoDB/GCS storage observability.
- Keep memory vectors in Postgres/pgvector and operational timeline state in DynamoDB.
- Add conservative artifact-write guardrails for free GCS ceilings.

### Phase acceptance criteria
- Raw evals/traces avoid database blob storage.
- Postgres holds queryable summaries/references.
- No public artifact access.
- Optional artifact failure does not fail successful inference.
- Export artifact failure is explicit.
- No large artifact bodies are stored in DynamoDB or Postgres.

### Explicitly out of scope
- online vector search in GCS
- public buckets
- indefinite raw trace retention
- using GCS as a shadow database

## Current state and reuse
Bounded account-export patterns and repository abstractions are reusable. `ArtifactStore`, `ArtifactRef`, GCS and cross-store retention/deletion are genuinely missing. Build on Phase 10's canonical-store map and idempotent cross-store rules.

## Phase 10 storage dependency

Postgres remains canonical for compact artifact metadata; GCS owns immutable bodies/generations. Reuse Phase 10 scoped references, readiness/recovery and declared export snapshot coverage. Required export failure stays explicit; no DynamoDB metadata mirror or credential retention is added. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites and work ordering
Required phases: 1, 14, 19 and 10. (Former prerequisites 1, 6, 11 map to 1, 14, 19.)

## Phase-specific invariants
- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Track operation counts as well as bytes; avoid one-object-per-tiny-event patterns.

## Work packages

### P20.0 — Artifact contracts and local store
Define `ArtifactStore`/`ArtifactRef` with fake implementation. Include owner/app/workspace, run/export identity, key/generation/hash, sensitivity/grant dependencies, schema/content/compression, compressed/uncompressed byte ceilings, expiry/status. Postgres keeps compact queryable summaries/references; vectors remain Postgres; operational timeline remains DynamoDB. No vector-GCS path.

**Acceptance:** Fake artifacts enforce scoped references, compression/hash/size and ready-state contracts.

### P20.1 — Private GCS lifecycle
Implement private object access through authorized services and version/generation preconditions; no public buckets or client arbitrary keys. Use pending/ready/missing/deleting/deleted states, idempotent upload/delete and bounded reconciliation because no Postgres/GCS atomic transaction exists. Hash/decompression validation, orphan cleanup and delayed expiry deletion are explicit. Optional debug artifact failure is advisory; required export returns failure until ready.

**Acceptance:** Every cross-store crash/duplicate/missing/corrupt/delete case has a bounded recoverable state and no public access.

### P20.2 — Consumers, retention and cost guards
Wire retained detailed **actual-build** context/routing traces, raw evaluation outputs, exports and debug/replay artifacts to this tier, with sensitive Health/Finance minimal/no verbose retention. Keep source-rights gates for retained research artifacts. Extend account export/deletion inventory and artifact propagation. Exports freeze a bounded manifest with object generations, source coverage and declared snapshot consistency; oversized or incomplete required exports fail explicitly rather than silently returning partial success. Account deletion denies future retrieval/provider dispatch and fences dependent jobs while physical cleanup is reconciled. Add operation/bytes/retention observability and conservative pre-write budgets, batching tiny events. Deployment uses eligible private region, IAM and no silently paid managed features; review versions/soft-delete/backups and index/image costs.

**Acceptance:** Retained consumers, exports/deletion propagation and byte/operation admission share one artifact store; sensitive verbose traces remain off by default.

## Requirement coverage
| Requirement | Work packages |
| --- | --- |
| R20.1 ArtifactStore/ArtifactRef | P20.0 |
| R20.2 fake + private GCS | P20.1 |
| R20.3 compressed JSON/JSONL | P20.0 |
| R20.4 compact Postgres artifact metadata | P20.1 |
| R20.5 detailed traces/evals/exports/debug artifacts | P20.2 |
| R20.6 retention/deletion + three-tier observability | P20.2 |
| R20.7 vectors/operational state stay in canonical DB stores | P20.0 |
| R20.8 free-tier artifact guardrails | P20.2 |
## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when this phase changes the truth of user-visible capabilities, architecture, tech stack, setup, deployment, provider support, or project status. Keep implementation details in `docs/`; if no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the phase-specific deterministic tests plus applicable backend/frontend test, lint, typecheck and build checks. Finish with `git diff --check`. External/provider/cloud checks are opt-in and skipped checks remain **unverified**, never passed. Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation evidence.
