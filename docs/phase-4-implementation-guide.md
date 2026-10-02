# Phase 4 experimental memory implementation guide

Phase 4 is implemented locally with fixed retrieval as the default and all
lifecycle mutation and inspection gates disabled. The [plan](phase-4-implementation-plan.md)
and [ADR 0010](decisions/0010-experimental-memory-lifecycle.md) define scope.
The [release record](releases/phase-4-experimental-memory.md) distinguishes offline
verification from outstanding emulator, provider, Pub/Sub and deployed checks.

## Plan-to-code map

| Plan | Delivered boundary | Verification |
| --- | --- | --- |
| P4.0 | `evaluation/memory-lifecycle-fixtures.json`, `evaluation/memory_lifecycle.py` | Twenty shared synthetic fixtures, three variants, deterministic IDs/clocks and measured service outcomes |
| P4.1 | ADR 0010, `memory/contracts.py`, `memory/lifecycle.py`, settings | V1/v2 separation, policy identity, gated defaults, invalid configuration and transitions |
| P4.2 | `memory/lifecycle_repositories.py` | Owner-scoped events/projections/jobs/relationships, transaction source checks, replay/rebuild, lease fencing |
| P4.3 | `score_memory`, `MemoryRetriever` | Versioned bounded components, fixed parity, stable ties, idempotent successful-injection frequency |
| P4.4 | `memory/lifecycle_jobs.py`, `memory/recovery.py`, `worker.py` | Persist-before-publish, reclaim/retry/terminal records, explicit bounded recovery, separate private worker |
| P4.5 | `DeterministicMemoryConsolidator`, atomic commit | Repeated explicit preferences or repeated compatible episodes, exact provenance, no partial write, duplicate/crash replay |
| P4.6 | `contradiction_decision`, `forgetting_decision`, transactional event policy validation | Explicit newer same-subject corrections, review-only uncertainty, dependency protection and source-safe reactivation |
| P4.7 | Retriever, assembler, supplied-ID inspector and existing proxy/panel | Variant selection, whole-record budget, backup source fit, metadata-only inspection |
| P4.8 | Chat post-terminal coordinator and worker composition | Unchanged SSE, actual injected-ID accounting, disabled parity and source rewrite exclusion |
| P4.9 | `make memory-lifecycle-eval`, CI, manual check entry points | Offline comparisons, promotion conditions, operational guidance and dated evidence |

## Retrieval and scoring

`fixed` retains Phase 3 similarity bands/correction/time/ID ordering and uses only
original memories. `scored` orders original records by normalized weighted score
and stable UUID ties. `consolidated` gives approved current corrections precedence,
then eligible derived records, then scored original records. All variants enforce
owner, vector compatibility, minimum similarity, current completed user sources,
root cuts and lifecycle eligibility. Fixed parity applies to initial lifecycle
state; switching variants never revives a superseded or forgotten record.

Policy `score-v1` defaults to .50 similarity, .15 importance, .15 effective-time
recency, .10 successful-injection frequency and .10 confidence. Recency decays with
90-day half-life; frequency saturates at ten successful injections. Importance is
an explicit type rule (correction 1, preference .8, summary .6, episode .4), or
validated sidecar metadata when present. Missing sidecars initialize from the
rule without a migration or a read-time write. The policy identity covers weights,
half-life and normalization; unknown versions and non-finite settings are rejected.
Invalid per-record inputs exclude that record. Scorer execution failure falls back
to fixed ordering over validated eligible original records. Unavailable lifecycle
or source state yields empty optional memory, leaving Phase 2 chat intact.

The assembler allocates mandatory instructions/prompt, fitting recent complete
turns and a useful working summary before optional memory. The prompt ends with
the latest user request. Derived information is labelled historical context.
Sources are omitted from the block only after their derived record fits; if it
fails budget checks, bounded source candidates can still fit individually. Scores,
event IDs, vectors and rationale codes never enter prompts. `memory_tokens` on the
context result counts the complete memory block; budget `memory_tokens` is its
marginal contribution to the whole counted request. Neither is a per-record sum.

## Immutable provenance and lifecycle

Original `memories` retain schema v1, exact excerpts, original identities and
single-conversation provenance. `derived_memories` use schema v2 and two to four
original source records, each with its fingerprint, conversation, completed turn,
user-message IDs and exact excerpt. They carry a deterministic source-set identity
and policy version. No original record is rewritten and no multi-hop consolidation
is permitted. Every derived read revalidates every source; one obsolete source
excludes the derived record.

The conservative extractive consolidator requires repeated identical normalized
assertions with compatible types. Repeated explicit preference assertions produce
a preference; repeated episode assertions produce a historical semantic summary.
Episodes alone cannot prove a general preference. The derived text retains exact
source statements rather than inventing a paraphrase. Confidence cannot exceed
the weakest source, importance cannot exceed supporting importance, and effective
time is the latest supporting assertion time. This narrow baseline is deliberate;
related but differently worded assertions may yield no plan.

Events are immutable; `memory_lifecycle_states` is a versioned projection that can
be reconstructed from ordered events. Consolidation/review do not deactivate
sources. Supersession/forgetting affect retrieval only. Reactivation is an internal
policy/test operation, has no public UI or API, and requires valid active source
provenance; it cannot undo an active supersession link. Reverse dependency records
protect sources with dependents. Forgetting is not physical or privacy deletion.

Contradiction policy only automatically replaces high-confidence (at least .9),
strictly newer compatible assertions sharing a parsed `for ...` subject and explicit
correction/replacement wording. Negation, conditional/unmatched wording and uncertain
relations are review-only or no-action. Forgetting policy protects preferences,
corrections, previously retrieved records and dependents. Only episodes/summaries
at least 365 days old, below .5 confidence and never retrieved can qualify. Current
Phase 3 extraction rejects confidence below .8, so newly extracted records normally
cannot qualify; the low-confidence forgetting fixture tests supported stored data,
not a promise that current extraction automatically forgets old memories.

## Jobs, failure recovery and private deployment

After durable assistant completion and a successful terminal SSE send, the retained
post-terminal task performs extraction, accounts for actual context-injected IDs
and discovers bounded lifecycle candidates. Query candidates, budget exclusions,
failed/cancelled turns and inspection do not increment frequency. Events deduplicate
by owner/assistant/memory. The post-terminal task can be lost on process shutdown
before durable enqueue; it does not promise exactly-once processing of all chats.

Jobs are durable before notification, with source IDs, policy snapshot, three-attempt
default, retry/terminal reason, next attempt and lease token/generation. Notifications
contain only job ID/schema version; stored data determines owner and source authority.
A worker gets a 60-second lease and at most 30 seconds execution; configuration
requires execution shorter than the lease. It processes at most one policy operation
per job. Default candidate bound is four; source ancestor traversal is bounded at
64 per source. Oversized or unavailable sources safely reject work. Firestore begin,
read and commit RPCs disable SDK retries and share a deadline; conflicts retry via
the job boundary. Mutation transactions read sources, reservations, lifecycle state,
lease and necessary dependencies before writing. Lost commit acknowledgements and
crashes after apply are safe through deterministic event/operation identities.

The separate `personal_ai.worker:app` owns `/tasks/memory`; the public
`personal_ai.main:app` has no task mutation routes. Deploy uses private Cloud Run IAM,
Pub/Sub authenticated push, distinct runtime/invoker accounts and an API publisher
grant. Existing subscriptions receive updated push configuration. Default bootstrap
still exposes public chat under the fixed `local` owner; this is not authenticated
personal-data protection. No cloud deployment was performed for this phase.

Malformed notifications and completed/no-op/terminal jobs acknowledge with 204;
active leases and retryable outcomes return 503 for redelivery. Terminal durable
records retain safe reasons after bounded attempts; there is no separate dead-letter
queue or always-running scheduler. The worker does not republish unrelated jobs
on every delivery. Recover notifications explicitly from a configured runtime
identity with Firestore access and topic publisher permission:

```sh
cd backend
python -m personal_ai.memory.recovery --limit 50
```

Recovery publishes pending eligible jobs within a bounded deadline and clears
publish-pending only for the matching stored job generation. If publication fails,
run it again; duplicates are safe. Disabled master/worker gates return a disabled
result without clients or mutation. A job created while gates are off is not an
activation mechanism. Enable experiments only deliberately with synthetic data.

## Configuration, indexes and inspection

See [backend environment examples](../backend/.env.example) for all settings.
`MEMORY_EXPERIMENT_VARIANT=fixed` remains normal default. Consolidation, contradiction,
forgetting and worker execution each have explicit false gates; master memory must
be enabled for experiments. The frontend lifecycle-inspection gate is independently
false. Backend and proxy context-inspection gates plus the appropriate memory or
lifecycle inspection gate are required for supplied-record inspection. Reports show
variant/policy, lifecycle state/events, source IDs, score components, fit/exclusion
and null relevance with `similarity_unavailable_in_inspector`; they do not embed,
query a vector index, call an LLM, enqueue, rebuild state or increment frequency.

Provision and wait for all matching indexes in [the manifest](../firestore.indexes.json)
before deliberate cloud enablement. Besides Phase 3 KNN, Phase 4 needs derived KNN,
typed original-memory KNN for clustering, owner/type/effective-time maintenance
queries, owner/memory/event-sequence indexes in both directions, owner/source reverse
links and pending/retry job queries. Use the configured embedding dimension (default
768) for both original and derived vector indexes. The bootstrap deploy script
continues to provision Phase 1–2 indexes only and leaves all memory gates off;
there is no collection-scan fallback. Missing indexes remain non-fatal chat-memory
failures or retryable worker storage failures. Emulator checks assert persistence,
not production KNN or IAM.

## Verification and promotion

From the locked README environment, run:

```sh
make backend-test backend-lint context-eval memory-eval memory-lifecycle-eval
make frontend-test frontend-lint frontend-typecheck
make backend-build frontend-build
bash -n infrastructure/gcp/deploy.sh
git diff --check
```

The lifecycle suite uses synthetic records and fake embedding/queue/provider
boundaries but executes the production worker, policies, retriever and assembler.
Results identify variants, configuration identity, candidate/rank/injected IDs,
components, event IDs, jobs/attempts, statuses, exclusions, budgets and failures.
They contain no raw prompts, personal content or vectors. No judge model is used.

Promotion requires fixed baseline parity and deterministic replay, zero forbidden
selections, cross-owner/provenance violations, false automatic contradictions,
protected forgetting, budget violations or lifecycle-induced chat failures. All
required fixture selections and state outcomes must pass. Rank improvements and
source deduplication are measured within this corpus; they do not establish general
recall quality or justify automatically enabling a non-fixed variant.

Opt-in external checks, from `backend`, with explicitly selected synthetic projects:

```sh
RUN_MEMORY_LIFECYCLE_EMULATOR_TEST=1 python -m pytest tests/test_memory_lifecycle_manual.py -q
RUN_MEMORY_LIFECYCLE_PUBSUB_TEST=1 python -m pytest tests/test_memory_lifecycle_manual.py -q
```

The emulator check requires explicitly exported `FIRESTORE_PROJECT_ID` and
`FIRESTORE_EMULATOR_HOST`, stores random-namespaced synthetic records, uses fake
embeddings and verifies consolidation, correction/review, forgetting, replay,
projection reconstruction and read-only inspection. The Pub/Sub check requires
cloud Firestore, a deliberately enabled private worker with contradiction policy
and ready indexes, publisher credentials/permissions and the configured topic.
It publishes a synthetic durable maintenance job and waits for committed
supersession. These tests leave synthetic audit records; they do not delete data.
The Pub/Sub check exercises the pipeline, not a full negative IAM/security audit.
Run provider, real vector-quality and deployed disconnect checks separately.
