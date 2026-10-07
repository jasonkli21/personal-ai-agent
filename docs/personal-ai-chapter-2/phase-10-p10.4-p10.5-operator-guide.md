# Phase 10 P10.4–P10.5 operator guide

Status: implementation tooling exists; the commands below are not evidence that
the source inventory, target engines, cloud permissions, or strict-$0 fit have
been verified for a real account. See the [implementation evidence](phase-10-p10.4-p10.5-implementation-evidence.md).

## Local emulator rehearsal

Use local-only Postgres/pgvector, DynamoDB Local, and the Firestore emulator.
The source remains canonical and the normal runtime factory remains Firestore.
From the repository root, `make persistence-bootstrap` applies the current
Postgres migrations and creates the disposable DynamoDB Local table. Docker
Compose is required for that target.

Apply schema migrations explicitly when running services outside Compose:

```sh
cd backend
P10_SCHEMA_POSTGRES_DSN='postgresql://personal_ai:personal_ai_local_only@127.0.0.1:54329/personal_ai' \
  .venv/bin/python -m personal_ai.persistence.postgres_schema_cli --environment local
```

With the emulators running and the local table bootstrapped, first inventory
without target writes:

```sh
cd backend
APP_ENVIRONMENT=local \
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 \
P10_MIGRATION_POSTGRES_DSN='postgresql://personal_ai:personal_ai_local_only@127.0.0.1:54329/personal_ai' \
P10_MIGRATION_DYNAMODB_LOCAL_ENDPOINT='http://127.0.0.1:8000' \
  .venv/bin/python -m personal_ai.persistence.firestore_migration_cli \
    --source-project demo-personal-ai --epoch emulator-rehearsal --dry-run
```

Review the bounded JSON counts, byte estimates, and rejection categories. Then
remove `--dry-run` to write the local target. Keep the same epoch and target
schema/configuration for safe restart. `--batch-size` is bounded to 500 and
`--max-records` to 500,000 per invocation. A new completed scan gets a new
generation; an interrupted running family resumes from its acknowledged page
cursor. Target writes are idempotent by logical ID and hash.

Unattributed active rate-limit windows and unresolved usage-budget owners block
parity. An expired unattributed request counter is only recorded as disposed
when the operator explicitly passes `--review-expired-counters`; active state is
never silently reset. Source-family mapping and storage migration do not
reassign the legacy `local` owner.

## Final-delta readiness

The source scanner cannot freeze writers. Before a final-delta command, the
operator must externally stop and drain every Firestore writer: API and streaming
callbacks, workers and Pub/Sub delivery, preparation/terminal callbacks,
maintenance/republish/cleanup work, and TTL/expiry behavior. Resolve in-flight
effects and account for TTL deletions. The `--writers-frozen` option is an
operator assertion; it does not pause or inspect those systems.

After the freeze, run the same command with `--final-delta --writers-frozen`.
The migrator rescans all 34 families, compares mapped and read-back hashes,
records explicit source deletions, and deletes target records only when the
target still matches the last migration-owned hash. It returns
`final_delta_ready=true` only when all family scans complete with no rejected
records, target conflicts, or unexplained disposition counts. A false result
blocks readiness. A true result is migration evidence only: **it does not
switch repositories, resume writers, authorize P10.6, or retire Firestore**.

## Cloud configuration and permissions

The Cloud Run service account remains the compute identity. Bind Neon DSNs
through Secret Manager, with `sslmode=verify-full`; use the bounded Neon
transaction-pooler endpoint for a future runtime and a direct endpoint only for
the explicit schema/migration tools. `NeonRuntimeDatabase` caps its pool at four
connections with no prepared statements; direct schema/migration clients use a
pool of at most two. Set Cloud Run service and worker instance maxima so the
aggregate connection count is inside the reviewed Neon limit.

The Cloud Run service account obtains an ID token for the configured HTTPS
audience and exchanges it with AWS STS `AssumeRoleWithWebIdentity`. The AWS role
trust template pins the Google service-account subject and both AWS-mapped
audience claims (`aud` and `oaud`). The adapter rejects local credential files,
does not consult AWS key-chain credentials, uses TLS verification and refreshes
short-lived STS credentials. Do not put browser user tokens or static AWS keys
in the service. Runtime, storage-migration, and DynamoDB bootstrap policies are
separate; the storage-migration role has target DML and migration-control reads
but no DynamoDB DDL, and the schema administrator is separate from both Neon
application roles.

The DynamoDB CloudFormation template requires explicit provisioned Standard
table and `job-publication-v1` GSI capacities. It does not configure on-demand
capacity, autoscaling, PITR, backups, or global tables. Apply it only with the
separate bootstrap role and capacities reviewed against the current account and
region. The app creates no NAT, peering, private endpoint, AWS compute, queue, or
stream resources; Cloud Run connects to the public Neon and AWS service TLS
endpoints. The static template check does not establish real account quotas,
IAM propagation, network usage, or price eligibility.

For remote schema work, `P10_SCHEMA_POSTGRES_DSN` must be supplied to the
explicit schema command using a temporary schema-administrator credential. Run
the P10 strict-$0 report gate before any cloud schema or migration command. The
report must be current and reviewed, contain a high-confidence eligible claim
with a hard cap and projected charge of exactly zero for every required Neon,
DynamoDB table/GSI, Cloud Run, Firestore source reads/storage, Pub/Sub, GCS,
Artifact Registry, build, Secret Manager, Scheduler, external-egress, AWS
return-traffic, and migration/recovery resource, and list no unknown costs.
Missing, stale, over-capacity, or uncertain
evidence blocks the command. Do not copy example allowances into a report; use
current account/region/plan evidence.

The opt-in cloud smoke is a test against already provisioned resources only. It
requires `P10_CLOUD_SMOKE=1`, Cloud Run identity, an approval reference, a valid
strict-$0 report, and existing Neon/DynamoDB configuration. It does not create a
table. It checks Neon pgvector SQL plus DynamoDB conditional put, read, update,
primary-table and publication-GSI queries, and cleanup. Running it against real
services remains a separately reviewed, potentially billable use of existing
capacity even when the report passes. Never infer cloud success from the
emulator or fake-target tests.

## Explicit boundary

No command in this package wires the new stores into normal API, worker,
account-safeguard, maintenance, or cleanup startup. Do not change the root README
to describe DynamoDB/Neon as the active production runtime. The cutover, rollback
window, old-revision fencing, and Firestore retirement decisions remain P10.6.
