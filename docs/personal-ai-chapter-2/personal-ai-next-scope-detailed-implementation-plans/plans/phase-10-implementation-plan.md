# Phase 10 implementation plan — Polyglot persistence foundation and Firestore migration

Status: P10.0–P10.5 implementation is recorded; Firestore remains the selected runtime database and P10.6 has not started. P10.4 synthetic migration/reconciliation and P10.5 static IAM/capacity checks pass. Real Firestore/target-engine runs, deployed cloud acceptance, Docker Compose execution and cutover remain unverified or open. Phases 3–9 are intentionally unused in this renumbered chapter so Phase 10 is the explicit architectural boundary before the preserved former Phase 3 roadmap resumes at Phase 11.

P10.0 documentation decisions completed 2026-10-06 against repository revision `e17ebd76afd1feb90fe47d959c43ab23eb553499`. P10.1–P10.3 have a local implementation and targeted evidence; P10.4–P10.5 implementation now has targeted synthetic/static evidence. Firestore remains the selected runtime database. P10.6 is not started. See the [P10.1–P10.3 implementation evidence](../../phase-10-p10.1-p10.3-implementation-evidence.md) and [P10.4–P10.5 implementation evidence](../../phase-10-p10.4-p10.5-implementation-evidence.md). Real-engine migration, Docker Compose execution, deployed cloud acceptance and cutover remain unverified.

Read [ADR 0021](../../../decisions/0021-polyglot-persistence-foundation.md), the [storage ownership/access-pattern contract](../../phase-10-storage-ownership-and-access-patterns.md) and [migration/cutover/verification plan](../../phase-10-migration-cutover-and-verification-plan.md). These Phase 10-specific documents contain the exhaustive inventory, keys, constraints, minimal recovery protocol and release mechanics; this plan remains authoritative for scope.

This phase is additive infrastructure work. It must not delete or weaken any previously planned product, security, provenance, export/deletion, evaluation, provider, domain, or ChatGPT scope.

## Scope boundary

**Goal:** Replace Firestore as the normal durable application database with a deliberately split persistence model while preserving local-first development and strict-$0 operation:

- **DynamoDB** for high-volume operational/event state with stable key/range access patterns;
- **Neon Postgres + pgvector** for relational/query-rich knowledge, memory, provenance, control state, and vector retrieval;
- **GCS** remains the planned bulky immutable artifact tier introduced later in Phase 20;
- **local Postgres + pgvector and DynamoDB Local** provide cloud-independent day-to-day development and deterministic persistence integration tests.

This is a persistence migration, not a rewrite of chat, memory, research, decisions, domains, auth, routing, or provider behavior.

## Canonical ownership map

### DynamoDB — operational timeline state

Initial canonical ownership:

- conversations and conversation metadata;
- branchable messages and active-branch ordering;
- working summaries;
- persisted model/tool/runtime events where retained;
- request/idempotency records belonging to DynamoDB-owned aggregates, not all replay records;
- workflow/checkpoint/job state where append/key/range access patterns justify it, not all workflow events;
- memory-lifecycle execution jobs/checkpoints, while durable memory records themselves remain Postgres-owned.
- current account-wide request-window counters.

Use one initial runtime table with collision-safe scoped keys, strong base-table recent-conversation directories and one sparse job-publication GSI. No LSI or normal-path Scan is required. The access-pattern contract defines pagination, ordering, conditional writes, branch revisions, chunked summary provenance and byte bounds. Preserve current message IDs, parent/branch relationships, timestamps, owner/app/workspace scope, summary coverage, replay semantics, and safe foreign-ID behavior.

### Neon Postgres + pgvector — interpreted/query-rich state

Initial canonical ownership:

- bounded Personal-AI global profile/preferences;
- memories and embeddings;
- embedding-space metadata, memory source attribution, provenance, lifecycle/supersession/forgetting state;
- research sessions, evidence metadata, canonical entities/aliases/claims, and durable research results;
- decisions and proposal/evaluation metadata;
- AI-owned account/owner metadata that benefits from relational constraints;
- persisted application/provider/model registry metadata when later phases require durability;
- compact usage/quota aggregates, evaluation summaries, and artifact references introduced by later phases;
- any durable state whose normal access requires joins, ad-hoc filtering, aggregation, constraints, or vector + metadata retrieval.

Transaction-bound exceptions are explicit: research sessions/runs, embedded events/budget ledger and their request keys; lifecycle events/state/application receipts; domain lookup replay/results; account lifecycle/identity/audit; daily usage budgets and provider-wide throttling remain Postgres-owned. Execution jobs are DynamoDB-owned; effect receipts are Postgres-owned. Future profile/registry/grant/evaluation/artifact assignments do not authorize their implementation in Phase 10.

Use ordinary versioned schema migrations and `pgvector`. Stable semantics should use typed columns/relations; evolving provider/domain metadata may use bounded JSONB where appropriate. Never flatten authoritative domain-application data into Personal AI.

### GCS — bulky artifact bodies, later

Phase 20 remains responsible for the `ArtifactStore` and private GCS implementation for large traces, raw eval outputs, export bundles, replay/debug artifacts, and permitted retained research artifacts. Postgres holds compact queryable artifact metadata/reference. DynamoDB must not become a blob store.

## Cross-store invariants

- Every durable record class has exactly one canonical store.
- Cross-store references use stable opaque IDs and preserve owner/application/workspace scope.
- There is no distributed transaction across DynamoDB, Postgres, and GCS.
- Cross-store projections/retries are idempotent and recoverable.
- Preserve existing atomic source/job validation for memory writes with the narrow guard/receipt protocol in the storage contract. Receipt arbitration and effects share a Postgres transaction; an unknown effect cannot be released merely because a guard expired or a receipt read returned absent.
- Keep single-store transaction groups within their canonical store; no generic saga/outbox or mirrored job authority.
- Export original embedding values and declare per-store snapshot/revision coverage; neither precision loss nor an unsupported distributed snapshot is acceptable.
- Do not introduce a permanent dual-write architecture.
- Do not mirror entire authoritative records merely for convenience.
- Account export/deletion inventory must cover every canonical store.
- Firestore is a migration source and bounded rollback source only after cutover; it is not a third long-term canonical store.

## Normative commitments

1. Preserve completed Phases 0–2 and all current externally visible behavior while introducing persistence contracts beneath existing services/repositories.
2. Define and document the canonical storage owner for every current Firestore record family before moving data.
3. Supersede the Firestore-native persistence ADR for future writes while retaining the old ADR as historical evidence.
4. Add local Postgres + pgvector and official DynamoDB Local development/test services.
5. Add versioned Postgres schema migrations and a repeatable DynamoDB schema/bootstrap path.
6. Implement Postgres repositories for knowledge/query-rich state and DynamoDB repositories for operational timeline state behind backend-neutral interfaces.
7. Preserve owner/application/workspace isolation, stable IDs, timestamps, branch lineage, source/provenance, vector model/dimension metadata, lifecycle state, replay/idempotency, and export/deletion semantics.
8. Provide an idempotent Firestore migration/backfill tool with dry-run, bounded batches, reconciliation, restartability, and explicit rejection reporting.
9. Validate local and cloud targets independently; DynamoDB Local does not establish production throttling/hot-partition behavior.
10. Perform a bounded cutover and retain Firestore only for an explicit rollback/verification window; then remove normal runtime Firestore dependencies and obsolete indexes.
11. Keep compute primarily on GCP; introduce only the AWS surface required for DynamoDB in this phase.
12. Treat Neon, DynamoDB, cross-cloud network use, credentials, and existing GCP resources as strict-$0 resources with explicit verification/observability rather than hard-coded quota assumptions.

## Explicitly out of scope

- moving Cloud Run compute to AWS;
- adding Lambda, API Gateway, SQS, SNS, EventBridge, Step Functions, Cognito, or ECS merely because DynamoDB is present;
- DynamoDB Streams in the first migration cut;
- DynamoDB vector search;
- replacing GCS with another object store;
- changing inference providers or routing policy;
- changing memory extraction semantics;
- redesigning domain integrations;
- long-lived Firestore/DynamoDB/Postgres dual writes;
- aggressive single-table DynamoDB modeling beyond demonstrated access patterns.

## Current state and reuse

The repository already has persistence seams that should be extended rather than bypassed, including storage repositories/fakes/async transaction helpers, memory repositories/lifecycle repositories, research repositories, decision storage, domain repositories, and account/owner inventory code. Existing Firestore-focused tests establish behavior to preserve; convert the reusable behavior into backend-neutral repository contract tests plus implementation-specific integration tests rather than discarding them.

Completed next-scope Phases 1–2 already provide application/workspace scope and the application registry/manifest boundary. Phase 10 must preserve those scopes in every new key/schema and migration path.

## Prerequisites and work ordering

Required phases: 1 and 2, both already completed at the chapter handoff revision. Work packages run in order and Phase 10 becomes a hard prerequisite for Phase 11 onward wherever persistence is consumed.

## Work packages

### P10.0 — Storage decision record and access-pattern ownership map

Inventory every current Firestore collection/repository and every planned durable record family referenced by later phases. For each record class, document canonical target, required reads/writes, consistency/idempotency requirements, expected cardinality/growth, indexes/vector needs, export/deletion obligations, retention, and cross-store references.

Create a polyglot-persistence ADR that supersedes the old Firestore-native ADR for future writes without rewriting historical truth. Confirm at minimum:

- DynamoDB owns conversation/message/summary/runtime timeline state;
- Postgres owns global profile, memory/vector/provenance and query-rich knowledge state;
- Postgres owns compact artifact metadata once Phase 20 exists while GCS owns artifact bodies;
- workflow/runtime state moves to DynamoDB only where key/range access patterns justify it;
- no authoritative domain-app state is copied into either database.

**Acceptance:** all 34 current literal Firestore collections, embedded aggregate records and planned durable families have one canonical target. Required reads/writes, scope, growth/retention, indexes, references, export/deletion and transaction exceptions are specified. ADR, access-pattern and migration contracts resolve cross-store correctness and storage/compute tradeoffs without implementing P10.1+ or rewriting historical evidence.

### P10.1 — Local persistence stack

Add a reproducible local stack following existing Docker/Make conventions:

- Postgres with `pgvector` enabled;
- official DynamoDB Local;
- persistent volumes for ordinary development;
- disposable/isolated databases/tables for integration tests;
- deterministic bootstrap, health checks, cleanup, and documented commands.

Local development must require neither AWS nor Neon credentials. Unit tests may still use fakes, but persistence contract/integration tests should exercise real local Postgres/DynamoDB semantics. Do not substitute SQLite or an in-memory relational model for DynamoDB access-pattern tests.

**Acceptance:** one documented local workflow starts both stores and persistence integration tests run with no cloud account access.

### P10.2 — Postgres schema, migrations, repositories, and pgvector

Introduce an async-compatible Postgres connection/session boundary underneath repository interfaces plus explicit versioned migrations. Migrate existing query-rich state assigned in P10.0: memories, vector metadata, provenance/lifecycle/receipts, research/evidence/entity/claim state and replay groups, decisions/domain results, account/control metadata and safeguards. Use typed scoped relations, null-safe workspace identity, constraints and named indexes; bounded JSONB holds evolving snapshots. Preserve existing same-store atomic groups. Global profile creation belongs to Phase 11; other future categories remain assigned ownership rather than new CRUD scope here.

Vector invariants:

- persist embedding provider/model/dimensions/normalization/task-space metadata;
- build/search only compatible pgvector spaces;
- reject incompatible vector spaces rather than silently mixing them;
- preserve lifecycle/source/scope filters before or alongside semantic ranking;
- preserve existing source attribution and v1/v2 logical compatibility through migration;
- keep deterministic fake/non-vector paths for offline tests where already required.
- store one lossless `double precision[]` embedding, using a transient pgvector cast for compatible exact cosine search; no redundant persisted vector column or default ANN index;
- preserve current 2,048d compatibility and original-value reads/exports; verify float32 cast distance threshold/band/tie parity against original values, with bounded boundary reranking or existing advisory failure when parity cannot be established;
- measure table/TOAST bytes and query compute/latency; the storage saving is a CPU tradeoff, not proof of Neon free-plan fit. Detailed numeric/index decisions live in the storage contract.

**Acceptance:** backend-neutral repository contracts pass against local Postgres; existing memory/research/decision semantics remain equivalent; vector incompatibility is explicit.

### P10.3 — DynamoDB runtime schema and repositories

Enumerate named access patterns before creating tables/indexes. At minimum support:

- get conversation metadata;
- append/read active-branch messages in deterministic order;
- list recent conversations by owner/application/workspace;
- persist/read working summary and branch lineage;
- conditional/idempotent writes for replay-sensitive operations;
- runtime/checkpoint lookup for record classes assigned to DynamoDB.

Prefer one initial runtime table if it satisfies reviewed access patterns without opaque overloading. Keep GSIs sparse and justified by named reads. Avoid `Scan` in normal request paths. Use the official AWS SDK below repository boundaries; if it is synchronous, reuse bounded async/offload patterns rather than blocking the FastAPI event loop.

Implement the reviewed strong directories, paginated revision-stable branch reads, bounded root cuts and manifest/chunk publication for summary coverage. The sole initial GSI is eventual job publication, with strong canonical rereads/claims; required recovery/export uses base keys. Preserve account-wide counter scope. Implement the minimal memory source/job guard protocol together with P10.2 receipts and test apply/abort/late-worker races; preparation-token expiry alone is insufficient for an in-doubt knowledge effect.

Production capacity configuration must be strict-$0-compatible and verified at deployment time; current provider allowance numbers must not become business-logic constants.

**Acceptance:** repository contract tests pass against DynamoDB Local; normal chat/list/branch paths use designed key/query/conditional operations and preserve current branch/replay semantics.

### P10.4 — Firestore backfill and parity verification

Build an idempotent migration command/script with:

- dry-run source inventory and target mapping;
- bounded/paginated source reads;
- stable source-to-target IDs;
- owner/application/workspace preservation;
- timestamp/branch-parent/summary preservation;
- memory embedding/profile/provenance preservation;
- resumable checkpoints outside the records being mutated;
- per-record validation/rejection reporting;
- count/hash/sample reconciliation;
- safe reruns without duplicate semantic records.

Do not add a permanent live dual-write path. Prefer a bounded personal-system cutover: backfill while Firestore is canonical, pause writes briefly, apply final delta/reconciliation, switch configured repositories, then resume writes.

Follow the Phase 10 migration contract: migration epoch and source update versions/hashes; checkpoint acknowledgement after target commit; logical rather than physical counts; complete final existence/version manifest covering deletes and embedded changes. Inventory global/shared/ownerless records and attribute active hashed counters explicitly. Keep storage migration separate from legacy owner reassignment. Freeze every API/callback/worker/maintenance/cleanup/TTL writer, not only new chat requests.

**Acceptance:** a synthetic/full migration can be rerun safely and produces repository-visible parity across all mapped record families.

### P10.5 — Cloud adapters, IAM, cross-cloud networking, and strict-$0 deployment

Add cloud configuration for Neon Postgres and AWS DynamoDB while retaining GCP Cloud Run as the compute home. Provide least-privilege AWS authorization limited to required DynamoDB resources/actions. Prefer short-lived/federated AWS authentication from GCP where practical; if a dedicated static credential is temporarily necessary, keep it least-privilege in Secret Manager with explicit rotation/revocation and a migration path away from it.

Add release-time checks/observability for current Neon storage/compute/connection behavior, DynamoDB capacity/storage/index configuration, GCP-to-external network use, and existing Cloud Run/GCS/Artifact Registry/Secret Manager resources. These are operational facts, not constants in application logic.

Review fixed provisioned Standard table/GSI capacity against actual account/region allocations; on-demand/autoscaling and paid extras are not implicit free paths. Bound pooled connections across API/worker instance maxima, use separate migration privileges, verify service-account federation and cross-cloud TLS, and budget migration/recovery/directory/index/embedding amplification and network use. Unknown eligibility blocks activation; alerts alone do not cap spending. Detailed release gates belong in the Phase 10 verification plan.

**Acceptance:** opt-in cloud smoke tests prove CRUD/query/vector paths against Neon and AWS without silently enabling an unreviewed paid path.

### P10.6 — Cutover, rollback window, Firestore retirement, and documentation closeout

Before cutover, run repository/evaluation regressions, reconcile source/target invariants, verify account export/deletion inventory, verify no cross-owner/app/workspace leakage, and validate Cloud Run/strict-$0 configuration.

Cut over with a short write freeze/final delta rather than indefinite dual writes. Keep Firestore data/read access only for a bounded rollback/verification window. A rollback after new writes must include an explicit replay/export plan; do not describe a config flip that loses post-cutover writes as lossless.

Cut over all API, worker, auth/safeguard, provider-throttling, maintenance and cleanup factories as one compatible bundle; fence old revisions/consumers. Reverse replay must cover cuts, knowledge effects, jobs/replay, audit, counters and deletion/tombstones, or use forward repair. Retirement requires no normal Firestore constructor/import/settings dependency or fallback, reconciled source dispositions and explicit legacy access/window policy. Open Phase 9 physical deletion, full owner migration, accounting and release obligations remain independent.

After acceptance:

- remove Firestore from normal repository wiring;
- remove obsolete Firestore vector/composite indexes and emulator/deployment assumptions that are no longer needed;
- remove paid TTL assumptions incompatible with strict-$0 operation;
- retain migration/export tooling and historical ADR/evidence as appropriate;
- update living architecture/deployment/project docs to describe Firestore as retired legacy storage rather than current architecture.

**Acceptance:** normal local/cloud runtime has no Firestore dependency, regression suites pass on the new stores, and rollback/recovery status is explicit.

## Requirement coverage

| Requirement | Work packages |
| --- | --- |
| R10.1: Define one canonical store per durable record class and supersede future Firestore architecture. | P10.0 |
| R10.2: Support cloud-independent local Postgres/pgvector and DynamoDB Local. | P10.1 |
| R10.3: Migrate query-rich/vector knowledge state to Postgres/pgvector. | P10.2 |
| R10.4: Migrate operational timeline state to DynamoDB using access-pattern-first design. | P10.3 |
| R10.5: Provide idempotent/reconcilable Firestore migration. | P10.4 |
| R10.6: Support strict-$0 Neon/AWS deployment while compute remains primarily GCP. | P10.5 |
| R10.7: Perform bounded cutover and retire Firestore from normal runtime. | P10.6 |
| R10.8: Preserve all prior product/security/provenance/export/deletion scope. | P10.0–P10.6 |

## README maintenance — required in this phase

The repository-root `README.md` is a required closeout artifact because this phase changes the implemented architecture and technology stack. Update it **after the migration/cutover is actually implemented**, not merely because this plan exists.

Keep the README high-level and factual. At minimum, reconcile:

- the architecture diagram so Firestore is no longer shown as the primary durable store;
- the repository-layout storage description;
- the tech stack to include Neon/Postgres + pgvector and AWS DynamoDB while retaining GCP Cloud Run/Pub/Sub/Secret Manager and any actually implemented GCS usage;
- local prerequisites/setup to use local Postgres + pgvector and DynamoDB Local instead of the Firestore emulator as the normal persistence path;
- cloud deployment topology/prerequisites and cross-cloud credential expectations;
- cost/free-tier notes so strict-$0 monitoring includes Neon, DynamoDB and network use;
- any Firestore references that would incorrectly describe the current runtime after cutover.

Do **not** put migration scripts, table schemas, low-level key design, or other implementation mechanics in the README. Historical ADRs/evidence remain historical rather than being rewritten to imply the new architecture existed earlier.

## Downstream-plan effects

Phase 11+ consumes this phase as a standing storage foundation. Specifically:

- Phase 11 global profile is created on Postgres; conversation/summary wrappers use DynamoDB; memory/evidence wrappers use Postgres.
- Phase 16 vector persistence/retrieval uses Postgres/pgvector while preserving embedding-space compatibility.
- Phase 19 compact quota/usage aggregates use Postgres; retained high-volume runtime invocation events may remain DynamoDB-owned when justified.
- Phase 20 artifact bodies use GCS and compact artifact references use Postgres; it must not restore Firestore or a “no DynamoDB” constraint.
- Phase 22 retained evaluation raw outputs use GCS and queryable summaries use Postgres.
- Phase 34 memory retrieval optimization benchmarks Postgres/pgvector rather than Firestore vector search.
- Phase 36 hardening evaluates DynamoDB + Postgres + GCS, cross-cloud failures, account export/deletion across stores, and absence of runtime Firestore dependencies.

## Targeted verification and closeout

Required local/offline checks include unit/lint suites, repository contract tests against fakes, Postgres integration tests, DynamoDB Local integration tests, migration dry-run/restart/idempotency tests, cross-store provenance/reference tests, account export/deletion inventory tests, vector compatibility/index tests, and whitespace/link validation.

External opt-in checks include Neon connectivity/migrations/vector queries, AWS DynamoDB IAM/table/GSI/conditional-write behavior, production capacity/throttle behavior not reproduced by DynamoDB Local, Cloud Run-to-Neon/AWS connectivity, safe Firestore-source migration against a controlled snapshot, and strict-$0 account/resource configuration. Skipped external checks remain **unverified**, not passed.

Phase 10 is complete only when the local stack is reproducible, cloud implementations satisfy repository contracts in opt-in smoke tests, migration is repeatable/reconciled, normal runtime no longer depends on Firestore, README/living docs accurately describe the implemented architecture, and no previously planned product scope has been removed.
