# Architecture notes

## System shape

```text
Browser -> public Next.js sign-in/UI -> /api proxy -> private FastAPI API
           in-memory Google ID token    service IAM + user-token verification
                                                |-- chat SSE -> shared context -> LLM
                                                |               |-> optional memory
                                                |-- research SSE -> search -> evidence
                                                |                   |-> shared context -> LLM
                                                '--> Firestore: chat, memory, research, decisions

Gated Phase 4 post-terminal work -> durable memory job -> Pub/Sub
                                                     -> private Cloud Run worker

Future separate domain applications -> explicit core API (after an auth boundary)
  domain apps own authoritative records, business rules, and rich UI
  Phase 6 adds reusable research entities, constraints, and ranking. Phase 7
  travel/shopping modules extend those shared contracts; neither becomes
  authoritative domain-app state.
```

The frontend uses Next.js, React, and TypeScript; FastAPI and Uvicorn power the API and worker. The deployment target is Cloud Run, with Firestore as the durable store, Pub/Sub for gated durable memory work, and Secret Manager for configured credentials. Repository contracts hide Firestore details from services; `llm` hides model-provider details. See [GCP deployment](gcp-deployment.md) for the runnable topology and cost boundaries.

## Core boundaries

- `services` owns conversation and durable chat-turn behavior.
- `agents/research` coordinates single-pass and iterative research without owning provider-specific logic.
- `auth` verifies Google user/service identity, resolves owner mappings, and owns
  request safeguards and account-data controls. API routes take their owner only
  from the verified principal; local/test development uses the explicit `local` seam.
- `context` selects token-budgeted active conversation turns and
  compatible working summaries for a model call. Phase 3 added optional labelled
  personal memory within the same total budget; Phase 5 standalone research counts whole evidence blocks through this same assembler.
  Summaries are not memory.
- `memory` owns durable user knowledge: preferences, episodic observations, semantic summaries, consolidation, and forgetting.
- `search` plans queries, fetches sources through adapters, extracts content, deduplicates it, and selects candidate evidence.
- `evidence` records what an external source stated, where it came from, when it was observed, and when it expires.
- `entities` contains chat records and owner-scoped canonical research identities with immutable, evidence-backed claims.
- `decisions` owns evidence snapshots, candidate evaluations, and read-only inspection contracts.
- `ranking` applies deterministic freshness/conflict handling and hard constraints before explainable soft ranking.
- `domains` registers thin travel and shopping schemas, provider mappings,
  hard-constraint additions, ranking features, and comparison views on top of
  shared Phase 5–6 services. Place/catalog adapters and domain gates are
  independently configurable; these modules do not own authoritative trip or
  purchase records.
- `evaluation` measures behavior across memory, research, and domain recommendation cases before experiments are promoted.

## Data-lifetime rule

Memory and evidence are deliberately different. A user preference can last months or years. Prices, inventory, flight availability, and opening hours must be stored as observations with a freshness policy and expiration. Conclusions should point back to their supporting evidence instead of being retained as facts.

## Persistence boundary

Repository contracts cover conversations, messages, memories, bounded research-session aggregates, canonical entities/aliases/claims, and immutable decision/evidence snapshots with candidate evaluations. These research records remain separate from an external application's authoritative trip, booking, or purchase state. Firestore remains the current store; its memory vector search is a separate portability concern from canonical-record persistence.


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

## Delivered Phase 6 decision boundary

`entities` keeps canonical research identity separate from time-sensitive
claims. `decisions` validates either selected Phase 5 session evidence or
explicitly supplied evidence with owner, URL, excerpt-fingerprint, and expiry
checks. `ranking` abstains on ambiguous identity, stale/conflicting/missing
required claims, or unsupported conversions; deterministic hard constraints
run before preferences. Persisted snapshots retain exact source references and
policy versions. The result view links claims back to their sources, and a
separate inspection gate exposes policy and candidate diagnostics without raw
memory or hidden model reasoning. All decision gates default off. See the
[Phase 6 guide](phase-6-implementation-guide.md), [ADR 0012](decisions/0012-evidence-grounded-decision-support.md),
and [release evidence](releases/phase-6-decision-support.md).

## Delivered Phase 7 domain boundary

`domains` maps registered travel and shopping facts into the same evidence,
entity, claim, constraint, and decision contracts. A domain adds typed display
fields and ranking features only after the shared evaluator filters hard
requirements. Immutable domain claim extensions and provider observations
retain claim/evidence IDs, source policy, attribution, adapter version, and
expiry in a bounded Firestore transaction. Comparison snapshots include
visible constraints and policy versions. The browser proxy and pages require
both the shared decision gate and an independent domain gate; comparison
inspection has another gate. Nominatim is limited to submitted place searches,
and Open Food Facts is limited to exact barcode identity lookup. Neither
provider supplies current stays/offers in this implementation. See the
[Phase 7 guide](phase-7-implementation-guide.md),
[provider ADRs](decisions/0013-nominatim-travel-place-source.md), and
[release evidence](releases/phase-7-travel-shopping.md).

## Delivered Phase 8 iterative-research boundary

`agents/research` persists a versioned run over the existing Phase 5
owner-scoped research session. Its finite-state transitions, safe progress
events, budget ledger, cancellation fence, and recovery lease are written
through repository contracts; Firestore run/session commits are transactional.
The deterministic assessor emits named gaps, and a schema-validated template
planner can only request bounded follow-up work tied to one gap and its frozen
allowed-domain set. Query execution, extraction, evidence selection, context
assembly and citation validation stay on their Phase 5 paths. Optional
candidate/constraint intents are re-evaluated by the shared Phase 6 decision
service; search output does not create verified claims or relax requirements.
Single-pass remains the default and all Phase 8 gates are off. No background
worker, open-ended autonomy, or Phase 9 operation is introduced. See the
[Phase 8 guide](phase-8-implementation-guide.md), [ADRs](decisions/0016-bounded-iterative-research.md),
and [release evidence](releases/phase-8-iterative-research.md).

## Partial Phase 9 operational boundary

Google OIDC verifies the browser principal, and Cloud Run IAM separately
verifies web-to-API invocation. The private worker verifies independently
configured Pub/Sub and Scheduler identities. Local/test development bypass is
rejected in staging/production. Browser identity stays in memory and passes
only through same-origin proxies.

Durable Firestore request limits and request-level usage estimates precede
provider-backed API operations. These estimates do not account for every
counting/embedding/worker RPC or settle actual usage. A bounded scheduled
handler marks expired research sessions ineligible and republishes durable
memory jobs; its schedule remains paused by default. Account export is bounded
and owner-scoped. Confirmed deletion stops at operator review and performs no
physical deletion. Full legacy-owner migration remains unsupported for records
with embedded ownership or derived owner keys.

See the [Phase 9 plan](phase-9-implementation-plan.md),
[authorization matrix](phase-9-authorization-matrix.md),
[operations runbook](phase-9-operations-runbook.md), and
[repository review](repository-review-2026-10-03.md). These local code paths do
not establish cloud IAM, recovery, provider-policy, or production readiness.

## Reconciled next-scope handoff — 2026-10-05

The [comprehensive Phase 0 reconciliation](personal-ai-next-scope-chatgpt-integrated-v2/09-phase-0-reconciliation.md) verifies the additive application/context, provider/routing, Firestore/GCS and ChatGPT/domain handoff against revision `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. Its next-scope Phases 0–28 are separate from the existing implementation history. Next-scope Phase 1 application/workspace identity is implemented and verified locally; see its [implementation guide](personal-ai-next-scope-chatgpt-integrated-v2/phase-1-implementation-guide.md) and [evidence](personal-ai-next-scope-chatgpt-integrated-v2/phase-1-implementation-evidence-2026-10-05.md). Workspace membership, live Firestore indexes, deployed IAM/proxy behavior, and existing Phase 9 physical deletion and owner migration remain unverified or open. The target is incremental and preserves domain authority, source-attributed memory/evidence, strict-free and privacy boundaries.

The current budget guarantee applies to chat/evidence/proposal/extraction preparation. Structured memory extraction still calls Gemini directly with character/output bounds; next-scope Phase 8 must route it through shared preparation. Existing Gemini remote token counting is a disclosure, and future provider fallback needs an eligible endpoint-specific counter rather than sending all prompts to Gemini. The current context inspector reports estimated reconstructed context, not an exact historical dispatch.
