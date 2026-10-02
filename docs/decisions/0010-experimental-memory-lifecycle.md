# ADR 0010: Experimental memory lifecycle

- Status: accepted
- Date: 2026-10-02
- Scope: Phase 4 lifecycle, scoring, consolidation, and worker behavior

## Context

Phase 3 stores immutable version 1 memories grounded in one completed
conversation turn and up to two exact user-message excerpts. Phase 4 needs
auditable scoring and lifecycle actions without changing that identity or
provenance contract. The public API is currently unauthenticated, so mutation
jobs must have a separate private worker entry point protected by Cloud Run IAM.

## Decisions

1. Keep version 1 memory IDs, reads, serialization, and exact-source validation
   unchanged. Multi-source records use an explicitly versioned `DerivedMemory`
   schema in an indexed collection. They list two to four original version 1
   memories, fingerprints, conversations, turns, user messages, and the exact
   excerpts covered by the derived text. No backfill or multi-hop derivation is
   performed.
2. Store lifecycle decisions as append-only events and maintain a rebuildable
   state projection. Every event has an expected state version and deterministic
   idempotency identity. Missing projections mean initial active state only for
   a valid source record; malformed or unavailable projections fail closed.
   Consolidation and review events do not suppress their sources. Retrieval
   events count only records actually injected after successful completion.
3. Keep `fixed` as the default retrieval variant. `scored` reorders validated
   original memories. `consolidated` may select derived memories. All variants
   honor committed forgotten and superseded state; scored never selects derived
   records. A selected derived record suppresses duplicate source representation
   only in that prompt block, and only after the derived record fits.
4. Score policy `score-v1` uses weights .50 similarity, .15 importance, .15
   effective-time recency, .10 successful retrieval frequency, and .10
   confidence, normalized by positive weight sum. Its identity covers all
   weights, half-life, normalization rule, and policy version. Recency uses a
   90-day half-life; importance by type is correction 1.0, preference .8,
   semantic summary .6, and episode .4. Derived importance is capped by its
   sources. Invalid score inputs exclude the record.
5. Consolidation is deterministic and extractive. It only joins exact,
   policy-approved compatible user assertions with explicit source coverage.
   A preference needs repeated explicit preference support. Similarity is a
   candidate selector, never proof of a shared subject. No model writes or
   rewrites durable memory in this phase.
6. Automatic contradiction requires an identical normalized subject key,
   compatible memory type, explicit correction or temporal replacement wording,
   a strictly newer effective time, and confidence at least .9. Other cases are
   review-only. Forgetting is limited to episodes or semantic summaries at least
   365 days old, below .5 confidence, never retrieved, and without a correction,
   current preference, or active dependent. Neither action deletes a source.
7. Persist durable jobs before Pub/Sub publication. Jobs keep candidate IDs,
   policy snapshot, bounded attempts, retry reason, next attempt, lease token,
   and lease generation. Every worker write is fenced by a live token. Source
   messages, root cuts, lifecycle versions, dependencies, and leases are
   revalidated in the same transaction that writes derived state. A stored
   operation key makes a post-apply crash replay-safe. Pending jobs have a
   bounded republish command.
8. The public API image contains chat and read-only inspector routes only. A
   separate worker ASGI app owns lifecycle mutation routes. Pub/Sub push uses
   Cloud Run IAM with a dedicated invoker identity; the worker runs as a
   different identity with only its runtime permissions. This protects the task
   transport and does not add end-user authentication.
9. All Phase 4 gates default off on API and worker. The shared Phase 2 context
   assembler remains the only prompt path; fitting Phase 2 context keeps its
   allocation priority. Inspection uses supplied stored IDs, makes no provider
   calls or writes, and reports null relevance when similarity is unavailable.

## Consequences

Phase 3 documents remain readable without migration, but derived records require
their own collection-group vector index. Lifecycle state can be reconstructed
from events. The experiment measures ranking and conservative policy outcomes;
it does not establish truth or guarantee recall. Forgetting affects ordinary
retrieval eligibility and is not deletion. Provider, emulator, and deployed
checks remain opt-in and are reported separately from offline fake tests.

## Rejected alternatives

- Storing a multi-conversation summary as a version 1 `Memory` would fabricate a
  single source turn and invalidate exact excerpt provenance.
- Allowing an LLM to synthesize assertions would add provider dependence and
  unsupported claims without a required measured benefit.
- Running worker routes on the public API image would expose mutation behavior
  through the existing public service.
