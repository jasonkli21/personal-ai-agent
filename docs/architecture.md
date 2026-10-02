# Architecture notes

## System shape

```text
Browser -> Cloud Run: Next.js web -> /api proxy -> Cloud Run: FastAPI API
                                                |-- chat SSE -> shared context -> LLM
                                                |               |-> optional memory
                                                |-- research SSE -> search -> evidence
                                                |                   |-> shared context -> LLM
                                                '--> Firestore: chat, memory, research

Gated Phase 4 post-terminal work -> durable memory job -> Pub/Sub
                                                     -> private Cloud Run worker

Future separate domain applications -> explicit core API (after an auth boundary)
  domain apps own authoritative records, business rules, and rich UI
  Phase 6/7 core work may add reusable entities, constraints, ranking, and
  thin travel/shopping intelligence; these are not delivered Phase 5 behavior.
```

The frontend uses Next.js, React, and TypeScript; FastAPI and Uvicorn power the API and worker. The deployment target is Cloud Run, with Firestore as the durable store, Pub/Sub for gated durable memory work, and Secret Manager for configured credentials. Repository contracts hide Firestore details from services; `llm` hides model-provider details. See [GCP deployment](gcp-deployment.md) for the runnable topology and cost boundaries.

## Core boundaries

- `agents` coordinates conversation and research flows without owning provider-specific logic.
- `context` selects token-budgeted active conversation turns and
  compatible working summaries for a model call. Phase 3 added optional labelled
  personal memory within the same total budget; Phase 5 standalone research counts whole evidence blocks through this same assembler.
  Summaries are not memory.
- `memory` owns durable user knowledge: preferences, episodic observations, semantic summaries, consolidation, and forgetting.
- `search` plans queries, fetches sources through adapters, extracts content, deduplicates it, and selects candidate evidence.
- `evidence` records what an external source stated, where it came from, when it was observed, and when it expires.
- `entities` currently contains chat records. Phase 6 plans canonical identity for products, hotels, places, merchants, and other research candidates.
- `ranking` is a Phase 6 placeholder for deterministic hard constraints followed by explainable soft ranking.
- `domains` contains Phase 7 placeholders for thin travel and shopping intelligence; future applications can own their separate state and UI.
- `evaluation` measures behavior across memory, research, and domain recommendation cases before experiments are promoted.

## Data-lifetime rule

Memory and evidence are deliberately different. A user preference can last months or years. Prices, inventory, flight availability, and opening hours must be stored as observations with a freshness policy and expiration. Conclusions should point back to their supporting evidence instead of being retained as facts.

## Persistence boundary

Current repository contracts cover conversations, messages, memories, and bounded research-session aggregates with nested queries, observations, and evidence. Phase 6 will define canonical entity and decision records. These research records must remain separate from an external application's authoritative trip, booking, or purchase state. Firestore remains the current store; its memory vector search is a separate portability concern from canonical-record persistence.


## Delivered Phase 2 request boundary

Chat services reserve and persist the user/branch mutation, then invoke the
provider-neutral context assembler before creating a streaming assistant.
`context` owns budget allocation, complete-turn selection, summary provenance,
and read-only inspection. Gemini counting and bounded summary-generation SDK
calls stay inside `llm`; Firestore summary records stay behind repository
contracts. The worker/Pub/Sub path remains idle. See
[Phase 2 implementation](phase-2-implementation-guide.md).

## Delivered Phase 3 memory boundary

After user/branch persistence, chat retrieves bounded owner-scoped vector candidates
through the memory repository and provider-neutral embedder. It revalidates active
user-source provenance, then the shared assembler counts whole optional historical
records without displacing Phase 2 context. Retrieval/counting failure falls back to
Phase 2. After successful durable assistant completion and the terminal SSE frame,
bounded extraction validates exact user excerpts before embedding and atomic storage.
Memory and inspection gates default off. No worker lifecycle is added. See
[Phase 3 implementation](phase-3-implementation-guide.md) and
[ADR 0009](decisions/0009-simple-attributable-memory.md).

## Delivered Phase 4 lifecycle boundary

`memory` now owns versioned deterministic scoring, separate derived-record provenance,
append-only lifecycle events, projections and bounded jobs. All variants retain the
shared assembler's allocation and source validation rules. The retained post-terminal
task accounts for actual injected IDs and persists optional jobs before notification.
A separate private worker app processes Pub/Sub delivery using fenced leases and
atomic source/state checks. Explicit bounded recovery republishes durable pending
notifications; no general scheduler is introduced. Defaults remain fixed with all
mutation gates off. See [Phase 4 implementation](phase-4-implementation-guide.md).

## Delivered Phase 5 research boundary

`agents/research` coordinates one gated request-owned pass with fenced execution.
`search` owns the deterministic planner, provider-neutral protocols, literal
snippet extractor and fixed-endpoint Brave integration. `evidence` owns expiring
observations, conservative dedupe, explained selection and strict excerpt/citation
validation. The shared context assembler counts the entire research request.
Storage retains typed immutable provenance in a bounded owner-scoped session
aggregate with an atomic request-key mapping. API/UI/proxy remain thin; normal
chat and memory are independent. No publisher-page fetches, research worker jobs,
entities, recommendations or iterative planning are introduced. See the
[Phase 5 guide](phase-5-implementation-guide.md).
