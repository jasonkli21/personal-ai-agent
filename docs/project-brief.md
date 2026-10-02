# Project brief and session handoff

Read this document before making implementation decisions. It carries the product intent and guardrails that sit behind the architecture and implementation plan.

## Purpose

This is a **personal learning and research project**, not an attempt to host or reproduce a frontier model. The goal is to learn the systems around an LLM—streaming chat, persistence, context management, retrieval, memory, search, evidence, ranking, and evaluation—and eventually use the system to experiment with AI memory architectures.

The end state is one reusable AI/research substrate with chat, memory, and evidence-grounded search. Travel and shopping may add shared AI-side domain modules here; future rich applications may live in separate repositories and own authoritative domain state, business rules, and UI.

## Current state

Phase 1–4 chat, context and memory, Phase 5 bounded research, and Phase 6
evidence-backed decision support are implemented locally. Phase 6 was explicitly
authorized on 2026-10-02; its decision and inspection gates remain disabled by
default. Offline checks use synthetic evidence and fakes. Real Firestore,
Gemini, licensed Brave, and deployed GCP behavior still need verification.
See the Phase 5 [reviewed plan](phase-5-implementation-plan.md),
[guide](phase-5-implementation-guide.md) and
[release evidence](releases/phase-5-source-grounded-research.md).
Existing earlier-phase external gaps remain open.

Implemented:

- Python/FastAPI and Next.js project structure.
- Minimal API and worker health endpoints.
- Web-to-API health check at `/api/health`.
- Conversation creation, listing, and reopening through FastAPI and the UI.
- Owner-scoped Firestore repositories and in-memory test repositories.
- A provider-neutral LLM interface and Gemini streaming adapter with timeouts
  and safe error mapping.
- SSE chat streaming, persisted completion/failure states, regenerate, and
  edit-and-retry flows with preserved superseded history.
- Provider-authoritative token budgets, complete-turn context selection, and
  response-size bounds.
- Branch-safe append-only working summaries with separate coverage/source provenance,
  incomplete-turn skipping, synchronous bounded refresh, and
  disabled-by-default read-only context inspection.
- Synthetic Phase 1/2 context evaluations and opt-in provider quality checks.
- Atomic turn/replacement preparation with bounded root-cut writes, deadline-aware
  counting and snapshot-independent reservation cleanup, overlap rejection, conditional terminal
  updates, and recovery of abandoned streaming placeholders.
- Gated source-grounded memory extraction, compatible normalized embeddings,
  owner-scoped durable/vector repositories, advisory retrieval and bounded injection.
- Fourteen deterministic memory evaluations and read-only supplied-record inspection.
- Versioned scoring, append-only memory lifecycle state, attributable derived records,
  conservative contradiction/forgetting, private fenced jobs and bounded recovery.
- Twenty deterministic lifecycle fixtures across three variants, with default-off gates.
- Gated standalone research sessions, atomic owner-scoped replay/fencing,
  bounded Brave snippets and fakes, literal evidence extraction, TTLs/dedupe,
  explainable selection, validated cited excerpts and a research UI/inspector.
- Thirteen synthetic full-pipeline research fixtures and opt-in external checks.
- Owner-scoped canonical research entities, append-only evidence-backed claims,
  conservative resolution, deterministic hard constraints, and explainable
  preference ranking with immutable decision snapshots.
- Session-backed and explicitly supplied evidence decision paths, a persisted
  Firestore repository, 15 deterministic decision fixtures, a source-grounded
  result view, and separately gated development inspection.
- Decision creation and inspection gates default off; current `local` ownership
  remains a development boundary, not authentication.
- Offline backend/frontend tests, lint/type checks, and GitHub Actions CI.
- Dockerfiles and a GCP bootstrap/deployment script.
- Architecture, deployment, research-agent, and implementation-plan documents.

Not implemented:

- Authentication or authorization.
- User-facing memory management, broad inferred consolidation or contradiction adjudication.
- Phase 7 domain-specific adapters and policies or Phase 8 iterative research.
- General scheduled maintenance; Phase 4 provides explicit bounded jobs and recovery.

Research/search/evidence implement the bounded Phase 5 pipeline; Phase 6 adds
shared evidence-backed decision support. Domain packages remain placeholders.
`memory` implements gated extraction, durable provenance, vector retrieval and inspection.
`context` and `evaluation` now implement conversation budgeting and synthetic
quality checks; `entities` still contains chat records.
See the [implementation guide](phase-1-implementation-guide.md) for delivered
code and the [verification record](releases/phase-1-vertical-slice.md) for
dated evidence. The [verification closeout plan](phase-1-verification-plan.md)
outlines the remaining Phase 1 external checks. The
[Phase 2 implementation guide](phase-2-implementation-guide.md) and
[Phase 2 release record](releases/phase-2-context-management.md) describe the
current context-management behavior and evidence.

## Non-goals and constraints

- Do not host a frontier model on free-tier compute. Use hosted LLM and embedding APIs behind the `llm` abstraction.
- Do not begin with memory, search, travel, or shopping features. Build and verify the basic chat system first.
- Do not introduce LangChain, LlamaIndex, or a large agent/orchestration framework initially. The point is to understand and implement the core abstractions directly.
- Do not treat the current public Cloud Run bootstrap as safe for real personal data. Authentication, authorization, and a deliberate provider-data policy are required before storing sensitive chats.
- Do not commit API keys, provider credentials, or user data. Add real credentials through Secret Manager when an adapter actually needs them.
- Do not let a model decide deterministic requirements such as whether a price meets a budget. Application code enforces hard constraints.

## Chosen technical direction

The current intended stack is:

- **Web:** Next.js, React, TypeScript, Cloud Run.
- **API and worker:** Python, FastAPI, Uvicorn, Cloud Run.
- **Durable data:** Firestore in Native mode.
- **Asynchronous work:** Pub/Sub push delivery to a Cloud Run worker.
- **Secrets:** Secret Manager.
- **Initial model direction:** Gemini for hosted inference and embeddings, behind a replaceable provider interface.

The deployment script configures request-based Cloud Run with zero minimum
instances. Chat uses Firestore; Pub/Sub is provisioned; gated Phase 4 post-terminal work can publish durable
lifecycle-job notifications to the private worker. Bootstrap leaves those gates off. See [GCP deployment](gcp-deployment.md)
for the topology, provisioning script, quota notes, and security boundary.

## Architectural invariants

These rules must hold as features are added:

1. **The LLM is replaceable.** Provider-specific code stays inside `llm` and adapter modules.
2. **Memory and external evidence are different data classes.** Memory represents durable, attributable user knowledge; evidence represents an observation from an external source at a point in time.
3. **Freshness is explicit.** Phase 5 evidence has source, observation time, and expiry or freshness policy. Phase 6 links claims to those observations without making a price, availability, or opening-hours value permanent entity truth.
4. **Conclusions are not facts.** Recommendations must preserve the evidence and reasoning that support them rather than becoming unqualified memory.
5. **Hard constraints precede preferences.** Filter on requirements such as budget, dates, location, availability, or dimensions before applying soft preference ranking.
6. **Memory may guide investigation.** It can influence query planning and ranking, but must not override current constraints or fresh evidence.
7. **Domain modules remain thin.** Shared travel and shopping intelligence may add schemas, source adapters, constraints, and features while reusing the core layers. Separate applications own authoritative trips, bookings, purchases, business rules, and rich UI.
8. **Experiments require evaluation.** Experimental memory or ranking behavior stays isolated until it has a baseline comparison and measured result.

## Implementation order

Follow [implementation plan](implementation-plan.md) in sequence. Phase 0–1
code paths are delivered; use the [Phase 0–1 plan](phase-1-implementation-plan.md)
and [implementation guide](phase-1-implementation-guide.md) to assess acceptance.
Phase 4 local implementation is delivered; use its [guide](phase-4-implementation-guide.md)
and [release evidence](releases/phase-4-experimental-memory.md) for behavior and checks. Keep the following
verification closeout work for delivered Phase 1–3 behavior visible:

1. Verify Firestore Emulator persistence across an API restart.
2. Maintain the disconnect, storage-failure, and concurrency regression suite;
   verify browser cancellation through the deployed proxy.
3. Run the opt-in Gemini smoke test and credentialed GCP deployment checklist
   when the required environment is available.
4. Run opt-in synthetic memory provider, persistence and vector-index checks;
   see the [Phase 3 guide](phase-3-implementation-guide.md).
5. Record results, revision, and remaining gaps without storing secrets or chats.

The [Phase 2 context-window plan](phase-2-implementation-plan.md) is implemented
locally. Finish its credentialed quality/deployed checks before declaring full
verification; Phase 3 was explicitly authorized and is now implemented locally.
See its [guide](phase-3-implementation-guide.md) and
[release evidence](releases/phase-3-simple-memory.md). Phases 5 and 6 are
implemented locally after explicit user authorization; their external
verification gaps remain open. Do not advance to Phase 7 without a completion
review and explicit user direction.

Do not add long-term memory in Phase 1. Phase 2 handles context-window management; Phase 3 introduces simple memory only after basic chat is stable.

## Phase 1 definition of done

Phase 1 is complete when all of the following are true:

- A single user can create a conversation, send a message, and receive a streamed model response.
- Conversations and messages survive a server restart through the selected persistence adapter.
- The frontend can display prior conversations and messages.
- Provider errors and timeouts produce understandable user-facing failures.
- The implementation includes tests for the API and persistence boundaries.
- The app has documented local run instructions and passes a basic deployed health check.
- No long-term-memory, search, research-agent, or domain-specific behavior has been added.

## Open decisions to resolve deliberately

Resolve these in short architecture decision records before implementation depends on them:

- Embedding-model changes or migrations after Phase 3. ADR 0009 selects configured
  Gemini embeddings initially. Chat already uses the Google
  Gen AI SDK with runtime model selection; see [ADR 0001](decisions/0001-llm-provider-boundary.md).
- Authentication approach for personal use and the point at which it becomes mandatory.
- Future Firestore schema migrations, backups, export, and deletion behavior.
  Phase 1 collections, owner scoping, and indexes are implemented; see the
  [API contract](api-contract.md) and [ADR 0002](decisions/0002-firestore-native-persistence.md).
- Additional search providers and their data, pricing, and attribution requirements. Phase 5's gated Brave snippet adapter and storage-rights policy are implemented locally.
- Travel and shopping providers, only when those domain phases begin.
- Operational safeguards: budgets, usage alerts, logging retention, backups, export, and deletion behavior.

## How to start a new session

1. Follow the root [agent instructions](../AGENTS.md), then read this brief,
   [architecture](architecture.md), [implementation guide](phase-1-implementation-guide.md),
   and the plan for the active task. Read [GCP deployment](gcp-deployment.md)
   when working on infrastructure.
2. Use the Phase 5 and Phase 6 guides and release records for delivered behavior and remaining verification gaps. Do not add Phase 7 domain work without explicit authorization.
3. Preserve the architectural invariants above.
4. Once a phase is authorized, implement its smallest testable vertical slice, update tests and docs, and do not expand into a later phase without a user decision.
