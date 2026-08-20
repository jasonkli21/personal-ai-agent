# Phase 2 implementation plan

This is the execution plan for keeping a long conversation coherent while
respecting a model's context window. It builds on the delivered Phase 1 chat
vertical slice; [the Phase 1 plan](phase-1-implementation-plan.md) remains the
source of the persistence, streaming, ownership, and branch-history behavior
that this phase extends.

Read the [project brief](project-brief.md) first. Its constraints override
convenience decisions in this plan. Read the [architecture notes](architecture.md)
for the intended `context` boundary.

## Scope boundary

Phase 2 adds context-window management for the current conversation only:

- A provider-neutral context-assembly boundary used for every model turn.
- Conservative, token-aware selection of a valid conversation prefix and recent
  active-branch turns.
- Durable, branch-safe summaries of older active conversation history.
- A disabled-by-default development context-inspection view.
- Offline regression evaluations and opt-in quality checks for long threads.

Phase 2 does **not** add long-term memory, embeddings, retrieval, search,
research, evidence, entities, ranking, authentication, background workers, or
domain modules. A conversation summary is a lossy working-context artifact for
one branch, not a user fact and never a Phase 3 memory record. The assistant
still has no web, tool-use, or citation capability.

The Phase 1 fixed message-count cap is replaced by the Phase 2 context budget.
The application must never silently exceed the configured input budget or drop
the newest user message. A turn whose mandatory content cannot fit fails with a
safe, actionable error instead of truncating content.

## Dependency map

```text
P2.1 Decisions/contracts ──> P2.2 Token accounting ──> P2.3 Context assembly ──> P2.5 Chat integration
          |                         |                         |                         |                 |
P2.0 Quality fixtures ──────────────┴─────────────────────────┼─────────────────────────┤                 |
                                                            P2.4 Summaries ──────────────┘                 |
P2.3 Context assembly ───────────────────────────────────────────────────────────────────> P2.6 Inspector |
P2.4 Summaries + P2.5 Chat integration ───────────────────────────────────────────────────> P2.7 Evaluation/deploy
P2.6 Inspector ───────────────────────────────────────────────────────────────────────────> P2.7 Evaluation/deploy
```

Tasks marked **decision required** should stop for user input only when the
documented default is unsuitable. All other tasks should be implementable
without expanding the phase.

---

## Phase 2 — Context-window management

### P2.0 — Establish long-conversation fixtures and the baseline

**Dependencies:** Phase 1 completion review

**Goal:** make context-management changes measurable before they alter model
requests.

**Work:**

- Add version-controlled, synthetic evaluation conversations: a short control,
  a thread that exceeds the old Phase 1 message cap, a thread with a fact only
  in an old turn, a branch created by edit-and-retry, and an oversized newest
  message.
- Define fixture metadata: active branch, expected included message IDs,
  expected excluded message IDs, required old facts, and whether the input must
  be rejected.
- Record a Phase 1 baseline for each fixture: fixed-cap behavior, input-message
  count, and known failure or loss of old context. Do not use real personal
  conversations in fixtures or committed evaluation output.
- Add a small evaluation-result format that records fixture version, context
  configuration, selected summary ID (if any), selected message IDs, estimated
  and provider token counts, result, and failure reason.

**Requirements:**

- Offline tests must use deterministic fake token counters and fake summary/
  model clients; they must not require a provider key, Firestore, or an
  evaluation judge model.
- Fixtures must exercise only the active path. Superseded messages may appear
  as audit setup but cannot be eligible context.
- A quality assertion must be grounded in a fixture's explicit required facts,
  not a subjective claim that a response is "better."

**Acceptance criteria:**

- The fixture suite reproduces the old fixed-cap limitation without calling an
  LLM.
- Every later context-selection and summary test uses at least one shared,
  named fixture.
- The fixture format makes a failed mandatory-content fit distinguishable from
  an ordinary model/provider failure.

**Out of scope:** a benchmark service, model-as-judge scoring, production
analytics, or importing private chat history.

### P2.1 — Record the Phase 2 decisions and define context contracts

**Dependencies:** P2.0  
**Decision required:** yes

**Goal:** make token accounting, summary validity, and overflow behavior
explicit before changing chat-turn construction.

**Work:** add short accepted ADRs and provider-independent domain contracts for:

1. **Budget authority:** the configured model's provider token counter is the
   authority when available. A deterministic local estimator is permitted only
   for offline planning and tests, and applies a configurable safety margin; it
   must not claim exact provider token counts.
2. **Budget allocation:** reserve tokens for the system instruction, a final
   model response, and a safety margin before selecting conversation context.
   The remaining input budget is shared by a compatible summary and complete
   recent turns. The newest user message is mandatory.
3. **Selection rule:** select newest complete active-branch turns backwards,
   preserving chronological order in the final request. Do not include an
   orphaned assistant message or truncate an individual persisted message.
4. **Summary validity:** a summary is usable only when its recorded source
   message IDs and fingerprint are a contiguous prefix of the current active
   branch. A regenerate or edit-and-retry that changes that prefix makes the
   summary ineligible; old summaries remain auditable rather than overwritten.
5. **Refresh execution:** summaries are generated synchronously and only when
   necessary to construct a bounded request. They are never generated by a
   Phase 2 Pub/Sub job. Summary failure falls back to a smaller recent-turn
   context when that fits; otherwise the turn fails safely.
6. **Inspection boundary:** context inspection is disabled by default and is
   available only when an explicit development setting is enabled. It must
   report selection metadata but never settings secrets or provider internals.

Define provider-neutral contracts in `context` (names may vary):

- `TokenCounter.count(messages) -> TokenCount`, including whether the result is
  provider-authoritative or estimated.
- `ContextAssembler.assemble(active_messages, pending_user_message) -> AssembledContext`.
- `ConversationSummarizer.summarize(source_messages, prior_summary) -> SummaryDraft`.
- `ConversationSummaryRepository` for owner-scoped create and compatible-summary
  lookup.

**Required summary fields:**

| Record | Required fields |
| --- | --- |
| Conversation summary | `id`, `conversation_id`, `owner_id`, `content`, `source_message_ids`, `source_fingerprint`, `covers_through_message_id`, `source_token_count`, `summary_token_count`, `model`, `created_at` |

The fingerprint is calculated from the ordered message IDs, roles, and content
of the source prefix. `source_message_ids` are retained so compatibility is
verifiable without trusting a summary's text.

**Required configuration:**

| Setting | Purpose |
| --- | --- |
| `MAX_CONTEXT_TOKENS` | Maximum provider input-plus-output context capacity used by the application |
| `MAX_RESPONSE_TOKENS` | Tokens reserved for the assistant response |
| `CONTEXT_SAFETY_MARGIN_TOKENS` | Conservative allowance for tokenization/request overhead |
| `SUMMARY_TRIGGER_TOKENS` | Unsummarized-history threshold that permits summary creation |
| `MAX_SUMMARY_TOKENS` | Upper bound for summary output included in context |
| `CONTEXT_INSPECTION_ENABLED` | Disabled-by-default development-only inspector gate |

**Requirements:**

- The chosen defaults must be documented for the configured model but model IDs
  remain environment configuration, not source-code constants.
- The summary prompt must say that it is a working summary, preserve explicit
  uncertainty and user corrections, and must not invent facts, preferences, or
  external evidence.
- Contracts return structured selection/overflow reasons. They do not log raw
  chat content by default.
- Existing Phase 1 ownership scoping, UUID validation, append-only history, and
  safe error-envelope rules remain unchanged.

**Acceptance criteria:**

- ADRs state the six decisions above, their consequences, and accepted status.
- Contract tests reject a summary whose source prefix is no longer active.
- Settings load from the example environment with safe fake values and reject
  impossible budgets, such as a response reserve greater than total context.

**Out of scope:** embedding tokenization, memory schemas, a universal tokenizer,
automatic model fallback, or a permanent summary retention policy.

### P2.2 — Implement conservative token accounting and budget validation

**Dependencies:** P2.0, P2.1

**Goal:** know whether a request can fit before sending it to the model.

**Work:**

- Implement an injectable token-counter boundary and deterministic fake.
- Add the configured-provider implementation without letting provider SDK types
  escape `llm` or `context` adapters. Count the final model request shape,
  including system instruction and summary wrapper text, when the provider
  supports it.
- Implement one budget calculation shared by normal turns, regenerate,
  edit-and-retry, summary generation, and inspection.
- Validate configuration and compute a structured budget report: capacity,
  response reserve, safety margin, mandatory content, optional summary,
  optional history, selected total, and counter kind.
- Add stable safe errors for `context_budget_invalid` and
  `context_message_too_large`; preserve Phase 1 provider-error handling for
  failures after a request has been sent.

**Requirements:**

- The budget calculation must reserve `MAX_RESPONSE_TOKENS` and
  `CONTEXT_SAFETY_MARGIN_TOKENS` before optional context selection.
- The estimator's result must be rounded conservatively and visibly labelled
  estimated in inspection and evaluation output.
- A latest user message that cannot fit with mandatory instructions and the
  reserve is rejected before creating a streaming assistant placeholder or
  calling the LLM. Its already-persisted user message remains auditable and the
  conversation remains usable through edit-and-retry.
- Token counts and errors must not include or log message content.

**Acceptance criteria:**

- Unit tests cover exact-fit, one-token overflow, configuration overflow,
  estimated-count safety margin, and no-provider-call rejection.
- The same fixture has identical selection decisions with the deterministic fake
  counter on every test run.
- Provider counting is opt-in/manual when credentials or a provider endpoint are
  required; the offline suite remains self-contained.

**Out of scope:** charging/accounting, provider rate-limit management, or
token-level UI rendering.

### P2.3 — Implement active-branch context assembly

**Dependencies:** P2.1, P2.2

**Goal:** give the LLM the smallest coherent context that fits the budget.

**Work:**

- Add a `context` application service that receives an ordered active path and
  produces immutable `AssembledContext` data for the existing `LLMClient`.
- Assemble, in order: short application instruction, one compatible summary if
  selected, then the selected chronological recent turns, ending with the
  pending user message.
- Treat a turn as a completed user message plus its completed assistant response
  when both are available; retain the newest pending user message even before it
  has an assistant reply.
- Walk backwards through complete turns until the remaining budget is consumed;
  reverse the selected set before issuing the request.
- Return selection metadata: selected and excluded message IDs, selected
  summary ID, token reports, and explicit reasons for exclusions or overflow.
- Make regeneration and edit-and-retry request their active path through the
  same assembler; remove Phase 1's message-count gate after the new budget gate
  is in use.

**Requirements:**

- Only `completed` active-branch message content can be sent as historical
  context. Failed, streaming, and superseded content is never silently treated
  as complete history.
- The assembler must not mutate persisted messages, summaries, or conversation
  timestamps.
- Summary text must be wrapped as clearly labelled historical context, not
  represented as a user or assistant utterance.
- If no compatible summary exists, selecting fewer recent turns is valid; only
  mandatory-content overflow is an error.

**Acceptance criteria:**

- Tests prove chronological output, newest-user retention, complete-turn
  selection, deterministic exclusions, and active-branch isolation.
- Tests prove a summary from the pre-edit branch is ignored after
  edit-and-retry or regenerate changes its covered prefix.
- A normal, regenerate, and edit-and-retry turn all invoke the same assembly
  boundary and produce a bounded request.

**Out of scope:** cross-conversation context, memory retrieval, semantic
selection, attachments, or a user-configurable context strategy.

### P2.4 — Persist and refresh branch-safe conversation summaries

**Dependencies:** P2.1, P2.2, P2.3

**Goal:** preserve useful older conversational context without repeatedly
sending the entire history.

**Work:**

- Add Firestore and in-memory summary repositories, owner-scoped and isolated
  from raw message repository details. Document/provision any required summary
  query indexes.
- Implement compatible-summary lookup from the active branch using the stored
  source IDs and fingerprint.
- Add a provider-neutral summarizer interface and provider adapter using bounded
  non-streaming generation or an equivalent bounded collection of deltas.
- When context assembly needs older information and the unsummarized prefix
  reaches `SUMMARY_TRIGGER_TOKENS`, summarize the largest compatible prefix
  that can itself fit the summary-input budget. A later summary may use a
  compatible prior summary plus additional complete turns.
- Validate generated summary size and persist a new immutable record only after
  the source fingerprint and all token limits are verified.
- On summary failure, surface a stable safe diagnostic to the assembler and
  continue with the fitting recent context when possible.

**Requirements:**

- Summary source content is only the current active branch and consists of
  complete turns. The summary must never include a pending request or a failed,
  streaming, or superseded message.
- The summarizer has an explicit output ceiling no greater than
  `MAX_SUMMARY_TOKENS`; oversized, empty, malformed, or provider-failed output
  is not persisted.
- Summaries are append-only. The application must neither overwrite an old
  summary nor mark source messages superseded merely because they were
  summarized.
- Firestore calls are hidden behind repositories; fake repositories cover all
  automated tests.

**Acceptance criteria:**

- Repository tests cover creation, owner isolation, compatibility lookup,
  invalid branch fingerprints, and newest compatible summary selection.
- Service tests cover first summary, incremental summary, invalidated summary
  after a branch rewrite, output-limit rejection, and summary-provider failure.
- A long-thread fixture can select a valid summary plus recent turns within the
  configured budget, without calling a real provider in automated tests.

**Out of scope:** user-visible summary editing, summary export, background
consolidation, semantic compression, or saving summaries as Phase 3 memories.

### P2.5 — Integrate context management into streamed chat turns

**Dependencies:** P2.2, P2.3, P2.4

**Goal:** make every streamed model request bounded and explainable without
regressing Phase 1 durability or SSE behavior.

**Work:**

- Refactor `ChatTurnService` so its request history is supplied by the context
  assembler rather than directly from every active completed message.
- Place summary lookup/creation and assembly after the new user message is
  durably persisted but before an assistant `streaming` record is created.
- Preserve Phase 1 event order for successful streams. If context preparation
  fails after the user record exists, return a safe error response and do not
  create a misleading assistant streaming record.
- Extend dependency injection for the token counter, assembler, summary
  repository, and summarizer. Tests continue to inject fakes.
- Retain current cancellation, response-size, provider-timeout, retry, and
  branch-supersession behavior.

**Requirements:**

- A successful SSE stream is still `message.created` (user),
  `message.created` (assistant), zero or more `response.delta`, then
  `response.completed`.
- Context preparation errors use the established safe JSON/API error envelope
  when streaming has not begun; a provider failure after streaming begins still
  emits exactly one `response.error` and persists the assistant as failed.
- Regenerate and edit-and-retry use the post-mutation active path, never the
  replaced path or an incompatible summary.
- Logs may contain request ID, counter kind, aggregate token counts, selected
  counts, and error class, but never raw prompts, summaries, responses, or
  secrets by default.

**Acceptance criteria:**

- Route integration tests cover successful bounded streaming, context overflow,
  summary-backed streaming, summary failure fallback, regenerate, and
  edit-and-retry.
- Tests prove no LLM stream starts for a rejected mandatory-message overflow.
- Existing Phase 1 stream lifecycle and persistence tests remain green after
  replacing the count-based limit.

**Out of scope:** streaming a separate summary-progress UI, parallel summary
generation, automatic retry of summary generation, or changing browser SSE
event names.

### P2.6 — Add a development-only context-inspection view

**Dependencies:** P2.3, P2.5

**Goal:** let a developer verify what will be sent to the model without making
context selection opaque.

**Work:**

- Add a read-only, owner-scoped inspection endpoint for a conversation's active
  path, guarded by `CONTEXT_INSPECTION_ENABLED` and unavailable when disabled.
- Return the assembler's structured report: capacity/reserves/margins, counter
  kind, selected summary metadata and coverage, selected message metadata,
  excluded message metadata and reasons, and overflow result.
- Add a small clearly labelled development panel or route in the frontend. Use
  the existing server-side API proxy; it must be absent or inaccessible in the
  normal disabled configuration.
- Document how to enable it locally and how to confirm that it is disabled in
  deployed environments.

**Requirements:**

- The inspection request must not call the model, create a summary, mutate
  storage, or alter the conversation's `updated_at` value.
- Do not return API keys, provider request objects, stack traces, or raw content
  that the normal conversation endpoint would not already return. Prefer
  message IDs, roles, timestamps, character counts, token counts, and summary
  provenance over duplicating text.
- A disabled inspector returns a consistent not-found or forbidden response
  without revealing configuration details.

**Acceptance criteria:**

- API tests cover enabled report shape, disabled behavior, malformed IDs,
  unknown conversations, owner isolation, and no mutation/provider calls.
- Frontend tests cover the disabled/default state and an enabled report with
  selected/excluded context explanations.
- Manual local verification shows estimated versus provider-authoritative token
  counts distinctly when each counter is configured.

**Out of scope:** a production admin console, arbitrary prompt replay, context
editing, exposing summary content separately, or telemetry collection.

### P2.7 — Evaluate, document, and verify the Phase 2 behavior

**Dependencies:** P2.0, P2.4, P2.5, P2.6

**Goal:** demonstrate that long conversations remain bounded and retain the
right context before advancing to long-term memory.

**Work:**

- Run the full offline quality suite and add it to the documented local and CI
  commands.
- Compare the Phase 1 baseline with Phase 2 on every fixture. Record selection
  correctness, budget adherence, summary compatibility, required-old-fact
  retention, and expected rejection behavior in a non-secret release note or
  evaluation record.
- Run an opt-in credentialed manual check with the configured model on a
  synthetic long conversation. Confirm that an old required fact is represented
  in a compatible summary, recent turns remain present, and the streamed answer
  remains coherent. Record model ID/configuration class, not credentials or
  prompt content.
- Update README and developer documentation with new settings, the overflow
  behavior, summary lifecycle, local inspection workflow, and the rule that
  summaries are not memory.
- Update deployment guidance so the development inspector remains disabled by
  default and no new worker/Pub/Sub behavior is introduced.

**Requirements:**

- CI remains fully offline and deterministic. Credentialed checks are clearly
  opt-in and skipped by default.
- A recorded manual result must distinguish provider-authoritative counts from
  estimates and state any model-specific limitations.
- Documentation must not promise perfect recall: summaries are lossy, branch
  scoped, and are used only to manage context.

**Acceptance criteria:**

- A clean checkout runs backend tests, lint, frontend tests, lint, type-check,
  and the context evaluation suite without cloud credentials or a model key.
- The evaluation record shows every fixture stayed within budget, selected no
  superseded context, and either retained its required old facts through a
  compatible summary or failed with the expected safe overflow result.
- The development inspector is verified disabled in the normal/deployed
  configuration.
- No Phase 3+ memory, embedding, retrieval, search, evidence, or worker
  behavior was added to make Phase 2 work.

**Out of scope:** production observability dashboards, A/B experimentation,
automated quality promotion, multi-user rollout, or a Phase 3 memory migration.

## Phase 2 completion review

Before declaring Phase 2 done, verify all task acceptance criteria and answer
these questions:

1. Does every normal, regenerate, and edit-and-retry model request pass through
   one token-budgeted context assembler?
2. Can the application prove which messages and summary were selected without
   exposing secrets or mutating the conversation?
3. Is the newest user message never silently dropped or truncated, and is an
   impossible request rejected before an LLM stream begins?
4. Can an old summary ever be reused after an edit/retry or regeneration changes
   the active prefix it summarizes? (The required answer is no.)
5. Do summaries remain append-only, branch-scoped working context rather than
   long-term memories?
6. Do all automated checks and deterministic evaluations run without a GCP
   project, provider key, or real personal data?
7. Is the inspector disabled by default and absent from the normal deployment
   path?

Only after all answers are yes should work advance to Phase 3.
