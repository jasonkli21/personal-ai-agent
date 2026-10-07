# Phase 10 P10.1–P10.3 implementation evidence

> Historical pre-cutover evidence. Runtime statements below describe the P10.1–P10.3
> worktree; P10.6 later changed active runtime wiring and removed Firestore code.
> See [P10.6 evidence](phase-10-p10.6-implementation-evidence.md) and
> [current state](../current-state.md) for present implementation and open gates.

Date: 2026-10-06

Tested source: review-fix working tree based on commit `c7b14b3` (`Implement local polyglot persistence foundation`). The review fixes and this evidence update are the separate follow-up change.

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
- Lifecycle events and retrieval accounting now use that same guard/receipt boundary, including the consumer conversation for completed-assistant validation. Bounded pending-effect pointers connect direct/job receipt recovery to scheduled maintenance and the recovery command; recovery processes only pending entries and caps owner namespace inventory.
- Fixed conditional conversation touch/update for both null and named workspace metadata. Pinned extraction replay conflicts at the unique-key race, restored domain identity to domain lookup replay uniqueness, and implemented the existing scheduled research expiry/audit operation.
- Postgres acquisition and statement timeouts now honor caller deadlines. Proposal, research, and extraction paths propagate remaining budgets, and async extraction writes retain the existing cancellation-draining behavior.
- Implemented bounded portable export across P and D. Postgres records are read in a repeatable-read, read-only snapshot; DDB records use strong bounded reads and revision/directory rechecks. Export includes per-store snapshot/revision coverage and retains the canonical stored embedding values. It explicitly reports that there is no cross-store atomic snapshot.

## Targeted checks

- Real local integration contracts: `21 passed` in `backend/tests/persistence/test_local_persistence.py`, using a local Postgres/pgvector database and DynamoDB Local. Coverage includes 2,048-dimensional lossless round-trip, vector compatibility/threshold/tie behavior and storage measurements, scoped replay/revisions, domain replay identity, extraction replay race, research expiry, portable export, DDB branch/history/summary/job behavior, direct and job effect recovery races, lifecycle replay/rebuild, and the async Postgres session.
- Focused behavior/contract tests: `167 passed` across Postgres deadlines, memory lifecycle/worker, booking extraction, itinerary proposals, research, iterative research, auth/account export, and persistence contract primitives (one upstream Starlette deprecation warning).
- `make backend-lint` with the backend virtual environment activated: passed.
- `make backend-build`: passed; build artifacts were removed after verification.
- Local persistence readiness and bootstrap commands: passed against real local services using dummy credentials.
- `git diff --check`: passed.

The full Phase 10 verification matrix was not run. No Neon, AWS, emulator, or deployed checks were performed. Docker Compose was unavailable, so the container-based workflow itself remains unverified.

## Compatibility notes and remaining risks

- Normal runtime still selects Firestore, preserving current account lifecycle behavior before cutover. P/D export now returns `personal-ai-export-v2` with explicit per-store coverage; consumers that assumed the prior export schema must handle v2. A single atomic snapshot across Postgres and DynamoDB is not available, so the export reports its bounded consistency model rather than implying one.
- Retrieval accounting now requires the completed assistant's conversation ID whenever an assistant ID is supplied. Callers that omit it receive the existing assistant-incomplete outcome rather than validating against memory provenance.
- Domain lookup replay uniqueness now includes `domain_id`; migration `007_domain_lookup_replay_scope.sql` is required before this adapter is used against an existing P10 schema.
- Postgres deletion request records and audits do not perform physical deletion; Phase 9 physical deletion remains open.
- Local Postgres/DynamoDB behavior is verified, but production capacity configuration, IAM, cloud connectivity, migration parity, and release/cutover safeguards remain outside this authorization.
- No change was made to the root README or to the approved P10.0 decision artifacts.

## P10.6 supersession addendum — 2026-10-06

This evidence records the pre-cutover implementation. P10.6 later switched
runtime construction to Neon/Postgres + DynamoDB and removed the Firestore
adapter code. The user reports that no deployed Firestore source existed, so
there was no data migration; no independent cloud inventory was performed.
See the [P10.6 evidence](phase-10-p10.6-implementation-evidence.md) for current
runtime and verification status.
