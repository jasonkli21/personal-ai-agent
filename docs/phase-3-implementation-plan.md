# Phase 3 implementation plan

This is the execution plan for adding simple, durable personal memory across
conversations. It builds on the delivered Phase 1 chat lifecycle and Phase 2
bounded context layer. The [Phase 1 plan](phase-1-implementation-plan.md)
remains authoritative for ownership, append-only message history, persistence,
and streaming. The [Phase 2 plan](phase-2-implementation-plan.md) remains
authoritative for token budgeting, branch-safe conversation summaries, and
context inspection.

Read the [project brief](project-brief.md) first. Its constraints override
convenience decisions in this plan. Read the [architecture notes](architecture.md)
for the `memory`, `context`, and data-lifetime boundaries.

## Execution status (2026-10-02)

P3.0–P3.8 are implemented locally; see the [implementation guide](phase-3-implementation-guide.md)
and [release evidence](releases/phase-3-simple-memory.md). Provider, emulator,
production vector-index and deployed checks remain pending, and all gates default
off. [ADR 0009](decisions/0009-simple-attributable-memory.md) clarifies extractive
semantic summaries, deterministic similarity bands, source-turn provenance,
optional-work deadlines, index ordering, and provider-free supplied-ID inspection.
Inspection estimates possible fit; it does not claim semantic relevance or replay
past requests. Phase 4 has not started.

## Scope boundary

Phase 3 adds a small, inspectable long-term-memory loop:

- Four explicit memory types: preference, episodic observation, semantic
  summary, and explicit user correction.
- Candidate extraction from completed active-conversation turns, with a human-
  auditable provenance link back to the source messages.
- Owner-scoped durable memory records with confidence, temporal metadata, and
  embedding metadata/vectors.
- Bounded semantic retrieval for a pending user query.
- Clearly labelled, token-budgeted memory injection through the existing
  context assembler.
- Deterministic offline evaluations for relevance, irrelevance, corrections,
  temporal change, ownership, and branch isolation.
- A disabled-by-default development inspection report for memory selection and
  provenance.

Phase 3 does **not** make memory a general research store. It does not add web
search, evidence, source adapters, research sessions, entities, ranking,
authentication, background workers, user-facing memory editing, automatic
consolidation, automatic contradiction resolution, decay, forgetting, or
cross-user sharing. Conversation summaries from Phase 2 remain branch-scoped
working context and must never be promoted to memory merely because they
exist.

Memory is attributable durable user knowledge, not an answer cache. Do not
store prices, availability, opening hours, externally sourced claims, model
conclusions, recommendations, credentials, or sensitive values merely because
they appeared in a conversation. Phase 5 evidence owns externally observed
facts; Phase 4 owns consolidation, supersession, contradiction handling, and
forgetting experiments.

The assistant must not claim that it remembers a fact unless the fact was
actually selected for the request or remains available in the active
conversation. Retrieval is advisory context: the current user request and
explicit correction take precedence over an older retrieved record.

## Dependency map

```text
P3.0 Fixtures/baseline ──> P3.1 Decisions/contracts ──> P3.2 Memory repository ──┬──> P3.4 Extraction ──┐
                                      |                                             |                       |
                                      └──> P3.3 Embeddings ─────────────────────────┴──> P3.5 Retrieval ──┼──> P3.7 Integration ──> P3.8 Evaluation/docs
P2 context assembler/inspector ───────────────────────────────────────────────────────> P3.6 Injection ────┘
```

Tasks marked **decision required** should stop for user input only when the
documented default is unsuitable. All other tasks should be implementable
without expanding the phase.

---

## Phase 3 — Simple long-term memory

### P3.0 — Establish memory fixtures and the no-memory baseline

**Dependencies:** Phase 2 completion review

**Goal:** make the first memory behavior measurable before it affects a model
request.

**Work:**

- Add version-controlled, synthetic memory fixtures for: a preference that is
  relevant in a later conversation; an episodic observation that should be
  retrieved only for a matching query; a semantic summary; an explicit user
  correction that changes an earlier statement; a temporal change; irrelevant
  but semantically similar facts; duplicate extraction input; and a branch
  created by edit-and-retry.
- Define fixture metadata: source conversation/message IDs, active branch,
  candidate records expected from extraction, expected retrieval IDs and order
  or permitted set, records that must not be retrieved, required provenance,
  query embedding fixture, and expected context-fit result.
- Record a Phase 2 baseline for each query: selected conversation context,
  absence of cross-conversation memory, and the required fact that cannot be
  supplied without Phase 3 memory. Do not call an LLM, embedding endpoint,
  Firestore, or a judge model to create this baseline.
- Add a compact evaluation-result format recording fixture version, extraction
  result, created/skipped memory IDs, embedding model/configuration class,
  retrieval candidate/selected IDs and scores, excluded IDs/reasons, context
  selection result, and failure reason. Do not record raw private content.

**Requirements:**

- Fixtures and committed results contain only invented data. They must not be
  derived from real personal conversations, provider logs, or production
  vectors.
- Offline tests use deterministic fake extractors, embedders, clocks, vector
  indexes, and token counters. Similarity values and tie-breaking must be
  repeatable.
- A fixture must state a concrete fact or record expectation, rather than claim
  that a response "feels more personalized."
- The correction and temporal-change fixtures must distinguish an older record
  that remains auditable from the newer context that should be preferred.

**Acceptance criteria:**

- The suite proves that Phase 2 alone cannot provide a fact from a separate
  conversation, without using a real provider.
- Every extraction, repository, retrieval, injection, and integration test uses
  at least one shared named fixture.
- The fixture format can distinguish extraction failure, embedding failure,
  no qualifying memory, context-budget exclusion, and model/provider failure.

**Out of scope:** importing existing chats, a production benchmark service,
model-as-judge scoring, or subjective personality evaluation.

### P3.1 — Record Phase 3 decisions and define memory contracts

**Dependencies:** P3.0  
**Decision required:** yes

**Goal:** make the meaning, provenance, retrieval, and privacy limits of a
memory explicit before durable records are written.

**Work:** add accepted ADRs and provider-neutral domain contracts for these
defaults:

1. **Memory vocabulary:** a `preference` is a durable user inclination; an
   `episodic_observation` is an attributable statement about a particular
   experience or event; a `semantic_summary` is a durable, source-grounded
   generalization; and an `explicit_correction` records the user's direct
   replacement or clarification of an earlier statement. These names are
   storage types, not model assertions of truth.
2. **Extraction authority:** candidate extraction runs only after a completed
   user/assistant turn on the active branch. It may use a bounded structured
   extractor behind a provider-neutral interface; rule-based candidates remain
   acceptable for explicit test cases. Extraction output is a candidate, not
   permission to invent facts.
3. **Write policy:** persist only valid, source-grounded candidates that pass
   allow/deny policy and embedding validation. Extraction is idempotent for the
   same source fingerprint and normalized candidate. It does not delete or
   mutate earlier memories.
4. **Retrieval policy:** retrieve owner-scoped, active records using query
   embedding similarity, a configured minimum similarity, a fixed candidate
   limit, deterministic tie-breaking, and a small type-aware preference for an
   explicit correction when otherwise comparable. This is a fixed Phase 3
   policy, not the multi-factor experimental scoring of Phase 4.
5. **Correction and time rule:** a matching explicit correction and a more
   recent temporal statement are labelled and ordered ahead of older memories.
   Older records remain auditable and may be returned to a developer report;
   Phase 3 does not infer broad contradiction relationships or mark records
   superseded automatically.
6. **Injection rule:** memories are optional, clearly labelled historical
   context. The assembler never drops/truncates the system instruction or
   newest user message to include them, and never presents memory as a current
   user utterance or external evidence.
7. **Privacy rule:** extraction excludes secrets, authentication material,
   financial account identifiers, health/legal data, and other configured
   sensitive categories by default. Raw prompts, embeddings, and memory text
   are not logged by default. The user must review provider-data suitability
   before enabling real personal extraction.

Define provider-neutral contracts in `memory` and `context` (names may vary):

- `MemoryExtractor.extract(source_turn, prior_active_messages) ->
  Sequence[MemoryCandidate]`.
- `Embedder.embed(texts) -> Sequence[Embedding]`.
- `MemoryRepository` for owner-scoped create, idempotency lookup, vector
  candidate search, and retrieval by ID for inspection.
- `MemoryRetriever.retrieve(owner_id, query, active_messages) ->
  RetrievalResult`.
- `MemoryContextSelector.select(retrieval_result, available_budget) ->
  MemorySelection` or an equivalent extension of `ContextAssembler`.

**Required memory fields:**

| Record | Required fields |
| --- | --- |
| Memory | `id`, `owner_id`, `memory_type`, `content`, `normalized_content`, `confidence`, `status`, `source_conversation_id`, `source_message_ids`, `source_fingerprint`, `observed_at`, `effective_at`, `created_at`, `embedding`, `embedding_model`, `embedding_dimensions`, `schema_version` |

`status` is initially `active` or `rejected`; rejected records are retained
only when needed for an auditable extraction attempt and must never be
retrievable. `observed_at` is when the source turn was recorded;
`effective_at` is the time asserted by the user when explicit and otherwise
equals `observed_at`. `source_fingerprint` is calculated from the ordered
source message IDs, roles, and content. `normalized_content` is used only for
idempotency/deduplication and must not replace the original attributable text.

**Required configuration:**

| Setting | Purpose |
| --- | --- |
| `MEMORY_ENABLED` | Master gate; disabled by default until provider/privacy review is complete |
| `MEMORY_EXTRACTION_ENABLED` | Separately permits post-turn candidate extraction |
| `MEMORY_EMBEDDING_MODEL` | Configured embedding model ID, never a source-code constant |
| `MEMORY_EMBEDDING_DIMENSIONS` | Expected vector dimension; rejects incompatible vectors |
| `MEMORY_MAX_CANDIDATES_PER_TURN` | Bound on valid candidates persisted from one turn |
| `MEMORY_RETRIEVAL_CANDIDATE_LIMIT` | Bound on vector candidates inspected per query |
| `MEMORY_RETRIEVAL_LIMIT` | Bound on records offered to the context assembler |
| `MEMORY_MIN_SIMILARITY` | Conservative retrieval threshold |
| `MEMORY_MAX_CONTEXT_TOKENS` | Maximum token budget available to selected memories |
| `MEMORY_INSPECTION_ENABLED` | Disabled-by-default development inspection gate |

**Requirements:**

- Settings reject invalid limits, non-positive vector dimensions, a retrieval
  limit greater than its candidate limit, or a memory-context budget larger
  than the Phase 2 usable input budget.
- `MemoryCandidate` includes type, content, confidence, source message IDs,
  optional asserted/effective time, and an extraction rationale code. It must
  not expose provider-specific objects outside the adapter.
- Memory contracts return structured reasons for rejection, duplicate skip,
  low similarity, inactive status, branch mismatch, and budget exclusion.
- Existing Phase 1 owner scoping and UUID validation, and existing Phase 2
  bounded-context/error rules, remain unchanged.

**Acceptance criteria:**

- ADRs record all seven decisions, their consequences, and accepted status.
- Contract tests reject an invalid memory type, a source outside the active
  branch, a mismatched embedding dimension, and an impossible setting set.
- Example environment settings load with safe fake values and leave extraction,
  retrieval, and inspection disabled by default.

**Out of scope:** user consent UX, bulk import, user memory deletion controls,
automatic contradiction graphs, memory decay, or an embedding-model migration.

### P3.2 — Implement durable, owner-scoped memory persistence

**Dependencies:** P3.1

**Goal:** persist attributable memory records without leaking Firestore or
vector-index details into application services.

**Work:**

- Add `Memory` domain records, validation, and an owner-scoped repository
  protocol. Keep memory data separate from conversations, messages, Phase 2
  summaries, and future evidence records.
- Implement Firestore storage in a dedicated `memories` collection. Store
  queryable owner/status/type/temporal metadata and the configured embedding in
  the repository representation; keep Firestore classes and query objects out
  of services.
- Implement the repository methods needed for create, idempotency lookup,
  active-vector candidate lookup, retrieval by ID, and inspection. Document or
  provision required composite/vector indexes and their deployment ordering.
- Implement an in-memory fake repository/vector index with the same ownership,
  filtering, deterministic ordering, and dimension-validation semantics for
  tests.
- Use a source fingerprint plus normalized candidate identity to prevent
  repeated post-turn attempts from creating duplicate active records.

**Requirements:**

- Every read and write scopes by `owner_id`; a vector result for another owner
  is never eligible even if it is a closer match.
- Repository methods return only `active` records for normal retrieval. A
  rejected record is neither injected nor returned by a normal application
  retrieval path.
- Persist source conversation/message IDs and fingerprint atomically with the
  record. A memory must never be persisted without valid attributable source.
- Validate vector dimension, finite numeric values, content bounds, type,
  confidence range, UTC timestamps, UUIDs, and schema version at the storage
  boundary.
- Firestore failures map to typed application errors. Unit tests use the fake;
  Firestore is used only in an explicit emulator/manual suite.

**Acceptance criteria:**

- Repository tests cover create, owner isolation, idempotent duplicate skip,
  active-status filtering, source provenance retrieval, similarity ordering,
  deterministic ties, malformed records, and dimension mismatch.
- A manual emulator check can create and retrieve a synthetic memory without
  source changes.
- No Firestore call occurs in ordinary unit/evaluation tests.

**Out of scope:** batch migration, deletion/retention controls, TTL, vector
backfill, collection-wide scans, or cross-owner search.

### P3.3 — Add a replaceable embedding boundary

**Dependencies:** P3.1, P3.2

**Goal:** produce compatible embeddings for memory writes and query retrieval
without coupling the memory subsystem to one provider.

**Work:**

- Define an injectable `Embedder` protocol and deterministic fake embedding
  implementation for offline tests and fixtures.
- Add a configured Gemini embedding adapter through the existing `llm`
  boundary. Model ID, dimensions, timeout, and batching limits come from
  settings; provider SDK request/response types stay in the adapter.
- Normalize and validate the same vector representation for candidate content
  and queries. Fail closed when the configured model/dimension differs from a
  stored vector rather than comparing incompatible embeddings.
- Map unavailable provider, timeout, invalid configuration, malformed response,
  and dimension mismatch to stable application errors/structured extraction or
  retrieval outcomes.

**Requirements:**

- Memory text is embedded only after allow/deny validation and only through the
  configured provider boundary. API keys are never logged.
- Query embedding occurs only when retrieval is enabled; Phase 1/2 behavior is
  unchanged when the master memory gate is off.
- The fake embedding space must support fixture-defined relevant, irrelevant,
  and tie cases without randomness or network access.
- Do not reuse chat token counts as embedding dimensions or claim that
  embedding similarity is factual truth.

**Acceptance criteria:**

- Unit tests prove stable fake vectors, correct batching/order, validation of
  non-finite/wrong-size vectors, and safe error mapping.
- A credentialed opt-in manual test embeds synthetic text with the configured
  model and validates the reported dimension; it is skipped by default.
- Provider code remains isolated to `llm`/adapter modules.

**Out of scope:** multiple embedding providers at once, hybrid keyword search,
reranking models, embedding cache infrastructure, or model migration.

### P3.4 — Extract, validate, and persist memory candidates after a completed turn

**Dependencies:** P3.0, P3.1, P3.2, P3.3

**Goal:** turn a small number of attributable user statements into useful
durable records without delaying or corrupting chat delivery.

**Work:**

- Add a bounded `MemoryExtractionService` invoked only after an assistant turn
  has completed successfully and the active path still contains its source
  messages. Provide its dependencies through injection and test with fakes.
- Give the structured extractor the completed source turn and only the minimum
  active-branch context needed for coreference; direct it to return zero or
  more candidates from the four Phase 3 types, exact source IDs, confidence,
  effective time when explicit, and stable rationale codes.
- Validate candidates against source content, active branch, type-specific
  rules, configured maximum count/length, sensitive-data policy, confidence,
  and source fingerprint. Reject unsupported external claims and model
  conclusions.
- Normalize valid candidate text, perform idempotency lookup, generate its
  embedding, validate the vector, and persist an active record with full
  provenance.
- Record aggregate outcome metadata (created, duplicate, rejected, failed) for
  diagnostics/evaluation without logging raw conversation or memory text.
- Run extraction outside the successful SSE event sequence. A completed answer
  must remain completed if extraction is disabled or fails; extraction failure
  must not create a new assistant error event or retry the chat model call.

**Requirements:**

- The source must include a completed user statement. An assistant-only claim
  cannot become memory. An assistant response may supply context but not add
  unsupported facts.
- An explicit correction must preserve the user's replacement wording and link
  to its source; it must not silently rewrite or delete the earlier memory.
- Candidate processing must be idempotent across retries and disconnect/replay
  scenarios. The same source must not create two active equivalent memories.
- Sensitive-data rejection is conservative and observable only through a safe
  reason code, never raw rejected content in normal logs or API responses.
- No Pub/Sub job, worker endpoint, background consolidation, or Phase 4
  lifecycle mutation is introduced. The bounded post-completion work may be
  synchronous or framework-managed post-response work, but must have an
  explicit timeout and must not block SSE completion.

**Acceptance criteria:**

- Service tests cover a valid record of each type, no-candidate output,
  candidate/source mismatch, branch rewrite before processing, sensitive-data
  rejection, duplicate retry, embedding failure, repository failure, and
  extraction timeout.
- Tests prove extraction never runs for failed/streaming/superseded turns and
  never changes Phase 1 assistant status or SSE event order.
- An opt-in synthetic manual turn creates inspectable source-linked memory when
  all gates are enabled; normal defaults create none.

**Out of scope:** extraction from historical backfill, manual approval UI,
automatic correction matching beyond fixed retrieval ordering, or summary
consolidation.

### P3.5 — Retrieve relevant memory with simple, deterministic policy

**Dependencies:** P3.0, P3.1, P3.2, P3.3

**Goal:** find a small relevant set for a new query without treating every
stored fact as prompt context.

**Work:**

- Add `MemoryRetriever` that embeds the pending user query, requests a bounded
  owner-scoped active vector candidate set, and applies the fixed Phase 3
  threshold/limit/type-aware ordering policy.
- Validate candidates again after retrieval: owner, status, vector model and
  dimensions, source provenance, content bounds, and current query eligibility.
- Preserve result metadata: candidate IDs/similarities, selected IDs/order,
  exclusion reasons, retrieval configuration class, and errors. Return no
  memories rather than using an unbounded or incompatible fallback.
- For an explicit correction or temporal-change fixture, prefer the newer,
  matching correction/statement over an older matching statement. Retain older
  records in developer-only audit metadata when they were considered; do not
  mutate their status.
- Query only after the new user message is durably persisted and use the same
  post-mutation active path for normal, regenerate, and edit-and-retry flows.

**Requirements:**

- Retrieval is scoped strictly to the owner and runs only when `MEMORY_ENABLED`
  is true. Disabled, unavailable, or no-match retrieval returns an empty,
  structured result and leaves Phase 2 context behavior intact.
- Similarity is one input to a fixed selection policy. Do not add Phase 4
  importance, frequency, decay, consolidation, learned ranking, or generic
  LLM reranking.
- A failure to embed the query or search the index is non-fatal to the chat
  turn by default: continue without memory and record a safe diagnostic. A
  deployment may choose a stricter policy only through an explicit future ADR.
- Raw query text, memory text, and vectors are excluded from default logs.

**Acceptance criteria:**

- Tests cover exact relevant retrieval, below-threshold exclusion, irrelevant
  semantic-neighbor exclusion, deterministic ties, owner isolation, inactive
  filtering, incompatible-vector exclusion, correction preference, temporal
  preference, and empty/error fallback.
- All normal, regenerate, and edit-and-retry paths request retrieval through
  the same boundary after their active path is determined.
- Offline fixture runs are deterministic and make no provider or Firestore
  calls.

**Out of scope:** keyword/hybrid retrieval, query rewriting, multi-hop memory
reasoning, user-configurable filters, or research/evidence retrieval.

### P3.6 — Select and inject memory through the token-budgeted context layer

**Dependencies:** P2.3, P2.5, P2.6, P3.1, P3.5

**Goal:** make memory available to the model in a bounded, explainable form
without regressing Phase 2 context correctness.

**Work:**

- Extend the existing context assembly contract to accept a `RetrievalResult`
  and select complete memory records within `MEMORY_MAX_CONTEXT_TOKENS` and
  the Phase 2 total input budget.
- Assemble in a stable order: system/application instruction; clearly labelled
  selected personal-memory block; compatible Phase 2 conversation summary;
  selected recent active-branch turns; then the pending user message. Keep the
  Phase 2 newest-message and complete-turn rules intact.
- Render each selected memory with its type and temporal qualifier where
  present, for example as historical personal context rather than an assistant
  utterance. Never include embeddings, source IDs, hidden scores, or developer
  rationale in the prompt.
- Exclude a whole memory record when it cannot fit. Do not truncate individual
  records, bypass the Phase 2 safety margin, or turn a fitting normal request
  into a mandatory-content overflow because optional memory is unavailable.
- Extend the disabled-by-default Phase 2 context inspection endpoint/panel (or
  an equivalent read-only memory-inspection endpoint) with selected/excluded
  memory IDs, types, source conversation/message IDs, timestamps, token counts,
  similarity bands/scores, and exclusion reasons. The normal chat response
  remains unchanged.

**Requirements:**

- Memory injection must be optional: no results, a retrieval failure, a
  disabled gate, or a token exclusion still produces the same valid Phase 2
  request shape without a memory block.
- The assembler does not mutate memory records, conversation summaries,
  messages, or timestamps.
- Inspection is owner-scoped, read-only, disabled by default, and must not
  call an LLM, embed text, create a record, refresh a summary, or expose raw
  content beyond what an existing conversation response already authorizes.
- Context reports identify memory as memory, never evidence. They must not
  falsely imply a memory was used when it was merely retrieved then excluded.

**Acceptance criteria:**

- Context tests prove stable ordering, whole-record selection, budget
  adherence, newest-user retention, no selection of inactive/cross-owner
  records, and correct fallback when no memory fits.
- Inspection tests cover enabled report shape, disabled behavior, owner
  isolation, selected versus merely considered records, and no mutation or
  provider calls.
- A long-conversation fixture proves a compatible Phase 2 summary, selected
  memories, and recent turns can coexist within the one total budget.

**Out of scope:** showing a memory-management screen, editing/deleting a
memory, allowing the user to pin memories, prompt replay, or production
telemetry dashboards.

### P3.7 — Integrate memory into durable streamed chat turns

**Dependencies:** P3.4, P3.5, P3.6

**Goal:** make the memory loop part of every eligible chat turn while retaining
the Phase 1/2 durability and failure behavior.

**Work:**

- Refactor `ChatTurnService` to persist the user message, construct the
  post-mutation active path, retrieve memory, and pass the result to the
  context assembler before creating the assistant `streaming` record.
- Preserve the established handling of a context-budget rejection: the user
  message remains auditable, no misleading assistant placeholder is created,
  and no model stream starts.
- Start the normal streamed answer from the assembled bounded context. On
  successful completion, schedule/begin the bounded extraction workflow using
  the completed source turn; do not alter browser SSE names or event order.
- Extend dependency injection for repository, extractor, embedder, retriever,
  and memory-aware context selector. Existing route tests continue to supply
  fakes.
- Surface aggregate safe diagnostics in logs/evaluation only, such as memory
  gate state, selected count, aggregate token count, and error class. Do not
  return private memory diagnostics through SSE.

**Requirements:**

- The successful stream remains `message.created` (user), `message.created`
  (assistant), zero or more `response.delta`, then `response.completed`.
- Memory retrieval failure is isolated from provider streaming. Chat must still
  succeed without memory where Phase 2 would have succeeded.
- Extraction begins only after final assistant persistence; a client disconnect,
  provider failure, or branch replacement cannot produce memory from an
  incomplete or obsolete path.
- Regenerate and edit-and-retry use their post-mutation path for retrieval and
  do not extract from the superseded source. They retain old memory records for
  audit; Phase 3 does not attempt to reconcile them.

**Acceptance criteria:**

- Route integration tests cover disabled-memory parity, successful relevant
  retrieval/injection, no-match fallback, retrieval failure fallback, context
  budget exclusion, successful post-completion extraction, extraction failure,
  regenerate, edit-and-retry, and client/provider failure.
- Tests prove that memory work does not change SSE ordering, assistant
  persistence semantics, or Phase 2 overflow behavior.
- Existing Phase 1 and Phase 2 API, storage, streaming, and context tests
  remain green with memory disabled and enabled fakes.

**Out of scope:** progress SSE events for extraction, automatic retry queues,
workers, user-facing memory notices, or a change to the public chat API.

### P3.8 — Evaluate, document, and verify Phase 3 behavior

**Dependencies:** P3.0, P3.4, P3.5, P3.6, P3.7

**Goal:** show that the system retrieves useful durable context across
conversations without over-retrieving, hiding provenance, or advancing into
Phase 4 behavior.

**Work:**

- Run the full deterministic memory evaluation suite and add it to documented
  local and CI commands. Compare its results with the P3.0 no-memory baseline.
- Record extraction precision against fixture expectations, source-provenance
  validity, duplicate suppression, retrieval relevance, non-retrieval of
  irrelevant facts, correction/temporal ordering, token-budget adherence, and
  empty/failure fallback. Record configuration/model class, never credentials
  or real private content.
- Run opt-in credentialed manual checks using synthetic conversations: extract
  one allowed preference, start a separate conversation with a matching query,
  inspect the selected record/provenance, and verify a non-matching query does
  not inject it. Confirm the provider/data policy before using any personal
  text.
- Update README, settings documentation, API/context inspection documentation,
  Firestore index/deployment guidance, and privacy notes. Explain that memory
  is durable, provenance-linked, fallible, not evidence, and not yet
  user-editable or automatically corrected/forgotten.
- Confirm deployment defaults leave `MEMORY_ENABLED`, extraction, and memory
  inspection disabled until an intentional configuration and provider-data
  review. Do not add a worker or Pub/Sub behavior to make Phase 3 work.

**Requirements:**

- CI remains offline, deterministic, and free of a GCP project, provider key,
  real embeddings, and personal data. Credentialed checks are explicitly
  opt-in and skipped by default.
- A recorded manual result distinguishes configured-model behavior from fake
  evaluation behavior and states any provider/vector-index limitations.
- Documentation must not promise perfect recall, correctness, privacy beyond
  the provider policy, automatic conflict resolution, or freshness of external
  facts.

**Acceptance criteria:**

- A clean checkout runs backend tests/lint, frontend tests/lint/type-check, and
  the memory evaluation suite without cloud credentials or a model key.
- The evaluation record shows every selected memory has valid active-source
  provenance, respects ownership and budget, retrieves each required relevant
  fixture, excludes each required irrelevant fixture, and prefers the expected
  correction/temporal context without mutating old records.
- The normal/deployed configuration has memory extraction, retrieval, and
  inspection disabled unless deliberately enabled, and the Phase 2 inspector
  remains protected.
- No Phase 4+ consolidation, automatic supersession/contradiction handling,
  decay/forgetting, search/evidence, entity, ranking, worker, or domain-agent
  behavior was added to satisfy Phase 3.

**Out of scope:** A/B tests, production dashboards, real-user memory import,
authentication rollout, bulk deletion/export, and a Phase 4 migration.

## Phase 3 completion review

Before declaring Phase 3 done, verify all task acceptance criteria and answer
these questions:

1. Are all persisted active memories one of the four defined types, source-
   linked to completed active-branch user statements, and owner-scoped?
2. Can the system explain, without exposing raw secrets or prompts, why a
   candidate was created, skipped, rejected, retrieved, excluded, or injected?
3. Does every memory-bearing model request pass through the same Phase 2 token-
   budgeted context assembler, while preserving the newest user message?
4. Can retrieval failure, no match, or a memory token exclusion ever break a
   chat turn that would otherwise succeed in Phase 2? (The required answer is
   no.)
5. Does an explicit correction or newer temporal statement receive the defined
   retrieval preference without silently deleting, rewriting, or claiming to
   resolve the older record?
6. Are external observations, recommendations, provider output, and Phase 2
   conversation summaries kept out of durable memory unless they meet the
   defined attributable user-knowledge policy?
7. Do all automated checks and deterministic evaluations run without a GCP
   project, provider key, real embeddings, or real personal data?
8. Are memory extraction, retrieval, and inspection disabled by default, with
   provider-data suitability reviewed before enabling real personal use?
9. Has the implementation avoided Phase 4 consolidation, contradiction
   handling, supersession, decay, forgetting, workers, and research features?

Only after all answers are yes should work advance to Phase 4.
