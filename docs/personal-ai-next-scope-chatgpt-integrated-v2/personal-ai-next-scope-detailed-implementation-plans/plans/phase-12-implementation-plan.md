# Phase 12 implementation plan — Cloud Storage artifact tier and retention

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Keep bulky immutable observability/evaluation/export artifacts out of Firestore.

### Normative commitments from the integrated roadmap

- Define `ArtifactStore` and `ArtifactRef`.
- Add fake/in-memory and private GCS implementations.
- Add compressed JSON/JSONL support.
- Persist compact artifact metadata/reference in Firestore.
- Use the tier for detailed routing/context traces, raw evaluation output, exports, and debug/replay artifacts.
- Add retention/deletion behavior and Firestore/GCS storage observability.
- Keep memory vectors and operational records in Firestore.
- Add conservative artifact-write guardrails for free GCS ceilings.

### Phase acceptance criteria

- Raw evals/traces can avoid Firestore storage.
- Firestore still holds queryable summaries/references.
- No public artifact access.
- Optional artifact failure does not fail successful inference.
- Export artifact failure is explicit.
- No DynamoDB dependency.

### Explicitly out of scope

- DynamoDB
- online vector search in GCS
- public buckets
- indefinite raw trace retention

## Current state and reuse

Firestore repository and bounded account export patterns are reusable. ArtifactStore, ArtifactRef, GCS and cross-store retention/deletion are genuinely missing.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/auth/account_data.py`
- `backend/src/personal_ai/auth/owner_data.py`
- `backend/src/personal_ai/storage/repositories.py`
- `backend/src/personal_ai/storage/firestore.py`
- `backend/src/personal_ai/storage/fake.py`
- `backend/src/personal_ai/evaluation/context.py`
- `backend/src/personal_ai/evaluation/research.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 1, 6, 11. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Never move memory vectors, active conversations, quota state, or authoritative domain data to GCS.
- Sensitive Finance/Health verbose traces default to minimal retention or no artifact.
- Track operation counts as well as bytes; avoid one-object-per-tiny-event patterns.

## Work packages

### P12.0 — Artifact contracts and local store

**Depends on:** required phases above.

Define future ArtifactStore/ArtifactRef at the existing storage boundary with fake implementation. Include scoped owner/app/workspace, run/export identity, key/generation/hash, sensitivity/grant dependencies, schema/content/compression, compressed/uncompressed byte ceilings, expiry/status. Firestore keeps compact queryable summaries/references; vectors and operational state remain Firestore. No DynamoDB or vector GCS path.

**Acceptance:** Fake artifacts enforce scoped references, compression/hash/size and ready-state contracts.

### P12.1 — Private GCS lifecycle

**Depends on:** P12.0.

Implement private object access through authorized services and version/generation preconditions; no public buckets or client arbitrary keys. Use pending/ready/missing/deleting/deleted states, idempotent upload/delete and bounded reconciliation because no Firestore/GCS atomic transaction exists. Hash/decompression validation, orphan cleanup and delayed expiry deletion are explicit. Optional debug artifact failure is advisory; required export returns failure until ready.

**Acceptance:** Every cross-store crash/duplicate/missing/corrupt/delete case has a bounded recoverable state and no public access.

### P12.2 — Consumers, retention and cost guards

**Depends on:** P12.1.

Wire retained detailed context/routing traces, raw evaluation outputs, exports and debug/replay artifacts to this tier, with sensitive Health/Finance minimal/no verbose retention. Keep source-rights gates for retained research artifacts. Extend account export/deletion inventory and artifact propagation. Exports freeze a bounded manifest with object generations, source coverage and declared snapshot consistency; oversized or incomplete required exports fail explicitly rather than silently returning a partial success. Account deletion must deny future retrieval/provider dispatch and fence dependent jobs while physical cleanup is reconciled; do not claim account physical deletion already exists. Add operation/bytes/retention observability and conservative pre-write budgets, batching tiny events. Deployment uses eligible private region, IAM and no silently paid managed features; review versions/soft-delete/backups and index/image costs.

**Acceptance:** Retained consumers, exports/deletion propagation and byte/operation admission share one artifact store; sensitive verbose traces remain off by default.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R12.1: Define `ArtifactStore` and `ArtifactRef`. | P12.0 |
| R12.2: Add fake/in-memory and private GCS implementations. | P12.1 |
| R12.3: Add compressed JSON/JSONL support. | P12.0 |
| R12.4: Persist compact artifact metadata/reference in Firestore. | P12.1 |
| R12.5: Use the tier for detailed routing/context traces, raw evaluation output, exports, and debug/replay artifacts. | P12.2 |
| R12.6: Add retention/deletion behavior and Firestore/GCS storage observability. | P12.2 |
| R12.7: Keep memory vectors and operational records in Firestore. | P12.0 |
| R12.8: Add conservative artifact-write guardrails for free GCS ceilings. | P12.2 |

## Targeted verification and closeout

Fake integration tests crash at every cross-store transition, corrupt/missing objects, duplicate put/delete, foreign scope, revoked grants, required versus optional failure, expiry, decompression bounds, object versions and account artifact propagation. Run bash -n if deploy.sh changes.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** GCS IAM/generation/lifecycle/soft-delete, Firestore transactions, bucket region/account allowances and cloud resource hard stops need opt-in deployed verification.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
