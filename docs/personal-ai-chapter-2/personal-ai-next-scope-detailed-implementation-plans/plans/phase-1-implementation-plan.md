# Phase 1 implementation plan — Application and workspace identity

Status: completed. This preserved plan records the completed next-scope Phase 1 scope. Later renumbering and the Phase 10 persistence migration do not rewrite its historical implementation claims.

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

Owner authentication and safe foreign-ID handling are reusable. Application/workspace fields, scoped vector queries and all AI record propagation need extension; no app/workspace isolation existed before this phase.

## Prerequisites and work ordering

Required phase: 0.

## Phase-specific invariants

- Never accept application/workspace identity as authority for ownership; authenticated principal remains authoritative.
- Workspace is optional and must have explicit null/no-workspace semantics.
- Existing conversation IDs and owner scoping must remain valid.

## Work packages

### P1.0 — Scope contract and compatibility

Define a validated request scope containing server-derived owner, canonical application ID and nullable workspace. Standalone is the explicit backward-compatible default only for existing standalone routes. Keep correlation request ID separate from operation idempotency key. Use a minimal canonical ID set in this phase; the full metadata registry is Phase 2. Unknown workspace authority and unsupported external app operations fail closed until their domain integration exists. Validate IDs and bounded capabilities/client context; these cannot authorize workspace membership. Extend the Next.js proxy/API helpers to forward validated correlation and scope without accepting client owner claims.

**Acceptance:** Validated scope reaches backend/proxy without client owner authority; standalone/null requests still work.

### P1.1 — Persist and enforce scope everywhere

Extend repository protocols and service calls for conversation/messages, summaries, original/derived memory, research/evidence, entities/claims, decisions, comparisons, proposals, extraction results, jobs and existing traces. Future grants and other new records must consume the same scope contract when introduced. Scope all reads, exports and replay keys, and include scope in deterministic memory/derived/job identities where needed. Vector queries prefilter scope with model/dimension/status. Worker messages carry scope but re-resolve it against the durable job. Foreign scope returns safe not-found, including direct ID access and retries.

**Acceptance:** Every existing AI record family and replay/vector path rejects foreign app/workspace under the same owner.

### P1.2 — Legacy and regression contract

Read absent scope as standalone/null only under its verified existing owner. Existing Travel/Shopping comparison screens are standalone Personal AI features; their domain labels do not retroactively relabel legacy records as an external app namespace. Do not backfill or move legacy local-owner data automatically. Define a scoped serialization version/query discriminator so legacy compatibility reads cannot fetch new foreign-app records; prove both original v1 and derived v2 source/ID compatibility without rewriting old records. Document the required scope-prefiltered and legacy-discriminator vector/composite indexes and their opt-in provisioning. Preserve branch links and superseded records; active branch cannot join messages from other scope. Capture identity tests before extending the record families so omission of any collection is visible.

**Acceptance:** Legacy standalone reads and branch/replay regressions pass without backfill or reassignment.

## Requirement coverage

| Requirement | Work packages |
| --- | --- |
| R1.1: Add/verify `application_id`. | P1.0 |
| R1.2: Add optional `workspace_id`. | P1.0 |
| R1.3: Thread identity through API, conversation, memory scope, tracing, and tools. | P1.1 |
| R1.4: Define canonical app IDs. | P1.0 |
| R1.5: Preserve standalone use. | P1.2 |

## README maintenance

Review the repository-root `README.md` at phase close. Update it only if the completed phase changes user-visible capabilities, architecture, tech stack, setup, deployment, or current-status statements. Do not add implementation-detail churn. For historical completed phases, do not rewrite the README to imply later Phase 10 storage choices existed earlier.

## Targeted verification and closeout

Test same owner across two apps/workspaces, foreign owner, absent/null workspace, forged client owner, direct-ID reads, vector filters, summary reuse, worker/replay collisions, export and legacy standalone reads. Existing send/regenerate/edit and SSE behavior must pass. Run the applicable test/lint/typecheck/build checks and finish with `git diff --check`.
