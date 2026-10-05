# Phase 8 implementation plan — Provider-neutral inference and embedding contracts

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Create neutral seams without intelligent routing.

### Normative commitments from the integrated roadmap

- Reconcile stream-only chat contract with structured generation.
- Add minimal neutral generation operations.
- Add explicit embedding boundary with model/dimension metadata.
- Add fake backend.
- Migrate existing Gemini call paths incrementally, closing generation/count/embedding disclosure bypasses before new providers are enabled.

### Phase acceptance criteria

- Higher-level migrated paths need no provider SDK import.
- Current chat streaming remains functional.
- Vector compatibility is preserved.

### Explicitly out of scope

- smart routing
- new provider selection
- quota optimization
- embedding re-index migration

## Current state and reuse

LLMClient.stream and optional concrete stream_bounded exist; structured extraction and embedding protocols are partial. Neutral generation/completion/usage/count metadata require extension, not a second SDK layer.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/llm/client.py`
- `backend/src/personal_ai/llm/gemini.py`
- `backend/src/personal_ai/llm/context.py`
- `backend/src/personal_ai/llm/memory.py`
- `backend/src/personal_ai/llm/errors.py`
- `backend/src/personal_ai/llm/fake.py`
- `backend/src/personal_ai/context/contracts.py`
- `backend/src/personal_ai/memory/contracts.py`
- `backend/src/personal_ai/memory/services.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 4, 7. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Provider SDK objects stay below the inference boundary.
- Embedding metadata includes provider/model/dimensions/normalization-task semantics.
- Existing memory vectors/indexes remain compatible until an explicit embedding migration.

## Work packages

### P8.0 — Minimal neutral generation and completion

**Depends on:** required phases above.

Extend the stream-only boundary with the actual stream, bounded generation and structured-result needs of current tasks. Define terminal success/incomplete/failure, actual provider/model, safe errors and usage confidence/source. Keep task schemas/validation in services. Preserve SSE compatibility via a narrow facade if needed; fakes support terminal events, bounds and cancellation rather than pretending iterator exhaustion proves every provider succeeded.

**Acceptance:** Fake and Gemini operations report explicit terminal/usage/error metadata while existing SSE callers remain compatible.

### P8.1 — Provider-aware fit and embedding metadata

**Depends on:** P8.0.

Use separate counter and embedding capabilities. Final assembly uses the selected endpoint serializer, context limits and an approved counter; planning estimates stay labelled. Gemini preserves its authoritative REST count transport. Document supported conservative local count bounds before using another endpoint; do not call an ineligible Gemini counter. Embedding results include provider/model/dimensions/normalization/task semantics; adapt existing Embedder and preserve normalized 768-dimensional Gemini spaces/indexes and immutable v1/v2 records. No re-index migration.

**Acceptance:** Endpoint-specific fit/count is policy-safe; old vectors and v1/v2 records remain readable unchanged.

### P8.2 — Migrate all disclosure paths incrementally

**Depends on:** P8.1.

Inventory chat, summaries, research/iterative synthesis, itinerary proposals, booking extraction, memory extraction and embeddings. Move direct Gemini memory extraction through shared bounded context preparation and neutral structured generation while preserving exact user-source validation and post-terminal advisory behavior. Migrate existing SDK use within llm, wire through dependencies, and leave no unrestricted generation/count/embedding bypass before new providers are enabled. Add per-invocation attribution now; Phase 13 persists selected runtime attribution on automatic turns.

**Acceptance:** No existing generation/count/embedding path bypasses the neutral admission/preparation inventory; exact-source validators still pass.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R8.1: Reconcile stream-only chat contract with structured generation. | P8.0 |
| R8.2: Add minimal neutral generation operations. | P8.0 |
| R8.3: Add explicit embedding boundary with model/dimension metadata. | P8.1 |
| R8.4: Add fake backend. | P8.0 |
| R8.5: Migrate existing Gemini call paths incrementally, closing generation/count/embedding disclosure bypasses before new providers are enabled. | P8.2 |

## Targeted verification and closeout

Fake-based contract tests cover terminal loss, unsupported operations, malformed JSON, error mapping, deadlines/cancellation, no SDK leakage, serializer/count mismatch, forbidden count/embedding disclosures and byte-for-byte compatible stored-vector reads. Preserve all task validators.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make memory-lifecycle-eval`, `make research-eval`, `make iterative-research-eval`, `make itinerary-proposal-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Gemini count/structured-output/embedding compatibility remains opt-in; an offline fake does not prove a tokenizer bound or live provider behavior.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
