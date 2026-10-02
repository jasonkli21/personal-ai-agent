# ADR 0009 — Simple attributable memory

Status: Accepted. Date: 2026-10-02.

## Context

Phase 3 adds cross-conversation user knowledge to the existing bounded chat path.
It must remain distinguishable from lossy working summaries and external evidence.
The Phase 3 plan supplies defaults; the user explicitly authorized implementation.

## Decisions

1. Persist `preference`, `episodic_observation`, `semantic_summary`, and
   `explicit_correction`. These classify attributable statements, not truth.
2. Run a structured extractor after a completed active user/assistant turn.
   Send only that bounded turn, never summaries. Start with exact excerpts and
   explicit first-person markers; a semantic summary is a user's explicit
   generalization, not a model-invented paraphrase. This conservative policy
   intentionally rejects many otherwise plausible memories.
3. Validate source IDs, exact user wording, confidence >= .8, type/rationale,
   and sensitive/external-content rules before embedding. Persist append-only
   records. Identity hashes owner, ordered user-source fingerprint, type and
   normalized text; concurrent creates are idempotent. `source_turn_id` additionally
   identifies the completed assistant that authorized the extraction attempt.
   Regeneration of unchanged user wording does not create another equivalent record.
4. Use configured Gemini embeddings through `llm`, normalized nonzero finite
   vectors, and owner/status/model/dimension-prefiltered Firestore cosine KNN.
   Do not scan the memory collection or fall back to incompatible vectors.
   Default model is `gemini-embedding-001`, 768 dimensions; configuration controls
   both. Firestore permits at most 2048 dimensions, so settings enforce that ceiling.
5. Require similarity >= .8. Sort by descending .05-wide similarity band,
   correction first, effective time descending, exact similarity descending,
   then UUID. This small fixed preference is not contradiction resolution.
   Revalidate user-source fingerprints and completed active user turns on reads;
   edited-out sources stay auditable but cannot be injected. Earlier independent
   statements remain active and inspectable.
6. Count the complete memory-bearing request through the shared assembler.
   Preserve Phase 2 selected history/summary and mandatory newest prompt.
   Add whole records only within memory and total budgets. Render labelled
   historical personal context before the working summary/history. Current
   instructions and explicit corrections take precedence. Similarity, provenance
   IDs and vectors stay out of model prompts. A counting error falls back to the
   already counted Phase 2 request.
7. Master, extraction and inspection gates default off. Sensitive/external
   categories and configurable terms are denied before provider embedding;
   sensitive queries also skip embedding. Log safe aggregate counts/reasons only.
   Exact excerpts and deny rules are defense in depth, not comprehensive privacy
   classification or authentication. Provider-data suitability needs intentional
   review before personal use.

## Consequences and gaps closed

Retrieval has a separate short deadline within one quarter of remaining chat
preparation time, leaving time for Phase 2 preparation. Every memory provider call
has a timeout and disables retries. Memory storage RPCs use remaining operation
budgets; transactional begin/commit are explicitly deadline-bound inside the
repository because the SDK decorator otherwise uses default retries. Source
ancestor reads and completed-assistant validation share the write transaction,
so a concurrent branch rewrite cannot persist an obsolete new memory.

After the ASGI layer successfully sends the terminal SSE frame, it schedules
bounded extraction in a retained in-process task whose service work runs in a
worker thread. Closing the client stream after that event does not cancel the
task. Process shutdown can still interrupt it; no durable queue, replay
guarantee or background worker is introduced. Successful chat durability never
depends on extraction. Deadline checks prevent processing late
extractor/embedding results.

Read-only inspection accepts bounded explicitly supplied memory IDs. It validates
ownership/provenance and estimates fit without embedding the query, searching
semantically, or claiming the records were used in a previous live request.
Similarity is null in this planning report; deterministic evaluations retain actual
fake similarity scores. This resolves the plan's tension between semantic selection
inspection and its prohibition on embedding during inspection.

When memory is disabled, its default budget need not fit a deliberately tiny
Phase 2 test configuration. An enabled or explicitly configured memory budget
must fit the usable input budget. Normal environment examples fit both budgets.

Provider and vector-index behavior still needs opt-in credentialed verification.
No authentication, user memory editing, consolidation, automatic supersession,
forgetting, evidence/search, or worker changes are included.

References: [Gemini embeddings](https://ai.google.dev/gemini-api/docs/embeddings),
[Firestore vector search](https://firebase.google.com/docs/firestore/vector-search),
[Phase 3 plan](../phase-3-implementation-plan.md).
