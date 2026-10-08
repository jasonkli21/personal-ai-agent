# Phase 16 independent review — Findings and resolution

Review date: 2026-10-07 (America/Los_Angeles). Original reviewed HEAD: `0fdf6fd` (`Implement phase 16 inference contracts`), against parent `e28d2b6`. The fixes and local verification are recorded below and in the [Phase 16 implementation evidence](personal-ai-chapter-2/phase-16-implementation-evidence.md). Existing untracked Phase 11–15 review documents were preserved.

## Verdict and resolution

**All nine findings below are addressed in the Phase 16 implementation and covered by local regression checks.** Fixes keep application-owned memory authorization through extraction, retrieval, counting, embeddings, and background consolidation; require explicit Gemini success metadata; close compatibility streams deterministically; bind authoritative counts to their generation endpoint and structured schema; enforce synchronous deadlines; preserve full embedding-space identity in Postgres lifecycle discovery; retain safe per-invocation metadata in non-chat generation paths; validate chat stream exhaustion after terminal events; and count the exact structured extraction request.

Resolution scope remains Phase 16. No provider, routing, registry product, quota accounting, or re-embedding was added. Phase 21 persistence of runtime attribution remains outside scope; per-invocation attribution is retained locally. The Phase 14 immutable policy/source references and Phase 15 derived-context revocation/membership gaps remain open prerequisites. Live Gemini, persistence, cloud/IAM, provider privacy, and production-identity checks remain unverified.

## Findings

### 1. [P1] Memory disclosure does not consume the application's authorization decision

**Affected:** `memory/extraction.py:61–79`, `memory/services.py` extraction/retrieval, `llm/context.py:41–70`, `llm/memory.py:39–59`, `api/dependencies.py` memory wiring, and post-completion/lifecycle extraction. Paths are under `backend/src/personal_ai/`.

Memory extraction counts the user-source prompt before constructing a hard-coded `InferenceContext('personal', 'personal', 'memory-extraction-policy-v1')`. Neither the extractor nor extraction service receives the resolved application policy. Post-completion extraction is scheduled by feature flags, irrespective of whether that application permits this auxiliary disclosure. Thus adding an envelope satisfies Gemini's presence check without establishing the application's permission or actual sensitivity. Regex exclusions and exact-source validation are valuable content controls, but do not authorize remote disclosure.

The counter and embedding adapter also expose remote operations without an authorization envelope; embedding validates a dummy `ChatMessage('user', 'embedding')`, not a disclosure decision. Ordinary planned memory retrieval has selection authorization upstream, but extraction and lifecycle embedding have no equivalent application-policy admission. This is an inherited policy gap left open by P16.2, which explicitly requires closing generation/count/embedding bypasses; it is not a request to implement future provider eligibility/routing.

**Expected fix:** Carry or resolve the applicable server-owned policy for memory extraction, remote counting, and document/query/lifecycle embeddings. Admit each disclosure before the first remote call; derive classification and version from that decision. Keep advisory failure behavior, content exclusions, and source validators. Background work must retain the required policy/scope or re-resolve it rather than synthesize permission.

**Validation:** With memory flags enabled, deny auxiliary memory disclosure in an otherwise chat-authorized application and prove zero counter, structured-generation, and embedding calls. Cover allowed policy attribution, sensitivity ceilings, extraction after terminal success, retrieval, and lifecycle/background operations. Add negative direct capability/admission fixtures without requiring live credentials.

### 2. [P2] Gemini invents terminal success when provider finish metadata is absent

**Affected:** `llm/gemini.py:366–373`, streamed terminal mapping and `_generate`; `tests/test_llm.py`, `tests/test_context_provider.py`, `tests/test_memory_provider.py`.

`_terminal_status(None, True)` returns `success`. A stream that emits text and exhausts without a finish reason therefore becomes an explicit successful terminal event. Non-streamed text with absent candidates/finish metadata likewise succeeds. This recreates the iterator-exhaustion assumption P16.0 was meant to remove and can persist a partial chat as completed or accept an incomplete summary/extraction. Several mocked successful responses omit finish metadata, so they currently encode this defect.

**Evidence:** A stub returning `text='partial', candidates=[]` from `complete` produced `metadata.status == 'success'` and passed the success contract.

**Expected fix:** Require a recognized provider success signal. Missing/unspecified finish metadata must produce an incomplete/invalid outcome even when text exists; preserve partial chat output. Handle explicit prompt blocking safely. Update successful transport fixtures to include realistic terminal metadata.

**Validation:** Stream and completion cases for text-without-finish, empty/unspecified reasons, STOP, MAX_TOKENS, rejection/blocking, and missing terminal chunks. Prove failed chat persistence and no acceptance of truncated summary/structured results.

### 3. [P2] Text compatibility facades lost deterministic provider teardown

**Affected:** `llm/gemini.py:46–82`; closing tests in `tests/test_llm.py`; text consumers in research, iterative synthesis, proposals, and booking extraction.

Both `stream` and `stream_bounded` now wrap an inner async generator without a `finally` that closes it. Closing the outer facade while suspended at a yielded delta does not close the inner generator/provider iterator or owned client deterministically. The parent revision explicitly closed `bounded` in `stream`'s `finally`; that protection was removed. Failed validation/oversized output or consumer disconnect can leave remote work and resources alive until async-generator finalization.

**Evidence:** Inside a still-running event loop, read one delta, call `await iterator.aclose()`, and check the provider's finalization flag: it was false immediately and after a loop tick. The current tests inspect after `asyncio.run` returns; loop shutdown finalizes leaked generators and masks the regression. Chat's direct `stream_events` producer has separate cleanup and is not the affected facade path.

**Expected fix:** Each facade must own and explicitly close its inner iterator under bounded cancellation-safe cleanup. Callers that abandon a text stream on validation failure must close the iterator as well. Preserve injected-client ownership.

**Validation:** Assert iterator and owned-client closure *inside* the running loop, immediately after closing `stream` and `stream_bounded`. Cover early break, oversized/invalid consumer output, task cancellation, owned versus injected clients, and a cleanup method that stalls. Do not rely on loop shutdown or garbage collection.

### 4. [P2] Fit admission is not bound to the generation endpoint

**Affected:** `llm/preparation.py:17–48`, `memory/extraction.py:61–72`, and final assembly/dispatch integration in `context/builder.py`, `context/assembler.py`, `services/chat_turns.py`.

The new preparation helper compares a count only with the counter's own identity. It never receives or compares the generator identity. A self-consistent counter for a different provider/model/serializer is accepted, so it cannot establish that the input fits the endpoint receiving it. Identity verification is skipped entirely when the counter lacks `identity`; `kind='provider'` is accepted regardless of authoritative confidence. Chat's final fit likewise never binds the new count identity to `GenerationClient.identity`.

**Evidence:** A counter returning one token with identity `other/other-model/other-serializer` and confidence `reported` was admitted by `prepare_bounded_input` while the intended generator was Gemini. The two identities were never compared. Current Gemini-only wiring happens to pair matching settings; the provider extension seam does not enforce that invariant.

**Expected fix:** Bind preparation/final fit to the selected generation endpoint's identity and approved counter semantics. Reject missing/mismatched identity and unapproved count confidence before generation, and before calling a counter that is not authorized for that endpoint. Preserve explicitly labelled offline estimation paths. No provider registry or routing engine is needed.

**Validation:** Distinct synthetic generator/counter fixtures for provider, model, and serializer mismatch; absent identity; reported/estimated versus authoritative counts; matching success. Exercise memory and actual chat/standalone assembly-to-dispatch paths, not just counter self-consistency.

### 5. [P2] Synchronous generation ignores the configured timeout cap

**Affected:** `llm/gemini.py:_generate`, summaries and structured memory extraction.

`stream_events` uses `min(request timeout, settings.request_timeout_seconds)`, but `_generate` forwards the caller timeout directly in per-request HTTP options. That override can exceed the client default and violate the documented stricter-of-two behavior. Neutral completion and structured generation therefore have weaker bounds than streaming.

**Evidence:** With `request_timeout_seconds=1`, `complete(..., timeout_seconds=90)` dispatched with HTTP timeout `90000` milliseconds.

**Expected fix:** Apply the configured cap to synchronous operations and retain caller deadlines. Check deadline expiration after synchronous dispatch before accepting a result; an outer preparation deadline should continue to bound the whole operation.

**Validation:** Stub/transport assertions for both completion and structured generation with caller deadlines shorter and longer than configuration, expired requests, and a result arriving after its deadline. Confirm safe timeout errors and no success acceptance after timeout.

### 6. [P2] Postgres lifecycle discovery still searches using the legacy default space

**Affected:** `persistence/postgres_lifecycle.py:374–382`, compared with `memory/lifecycle_repositories.py:discover_related` and the expanded `PostgresMemoryRepository.search`.

`discover_related` passes only model and dimensions. Search now also filters provider, normalization, tasks, and version, whose defaults select `google_genai/.../v1`. For an anchor with another valid provider/version, discovery searches the wrong space, misses compatible siblings, and can return incompatible IDs for later rejection. The in-memory implementation compares the entire space, so offline lifecycle fixtures do not establish Postgres parity. Consolidation's later compatibility rejection prevents creating a mixed-space derived record, but does not repair discovery.

**Expected fix:** Forward the anchor's full embedding-space identity into lifecycle search and defensively exclude incompatible results. Keep existing vector values unchanged.

**Validation:** Recording-repository unit fixture proves every space component is forwarded. Repository parity/opt-in Postgres fixtures with identical model/dimensions but distinct providers and versions prove compatible-only discovery, including legacy payloads with absent version defaulting to `v1`.

### 7. [P2] Non-chat text generation discards per-invocation attribution

**Affected:** `llm/gemini.py:stream_bounded`, `agents/research/service.py:285`, `agents/research/iterative_service.py:1569`, `itinerary_proposals/service.py:601`, `booking_extractions/service.py:267`.

These production paths consume only text through the compatibility facade. Gemini constructs actual provider/model/usage/status metadata internally, then discards it after its success check. None of these callers receives or records it. Chat logs attribution and memory extraction returns it; those implementations do not satisfy P16.2's per-invocation attribution requirement for the other inventoried paths. This also leaves failure/incomplete usage invisible where providers supply it.

**Expected fix:** Expose terminal metadata through a small neutral consumption seam or operation result and retain safe per-invocation attribution in each existing path, including non-success outcomes when available. Keep task validators in their services. Bounded logging or returned invocation metadata suffices; do not add Phase 19 accounting or Phase 21 automatic-turn persistence.

**Validation:** Each path consumes a distinct synthetic provider identity and preserves actual identity, terminal status, usage source/confidence, and explicit unavailable usage. Assert logs/metadata contain no prompts, evidence values, booking documents, secrets, or raw provider errors. Preserve existing synthesis/citation/proposal/extraction validators.

### 8. [P2] Chat's post-terminal protocol check cannot observe trailing events

**Affected:** `services/chat_turns.py:465–475` and `_produce_deltas:648–651`.

The consumer waits for a queue tail and intends to reject data after terminal. But the producer stops immediately on the first terminal event, closes the generator, and queues `None`. It never observes a second terminal, trailing delta, or exception following the terminal yield, so the consumer's invalid-tail check is unreachable for those violations. A malformed adapter can be recorded as successful despite violating the new stream contract.

**Evidence:** A synthetic iterator yielding success then a delta was closed before its second yield; `_produce_deltas` delivered terminal followed by `None`.

**Expected fix:** Validate end-of-stream after the terminal under the remaining deadline, without releasing trailing deltas to clients, or establish an equivalently enforced adapter conformance boundary. Reject extra events/errors safely and preserve cleanup/backpressure behavior.

**Validation:** Success terminal followed by delta, duplicate terminal, exception, normal exhaustion, and stalled exhaustion. Verify no completed persistence on a violated protocol and no deadlock/disconnect leak.

### 9. [P2] Structured extraction counts a different request from the one generated

**Affected:** `memory/extraction.py:61–72`, `llm/preparation.py`, `llm/context.py:60–68`, `llm/gemini.py:223–229`.

Memory extraction prepares/counts only messages. The REST `generateContentRequest` used for counting contains model, contents, and system instruction, but no generation configuration/schema. Only afterward does structured generation attach `MemoryCandidateResponse.model_json_schema()`. The counter API/cache has no schema parameter, so this is not the exact structured endpoint input. Google documents that response-schema size contributes to the input token limit. [Google structured-output documentation](https://firebase.google.com/docs/ai-logic/generate-structured-output).

Consequently the authoritative text-only count can admit a structured request whose full input exceeds the memory ceiling or endpoint allowance. The existing over-budget test checks only a synthetic `totalTokens` value; it never checks count/generation schema parity. This is separate from finding 4's wrong-endpoint admission: it occurs with today's correctly paired Gemini clients.

**Expected fix:** Prepare one neutral structured request including its schema and count the actual adapter serialization/configuration used for generation. Include count-affecting configuration in cache identity. Do not duplicate schema instructions in user text as a substitute for counting the actual request.

**Validation:** Locked-SDK/REST transport fixtures compare the effective schema and other count-affecting fields between counting and generation. Add a schema-aware near-ceiling case where text alone fits but the complete structured request does not, proving zero generation calls. Keep live count compatibility opt-in and report it separately.

## Original review evidence

Reviewed the Phase 16 written plan, guide/evidence, parent-to-commit diff, neutral and Gemini adapters, SDK transport fixtures, context assembly/deadlines/authorization, chat state handling, memory services/lifecycle, Postgres integration, composition wiring, research/proposal/booking consumers, architecture/product intent, and preceding Phase 15 review/fix context.

The original review ran on `0fdf6fd` and recorded:

- `source backend/.venv/bin/activate && make backend-test backend-lint`: **743 passed, 26 skipped, one existing Starlette/httpx deprecation warning; lint passed**.
- In-memory/stub reproductions for missing finish metadata, facade closure during a live event loop, unrelated-counter admission, synchronous timeout override, and trailing-event suppression. No external calls or repository test changes.
- `git diff --check` after writing this handoff.

No live Gemini, Postgres/DynamoDB Local, cloud/IAM, production identity, or provider privacy acceptance was performed during the original review. The existing manual Gemini smoke checks do not provide comprehensive structured/embedding conformance evidence.

## Resolution coverage

| Finding | Resolution and regression coverage |
| --- | --- |
| 1. Memory disclosure authorization | Application policy now gates memory count, structured extraction, query/document embeddings, and background consolidation. `tests/test_memory_disclosure_authorization.py`, `tests/test_memory_provider.py`, and terminal post-completion integration coverage exercise denied and allowed paths. |
| 2. Missing Gemini finish metadata | Missing or unspecified terminal metadata is incomplete; prompt blocking is rejected safely. `tests/test_llm.py` and adapter transport fixtures cover missing, STOP, and non-success outcomes. |
| 3. Compatibility stream teardown | Bounded text facades own and close event iterators under bounded shielded cleanup. `tests/test_llm.py` checks closure inside a running loop, including injected and owned clients. |
| 4. Counter/generator endpoint mismatch | Preparation rejects absent/mismatched identities and non-authoritative counts before dispatch; chat and standalone assembly also validate the returned authoritative count identity against the generation endpoint. `tests/test_llm.py` and `tests/test_context_builder.py` cover provider, model, serializer, missing identity, confidence, and assembled-count mismatch cases. |
| 5. Synchronous timeout cap | Completion and structured generation apply the configured timeout cap and reject late results. `tests/test_llm.py` covers caller/configuration bounds and late completion. |
| 6. Postgres lifecycle embedding space | Discovery forwards and rechecks every embedding-space field. `tests/test_postgres_lifecycle_contract.py` covers mismatched providers/versions and legacy `v1` defaults. |
| 7. Non-chat invocation attribution | Research, iterative synthesis, itinerary proposals, and booking extraction retain safe provider/model/status/usage metadata and close their streams. `tests/test_llm.py` checks populated and unavailable usage logging; the full backend suite exercises these consumers. No prompts, evidence, documents, secrets, or raw provider errors are logged. |
| 8. Trailing chat events | The producer continues through stream exhaustion after terminal and chat rejects trailing data, duplicates, errors, or stalled completion. `tests/test_chat_stream_lifecycle.py` covers protocol violations and prevents successful persistence. |
| 9. Structured request count parity | Memory extraction counts the same response schema and count-affecting generation configuration, included in the cache identity, that structured generation sends. `tests/test_memory_provider.py` checks REST schema parity and schema-aware near-ceiling rejection before generation. |

Final command results, exact tested base revision, skipped checks, and remaining external gates are in the [implementation evidence](personal-ai-chapter-2/phase-16-implementation-evidence.md). Offline fakes and mocked SDK transports do not establish live provider, emulator, cloud, or production-security behavior.
