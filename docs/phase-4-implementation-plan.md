# Phase 4 implementation plan

This is the scope/acceptance plan for Phase 4, implemented locally on 2026-10-02.
See the [implementation guide](phase-4-implementation-guide.md) and
[release evidence](releases/phase-4-experimental-memory.md) for the code map and
remaining external verification gaps. It makes the Phase 3 memory subsystem
experimentable. It builds on the delivered Phase 1 chat lifecycle, Phase 2
bounded context layer, and Phase 3 attributable-memory loop. The [Phase 3
plan](phase-3-implementation-plan.md) remains authoritative for memory types,
owner scoping, source provenance, sensitive-data exclusion, embedding
compatibility, token-budgeted injection, and the requirement that retrieval
failure cannot break a chat turn.

Read the [project brief](project-brief.md) first. Its constraints override
convenience decisions in this plan. Read the [architecture notes](architecture.md)
for the memory/evidence lifetime boundary. Externally observed facts remain
Phase 5 evidence: Phase 4 must not retain prices, availability, search results,
or model conclusions as personal memory.

## Scope boundary

Phase 4 turns the fixed Phase 3 retrieval policy into a measured memory
lifecycle experiment:

- Versioned, explainable scoring using semantic similarity, importance,
  recency, frequency, and confidence.
- Append-only lifecycle events and an auditable derived state for supersession,
  contradiction review, consolidation, decay, and forgetting eligibility.
- Bounded asynchronous consolidation of related, attributable episodes into a
  source-linked semantic summary or preference.
- Deterministic contradiction matching, with conservative automatic
  supersession only for sufficiently clear same-owner statements.
- Retrieval variants for the fixed Phase 3 baseline, scored records, and
  scored records with consolidated memory.
- Deterministic offline evaluation and a development-only inspection report
  that explains scores, lifecycle decisions, and selected versus excluded
  records.

Phase 4 does **not** add web search, evidence, research sessions, entities,
recommendation ranking, authentication, user-facing memory editing/deletion,
bulk historical import, learned ranking, a model judge, or cross-owner memory.
It does not delete source memories or silently alter their content. It must not
claim that a consolidated record proves anything beyond its linked user
statements. Forgetting changes normal retrieval eligibility; it is not a data
deletion mechanism and does not replace Phase 9 deletion controls.

The normal chat API and SSE event contract remain unchanged. All lifecycle
work is best-effort and never turns a model request that would otherwise fit
into a failed chat turn. Scoring failure may use fixed ordering over already
validated eligible source records; unavailable lifecycle/provenance state
requires empty memory, never resurrection of excluded records.

## Dependency map

```text
P4.0 Fixtures/baselines ──> P4.1 Decisions/contracts ──> P4.2 Lifecycle storage ──┬──> P4.3 Scoring ──┐
                                             |                                      |                   |
                                             └──> P4.4 Jobs/leases ──> P4.5 Consolidation ──> P4.7 Retrieval/injection ──> P4.8 Integration ──> P4.9 Evaluation/docs
P3 memory repository/extractor/retriever ────────────────────────────────> P4.6 Contradiction/forgetting ─┘
P2 context assembler/inspector ────────────────────────────────────────────────────────────────────────> P4.7
```

Tasks marked **decision required** should stop for user input only when the
documented default is unsuitable. All other tasks should be implementable
without expanding the phase.

---

## Phase 4 — Experimental memory

### P4.0 — Establish lifecycle fixtures and comparison baselines

**Dependencies:** delivered Phase 3 contracts and offline baseline; outstanding
credentialed Phase 1–3 checks remain documented, not implementation blockers

**Goal:** make each experimental retrieval and lifecycle outcome measurable
before it changes durable state or prompt context.

**Work:**

- Add version-controlled, synthetic fixture families for: semantic similarity
  versus importance; equal similarity with different recency/frequency/
  confidence; score ties; a preference supported by repeated episodes; a
  non-consolidatable mixed-topic cluster; clear correction; ambiguous apparent
  contradiction; temporal change; stale low-value memory; protected explicit
  correction; branch rewrite before a job runs; duplicate job delivery; and
  cross-owner near matches.
- Define each fixture's active records, immutable lifecycle events, clock,
  score configuration/version, candidate vector order, permitted and forbidden
  selections, consolidation input/output/provenance, and expected state
  transitions. Specify whether a result is an automatic action, a review-only
  finding, or no action.
- Record three baseline result sets for every query: Phase 3 fixed retrieval,
  Phase 4 scored retrieval without consolidation, and Phase 4 scored retrieval
  with only fixture-approved consolidated records. State the required fact,
  records that must not be selected, and the expected safe empty fallback.
- Extend the compact evaluation-result format with fixture/version IDs, variant
  ID, score components and rank order, lifecycle event IDs, job attempts,
  candidate/selected/excluded IDs, derived statuses, and failure reason. Do
  not commit raw personal content, vectors, prompts, or provider output.

**Requirements:**

- Fixtures, clocks, vector indexes, extractors, token counters, queues, and
  model clients are deterministic fakes. Automated evaluation must not call
  Firestore, Pub/Sub, a provider, or a judge model.
- A fixture's expected outcome is a record/state assertion, not a subjective
  claim that an answer is more personal.
- Each destructive-looking case proves that original content and source links
  remain auditable, even when the derived state is superseded or forgotten.

**Acceptance criteria:**

- The suite distinguishes a scoring error, unavailable candidate, lifecycle
  event conflict, job failure, consolidation rejection, budget exclusion, and
  model/provider failure.
- Every later scoring, lifecycle, worker, retrieval, and integration test uses
  at least one named shared fixture.
- The Phase 3 baseline remains reproducible from the same fixture corpus.

**Out of scope:** real-user A/B tests, production analytics, imported chat
history, or provider-generated expected answers.

### P4.1 — Record Phase 4 decisions and define lifecycle contracts

**Dependencies:** P4.0  
**Decision required:** yes

**Goal:** define the meaning and limits of an experimental memory lifecycle
before a job may change normal retrieval eligibility.

**Work:** add accepted ADRs and provider-neutral contracts for these defaults:

1. **Variant authority:** `fixed`, `scored`, and `consolidated` are explicit
   configured experiment variants. `fixed` preserves the Phase 3 policy;
   `scored` changes ordering only; `consolidated` permits qualifying derived
   records. A request records the applied variant/version and never mixes
   variants implicitly.
2. **Score rule:** all component inputs are normalized to `[0, 1]`; score is a
   configured, versioned weighted sum of similarity, importance, recency,
   frequency, and confidence. Missing/invalid inputs exclude a record rather
   than receiving an invented value. Stable ID order breaks exact ties.
3. **Lifecycle audit rule:** source records and their text/provenance are
   immutable. State changes are append-only `MemoryLifecycleEvent` records; a
   validated projection determines normal retrieval eligibility.
4. **Consolidation rule:** a bounded worker may create a new attributed
   `preference` or `semantic_summary` only from same-owner, active, compatible
   source memories. It links every source and does not rewrite or remove them.
5. **Contradiction rule:** automatic supersession is permitted only for a
   deterministic, type-compatible, high-confidence match with explicit newer
   user wording. Ambiguous, cross-topic, and assistant-derived cases are
   review-only and leave both records active.
6. **Decay/forgetting rule:** decay reduces retrieval score after an explicit
   effective-time policy; forgetting changes a derived status from `active` to
   `forgotten` only when policy allows it. Explicit corrections, current
   preferences, and records with active dependents are protected by default.
7. **Worker rule:** consolidation and lifecycle projection run through an
   idempotent, owner-scoped job boundary with a lease, attempt limit, safe
   retry classification, and dead-letter/terminal record. A job must re-read
   its candidates and source branch before committing.

Define provider-neutral contracts (names may vary):

- `MemoryScorer.score(query, candidates, policy) -> ScoredRetrieval`.
- `MemoryLifecycleRepository` for append-only event creation, idempotency
  lookup, derived-state lookup, and owner-scoped inspection.
- `MemoryConsolidator.plan(owner_id, candidates, policy) -> ConsolidationPlan`.
- `MemoryLifecycleService.apply(plan_or_event) -> LifecycleOutcome`.
- `MemoryJobQueue.enqueue(job)`, `claim`, `complete`, and `fail`.

**Required new fields:**

| Record | Required fields |
| --- | --- |
| Memory lifecycle event | `id`, `owner_id`, `memory_id`, `event_type`, `reason_code`, `policy_version`, `actor`, `occurred_at`, `idempotency_key`, `related_memory_ids`, `job_id` (nullable), `schema_version` |
| Derived memory state | `memory_id`, `owner_id`, `retrieval_status`, `effective_status_at`, `superseded_by_memory_id` (nullable), `consolidated_into_memory_ids`, `last_retrieved_at` (nullable), `retrieval_count`, `state_version` |
| Memory job | `id`, `owner_id`, `job_type`, `candidate_memory_ids`, `policy_version`, `status`, `attempt_count`, `lease_expires_at`, `idempotency_key`, `created_at`, `updated_at` |

`event_type` initially includes `consolidated`, `superseded`, `forgotten`,
`reactivated`, `retrieved`, and `review_required`; `actor` is `system` or `developer_test`.
Only an accepted future user-management phase may add a user actor.

**Required configuration:**

| Setting | Purpose |
| --- | --- |
| `MEMORY_EXPERIMENT_VARIANT` | `fixed`, `scored`, or `consolidated`; normal default remains `fixed` |
| `MEMORY_SCORING_POLICY_VERSION` | Names the immutable weight/normalization policy |
| `MEMORY_SCORE_*_WEIGHT` | Bounded weights for the five score components |
| `MEMORY_RECENCY_HALF_LIFE_DAYS` | Explicit decay schedule for eligible records |
| `MEMORY_CONSOLIDATION_ENABLED` | Separately permits job enqueue and worker execution; disabled by default |
| `MEMORY_CONSOLIDATION_MAX_SOURCES` | Bound on sources and prompt/input size per job |
| `MEMORY_CONTRADICTION_AUTOMATION_ENABLED` | Explicit gate for clear automatic supersession; disabled by default |
| `MEMORY_FORGETTING_ENABLED` | Explicit gate for derived forgetting; disabled by default |
| `MEMORY_JOB_MAX_ATTEMPTS` | Bounded retry count |
| `MEMORY_LIFECYCLE_INSPECTION_ENABLED` | Development-only read-only inspection gate |

**Requirements:**

- Settings reject negative weights, all-zero weights, invalid variants,
  non-positive half-life/limits, unsupported event transitions, and enabled
  consolidation without its master Phase 3 memory gate.
- The scorer and lifecycle services must return structured exclusion or
  rejection reasons, never provider-specific objects or raw private content.
- Existing Phase 3 source fingerprint, owner, active-branch, embedding, and
  sensitive-data validations apply to derived records and every lifecycle job.

**Acceptance criteria:**

- ADRs record all seven decisions, consequences, and accepted status.
- Contract tests reject an invalid score policy, cross-owner relation,
  unsupported state transition, duplicate event key, and job with an expired
  or missing lease.
- Example settings load with Phase 3 behavior intact: fixed retrieval and all
  lifecycle mutation, jobs, and inspection disabled.

**Out of scope:** learned weights, per-user tuning controls, a human review UI,
or a deletion/retention policy.

### P4.2 — Persist append-only lifecycle events and derived state

**Dependencies:** P4.1

**Goal:** make experimental lifecycle decisions auditable and reversible
without mutating source memory records.

**Work:**

- Add validated domain records and repository protocols for lifecycle events,
  derived state, source/dependent relationships, and job records.
- Implement Firestore persistence in dedicated collections, with owner-scoped
  event queries, state lookup, idempotency lookup, and required composite
  indexes documented or provisioned before use.
- Apply an event atomically with its state projection where Firestore permits;
  otherwise use an optimistic state version and idempotent reconciliation so a
  duplicate delivery cannot apply the transition twice.
- Implement equivalent in-memory fakes with deterministic ordering,
  transitions, leases, and simulated contention for all unit tests.

**Requirements:**

- Normal retrieval reads the projection but inspection can reconstruct the
  decision from immutable events and source links.
- Every event, state, relationship, and job is strictly owner-scoped. A state
  or event from another owner is never used to rank, consolidate, or suppress a
  memory.
- A `superseded` or `forgotten` source remains readable to the owner only in
  audit/inspection paths; it is excluded from ordinary retrieval.
- Repository failures map to typed application errors; ordinary tests make no
  Firestore calls.

**Acceptance criteria:**

- Tests cover event append, idempotent replay, valid/invalid transitions,
  projection rebuild, source preservation, ownership isolation, concurrent
  state-version conflict, and deterministic event ordering.
- An emulator/manual check writes a synthetic event and verifies its derived
  state without source-memory mutation.

**Out of scope:** live migration of Phase 3 records, user deletion, collection
scans without a bounded job, or cross-owner analytics.

### P4.3 — Implement deterministic, versioned memory scoring

**Dependencies:** P4.0, P4.1, P4.2

**Goal:** rank eligible memories transparently while retaining the fixed Phase
3 policy as a comparable baseline.

**Work:**

- Implement score-component functions for semantic similarity, persisted
  importance, effective-time recency, retrieval frequency, and extraction/
  consolidation confidence. Normalize them according to the policy version.
- Compute scores only after Phase 3 candidate validation and lifecycle-status
  filtering. Keep score calculation deterministic, bounded, and free of model
  calls.
- Define importance only from attributable candidate metadata and explicit
  type-safe rules; frequency only from successful selection/injection events,
  not raw query volume. Update frequency through an idempotent aggregate event
  after a completed selection, never before a provider response.
- Return the full non-content score breakdown, policy version, tie-break
  result, and exclusion reason for evaluation/inspection.

**Requirements:**

- Similarity remains a retrieval candidate input, not a truth claim. A high
  score cannot bypass owner, status, provenance, vector, or token validation.
- Recency uses `effective_at` and an injected clock; it never substitutes
  `created_at` merely because an old record was reprocessed.
- A consolidated record's importance/confidence is bounded by its policy and
  sources; it must not gain arbitrary authority because it is shorter.
- `fixed` variant results remain byte-for-byte equivalent to the Phase 3 fake
  policy for a shared fixture.

**Acceptance criteria:**

- Tests cover normalization bounds, each component's monotonic behavior,
  version isolation, exact ties, missing input exclusion, protected-status
  filtering, idempotent frequency updates, and Phase 3 fixed parity.
- Fixture results expose enough metadata to reproduce every rank without
  storing raw text or vectors.

**Out of scope:** neural reranking, query rewriting, adaptive online learning,
or changes to embeddings/vector search.

### P4.4 — Add bounded, idempotent lifecycle job execution

**Dependencies:** P4.1, P4.2

**Goal:** run consolidation and lifecycle work outside chat delivery with
reliable retry behavior and no duplicate mutations.

**Work:**

- Add a job publisher/worker adapter using the project's Pub/Sub and Cloud Run
  worker direction, behind the `MemoryJobQueue` boundary. Add an in-process
  fake queue for offline tests.
- Enqueue a bounded owner-scoped consolidation candidate job after eligible
  completed turns, subject to gates and dedupe key. Do not delay `response.completed`.
- Claim jobs with a lease; revalidate source states, provenance, and branch
  eligibility; execute one lifecycle operation; then atomically complete or
  classify failure for retry/terminal handling.
- Add safe worker logs and metrics using IDs, counts, policy version, attempt,
  and error class only. Document queue permissions, retry/dead-letter behavior,
  and the worker's disabled deployment default.

**Requirements:**

- The worker trusts neither message delivery count nor payload alone; it uses
  stored idempotency keys and authoritative owner-scoped records.
- A stale, superseded, forgotten, cross-owner, or branch-invalid source causes
  a safe no-op/review outcome, not a new memory or status rewrite.
- No queue callback exposes a public unauthenticated mutation path. Real cloud
  checks are opt-in; CI uses fakes.

**Acceptance criteria:**

- Tests cover enqueue dedupe, duplicate delivery, lease expiry/reclaim,
  retryable versus terminal failure, source change before execution, worker
  crash after apply, and disabled-gate no-op.
- Integration tests prove chat SSE ordering and completed assistant persistence
  are unchanged when enqueueing succeeds or fails.

**Out of scope:** a general-purpose scheduler, bulk backfill, job UI, or
research/search jobs.

### P4.5 — Consolidate compatible memories with complete provenance

**Dependencies:** P4.0, P4.1, P4.2, P4.3, P4.4

**Goal:** create a small number of useful generalizations without erasing the
episodes that support them.

**Work:**

- Select a bounded, same-owner cluster of active compatible episodes or
  preferences using deterministic eligibility rules before any optional
  provider-assisted synthesis.
- Define a provider-neutral consolidator. It receives only the source records
  needed for one cluster and may return no plan; its output includes target
  type, attributable content, confidence, source IDs, effective time, and a
  stable rationale code.
- Validate the plan as strictly as Phase 3 extraction: source ownership/status,
  type compatibility, content bounds, sensitive-data policy, source coverage,
  no unsupported external claim, embedding compatibility, and idempotency.
- Persist a new memory with complete source links, then append `consolidated`
  events for sources. Default source projection stays retrievable with an
  explicit consolidation relationship unless the selected policy says a source
  is safely redundant; never delete it.

**Requirements:**

- Consolidation must not combine unrelated facts simply because their vectors
  are close, nor turn an assistant recommendation into a preference.
- A source may appear in multiple auditable consolidation attempts, but an
  idempotency rule prevents equivalent active derived memories.
- A failed/empty/oversized provider result, an incompatible embedding, or a
  stale source produces no partial derived memory or lifecycle event.

**Acceptance criteria:**

- Tests cover repeated explicit-preference consolidation and episode-to-summary cases,
  no-plan, mixed-topic rejection, duplicate job, stale source, sensitive-data
  rejection, provider/embedding/storage failure, and full source provenance.
- A fixture proves a consolidation can improve allowed retrieval selection
  while all original source memories remain auditable.

**Out of scope:** user approval workflow, broad historical clustering,
multi-hop consolidation, automatic source deletion, or evidence synthesis.

### P4.6 — Apply conservative contradiction, supersession, decay, and forgetting

**Dependencies:** P4.0, P4.1, P4.2, P4.3, P4.4

**Goal:** prefer current relevant user knowledge without pretending to resolve
uncertain personal facts or destroying history.

**Work:**

- Implement deterministic matching for potential same-subject, same-memory-
  type conflicts. Require explicit newer user wording, configured confidence,
  temporal ordering, and a policy-approved relation before automatic action.
- Append `superseded` linking events only for approved clear cases. Emit
  `review_required` for ambiguous cases and leave both records normally
  eligible, with score/temporal ordering still visible.
- Calculate decay using effective time and the configured half-life; apply it
  only as a score component until an enabled forgetting policy emits an event.
- Implement forgetting eligibility with explicit protected categories and
  dependency checks. A forgetting event removes normal retrieval eligibility
  but preserves audit, provenance, and potential future reactivation.

**Requirements:**

- Automatic supersession and forgetting are separately gated and disabled by
  default. Their disabled behavior is observational/report-only.
- An explicit correction is never overwritten by an older or assistant-derived
  statement. Current preferences and memories referenced by active derived
  records are protected unless an explicit later policy permits otherwise.
- No operation compares or joins memories across owners; an uncertain relation
  is never promoted just to make retrieval cleaner.

**Acceptance criteria:**

- Tests cover clear correction, temporal preference, ambiguous contradiction,
  type mismatch, older-versus-newer protection, protected records, decay
  boundaries, forget/reactivate transition, audit reconstruction, and
  duplicate-event safety.
- Fixture runs show that an old memory is never silently deleted or rewritten,
  and ambiguous conflicts never reduce to a false automatic conclusion.

**Out of scope:** a contradiction graph UI, human adjudication workflow,
retention deletion, legal/privacy deletion requests, or model-based truth
arbitration.

### P4.7 — Select experimental memory variants and inject them safely

**Dependencies:** P2.3, P2.5, P2.6, P4.3, P4.5, P4.6

**Goal:** use the selected experimental variant through the one existing
token-budgeted context path.

**Work:**

- Extend `MemoryRetriever` to choose an explicit variant after Phase 3 vector
  candidate validation. Apply lifecycle eligibility, scoring, and consolidation
  policy as configured, then pass the bounded result to the existing memory
  context selector.
- Preserve Phase 2 allocation priority: count mandatory instructions and the
  newest prompt, select fitting recent complete turns and a compatible summary,
  then add whole optional memory records only in remaining budget. Within the
  memory block, approved current corrections precede consolidated records and
  selected sources; prompt layout remains memory, summary, chronological raw
  history with the newest prompt last. Memory never evicts fitting Phase 2 context.
- Extend development-only inspection with variant/policy versions, state,
  score components/bands, lifecycle event IDs, source counts, selected and
  excluded records, and token exclusion reasons. Do not reveal raw content
  beyond the Phase 3 authorized inspection boundary.

**Requirements:**

- A failed scorer uses fixed ordering only over lifecycle/provenance-validated
  source records. Unknown or unavailable eligibility returns empty memory.
  Worker/consolidator failure leaves committed valid state intact; optional
  memory never becomes mandatory. Record requested and applied variants plus
  fallback reason.
- Prompts label consolidated information as historical personal context, never
  as external evidence or a current user statement. Do not include hidden
  scores, event IDs, rationale, or vectors in the prompt.
- Inspection is owner-scoped, read-only, disabled by default, and cannot
  enqueue jobs, update frequencies, reproject state, call an LLM, or mutate
  storage.

**Acceptance criteria:**

- Tests prove fixed parity, scored ordering, consolidated selection, status
  filtering, correction precedence, whole-record budget exclusion, no-memory
  fallback, owner isolation, and no mutation during inspection.
- A long-context fixture proves experimental memory plus a compatible Phase 2
  summary and recent turns remain within the one total budget.

**Out of scope:** user-selectable variants, prompt replay, memory editing,
research evidence injection, or a public lifecycle API.

### P4.8 — Integrate lifecycle experiments into chat and worker flows

**Dependencies:** P4.4, P4.5, P4.6, P4.7

**Goal:** make experimental memory available to eligible turns without
regressing durability, streaming, or Phase 3 safe fallback behavior.

**Work:**

- Extend dependency injection for scorer, lifecycle repository/projection,
  queue, consolidator, worker, and variant-aware retriever; preserve fake-only
  route tests.
- After a new user message is durable, use the variant-aware retriever before
  assistant placeholder creation. Keep Phase 2 mandatory-context rejection
  behavior unchanged.
- After final assistant persistence and successful Phase 3 extraction, enqueue
  an eligible lifecycle job best-effort. Do not wait for the job or publish its
  progress through the browser SSE stream.
- Ensure regenerate/edit-and-retry use their post-mutation active path and
  cause queued work whose sources are no longer active to no-op safely.

**Requirements:**

- Successful browser behavior remains `message.created` (user),
  `message.created` (assistant), zero or more `response.delta`, then
  `response.completed`.
- The default configuration is Phase 3 fixed retrieval with no worker mutation.
  All enabled variants retain Phase 3's non-fatal retrieval fallback.
- Logs/evaluation may record safe IDs, counts, variant, policy version, and
  error class, but not memory text, query text, vectors, secrets, or prompt
  contents by default.

**Acceptance criteria:**

- Route/worker integration tests cover disabled parity, each enabled variant,
  selected/excluded memory, scoring failure fallback, worker enqueue failure,
  completed consolidation, stale job after branch rewrite, regenerate,
  edit-and-retry, disconnect, and provider failure.
- Existing Phase 1–3 API, persistence, streaming, context, and memory tests
  remain green with all Phase 4 gates disabled.

**Out of scope:** new SSE events, user lifecycle notifications, automatic job
retry from the chat request, or changing the public chat API.

### P4.9 — Evaluate, document, and verify Phase 4 behavior

**Dependencies:** P4.0, P4.3, P4.5, P4.6, P4.7, P4.8

**Goal:** establish whether the experiment improves defined retrieval behavior
without weakening provenance, privacy, or Phase 3 reliability.

**Work:**

- Run the deterministic lifecycle suite for every variant and compare against
  the P4.0 baselines. Report retrieval precision/required-fact coverage,
  forbidden retrievals, rank changes, consolidation precision/provenance,
  contradiction false actions, forgetting protection, budget adherence, job
  idempotency, and safe fallback.
- Define promotion thresholds in documentation before enabling a non-fixed
  variant outside development. A result that improves one fixture but violates
  a forbidden selection, provenance rule, or safe fallback is not promotable.
- Run opt-in manual checks with synthetic data only: create source memories,
  inspect a score report, process one consolidation job, test a clear and an
  ambiguous correction, and confirm disabled gates make no lifecycle mutation.
- Update README, settings, API/inspection, worker/deployment, Firestore-index,
  privacy, and evaluation documentation. Explain that lifecycle states are
  fallible experiment outputs, sources remain auditable, and forgetting is not
  deletion.

**Requirements:**

- CI remains offline and deterministic, with no GCP project, provider key,
  real queue, real embeddings, or personal data. Credentialed/cloud checks are
  explicit opt-in and skipped by default.
- Recorded results name the variant and policy versions; they do not conflate
  fake evaluation with configured provider behavior.
- Documentation must not promise perfect recall, conflict resolution, factual
  truth, automatic deletion, or freshness of external facts.

**Acceptance criteria:**

- A clean checkout runs backend tests/lint, frontend tests/lint/type-check,
  worker tests, and the Phase 4 evaluation suite without credentials.
- The comparison record proves fixed baseline reproducibility, deterministic
  scored/consolidated results, full selected-record provenance, no cross-owner
  leakage, correct protected/ambiguous behavior, and no broken chat turn from
  lifecycle failure.
- Normal/deployed configuration leaves consolidation, automatic supersession,
  forgetting, worker mutation, and lifecycle inspection disabled unless
  deliberately enabled; `fixed` remains the default variant.
- No Phase 5+ search, evidence, entity, ranking, domain-agent, authentication,
  export, or deletion behavior was added to satisfy Phase 4.

**Out of scope:** production experiments on personal data, user controls,
research-agent integration, Phase 5 migration, or operational retention.

## Reviewed execution contracts (2026-10-02)

The user explicitly authorized full Phase 4 implementation after this planning
review. The following defaults resolve implementation gaps and take precedence
where the task prose is less specific. Record them in accepted ADRs during P4.1;
routine implementation choices require no further approval. Later phases remain
out of scope. Planning review does not certify provider/emulator/cloud behavior.

### Schema and attribution

Phase 3 `Memory` schema v1 stores one source conversation, one completed turn,
and at most two exact-excerpt user-message sources. Do not manufacture one of
those fields for a multi-conversation consolidation or relax v1 excerpt checks.
Introduce an explicitly discriminated derived schema (or separate derived record
contract) with bounded `source_memory_ids`, per-source fingerprints, conversation,
message and completed-turn references, derivation policy/version and source-set
identity. Keep v1 reads/identities/serialization compatible without a backfill.
Derived records must enter bounded indexed vector retrieval with compatible model
and dimensions; document indexes for their chosen storage layout. Never substitute
a collection scan. All direct sources must be original v1 records: no multi-hop
consolidation. Validate every linked active completed user source on retrieval,
inspection and mutation, including ancestor root cuts and conversation preparation
reservations. One invalid source excludes the entire derived record.

The default consolidator is deterministic and extractive: combine bounded exact
user assertions on a policy-approved common subject, with source-to-excerpt
coverage. A preference requires repeated explicit preference support, not inference
from one experience. A semantic summary may join compatible episode excerpts with
clear historical attribution. This satisfies P4.5 without an optional live synthesis
adapter. Similar vectors alone do not establish a common subject. Reject unsupported
paraphrases, sensitivity/external claims, mixed topics, and excessive output.
Use the latest supporting effective time, never worker creation time, and confidence
no higher than the least confident source. Preserve every original source.

### State, policy and fallback

A missing projection for a valid v1 record means initial active state with zero
retrieval count; a corrupt/unavailable projection does not mean active. Projections
are rebuildable from sequenced immutable events. Events carry expected state
version and deterministic ordering; an idempotent identical replay returns the
original outcome, while reuse of its key with different payload is rejected.
`consolidated` adds a relation without suppressing its source; `review_required`
does not suppress; `retrieved` increments usage without changing eligibility.
`superseded` and `forgotten` exclude retrieval, and reactivation cannot bypass
source validation or clear an active supersession. Define/test a transition table.

`fixed` preserves Phase 3 candidate ordering and source-only selection with all
Phase 4 mutations off. Once lifecycle actions are enabled, every variant honors
committed lifecycle exclusions; fixed parity is against unchanged initial state,
not permission to revive forgotten/superseded records. `scored` excludes derived
records; `consolidated` allows them and suppresses duplicate source representation
only within the selected block, without changing source state. If a derived record
does not fit, its sources remain candidates for whole-record fit.

Default score policy v1 uses weights .50 similarity, .15 importance, .15 recency,
.10 frequency, .10 confidence, normalized by their positive total. Similarity is
clamped cosine in [0,1] after Phase 3 minimum-similarity validation; recency is
2 ** (-max(0, age_days) / half_life_days), default half-life 90 days; frequency is
min(retrieval_count / 10, 1). Importance defaults are explicit correction 1.0,
preference .8, semantic summary .6, episode .4; persist this versioned metadata in
sidecar state for v1 and the derivation record for derived memories, without editing
v1 text. Missing sidecar initializes from these explicit type rules; malformed
metadata excludes. Derived importance cannot exceed the maximum supporting source
importance. Policy identity includes all weights/normalization settings, so changed
weights cannot silently reuse an identical policy identity. Reject NaN/infinite
weights and unknown versions. Apply decay only through recency, never twice.

Contradiction automation defaults to a small documented deterministic assertion
matcher: require identical subject key, compatible types, explicit correction or
explicit temporal replacement wording, strictly newer effective time and confidence
at least .9. Unmatched language, equal timestamps and uncertain negation are
review-only. No LLM decides supersession. Forgetting defaults to episodes or semantic
summaries at least 365 days old, confidence below .5, zero successful retrievals,
no explicit correction/current preference and no active dependent; record thresholds
as versioned policy. Discover dependencies with bounded indexed reverse links.
No match or unknown/incomplete dependency state means no mutation. Maintenance is
triggered by explicit bounded jobs, not an unimplemented global scheduler.

### Atomic commits and reliable jobs

Re-read sources, ancestor/root-cut state, lifecycle versions, reverse dependencies
and lease fencing token in the same transaction that creates derived records,
relations, events and projections. A preflight read followed by independent writes
is insufficient. In-memory fakes share source mutation locks for equivalent behavior.
Bound source count, ancestor reads, transaction work, payload bytes and total
execution time; reject an operation that cannot fit, without partial visibility.
Existing Phase 3 deadlines and snapshot-independent reservation cleanup remain intact.

Separate the durable job repository (claim/lease/complete/fail) from the Pub/Sub
notification publisher. Persist a pending job before publishing; retain publish
status and provide an explicit bounded pending-job republish/recovery command.
No always-running scheduler is required, but publish failure must not strand a job
without a documented tested recovery path. Candidate discovery uses bounded indexed
same-owner/type queries, including related earlier turns, not only the newest
extraction result. Empty extraction may skip consolidation but must not prevent
independently eligible contradiction/forgetting jobs. Store job type, policy snapshot,
source set, retry/terminal reason, next eligible attempt and a lease token/generation.
Payload contains only job ID/schema version; derive owner and candidates from storage.

Claims require an unexpired fencing token for every write, completion and failure;
expired workers cannot apply after another worker reclaims. Default limits: four
sources, three attempts, 30-second execution deadline and 60-second lease; ensure
configuration cannot allow execution to outlive a lease without renewal. Transactional
operation keys handle crashes after apply before acknowledgement. Complete/no-op and
terminal failures acknowledge push delivery; retryable failures return a retryable
HTTP status, active leases avoid premature acknowledgement, and terminal records
retain safe reasons. Test publish-loss recovery, crash windows, stale lease holders,
transaction conflicts and bounded processing in addition to duplicate delivery.

At planning review, the API image exposed an idle `/tasks/research` endpoint and
was public, while the Cloud Run worker used the same entry point. Add a separate worker app or
explicit service-role gate so lifecycle mutation routes do not exist on the public
API. Use Cloud Run IAM and Pub/Sub authenticated push for the private worker, with
explicit worker runtime Firestore/required-secret permissions and API publisher
permissions. Keep push invoker and worker runtime identities distinct. Update an
existing subscription's endpoint/configuration, not only create a new subscription.
Deployment defaults explicitly disable every Phase 4 mutation/inspection gate on
both services; tests cover public API absence and disabled private-worker no-op.
This private task boundary is required transport protection, not Phase 9 end-user
authentication. Local tests use injected fakes without cloud tokens.

### Completion accounting, inspection and delivery

Frequency counts only IDs that the assembler actually injected, once per durably
completed assistant after successful terminal send. Never count candidates, token
exclusions, failed/cancelled turns or inspection. Use an idempotent `retrieved` event
key containing owner, assistant and memory ID. Enqueue after extraction in the
existing retained post-terminal task; failures cannot change SSE or assistant status.
Document that process death before the durable enqueue may lose this optional work;
recovery applies once a durable job exists, not an exactly-once chat promise.

Extend the supplied-ID inspector: read bounded stored state/events and compute
scores only from supplied/stored candidate metadata; never embed a query or invoke
providers. If similarity is unavailable, show null score with an explicit reason,
not invented relevance. Distinguish fit estimates from historical actual injection.
Require backend/frontend development gates; reveal metadata only, retain foreign-ID
404 behavior, and test no writes/provider/queue calls.

Add `make memory-lifecycle-eval` and an offline CI step. Use shared named fixtures
for the three variants and run all existing backend/frontend tests, lint, typecheck,
context/memory evaluations plus this new suite. Dependency/build changes also need
locked installation, backend/frontend builds and affected Docker builds if available;
deployment changes need shell syntax checking. Finish with `git diff --check`.
Promotion requires zero forbidden selections, false automatic contradiction actions,
protected forgetting, provenance/owner violations, budget violations or lifecycle-
induced chat failures, fixed baseline parity and deterministic replay. Report measured
coverage/rank improvements without claiming universal recall improvement.

Deliver in roughly four to six coherent commits (adjust for real boundaries):
contracts/storage and fixtures; scoring/lifecycle policy; queue/worker/consolidation;
chat/inspection integration; evaluation, operational docs and closeout. Do not commit
once per plan task. The initial implementation handoff used a Luna Extra High agent. The user later
requested that it stop after its current commit and that the main session finish
implementation, acceptance fixes and verification; that later ownership instruction
is authoritative. Update
phase status, implementation guide and dated release evidence with tested revision,
commands, outcomes, commit map and explicit remaining external verification gaps.
Full local implementation includes real adapters and opt-in check entry points;
unavailable cloud/provider/emulator environments do not block offline completion
and must never be recorded as passed. Do not deploy or promote gates as a side effect.

## Phase 4 completion review

Before declaring Phase 4 done, verify all task acceptance criteria and answer
these questions:

1. Does `fixed` retrieval still reproduce Phase 3 behavior, and is every other
   variant explicit, versioned, and evaluated against it?
2. Can the system reconstruct why a memory was ranked, consolidated,
   superseded, retained, forgotten, or excluded without exposing raw secrets?
3. Are source memories, their content, and provenance immutable and auditable
   after every lifecycle action?
4. Can a duplicate, stale, cross-owner, or branch-invalid job ever create a
   new active record or apply a lifecycle event? (The required answer is no.)
5. Are automatic contradiction and forgetting actions conservative, separately
   gated, disabled by default, and protective of explicit corrections/current
   preferences/dependent records?
6. Does every variant still enter the one Phase 2 token-budgeted context
   assembler, preserve the newest user message, and fall back safely when
   memory work fails?
7. Do all automated checks and evaluation comparisons run without cloud
   credentials, providers, queues, real embeddings, or personal data?
8. Are lifecycle jobs and inspection disabled in normal deployment until an
   intentional provider-data, worker-security, and experiment review occurs?
9. Has the implementation avoided search/evidence, entities, ranking, domain
   agents, authentication, user deletion/export, and other Phase 5+ scope?

The implementation agent must answer each question with evidence, using “no” for
question 4 and “yes” for the remaining questions. Record unavailable
external checks separately. Completing Phase 4 does not authorize Phase 5; obtain
an explicit later user instruction before advancing.
