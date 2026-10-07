# Phase 36 implementation plan — Integrated evaluation and hardening

Renumbered from former Phase 28. Its release/operational scope is preserved and expanded only where Phase 10 changes the data plane from Firestore/GCS to DynamoDB + Postgres/pgvector + GCS.

## Scope boundary

**Goal:** Validate the complete multi-app, multi-provider, polyglot-persistence platform before deeper feature expansion.

### Normative commitments

Evaluate all former Phase 28 dimensions: app/workspace isolation; context relevance/omission; provenance and authority confusion; mutation safety; strict-free enforcement; provider failure/exhaustion; cascade correctness; sensitive routing; storage growth/retention; artifact authorization; deletion/export propagation; provider removal/change; and ChatGPT credential/bridge/auth/account/model/consent/usage/interruption/explicit-routing/context-minimization/attribution/action boundaries.

Phase 10 adds required hardening for:

- DynamoDB operational growth, hot-key/access-pattern/capacity behavior, conditional/idempotent writes, and local-vs-cloud semantic gaps;
- Postgres schema migrations, storage/compute/connection behavior, pgvector index/vector-space compatibility, and relational/vector query correctness;
- GCS artifact authorization/retention/operation counts;
- cross-cloud timeouts, retry/cancellation behavior, credentials and network/free-tier monitoring;
- export/deletion propagation across DynamoDB, Postgres, and GCS;
- verified absence of normal runtime Firestore dependencies after the migration rollback window closes.

### Acceptance criteria

- No known cross-app isolation failure.
- No known paid-overflow path or sensitivity-unsafe fallback.
- No public/unauthorized artifact path.
- No record class is accidentally canonical in two stores.
- Bulky raw outputs avoid operational/relational DB storage where the artifact tier is intended.
- Provider/storage/network failures degrade explicitly.
- Regression suites cover quality, privacy, mutation, resource, and persistence behavior.
- Firestore is absent from normal runtime after Phase 10 retirement acceptance.

### Explicitly out of scope

new domain/product features, new provider families, major architecture rewrites, or compliance claims.

## Current state and reuse

Reuse established deterministic evaluation suites, account inventory/lifecycle safeguards, provider/runtime tests, and Phase 10 persistence contract/migration evidence. Existing historical Phase 9 release obligations remain owned by their original evidence/checklists and must be closed truthfully rather than duplicated or declared complete by renumbering.

## Phase 10 storage dependency

Consume the Phase 10 local/cloud, numerical parity, guard/receipt race, logical reconciliation and retirement evidence separately. No fake/local result closes cloud gates or the original Phase 9 physical deletion, full owner migration, provider accounting and release obligations. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites

Required phases: 20, 25.4, 30, 31, 32, 33, 34, and 35, plus the standing Phase 10 foundation.

## Invariants

Offline deterministic and external cloud/provider evidence remain separately reported; strict-$0 applies to models and supporting GCP/Neon/AWS/network resources; security/privacy failures block the affected release rather than being relabelled passed behind a disabled flag.

## Work packages

### P36.0 — Integrated negative, quality, and polyglot-storage matrix

Exercise app/workspace isolation, relevance/omission, provenance/authority confusion, mutation confirmation/idempotency, sensitivity-preserving routing/fallback/cascades, strict-free exhaustion, and provider/model changes. Exercise DynamoDB/Postgres/GCS growth, retention, authorization, required/optional artifact failures, cross-store references, migration-derived IDs, export/deletion propagation, and cross-cloud failure/retry semantics. Include local-vs-real-Dynamo differences and Postgres/pgvector compatibility. Establish held-out quality/resource thresholds and keep offline/external evidence distinct.

**Acceptance:** integrated fixtures cover every required domain/provider/persistence/permission/mutation/resource boundary.

### P36.1 — Close existing operational/account obligations

Use the existing owner migration/account export/deletion/recovery work as the authoritative release obligation rather than duplicating it. Verify lifecycle propagation across messages/summaries (DynamoDB), memories/research/decisions/proposals/control metadata (Postgres), artifacts (GCS), jobs, and retained bounded replay/audit records. Verify provider accounting coverage and strict-$0 deployment, IAM/service credentials, telemetry redaction, backup/recovery strategy, migration/rollback documentation, and resource admission. No Firestore TTL or hidden paid dependency may remain required for the normal post-Phase-10 runtime.

**Acceptance:** migration/deletion/accounting/recovery obligations have truthful evidence or remain explicit blockers.

### P36.2 — ChatGPT/domain safety and final release gate

Test credential absence, bridge caller authorization, auth/account changes, missing models/scopes/eligibility/usage, interrupted completion, explicit-only route, no silent billing/provider switch, context minimization/revocation, and Copy/Insert/Apply boundaries across domains. Verify supported-client distribution/plan-only billing/transport gates before promotion. A disabled capability with missing mandatory verification stays unavailable; it is not called passed.

**Acceptance:** ChatGPT/domain clients cannot be promoted with failed eligibility, billing, caller, privacy, mutation, or persistence-isolation checks.

## Requirement coverage

All former Phase 28 commitments remain normative. Phase 10 adds the explicit three-store/cross-cloud/Firestore-retirement hardening requirements above; it does not replace any former evaluation or release requirement.

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Run the applicable backend/frontend test, lint, typecheck, build, and established evaluation commands for the touched surfaces and finish with `git diff --check`. Add a new runner to documentation only when the implementing phase actually creates it. Use deterministic fakes and synthetic fixtures by default; credentials/network/private domain data must not be required for offline coverage. External provider/cloud/domain/browser checks are opt-in and skipped checks remain **unverified**, not passed.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in implementation/release evidence. Completion requires every normative commitment and work package to be locally verified; an externally gated capability may remain unavailable with that gap explicit, but may not be described as complete.
