# Phase 10 P10.1–P10.3 implementation evidence

Date: 2026-10-06

Tested source: working tree based on `3238dc527de32cba8854c81b63513aee5551245f`; changes were uncommitted when checked.

Scope: P10.1, P10.2, and P10.3 only. P10.4 backfill, P10.5 cloud adapters/release checks, and P10.6 cutover were not started.

## Implemented

### P10.1 — Local persistence stack

- Added a Docker Compose stack for Postgres 17 with pgvector and official DynamoDB Local, persistent development volumes, and an isolated `tmpfs`/in-memory integration profile.
- Added readiness, bootstrap, cleanup, and disposable test targets to the Makefile, plus a deterministic local readiness/bootstrap command and setup documentation.
- Local Postgres endpoint policy and explicit DynamoDB Local endpoint/dummy credentials prevent local checks from discovering cloud credentials.

The local engines were started outside Docker because Docker Compose is not installed in this environment. Readiness, migrations, and DynamoDB table bootstrap were exercised against real local Postgres/pgvector and DynamoDB Local. The Compose container startup, health checks, and volume cleanup have not been exercised here.

### P10.2 — Postgres repositories and vector behavior

- Added six checksum-verified, versioned SQL migrations; typed scoped relations; null-safe workspace keys; revision/event sequencing; constraints and named indexes.
- Added bounded synchronous and async psycopg pools/sessions. Existing synchronous repository contracts remain behind the factory boundary; async services use their existing offload points.
- Added Postgres adapters for memory/provenance/vector search, lifecycle states/events, research and iterative research, decisions/evidence/entities/claims, domain results/lookups, itinerary proposals, booking extractions, identity mappings, deletion requests/audit, usage budgets, and provider rate control.
- Preserved stable IDs, replay keys, transaction groups, revisions, owner/application/workspace checks, immutable snapshots, provenance links, and deletion tombstones.
- Persisted the approved lossless `double precision[]` embedding representation and vector-space metadata. Compatible exact search uses a transient pgvector cast, original-value scoring/tie checks, bounded scans, and failure when parity cannot be established. No persisted vector column or ANN index was added.
- Introduced backend-neutral factory and account-data protocols. Firestore remains the selected runtime factory until a later authorized migration/cutover.

### P10.3 — DynamoDB runtime repositories

- Added one runtime table with the single sparse eventual `job-publication-v1` GSI. Conversation directories, metadata, branches, replay-sensitive writes, summaries, jobs, and effect guards use base-table keys and conditional/transactional operations; request paths do not use `Scan`.
- Added strong metadata/revision reads, revision-checked directories, paginated active-branch reads, bounded root cuts, and summary manifests/chunks with a 256-ID chunk bound.
- Added account-wide DDB request counters and kept P-side provider budget/rate state in Postgres.
- Added the narrow P/D memory-effect guard and Postgres receipt boundary. Applied effects and their receipts share one P transaction; abort recovery arbitrates on the same key; DDB blocks source/job changes until acknowledgement. Direct source writes and job effects use separate guard paths without a general distributed-transaction framework.

## Targeted checks

- Real local integration contracts: `17 passed` in `backend/tests/persistence/test_local_persistence.py`, using a local Postgres/pgvector database and DynamoDB Local. Coverage includes 2,048-dimensional lossless round-trip, vector compatibility/threshold/tie behavior and storage measurements, scoped replay/revisions, repository-family transactions, DDB branch/history/summary/job behavior, direct and job effect recovery races, lifecycle replay/rebuild, and the async Postgres session.
- Existing focused behavior contracts: `216 passed` across memory lifecycle/worker, auth/account data, safeguards, domain/decision, booking extraction, itinerary proposal, research, iterative research, and persistence primitives.
- `make backend-lint`: passed.
- `make backend-build`: passed; build artifacts were removed after verification.
- Local persistence readiness and bootstrap commands: passed against real local services using dummy credentials.
- `git diff --check`: passed.

The full Phase 10 verification matrix was not run. No Neon, AWS, emulator, or deployed checks were performed. Docker Compose was unavailable, so the container-based workflow itself remains unverified.

## Compatibility notes and remaining risks

- Normal runtime still selects Firestore, preserving current export/deletion request behavior before cutover. The new Postgres account adapter currently records export audit and deletion lifecycle state, but its portable `export_owner` operation is deliberately unavailable pending the P/D revision-snapshot export adapter. Do not select the P/D factory for account export or cut over until export covers the declared P and D inventory and reports per-store snapshot/revision coverage. This is the main unresolved compatibility item for review.
- Postgres deletion request records and audits do not perform physical deletion; Phase 9 physical deletion remains open.
- Local Postgres/DynamoDB behavior is verified, but production capacity configuration, IAM, cloud connectivity, migration parity, and release/cutover safeguards remain outside this authorization.
- No change was made to the root README or to the approved P10.0 decision artifacts.
