# Phase 10 P10.4–P10.5 implementation evidence

Date: 2026-10-06 (America/Los_Angeles)
Tested source: P10.4/P10.5 working tree based on clean commit
`e1314dd3faf791b3b9f6f7453deb068c1015e2c0`; the final single commit is
reported in the handoff. The targeted code checks below ran against the final
implementation tree recorded here.
Scope: P10.4 and P10.5 only. No P10.6 runtime cutover or Firestore retirement.

## Implemented

### P10.4 — Firestore inventory, bounded migration and reconciliation

- Added an operator-only Firestore source reader and migration command that
  scans all 34 source families with document-ID pagination, bounded batch/record
  limits, dry-run inventory and mapping validation, safe rejection codes and
  deterministic source/mapped hashes. The normal persistence factory does not
  load the migration command.
- Added versioned Postgres migration epochs, per-family resumable checkpoints,
  a shared-target advisory lock, source update versions/hashes, target ownership
  hashes, source-to-target locators and explicit applied/rejected/disposed/
  source-deleted dispositions. P target writes and checkpoint acknowledgements
  share one transaction; D target acknowledgements follow the idempotent target
  commit. The unique logical-target index rejects duplicate semantic identities.
- Maps source logical IDs while preserving owner, application/workspace scope,
  private/shared/global namespace, timestamps, branch lineage, summary payloads,
  memory vectors/vector-space metadata, source provenance, lifecycle values,
  request/replay identities, policy versions and expiry. Embedded aggregate
  edits are covered by source and mapped hashes. Memory embeddings are stored
  once in the P vector column; the logical hash reconstructs the typed record
  from that column plus the payload, and the JSON envelope has its own 32 KiB
  bound. Full global provider-throttle envelopes and legacy lifecycle operation
  payloads remain queryable.
- Resolves ownerless decision/domain/entity children against their source
  parents and rejects missing, cross-owner or cross-scope parents. Active hashed
  request counters and opaque daily usage budgets require deterministic owner
  attribution; unresolved active state blocks. Expired unattributed counters
  require the explicit reviewed-disposition option. Storage migration does not
  change legacy owners.
- Adds bounded final-delta enumeration and deletion in dependency order. A target
  is deleted only when it still matches the last migration-owned hash. A
  post-write paginated read-back hashes every applied logical record. Family
  reports include unique source/disposition counts, replay scan-attempt counts,
  mapped-target and target-read-back digests, and reconciliation counts. A
  checkpoint-loss retry, source edit, target divergence and source deletion are
  covered by synthetic tests. `final_delta_ready` reports migration readiness;
  it never switches runtime storage.
- Added migrations 008–012 for the migration control plane, source envelope and
  target locator preservation, effect-receipt payload fidelity, duplicate target
  identity rejection, and full provider-rate-limit source payload.

### P10.5 — Cloud adapters, IAM and strict-$0 controls

- Added opt-in Neon runtime/direct clients. Deployed DSNs require Neon hostname
  and verified TLS; runtime uses the transaction pooler, a zero-minimum/four
  maximum connection pool and disabled prepared statements. Schema and migration
  tools use a separate direct Neon endpoint and a pool of at most two. The
  settings flag validates adapter configuration but does not select these
  clients in normal runtime.
- Added Cloud Run Google service-account ID-token → AWS STS web-identity
  federation, exact `aud`/`oaud`/`sub` mapping, bounded token/SDK timeouts,
  refreshable one-hour credentials and TLS-verified DynamoDB access. The adapter
  rejects local credential files and cannot bootstrap cloud tables.
- Added separate DynamoDB runtime, migration and bootstrap policy templates;
  exact Google OIDC trust template; a provisioned Standard table/GSI
  CloudFormation template with explicit non-default capacities and no autoscale,
  PITR, backup or global-table settings; and separate Neon runtime, migration
  and schema-administrator grant boundaries.
- Added a strict-$0 release validator. Fresh high-confidence eligibility,
  account/configuration source, hard-cap enforcement and projected zero charge
  are required for every Neon, DynamoDB table/GSI, GCP service, external
  network, Firestore source read/storage, AWS return-traffic and migration/
  recovery resource. Non-finite capacity, unknown costs or stale/missing evidence
  block cloud schema and migration commands.
- Added an explicitly gated cloud smoke for Neon pgvector and DynamoDB
  conditional create/read/update/delete, base-table and publication-GSI queries
  against pre-existing resources.
  The test never bootstraps cloud infrastructure and remains skipped without
  reviewed opt-in. Connectivity uses public TLS endpoints from Cloud Run; no
  NAT, peering, private endpoint or unrelated AWS service was added.
- Added the [operator guide](phase-10-p10.4-p10.5-operator-guide.md). The root
  README was not changed, and Firestore remains selected in normal runtime.

## Targeted checks

Results from the implementation working tree:

- Migration/reconciliation, cloud adapter/configuration, strict-$0, static IAM/
  capacity and gated smoke selection: **20 passed, 1 skipped**. The skip is the
  cloud smoke, whose explicit Cloud Run/review opt-in was absent.
- Settings/Postgres endpoint and pool checks: **13 passed**.
- Auth/export regressions: **21 passed** (one existing Starlette/httpx
  deprecation warning).
- Real-engine `persistence_integration` selection: **22 skipped** because
  `PERSISTENCE_TEST_POSTGRES_DSN` and `PERSISTENCE_TEST_DYNAMODB_ENDPOINT` were
  absent; Docker is not installed in this environment.
- Focused Ruff: **passed**. Python bytecode compilation: **passed**.
- `infrastructure/phase10/validate_cloud_config.py`: **passed**.
- `make backend-build`: **passed**, building wheel and source distribution.
- `git diff --check`: **passed**.

The full Phase 10 verification matrix was not run.

## External verification gaps and risks

- No actual Firestore dataset/emulator inventory, real Postgres/DynamoDB migration,
  snapshot capture, final-delta freeze, account export parity or live Cloud Run
  run is proven by the synthetic migration tests. Docker Compose/local engine
  verification is unavailable in this environment.
- No live Neon TLS/pooler/vector check, AWS STS federation, deployed IAM
  evaluation, DynamoDB capacity/hot-key/GSI behavior, Google service-account
  claims, Cloud Run egress measurement, Neon/account allowance, or strict-$0
  account report was available here. The cloud smoke is unverified if skipped.
- The operator’s writer-freeze assertion cannot itself pause or prove all API,
  worker, callback, Pub/Sub, maintenance, cleanup, TTL and expiry writers. A
  final delta without the externally completed freeze is unsafe and must not be
  treated as ready. Firestore TTL/accounting and existing Phase 9 obligations
  remain separately open.
- Per-record target hashes prove payload parity for records the mapper accepts;
  they do not claim a cross-store atomic point-in-time snapshot or prove
  application-level export/deletion acceptance. Rejected data or conflicts block
  final readiness and need explicit disposition or source repair.
- P10.6 remains required for complete real-engine parity, application repository
  regressions, writer fencing, rollback/replay review, runtime cutover and
  Firestore retirement. Do not activate the cloud adapters or describe the new
  architecture as the production runtime before that review.

No deviation from the approved P10.0 store ownership or P10.1–P10.3 runtime
contracts is intended. Real account quotas, cross-cloud connectivity and
repository/API parity remain unverified release evidence, not implementation
defaults.

## P10.6 supersession addendum — 2026-10-06

P10.6 has since switched local runtime wiring to Neon/Postgres + DynamoDB and
removed the Firestore SDK, repositories, source-migration command, and
migration-only control schema. The user reports that Firestore was never
deployed; no cloud inventory or real migration was performed. This P10.4–P10.5
evidence remains historical for its synthetic migration and static cloud
checks. See the [P10.6 implementation evidence](phase-10-p10.6-implementation-evidence.md)
for current tests and open engine/cloud verification.
