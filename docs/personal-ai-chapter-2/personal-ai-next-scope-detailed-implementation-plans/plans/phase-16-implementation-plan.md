# Phase 16 implementation plan — Provider-neutral inference and embedding contracts

Renumbered on 2026-10-06 from former next-scope Phase 8. This plan preserves the former detailed plan’s normative commitments, work packages, invariants, acceptance criteria, and verification scope. The 2026-10-07 reconciliation clarifies the neutral extension seam and embedding-space identity in addition to numbering/persistence/README updates. Read the source roadmap, Phase 10 persistence plan, and shared execution contract first. This plan defines future implementation; it does not claim delivery.

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
- BYOK selection/execution or hosted secret storage

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

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends the post-Phase-10 GCP/Neon/DynamoDB deployment assets, `Makefile`, and `.github/workflows/quality.yml` only when required; do not reintroduce Firestore as a canonical runtime dependency. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Phase 10 storage dependency

Consume the Phase 10 lossless embedding-array/exact pgvector-cast baseline. Original stored values and embedding-space metadata round-trip unchanged; casts do not redefine the byte-compatible read contract. No provider/model change or re-embedding is implied. See the [Phase 10 storage contract](../../phase-10-storage-ownership-and-access-patterns.md); existing work packages and acceptance remain unchanged.

## Prerequisites and work ordering

Required phases: 12, 15, 10. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Provider SDK objects stay below the inference boundary.
- Embedding metadata includes provider/model/dimensions/normalization-task semantics.
- Existing memory vector semantics remain compatible in Postgres/pgvector until an explicit embedding migration.

## Work packages

### P16.0 — Minimal neutral generation and completion

**Depends on:** required phases above.

Extend the stream-only boundary with the actual stream, bounded generation and structured-result needs of current tasks. Define terminal success/incomplete/failure, actual provider/model, safe errors and usage confidence/source. Keep task schemas/validation in services. Preserve SSE compatibility via a narrow facade if needed; fakes support terminal events, bounds and cancellation rather than pretending iterator exhaustion proves every provider succeeded.

Treat these neutral capability declarations as the [provider extension seam](../../02-target-architecture.md#9-provider-runtime), including supported counting/embedding operations, safe failures, and cancellation. Higher layers consume contracts; protocol/SDK/serialization remains adapter-owned.

**Acceptance:** Fake and Gemini operations report explicit terminal/usage/error metadata while existing SSE callers remain compatible.

**Extension acceptance:** A synthetic provider with a distinct identity passes supported neutral stream/bounded/structured/usage/error/cancellation contract fixtures, explicitly rejects unsupported capabilities, and needs no context/domain/runtime provider-name branch. Offline conformance does not establish live compatibility or eligibility.

### P16.1 — Provider-aware fit and embedding metadata

**Depends on:** P16.0.

Use separate counter and embedding capabilities. Final assembly uses the selected endpoint serializer, context limits and an approved counter; planning estimates stay labelled. Gemini preserves its authoritative REST count transport. Document supported conservative local count bounds before using another endpoint; do not call an ineligible Gemini counter. Embedding results include provider/model/dimensions/normalization/task semantics; adapt existing Embedder and preserve normalized 768-dimensional Gemini vector spaces/index semantics and immutable v1/v2 records. No re-index migration.

**Acceptance:** Endpoint-specific fit/count is policy-safe; migrated vectors and v1/v2 logical records remain readable with equivalent semantics.

Embedding-space identity also includes an explicit version with provider/model/dimensions/normalization/task semantics. A future migration creates a new identity, never mixes incompatible vectors, and requires separately authorized re-embedding/re-index acceptance. Current Gemini spaces and original vector values remain compatible.

### P16.2 — Migrate all disclosure paths incrementally

**Depends on:** P16.1.

Inventory chat, summaries, research/iterative synthesis, itinerary proposals, booking extraction, memory extraction and embeddings. Move direct Gemini memory extraction through shared bounded context preparation and neutral structured generation while preserving exact user-source validation and post-terminal advisory behavior. Migrate existing SDK use within llm, wire through dependencies, and leave no unrestricted generation/count/embedding bypass before new providers are enabled. Add per-invocation attribution now; Phase 21 persists selected runtime attribution on automatic turns.

**Acceptance:** No existing generation/count/embedding path bypasses the neutral admission/preparation inventory; exact-source validators still pass.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R16.1: Reconcile stream-only chat contract with structured generation. | P16.0 |
| R16.2: Add minimal neutral generation operations. | P16.0 |
| R16.3: Add explicit embedding boundary with model/dimension metadata. | P16.1 |
| R16.4: Add fake backend. | P16.0 |
| R16.5: Migrate existing Gemini call paths incrementally, closing generation/count/embedding disclosure bypasses before new providers are enabled. | P16.2 |

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only when implementation in this phase changes the truth of user-visible capabilities, architecture, technology stack, prerequisites, local setup, cloud deployment, provider support, or current project status. Keep implementation mechanics in detailed docs rather than the README. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Fake-based contract tests cover terminal loss, unsupported operations, malformed JSON, error mapping, deadlines/cancellation, no SDK leakage, serializer/count mismatch, forbidden count/embedding disclosures and byte-for-byte compatible stored-vector reads. Preserve all task validators.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make memory-lifecycle-eval`, `make research-eval`, `make iterative-research-eval`, `make itinerary-proposal-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Gemini count/structured-output/embedding compatibility remains opt-in; an offline fake does not prove a tokenizer bound or live provider behavior.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
