# Phase 10 migration, cutover and verification plan

Status: normative migration/cutover contract, reviewed 2026-10-06 against
repository revision `e17ebd76afd1feb90fe47d959c43ab23eb553499`. P10.6 runtime
cutover and code retirement are implemented locally. The user reports that
Firestore was never deployed and no records exist; no cloud inventory or data
migration was performed. Docker Compose/target-engine execution, cloud
connectivity, and strict-$0 eligibility remain unverified. See the
[P10.6 implementation evidence](phase-10-p10.6-implementation-evidence.md).

Read the authoritative [Phase 10 plan](personal-ai-next-scope-detailed-implementation-plans/plans/phase-10-implementation-plan.md),
[ADR 0021](../decisions/0021-polyglot-persistence-foundation.md) and
[ownership/access-pattern contract](phase-10-storage-ownership-and-access-patterns.md).
This document remains the normative acceptance contract. The P10.4–P10.5
operator guide is retained as historical evidence of synthetic migration
tooling; P10.6 removed those commands for the no-source path.

## Migration contract

When an actual Firestore source exists, Firestore remains canonical during
backfill. Targets are migration-only until cutover; there is no permanent live
dual write or normal-request source fallback. Each logical family has exactly
one target from the ownership inventory. The no-source branch skips data
backfill and removes its operator code, as recorded in P10.6 evidence.
Record migration version, source project/database, source schema/scope versions,
target schema/key/extension versions, configuration, revision and safe counts.
No credentials or private bodies enter reports/fixtures.

### Source classification

- Enumerate all 34 collection names and embedded records, global/shared controls,
  ownerless children, legacy scope envelopes, operational counters and active jobs.
  Do not equate `OWNER_DATA_COLLECTIONS` with a complete source inventory.
- Preserve logical IDs, timestamps, content, branch links, embedding values,
  fingerprints, expiry, lifecycle state, request keys and immutable policy versions.
  Record source document IDs separately when different from logical IDs.
- Legacy absent scope means standalone/null only under the established contract.
  Preserve embedded v1 child envelopes; normalize queryable target scope without
  rewriting the historical logical payload or deterministic identity formulas.
- Resolve ownerless candidate evaluations via decisions and domain claim extensions
  via claims. Validate parent owner/scope; orphan/conflicting rows are rejections,
  not silently omitted data. Shared `*` entities/aliases remain explicitly shared.
  Domain registrations/provider-wide limits remain global control metadata.
- Request-window owner hashes and usage owner/day hashes require verified
  deterministic attribution against known source owner/window metadata. Do not
  reset/drop unresolved active counters; reject/block or record an explicit
  operator-reviewed expired-record disposition with counts.
- Do not combine persistence migration with `local`→OIDC owner reassignment.
  [The existing owner migration](../../backend/scripts/migrate_local_owner.py)
  deliberately supports only chat. Full owner-derived/nested-key migration remains
  open under the original Phase 9 obligation; no generic owner rewrite is safe.

### Idempotent backfill

1. Dry-run complete source inventory, mapping, reference validation and anticipated
   target item/row sizes, with explicit rejection categories and no target writes.
2. Bootstrap pinned target schemas/keys; establish a migration epoch preventing
   runtime writes or competing migration configuration from altering targets.
3. Load owner/control/reference foundations and D conversations/messages/summaries;
   load P parent knowledge/research/entity records before dependent relationships.
4. Load P lifecycle/derived sources, session/run replay groups, decision/domain
   children and capability results. Preserve their atomic target transaction groups.
   Load D jobs and account safeguards before enabling corresponding consumers.
5. Build minimal D directories/locators and summary manifests/chunks from canonical
   records; validate all cross-store references before making migrated groups usable.
6. Reconcile counts/hashes/samples and repository-visible behavior; rerun safely.

Use bounded/paginated source reads, target batches, deadlines and explicit retry
classification. Checkpoints live in a dedicated P migration-control area outside
business records, including migration/source/config identity, per-family cursor,
source update time/version/hash, target disposition and rejection counts. A retry
after target commit but before checkpoint acknowledgement resolves the same
logical identity/hash. Same-hash writes are no-ops; conflict is explicit. A changed
source version may replace only the prior migration-owned target version using
conditions; never overwrite unrelated target divergence. Strict DTOs receive no
unrecognized migration fields. No ordinary backfill mutates source records.

### Reconciliation

Compare logical records, not physical row/item totals: relational children,
locators, directories, receipts and chunks amplify physical counts. Each family
has source count, migrated count, explicit rejected/disposed count and digest;
counts must close without an unexplained gap. Normalize native/ISO timestamps to
UTC instants consistently, while preserving source values and intentional absent
versus explicit envelope semantics. Lossless embeddings hash/round-trip original
values; separately test pgvector numeric distance parity.

Full logical hashes include embedded evidence/run history, branch links/cuts,
summary coverage, source/lifecycle refs, replay fingerprints, policy versions,
scope and expiry. Sample repository/API views, ordered active history, summary
eligibility, memory eligibility, replay outcomes and portable exports. Detect
cycles, missing parents, cross-scope refs, unmatched jobs/receipts, duplicate
semantic identities and invalid vector spaces. Reject/quarantine reports remain
safe; a quarantine is not acceptance or a hidden alternate canonical store.

## Source disposition and runtime cutover

First determine which branch applies:

- **Source exists:** use the full inventory, backfill, final-delta and bounded
  cutover protocol below. A no-source assertion does not override an actual
  deployed database, emulator dataset, backup/export, or other Firestore source.
- **No source/data:** record the operator disposition, date, basis, checked
  deployment/configuration surfaces, and any surfaces that could not be checked.
  The user reports that Firestore was never deployed; this report is context, not
  independent cloud-account evidence. In this branch, do not run an empty live
  backfill, final delta, data rollback window, or source teardown. Preserve
  synthetic migration results in historical evidence, then remove the
  Firestore source reader/command and migration-only schema/code if no future
  import use case is retained.

At the time this plan was written, both branches required a runtime cutover from
Firestore to Postgres/DynamoDB. P10.6 has implemented that local code/runtime
switch and fenced old construction paths. Complete target-store parity and
isolation checks against the final tree and record the recovery path before
release activation. A no-source data disposition does not establish cloud
connectivity or strict-$0 eligibility.

### If a Firestore source exists

Choose and record the operator, write-freeze budget and rollback-window duration
before cloud cutover; repository plans cannot infer them from a live account.

1. Prevent new mutations/dispatch and drain API streams/preparation/post-terminal
   callbacks, worker effects and bounded offloaded writes. Pause Pub/Sub delivery
   or fence old consumers, republish/maintenance, expiry and cleanup writers.
2. Resolve in-flight/unknown cross-store effects and abandoned source streams
   using their original identities, or keep affected capabilities unavailable.
   A client disconnect is not evidence that a worker/provider never ran.
3. Freeze/account for source TTL deletions and cleanup. Remove the paid Firestore
   TTL requirement before claiming strict-$0; old deploy scripts must not recreate
   it. Source TTL can continue deleting even after API requests stop.
4. Re-enumerate a complete bounded source manifest using document update versions
   and existence. Detect inserts, updates, root cuts, embedded aggregate changes
   and deleted documents since backfill. Application `updated_at` alone misses
   these changes. Do not require DynamoDB Streams or a permanent dual-write feed.
5. Apply final changes/removals under the migration epoch, with source deletion
   dispositions and reference-safe ordering. Reconcile all family hashes/counts,
   scope/reference invariants and export coverage; block on unexplained differences.
6. Switch compatible API/worker/safeguard/maintenance/cleanup repository wiring as
   one release bundle. Old Cloud Run revisions/consumers cannot resume source
   writes. Verify auth, conditional writes, capacity and safe readiness separately
   from model/provider smoke tests; then resume target writes.
7. Observe the explicit rollback window with target writes canonical and Firestore
   source access read-only. Record approved evidence and remaining gaps.

The bounded personal-system inventory may use operator migration scans; normal
request/export/maintenance paths use designed scoped keys/queries. Lack of a
complete source snapshot is a cutover blocker, not permission to silently skip
records. Pause acceptance if source volume cannot fit the reviewed freeze/budget.

## Rollback and Firestore retirement

Before target writes resume, a return to the unchanged frozen source can be
straightforward. After new writes, a config flip alone loses data. Freeze target
writers, export/replay all post-cutover mutations and reconcile before reverting:
messages/cuts/terminal states, knowledge effects, job/replay state, account audit,
counters, expiry/deletion/tombstones and policy refs. Reverse transformation must
represent target changes safely; where it cannot, supported recovery is forward
repair. Maintain compatible application/schema revisions and deletion-aware
restore requirements. A rollback plan is not proof of a tested restore.

For an actual source, retirement acceptance requires:

- complete reconciliation or explicit approved per-record dispositions;
- scoped repository/evaluation regressions and export/lifecycle inventory checks;
- verified opt-in cloud and strict-$0 gates required by Phase 10;
- no normal runtime Firestore constructor/import/settings dependency or fallback
  in API, worker, auth/safeguards, domain throttling, maintenance or cleanup;
- removal of obsolete runtime IAM grants, source provisioning/index/emulator/TTL
  and paid backup assumptions; explicit legacy-data/access/window disposition;
- legacy migration/export tooling isolated from normal runtime dependencies, if a source exists and the tool is retained;
- factual README/architecture/setup/deployment/runbook closeout and recovery status.

For a documented no-source disposition, replace source reconciliation and the
rollback-window requirements with recorded no-source evidence; do not report
them as completed migrations. Retirement still requires the full runtime
dependency removal, affected regressions, target-store recovery status, obsolete
Firestore setup/grant removal, and factual documentation closeout. This project's
re-scoped path removes the Firestore migration tool and migration-only control
schema because no legacy import source is expected; preserve this contract and
existing migration evidence as historical documentation.

Historical ADRs/evidence remain historical. Physical account deletion, full legacy
owner migration, complete provider accounting and operational release readiness
remain open under [Phase 9 evidence](../phase-9-implementation-evidence.md) until
independently closed. P10 validates cross-store inventory and does not fabricate
their completion. Later Phase 36 consumes, rather than replaces, those obligations.

## Implementation constraints by package

### P10.1–P10.3

- Pin local Postgres/pgvector and official DynamoDB Local images; persistent dev
  volumes, isolated disposable test databases/tables, deterministic migrations/
  bootstrap/health and explicit destructive cleanup. No SQLite substitute.
- Local endpoints use dummy local credentials and cannot fall through to cloud
  discovery; staging/production rejects local endpoints. Unit fakes stay independent.
- Extend protocols/factories beneath existing services. Remove concrete Firestore
  types and client inspection from dependency wiring/domain throttling/worker/
  cleanup paths when implementing their adapters; do not rewrite product behavior.
- Use bounded SDK/SQL deadlines, pools/offload and cancellation draining. No
  synchronous blocking of the FastAPI event loop or uncontrolled late writes.
- Implement narrow source-guard/receipt correctness together with P/D repositories;
  test branch cuts, live/expired leases, applied/abort races and duplicate recovery.
- Establish exact-search/lossless-array baseline, compatible spaces and metadata
  indexes. Test 2,048d exact search, stored-value round-trip and numeric boundaries;
  measure query work/bytes before claiming Neon budget fit. No new embedding model.

### P10.4–P10.5

- Freeze schema/key versions before repeatable migration; separate storage/owner
  migrations and separate privileged migration/bootstrap from runtime credentials.
- Use the same contracts locally/cloud. Retain Cloud Run/Pub/Sub/private Google
  user/service auth. AWS scope is DynamoDB plus required IAM/STS, not an AWS compute
  migration or new queue/stream/orchestration stack.
- Prefer service-account OIDC→AWS STS federation with exact subject/audience trust,
  tested Google `aud`/`azp` mapping and bounded refresh. Never send browser user/IAM
  tokens as AWS credentials. Temporary static credentials, if needed, are narrowly
  scoped Secret Manager secrets with explicit rotation/revocation/migration away.
- Runtime rights are required table/index CRUD/query/transaction actions only;
  bootstrap/DDL permissions are separate. Use authenticated TLS and verified endpoint
  configuration. No incidental paid NAT/peering/private endpoint resources.
- Bound connections across API/worker processes and instance maxima. Prefer
  transaction-safe pooled Neon runtime connections, direct migration/admin
  connections; no idle-keepalive probes that defeat scale-to-zero accidentally.
- Review fixed provisioned Standard DynamoDB table/GSI capacity against actual
  account/region allowance and existing allocations. Do not silently enable
  on-demand/autoscaling/PITR/backups/global tables/paid telemetry or other extras.
- Verify current Neon plan storage/compute/connection/transfer/overflow behavior,
  GCP external egress, AWS return traffic and supporting Cloud Run/Pub/Sub/GCS/
  Artifact Registry/Build/Secret Manager/Scheduler usage. Include migration,
  recovery, directory/index amplification and vector table/TOAST/index bytes.
- Allowance facts carry source/configuration/date/confidence, not hard-coded
  business constants. Unknown eligibility blocks activation; alerts are not caps.
  Operational resource evidence does not implement Phase 19's provider ledger.

### P10.6

- For a source-backed cutover, freeze every writer; in either branch, cut over the
  complete compatible runtime bundle.
- Run all affected existing repository/evaluation regressions, real local-engine
  contract tests, migration/recovery/final-delta tests and export/isolation checks.
- Verify live Neon/AWS/GCP paths separately; local DynamoDB ignores provisioned
  throughput and cannot prove throttling, hot keys, GSI lag, IAM or free-tier fit.
- Prove Firestore retirement and update README/living docs only to implemented
  facts. Keep optional gates off until their corresponding external review passes.
- Record revision/configuration/commands/results/skips and actual rollback status.
  Full Phase 10 completion requires its cloud acceptance; missing credentials
  never weaken offline tests or become evidence of passing cloud checks.

For the no-source branch, writer freeze/final delta/data rollback-window bullets
above apply only if a source is found. Record the evidence basis and limits for
the no-source disposition, still perform runtime cutover and parity checks, and
remove migration-only Firestore code when no legacy import is retained.

## Verification matrix — future acceptance, not execution evidence

| Surface | Deterministic/local checks | Separate opt-in checks |
| --- | --- | --- |
| Scope/repositories | Fakes plus local P/D contracts; direct IDs/list/null workspace/shared/legacy children; no cross-scope leakage | Neon/AWS contracts and live credentials/IAM |
| D branches/summaries | Immediate listings, revision changes across pages, root cuts/late terminal writes, token cleanup, oversized chunks/crash publication/replay | Real GSI propagation, conditional conflicts, capacity/throttle/hot-key behavior |
| P knowledge/research | Atomic run/session and effect/state commits; FK/replay constraints; v1/v2/expiry/source parity | Neon migrations/pooled connection/version behavior |
| Embeddings | Original-value round-trip, provider/task/dimension mismatch, 768d and 2,048d exact casts, numeric threshold/band/tie coverage; CPU/byte measurements | Neon extension/vector queries and plan resource fit; no provider calls for backfill |
| Cross-store recovery | Crash before/after P apply/D ack, applied-versus-abort receipt race, expired guard, stale worker, lease replacement and source edits | Cross-cloud timeout/outage/cancellation recovery |
| Migration | Dry-run/rerun/restart/checkpoint-loss, source updates/deletes, rejection/count/hash closure and complete scoped export when a source exists; otherwise a documented no-source disposition | Controlled Firestore snapshot and final delta only when a source exists |
| Account lifecycle | Full inventory, authorized export completeness/size/failure, tombstones/derived deps; preserve pending-operator deletion | Export fidelity, backup/deletion-aware restore remain independent obligations |
| Deployment/cost | Configuration rejects cloud fallback/unknown billing paths; bounded clients and defaults | Service federation, Cloud Run→Neon/AWS TLS, private IAM, account/region pricing/limits/network and recovery |

Use existing backend/frontend test/lint/typecheck/build and affected context,
memory, lifecycle, research, iterative, decision, domain, proposal/extraction
evaluations as appropriate. Add/document actual persistence/migration commands in
their implementing packages before claiming they ran. Dependency/build edits
require relevant package/image builds; deployment script edits require shell
syntax/fake-CLI checks. Finish with link/content/manifest review and
`git diff --check`. P10.0 requires only lightweight documentation validation.

External reference facts reviewed 2026-10-06 (reverify for release):
[DynamoDB Local differences](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.UsageNotes.html),
[AWS OIDC conditions](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_iam-condition-keys.html),
[DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/),
[Neon transaction pooling](https://neon.com/blog/survive-thousands-connections),
[Neon Free-plan change](https://neon.com/blog/neon-free-plan-1-gb-per-project).
No live account allowance or credential suitability is established by these links.

## Open external/operator gates

Only these facts cannot be resolved from repository plans: actual source records/
volumes/inconsistencies; target accounts/regions/allowances and network consumption;
live service federation claims/trust/refresh; write-freeze/rollback duration,
backup/restore policy and approved disposition of unresolved/legacy records.
They do not reopen canonical ownership, authorize silent loss, or block P10.0
documentation completion. P10.1+ remains a separate implementation authorization.
