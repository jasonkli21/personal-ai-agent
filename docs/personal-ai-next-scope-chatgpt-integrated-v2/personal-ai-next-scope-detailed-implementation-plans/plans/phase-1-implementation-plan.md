# Phase 1 implementation plan — Application and workspace identity

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Make every request explicitly application-aware.

### Normative commitments from the integrated roadmap

- Add/verify `application_id`.
- Add optional `workspace_id`.
- Thread identity through API, conversation, memory scope, tracing, and tools.
- Define canonical app IDs.
- Preserve standalone use.

### Phase acceptance criteria

- App namespaces cannot leak.
- Existing chat works.
- Traces identify app/workspace.

### Explicitly out of scope

- application registry policy
- cross-app permissions
- domain database access
- new domain features

## Current state and reuse

Owner authentication and safe foreign-ID handling are reusable. Application/workspace fields, scoped vector queries and all AI record propagation need extension; no app/workspace isolation currently exists.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/api/schemas.py`
- `backend/src/personal_ai/api/dependencies.py`
- `backend/src/personal_ai/auth/contracts.py`
- `backend/src/personal_ai/auth/middleware.py`
- `backend/src/personal_ai/services/conversations.py`
- `backend/src/personal_ai/services/chat_turns.py`
- `backend/src/personal_ai/entities/conversation.py`
- `backend/src/personal_ai/storage/repositories.py`
- `backend/src/personal_ai/storage/firestore.py`
- `backend/src/personal_ai/storage/fake.py`
- `backend/src/personal_ai/memory/contracts.py`
- `backend/src/personal_ai/memory/repositories.py`
- `backend/src/personal_ai/memory/lifecycle_jobs.py`
- `backend/src/personal_ai/auth/owner_data.py`
- `backend/src/personal_ai/context/repositories.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 0. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Never accept application/workspace identity as authority for ownership; authenticated principal remains authoritative.
- Workspace is optional and must have explicit null/no-workspace semantics.
- Existing conversation IDs and owner scoping must remain valid.

## Work packages

### P1.0 — Scope contract and compatibility

**Depends on:** required phases above.

Define a validated request scope containing server-derived owner, canonical application ID and nullable workspace. Standalone is the explicit backward-compatible default only for existing standalone routes. Keep correlation request ID separate from operation idempotency key. Use a minimal canonical ID set in this phase; the full metadata registry is Phase 2. Unknown workspace authority and unsupported external app operations fail closed until their domain integration exists. Validate IDs and bounded capabilities/client context; these cannot authorize workspace membership. Extend the Next.js proxy/API helpers to forward validated correlation and scope without accepting client owner claims.

**Acceptance:** Validated scope reaches backend/proxy without client owner authority; standalone/null requests still work.

### P1.1 — Persist and enforce scope everywhere

**Depends on:** P1.0.

Extend repository protocols and service calls for conversation/messages, summaries, original/derived memory, research/evidence, entities/claims, decisions, comparisons, proposals, extraction results, jobs and existing traces. Future grants and other new records must consume the same scope contract when introduced. Scope all reads, exports and replay keys, and include scope in deterministic memory/derived/job identities where needed. Vector queries prefilter scope with model/dimension/status. Worker messages carry scope but re-resolve it against the durable job. Foreign scope returns safe not-found, including direct ID access and retries.

**Acceptance:** Every existing AI record family and replay/vector path rejects foreign app/workspace under the same owner.

### P1.2 — Legacy and regression contract

**Depends on:** P1.1.

Read absent scope as standalone/null only under its verified existing owner. Existing Travel/Shopping comparison screens are standalone Personal AI features; their domain labels do not retroactively relabel legacy records as an external app namespace. Do not backfill or move legacy local-owner data automatically. Define a scoped serialization version/query discriminator so legacy compatibility reads cannot fetch new foreign-app records; prove both original v1 and derived v2 source/ID compatibility without rewriting old records. Document the required scope-prefiltered and legacy-discriminator vector/composite indexes and their opt-in provisioning. Preserve branch links and superseded records; active branch cannot join messages from other scope. Capture identity tests before extending the record families so omission of any collection is visible.

**Acceptance:** Legacy standalone reads and branch/replay regressions pass without backfill or reassignment.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R1.1: Add/verify `application_id`. | P1.0 |
| R1.2: Add optional `workspace_id`. | P1.0 |
| R1.3: Thread identity through API, conversation, memory scope, tracing, and tools. | P1.1 |
| R1.4: Define canonical app IDs. | P1.0 |
| R1.5: Preserve standalone use. | P1.2 |

## Targeted verification and closeout

Test same owner across two apps/workspaces, foreign owner, absent/null workspace, forged client owner, direct-ID reads, vector filters, summary reuse, worker/replay collisions, export and legacy standalone reads. Existing send/regenerate/edit and SSE behavior must pass.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make memory-lifecycle-eval`, `make research-eval`, `make decision-eval`, `make domain-eval`, `make iterative-research-eval`, `make itinerary-proposal-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Emulator transactions/index readiness and deployed Google/IAM/proxy membership behavior are opt-in; local owner migration remains existing Phase 9 work.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
