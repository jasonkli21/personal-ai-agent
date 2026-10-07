# Phase 10 P10.6 implementation evidence

Date: 2026-10-06 (America/Los_Angeles)
Tested tree: P10.6 working tree based on the documentation-only commit
`3be8a33`; the final implementation commit contains this evidence and code.
Scope: P10.6 no-source runtime cutover and Firestore code retirement.

## Source disposition

The user reports that Firestore was never deployed and there is no Firestore
dataset. This is the basis for the no-source path; no GCP/AWS account inventory,
Firestore project/database check, export/backup search, or emulator-disk search
was performed. No empty backfill, final delta, data rollback window, source
teardown, or real data migration occurred. This evidence does not claim a
deployed cloud cutover.

## Implemented

- Replaced the normal persistence factory with a Postgres/DynamoDB composition.
  Local/test configuration uses explicit local Postgres and DynamoDB Local
  endpoints. Staging/production requires the P10 cloud-adapter flag, Neon
  transaction-pooler DSN, and federated AWS role/audience; there is no local or
  Firestore fallback. API and worker shutdown close shared clients.
- Removed Firestore adapters from chat, summaries, memory/lifecycle, research,
  decisions, domains, proposal/extraction, identity, safeguards, and account
  persistence. Provider-wide throttling now uses the Postgres adapter. Durable
  repository contracts and feature gates remain in place.
- Removed the Firestore migration reader/CLI and migration-only storage code,
  emulator settings, SDK dependency, root index manifest, Firestore tests, and
  deployment provisioning/IAM setup. Historical schema migrations 008–012
  remain unchanged; migration 013 drops their migration-control tables and
  source-only columns on a target schema upgrade.
- Updated `.env.example`, current setup/architecture/deployment docs, and
  operator notes. Historical ADRs and prior phase evidence remain historical;
  the P10.4–P10.5 evidence now has a supersession addendum.
- Added runtime-factory selection/close tests for local endpoints, deployed
  Neon/federated-Dynamo construction, cache reuse, and fail-closed environment
  configuration.

## Checks

- `make backend-test`: **564 passed, 24 skipped**. The skips were 21 local
  persistence-engine cases (explicit Postgres/DynamoDB test endpoints were not
  configured), one cloud smoke test (no reviewed cloud opt-in), and two manual
  provider checks.
- `make backend-lint`: **passed**.
- `make backend-build`: **passed**; source distribution and wheel built.
- `uv lock --check --offline --directory backend`: **passed**.
- `bash -n infrastructure/gcp/deploy.sh`: **passed**.
- `git diff --check`: **passed**.

Docker is unavailable on this host, so `make persistence-up`, `make
persistence-bootstrap`, and `make persistence-test` were not run. The skipped
tests do not establish Postgres/DynamoDB Local behavior.

## Remaining verification

- Run the local Postgres/pgvector + DynamoDB Local bootstrap and full persistence
  integration suite on a host with Docker.
- Verify the pre-provisioned Neon schema/transaction pooler, AWS OIDC-to-STS
  trust and DynamoDB table/GSIs from the intended Cloud Run identities.
- Complete staged API/worker persistence, auth, export, deletion, recovery,
  capacity/throttle, cross-cloud network, and strict-$0 checks before production
  use. Static tests and local DynamoDB cannot prove cloud IAM, provisioned
  throughput, GSI behavior, account allowances, or costs.
- If a Firestore deployment, backup, export, or emulator dataset is later found,
  stop before treating the no-source disposition as valid; restore the
  source-backed inventory/final-delta/cutover procedure before deleting or
  abandoning that source.

Phase 10 code/runtime retirement is implemented locally. Phase 10 release
acceptance remains open for local-engine and deployed-cloud verification. Phase
9 physical deletion, full owner migration, provider accounting, and operational
release gates also remain independently open.
