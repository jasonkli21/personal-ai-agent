# Phase 10 storage ownership and access-pattern contract

Status: P10.0 documentation decision, 2026-10-06. Reviewed code revision:
`e17ebd76afd1feb90fe47d959c43ab23eb553499`. P10.6 code cutover is implemented
locally; no source migration ran because the user reports there was no deployed
Firestore dataset. Target-engine/cloud acceptance remains unverified.

The [Phase 10 plan](personal-ai-next-scope-detailed-implementation-plans/plans/phase-10-implementation-plan.md)
owns scope. [ADR 0021](../decisions/0021-polyglot-persistence-foundation.md) records
the decision. This document fixes ownership, access patterns and correctness
boundaries without implementing later profile/provider/grant/artifact features.

## Repository basis and inventory conventions

Inventory covers all 34 literal collection names in `backend/src/personal_ai`,
not just [the owner inventory](../../backend/src/personal_ai/auth/owner_data.py).
Repositories also contain embedded records: these follow their aggregate unless
a separate family below owns them. No live source contents/counts were inspected.

The inventory reflects the pre-cutover implementation reviewed at
`e17ebd76afd1feb90fe47d959c43ab23eb553499`; the Firestore adapter files from
that revision were removed in P10.6. The current Postgres and DynamoDB
implementations live under `backend/src/personal_ai/persistence/`. This
inventory describes required behavior and access patterns, not a claim that a
deployed Firestore dataset was inspected.

Table shorthand: D = DynamoDB, P = Postgres; scope = authenticated owner,
application and nullable workspace unless marked account-wide/global. "Retain"
means preserve current history/eligibility and export/deletion obligations; it
does not invent indefinite retention or claim physical cleanup is implemented.
Live inventory must measure actual records/bytes rather than extrapolate quotas.

## Current collection ownership — exhaustive

| Firestore family | Target | Required reads/writes and consistency/index boundary | Growth, retention and references |
| --- | --- | --- | --- |
| `conversations` | D | Scoped get/recent list/create/touch; revision/token-conditioned mutations; strong directory | One per conversation; retain; parent of messages/summaries and P memory sources |
| `messages` | D | Scoped ID/history/active branch; atomic preparation/root cut/terminal transition; timestamp + ID order | Per turn/replacement; retain superseded records and parent/supersedes links |
| `conversation_summaries` | D | Append/newest compatible; ordered prefix query, hash-valid manifest/chunks | Per refresh, coverage grows with history; retain source/coverage IDs, fingerprints and model |
| `memory_lifecycle_jobs` | D | Create/replay/get/claim/fail/complete/republish; live token/generation conditions; sparse publication GSI | Bounded candidate sets/attempts, per job; retain replay/recovery policy; references P memory/effect IDs |
| `rate_limit_windows` | D | Account-wide owner/window get + conditional increment; no app-split counter | Per owner/minute; existing expiry eligibility, bounded cleanup; legacy owner attribution requires validation |
| `memories` | P | Scoped get/compatible cosine search/idempotent create; source guard + unique identity | Per accepted extraction; retain; D conversation/turn/user-source IDs; embedding space |
| `derived_memories` | P | Scoped get/search/create with original-source/lifecycle validation | Per accepted derivation; retain; 2–4 original memories, exact excerpts/fingerprints |
| `derived_memory_sources` | P | Dependencies by original/derived ID; atomic relation creation; scoped FKs/indexes | Per derivation source; retain; no dangling or cross-scope relation |
| `memory_lifecycle_states` | P | Get/version-conditioned update/rebuild; atomic with lifecycle event | One projection per memory; rebuildable; not authoritative independent of events |
| `memory_lifecycle_events` | P | Append/replay/by-memory ordered history; unique idempotency and expected version | Per applied/retrieval event; retain audit; links memory/related IDs and D job/assistant |
| `memory_lifecycle_operations` | P | Applied-effect receipt lookup/create atomically with derivation/events/state | Per effect, preserve operation keys; extend narrow receipt contract for applied/aborted recovery |
| `research_sessions` | P | Create/get/claim/save/expire; revision fence and atomic child provenance | Per bounded session; embedded queries/attempts/observations/evidence/selection/citations; expiry excludes, not blanket deletion |
| `research_request_keys` | P | Scoped request replay/fingerprint conflict; atomic with session | Per request; preserve mapping identity and session lifetime/replay policy |
| `iterative_research_runs` | P | Get/claim/commit/cancel/recover; atomic run/session revision/lease changes | Per bounded run; events, iterations, assessments and budget ledger stay P-owned |
| `iterative_research_request_keys` | P | Scoped request replay; atomic run creation/session validation | Per request; immutable fingerprint and run reference |
| `canonical_entities` | P | Owner or explicit shared active/type/ID lookup; bounded indexed queries | Per canonical research entity; preserve shared marker/identity versions; no domain authority |
| `entity_aliases` | P | Entity/normalized alias lookup; immutable create with validated entity scope | Per alias; shared/owner rules preserved; source evidence refs |
| `entity_claims` | P | Entity/attribute/evidence lookup; immutable attributed create | Per observation; freshness/conflict remains explicit; entity/evidence relationships |
| `entity_matches` | P | Immutable decision-associated resolution reads/writes | Per resolution; retain candidate IDs/policy/evidence and review outcome |
| `decision_snapshots` | P | Immutable create/detail with child records in one transaction | Per decision; preserve frozen constraints/ranking/policies and evidence snapshot |
| `decision_evidence_snapshots` | P | Immutable source attribution snapshot create/detail | Per decision; intentional historical snapshot, not a mutable evidence mirror |
| `candidate_evaluations` | P | By decision/entity; atomic decision writes; scoped FK via validated parent | Per bounded candidate; legacy ownerless rows derive scope from decision |
| `domain_registrations` | P | Global versioned module metadata lookup/insert; unique module/policy versions | Small/versioned, no private owner; preserve bounded module schemas and enablement gates |
| `domain_claim_extensions` | P | Claim/domain lookup/immutable create; validated claim-parent scope | Per claim extension; legacy ownerless rows derive owner from claim; exact evidence refs |
| `provider_observations` | P | Scoped observation ID/attribution/freshness lookup and insert | Per bounded observation; preserve source rights/expiry; no raw provider response storage |
| `domain_comparison_views` | P | Scoped detail/create; immutable result and atomic lookup completion | Per comparison; preserve candidate order, rows, source/policy refs |
| `domain_lookup_idempotency` | P | Reserve/get/fenced complete/failure/uncertainty; transaction with result | Per lookup; original key/fingerprint, unknown outcomes remain fenced |
| `itinerary_proposals` | P | Begin/replay/detail/conditional complete in one result aggregate | Per proposal; result at most 24h and evidence-bounded, replay at most 48h; P research refs |
| `booking_document_extractions` | P | Begin/replay/detail/complete/delete/delete-by-key/expiry cleanup | Per extraction; result at most 7d, preserve existing tombstone/replay contract; never raw input |
| `identity_mappings` | P | Principal check/bootstrap/deactivate/active owners; unique issuer/subject and bootstrap audit transaction | Per identity; account-wide, preserve owner IDs/status; never tokens |
| `account_lifecycle_requests` | P | Scoped request/get/confirm/cancel with atomic audit/replay | Per account action; standalone lifecycle restriction stays; confirmed deletion still pending operator |
| `audit_events` | P | Append/replay/scoped export, transaction with P control changes | Per bounded control action; distinguish account-wide and explicitly scoped events; safe metadata only |
| `usage_budgets` | P | Account-wide owner/day conditional reserve; atomic compact counter | Per owner/day; current 90d expiry field/policy preserved, no actual settlement fabricated |
| `domain_provider_rate_limits` | P | Provider-wide serialized slot reserve; bounded deadline | One compact shared control per provider; not per-owner/application; no private domain state |

Every private family participates in authorized export/deletion inventory,
including dependencies, operational counters, receipts and projections. Global
module/provider controls are inventoried separately, not deleted as private owner
data. Shared public entities/aliases retain their explicit shared classification
and existing app/workspace restrictions. Deleting an owner must not remove
unrelated shared records. Parent-resolved children must be attributed before
migration/export; absence of `owner_id` is not proof that a row is global.

## Future families — assignment does not implement them

| Durable family | Canonical target and scope |
| --- | --- |
| Bounded global profile/preferences/user-set provenance | P, owner-wide with permitted field sharing; Phase 11 creates the provider |
| Persisted app/provider/model registry versions | P; preserve current code-defined Phase 2 manifests; no new registry product now |
| Permission/grant/revocation metadata | P; versioned source/destination scope/purpose, Phase 15/30 contracts |
| Invocation reservations/settlements/quota/health/cooldown | P; account/provider buckets distinct from attributable owner/app usage, Phase 19 |
| Retained runtime/model/tool/invocation events | D; scoped aggregate/sequence access, bounded safe metadata and retention |
| Compact actual-build turn/context manifests and producing-model attribution | D; references immutable P policy/registry/grant versions, Phases 14/21 |
| External-turn preparation/finalization/replay | D; same conversation/branch contract, Phase 25.2 |
| Knowledge application receipts for cross-store effects | P; same transaction as canonical effects, not D execution state |
| Mutation proposals/confirmation/evaluation/result reconciliation | P; domain actions/state remain authoritative externally, Phase 31 |
| Evaluation summaries/quality profiles/experiment metadata | P; versioned configuration/coverage, Phases 22/33/35 |
| Compact artifact metadata/reference/lifecycle | P; object generation/hash/status, Phase 20 |
| Bulky permitted traces/raw eval/export/replay artifacts | GCS; Phase 20 bodies only, no database blob or shadow database |
| Safe managed ChatGPT connection/policy metadata | P when required; turn attribution remains D, usage trust provenance preserved |
| ChatGPT reusable credentials/protected local bridge registration | Protected user-controlled local storage only, Phase 25.1; never managed persistence |

Persistent caches or new workflow families need an explicit assignment under this
contract before introduction. Do not add them merely because keys can support
them. Domain trip/booking/purchase/portfolio/health truth is never migrated here.

## DynamoDB access-pattern design

One initial runtime table, composite key, no LSI; one sparse publication GSI.
Namespace `N` is a versioned collision-safe encoding of owner, application and
workspace presence/value. Use length-delimited or equivalent unambiguous encoding;
null differs from every legal workspace ID. Preserve logical IDs independently
of physical keys. All key lengths must fit the reviewed service constraints.
Fixed-width UTC timestamps include consistent fractional precision; ID is the tie
break. Do not sort mixed native/ISO timestamp representations lexically.

| Named read/write | Primary/sort key design |
| --- | --- |
| Conversation get | `PK=N#CONV#id`, `SK=META` |
| Ordered historical message range | Same PK, `SK=MSG#created_at#message_id` |
| Message point lookup | Same PK, `SK=MID#message_id`, locator to the single canonical message key |
| Root cut | Conditional update of canonical root message/cut status plus metadata revision; reconstruct descendant effective status from ancestry |
| Summary selection | Same PK, `SK=SUM#created_at#summary_id`, newest-first query |
| Large summary provenance | Same PK, `SK=SC#summary_id#kind#chunk_sequence`; bounded chunk manifest/hash/count |
| Recent conversations | `PK=N#CATALOG`, `SK=CONV#updated_at#conversation_id`, descending query |
| Scoped job inventory | Same catalog PK, `SK=JOB#job_id` |
| Owner namespace inventory | `PK=OWNER#owner_id`, `SK=NS#encoded_application_workspace` |
| Privileged maintenance namespace inventory | `PK=MAINT#NAMESPACES`, `SK=encoded_owner_application_workspace`; minimal namespace reference, no private payload |
| Job get/claim/checkpoint | `PK=N#JOB#id`, `SK=META` and bounded checkpoint children |
| Worker job-ID resolution | Service-only minimal locator to scoped canonical key; authorize worker before lookup |
| Fixed-window request counter | `PK=OWNER#owner_id`, `SK=RATE#window_epoch`; account-wide counter |
| Scoped runtime event/replay | Aggregate partition, ordered sequence/event keys and operation-specific replay keys |
| Direct memory-effect coordination | Conversation partition operation record if no job exists; source guards remain in conversation metadata |

Directories/locators are rebuildable references with minimal index metadata,
never full authoritative copies. Conversation create/touch/mutation atomically
creates or moves the recent-list entry (deleting its old key), conditioned on
metadata revision. Namespace/job catalog entries are created transactionally
with their referenced D aggregate, enabling scoped export/deletion without Scan.
Account-wide counters and global/service-only locator keys have explicit scope
exceptions; they are not user-facing unrestricted ID read paths.
Namespace creation also transactionally registers its minimal maintenance entry;
privileged republishing enumerates this base-key catalog and scoped partitions,
including migrated unmapped owners, rather than scanning the table or depending
on identity mappings that exclude them. This low-frequency namespace directory
is not a global per-job queue. User routes cannot query it; export uses the
owner's catalog. Reconciliation/cleanup preserves directories while dependencies
or unknown effects remain.

### Publication GSI

Only pending/retry jobs with `publish_pending=true` receive:

- partition `PUB#N#status`;
- sort `created_at#job_id`;
- minimal projection: canonical key, revision and scheduling fields.

Query both statuses, page past future retry times before applying the output
limit, then merge eligible results in `(created_at, id)` order. Bound candidate
reads/time and fail explicitly if the bound prevents a complete requested
window; never return a falsely complete prefix. Enumerate only authorized owner
namespaces for maintenance. Strongly reread canonical jobs and conditionally
claim/update before any effect. Index propagation may delay notifications, not
authorize duplicates. Required recovery/export never relies on the GSI.
No recent-list GSI, speculative event indexes or global queue hotspot is needed
for this cut. New GSIs require a named read and capacity/storage evidence.

### Branch, concurrency and size rules

- Preserve `active_path`, valid ancestry, deterministic newest intact leaf,
  effective descendant supersession and bounded root cuts. No historical deletion.
- Metadata carries a bounded mutation revision/branch fingerprint and preparation
  token/time; do not grow a full active-ID array in it.
- Strong metadata read, paged strong history reads, then metadata reread establish
  one branch revision. Retry within the deadline if changed; fail on exhaustion.
- Every branch/message/status mutation advances revision. Preparation conditions
  on revision, active snapshot and its own token; creates root cut/new messages
  and metadata/list movement in one transaction.
- Conditional terminal writes still reject superseded ancestry. Release/recovery
  affects only its own reservation; expired requests cannot clear a newer token.
- Ordinary turn preparation expiry differs from an in-doubt memory-effect guard;
  the latter follows the recovery protocol below.
- Retain explicit SDK deadlines, bounded retries and cancellation draining.
  Use conditional create, stable operation IDs and fingerprint conflict checks;
  the SDK transaction token is not durable application replay state.
- Enforce item/transaction byte ceilings before dispatch, accounting for locators
  and directory writes. No unbounded ancestry expression or descendant write set.
- Summary source/coverage arrays can exceed one item. Prewrite bounded immutable
  chunks, then conditionally publish their complete manifest. Only hash/count-valid
  published summaries are readable. Interrupted staging is reconciled/cleaned;
  never truncate provenance or move it to future GCS to bypass this requirement.

Current AWS semantics: GSIs are eventually consistent; strong base-table reads
are supported. Items are limited to 400 KiB, transactions to 100 distinct items
and 4 MiB, and Query pages to 1 MiB. One transaction cannot act twice on one item.
SDK transaction token replay lasts ten minutes. Reverify/pin integration versions;
these are service constraints, not free-tier allowance constants.
Sources: [consistency](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html),
[constraints](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html),
[transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html).

## Postgres schema/repository decisions

One database with modular control, knowledge, research, decisions/domains and
capability-result groupings. Extend existing contracts and aggregate DTOs; exact
module/table placement follows existing seams rather than creating a parallel
framework. Psycopg 3 with bounded pools and explicit SQL/versioned migrations is
the minimal default. Existing synchronous protocols may use bounded offload and
cancellation draining; async compatibility does not require rewriting services.

- Stable semantics use UUID/text IDs, typed timestamps/status/revision/expiry,
  fingerprints and bounded numeric fields. Preserve source document IDs in
  migration-control metadata, not extra fields that strict DTOs reject.
- A scope namespace relation supplies non-null `scope_id`; enforce unique owner,
  application and null-safe workspace identity. Child FKs include scope. An owner
  namespace is not a verified identity mapping: preserve local/unmapped/shared
  cases without granting authentication.
- Predicate all private SQL reads by authorized scope before ranking/limits.
  Explicit shared/global records need their existing authorization classification.
  If RLS is used, set transaction-local scope and test pooling; do not assume
  persistent session state or let a connection inherit another request's scope.
- Use unique scoped replay identities/fingerprints; version-conditioned updates;
  append-only sequence/event constraints. Preserve expected state transitions and
  immutable decision/evidence snapshots. Ordinary forgetting/supersession does
  not cascade-delete sources; physical deletion remains explicit lifecycle work.
- Research run/session/replay/provenance commits stay one transaction. Domain
  lookup reservation/result completion and account/control audit stay atomic.
  Session evidence, queries, attempts and run events/ledger remain P-owned whether
  stored as bounded children or aggregate payloads; there is no D event mirror.
- Index named scoped entity/type/alias/claim/evidence/dependency lookups, event
  order, state/expiry and embedding-space eligibility. Model cross-links as
  relations where constraints/querying need them; no speculative JSONB GIN indexes.
- JSONB holds bounded evolving provider/domain payloads and versioned request,
  policy or result snapshots. No universal untyped document table, database blob
  store or duplication of whole mutable aggregates just to index them.
- Version migrations with checksums and a migration lock. Separate schema/admin
  credentials from runtime privileges, set connection/statement deadlines and
  handle rollback of compatible application/schema versions explicitly.
- Profile, future registries/grants/evaluation/artifact categories have assigned
  ownership only. Their CRUD/providers/jobs are implemented by their later phases.

## Embeddings: lossless storage without a second persisted projection

Sanity-check decision on 2026-10-06: storing both a lossless array and a pgvector
column is **not necessary for the initial exact-search baseline**. The existing
Phase 16 plan requires byte-compatible stored-vector reads; one float32 vector
column cannot guarantee round-trip values from Firestore/Python doubles. Keep
one canonical `double precision[]` array per embedding and full space metadata;
cast the array to pgvector transiently for compatible exact cosine search.
Reads/exports use the original values, never a float32 round-trip. No second
stored vector column or ANN index is installed by default.

At 768 dimensions, value payloads are approximately 6,144 bytes for float64
versus 3,072 for float32. Keeping both would use approximately 9,216 bytes;
array-only saves approximately one third of that two-copy value payload, before
row/array/TOAST/index overhead. Float32-only is smaller but weakens the existing
compatibility requirement. Measure actual table/TOAST bytes; these calculations
are representation arithmetic, not Neon capacity guarantees.

The tradeoff is per-query cast/distance CPU and exact-search work. P10.2 must
measure bounded query latency/compute and P10.5 must verify Neon free-plan fit;
storage savings do not prove strict-$0 compute. A future measured index can be an
expression index over the array cast, avoiding a redundant heap vector column,
but still consumes index bytes and needs explicit recall/resource evaluation.
Phase 34 owns retrieval optimization; no silent switch to ANN or precision loss.

Required semantics:

1. Embedding-space identity includes provider/model/dimensions/normalization and
   document/query task compatibility. Current Gemini uses normalized 768d vectors
   and distinct compatible retrieval document/query tasks. Attribute legacy
   metadata only from established adapter/config evidence; unknown stays unknown.
2. Enforce finite, nonzero, valid dimensions/array shape and normalization policy
   in code/constraints; reject incompatible spaces before search. Do not change
   the current accepted ceiling of 2,048 or re-normalize migrated values silently.
3. Exact pgvector cosine search operates on authorized compatible P rows, with
   lifecycle/status/type predicates before limits and deterministic ID ties.
   D chat-source revalidation remains mandatory before injection/effects.
4. Casts still calculate with float32. P10.2 numerical fixtures must cover the
   similarity threshold, scoring bands and nearest-cutoff ties. Define a tested
   error bound and rerank/expand boundary candidates from original values when
   required to preserve decisions; a small arbitrary overfetch is not proof of
   complete candidate coverage. Fail/fall back through existing advisory memory
   behavior when bounded work cannot establish parity. Do not equate exact search
   recall with byte-identical floating-point distance arithmetic.
5. Preserve v1 original/v2 derived identities, excerpts, fingerprints and source
   relations. Migration does not change provider/model, task, precision of stored
   values or extraction semantics. Fakes/non-vector paths remain deterministic.
6. pgvector storage/exact search permits current 2,001–2,048d spaces even though
   ordinary `vector` ANN indexes are limited to 2,000d. No truncation, `halfvec`,
   quantization or re-embedding workaround is silently enabled.

The [pgvector reference](https://github.com/pgvector/pgvector) documents float32
elements, exact versus approximate search and ANN dimensional/filtering limits;
the [extension SQL](https://github.com/pgvector/pgvector/blob/master/sql/vector.sql)
defines the double-precision-array cast. Local/Neon implementation checks must
confirm the pinned extension/version semantics independently.

## Cross-store references and minimum recovery protocol

| Direction | Reference and validation |
| --- | --- |
| P memory/provenance → D chat | Conversation/turn/user-message IDs, fingerprints, branch/source versions, matching scope and active completed ancestry |
| D lifecycle job → P knowledge | Candidate memory IDs, policy version and expected lifecycle versions; no copied memory bodies |
| P lifecycle event/receipt → D job | Job ID, operation identity and execution generation; receipt proves effect, not current job state |
| D runtime/turn → P policy metadata | Versioned registry/grant/policy refs where later phases require them; no invented grants now |
| P artifact metadata → GCS | Object key/generation/hash/readiness, Phase 20 only; operational D pointers are references |

All IDs stay opaque/stable and scoped. P-only groups use P transactions; D-only
groups use conditional D transactions. Do not route them through cross-store
coordination. Read-only memory retrieval revalidates D sources and can omit
unverifiable optional memory; it does not acquire durable write guards.

The narrow coordinator is needed only for new memory/effect writes that today
atomically validate chat ancestry/completed assistant or a lifecycle job in
Firestore. Reuse per-conversation metadata guards, existing job state and the
P operation-receipt boundary. Direct extraction needs a small D operation record
because it has no durable job; job effects use the job's pending operation.
Keep only operation ID/fingerprint, scoped resource refs/revisions, generation,
deadline and terminal acknowledgement. No generic saga/outbox platform, mirrored
P job/lease authority, provider orchestration or new automatic scheduler.

Distinguish stable semantic effect/replay identity from its coordination attempt.
The scoped receipt key includes the fixed attempt/generation; all retries of an
unknown attempt keep that key. Only a confirmed abort and D acknowledgement allow
a fresh guarded attempt. Existing unique memory/lifecycle semantic identities
remain unchanged across attempts, and their replay constraints are enforced in
the effect transaction. An applied effect replays its result rather than being
applied again. Attempt outcome receipts are evidence, not a second job authority;
never reuse an aborted attempt key or let its delayed worker affect a newer one.

### Apply and recover

1. Finish extraction/embedding outside guards. Strongly validate sources, then
   atomically guard the bounded source conversations at their revisions and,
   if applicable, the current live job token/generation. Refuse preparation or
   conflicting guards. Record the stable pending operation. Bound all resources
   within one D transaction; supported derivation remains 2–4 original sources.
2. Conflicting chat/root-cut/status writers and job lease replacement, failure,
   cancellation or terminal writers must honor
   these guards. They cannot simply expire an in-doubt effect. This coordination
   exists beneath repository behavior, not as a product workflow.
3. In one bounded P transaction, arbitrate the unique scoped operation receipt,
   validate fingerprint/source/lifecycle versions and apply effects plus receipt.
   Receipt outcomes are `applied` (result refs/hash) or `aborted` (no effects).
   Validate the captured execution deadline before effect application. Duplicate
   applied operations replay; different intent under the same identity conflicts.
4. Conditionally acknowledge in D and release only this operation's guards.
   Publication/worker acknowledgement cannot precede durable effect determination.
5. On timeout/crash, keep the original identity. Resolve the P receipt; if absent,
   recovery must atomically insert an abort receipt under the same unique key,
   serialized against the apply transaction. A read of "absent" alone is unsafe:
   an old worker may still be applying. Apply cannot bypass an abort receipt.
   If applied won, replay its result; if abort won, no late effect can commit.
6. Only then acknowledge/release D guards or permit a new job generation. Store
   failure leaves the operation in doubt and fails closed. Expiry starts bounded
   reconciliation; it does not unilaterally clear source guards. Reuse existing
   worker/recovery/operator entry points; no general autonomous recovery service.

Receipt arbitration and knowledge writes must share the P transaction; applying
effects then recording a receipt separately is invalid. Tests must interleave
apply, abort, old-worker completion, branch cuts and lease replacement. Pure turn
preparation recovery retains its existing behavior when no knowledge effect is
pending. After release, later source edits still make memories ineligible on
reuse through ordinary source checks; guard acquisition does not grant permanent
source validity. Cancellation drains bounded offloaded writes before local cleanup.

## Export, deletion and retained-state invariants

- Private direct IDs, listings, vector queries, jobs and references authorize
  owner/app/workspace before private hydration/disclosure. Client labels confer
  no access; default workspace membership denial and cross-app denial remain.
- Preserve v1 absent-envelope standalone/null compatibility and v2 explicit
  envelopes, including embedded historical children. Do not recursively stamp
  today's request scope onto historical records during backfill.
- Export inventory covers every canonical family/derived relation plus D
  locators/catalogs/chunks/receipts as appropriate. Current scoped exports and
  standalone-only account lifecycle authority remain unchanged.
- Required exports fail on missing stores, unresolved references or size bounds;
  never report partial output as success. Declare per-store snapshot/revision
  coverage and generated interval; no unsupported single cross-store instant.
- Adapt the portable logical export schema intentionally; preserve existing
  family labels/value fidelity or version the format with consumer compatibility.
  Store-specific physical rows/projections are not additional semantic records.
- Physical deletion inventories all originals/derived effects/jobs/projections,
  replay tombstones and future artifacts, with access denial/job fencing and
  deletion-aware restore obligations. P10 does not complete open Phase 9 physical
  deletion or broaden confirmation/cancellation behavior. Forgetting is not deletion.
- Cleanup never removes a receipt/guard needed to resolve an unknown effect.
  Retention windows and replay safety must agree before deleting operational data.
- No tokens, raw booking text, personal fixture data or reusable ChatGPT credentials
  enter managed persistence/logs/exports. Domain source rights remain binding.

## Downstream consumers

Phases 11/14/16 consume the scoped repository/vector baseline. Phase 19 keeps
admission/settlement in P, operational events in D. Phase 20 extends refs to GCS.
Phases 21/25.2 share D branch/attribution/replay; Phase 30 grants remain P and
propagate dependencies across stores; Phase 31 proposals remain P while domain
truth stays external. Phases 22/33/35 use P summaries and GCS permitted bodies;
Phase 34 benchmarks this exact-search baseline. Phase 36 consumes migration and
recovery evidence without erasing original Phase 9 gaps. See the
[migration/verification plan](phase-10-migration-cutover-and-verification-plan.md)
for package dependencies and external gates.
