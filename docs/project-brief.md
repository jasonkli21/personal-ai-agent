# Project brief and session handoff

Read this document before making implementation decisions. It carries the product intent and guardrails that sit behind the architecture and implementation plan.

## Purpose

This is a **personal learning and research project**, not an attempt to host or reproduce a frontier model. The goal is to learn the systems around an LLM—streaming chat, persistence, context management, retrieval, memory, search, evidence, ranking, and evaluation—and eventually use the system to experiment with AI memory architectures.

The end state is one reusable personal research platform with chat, memory, and evidence-grounded search. Travel and shopping are the first domain modules, not separate applications.

## Current state

Phase 1 chat code is implemented. Offline quality checks pass, but real
Firestore persistence, Gemini, deployed GCP behavior, and client-disconnect
integration still need verification. Do not equate implemented code with a
fully verified deployment. The active scope is **Phase 1 verification and
handoff maintenance**; Phase 2 is planned, not started.

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
- A fixed history cap (40 messages by default) and response-size bounds.
- Offline backend/frontend tests, lint/type checks, and GitHub Actions CI.
- Dockerfiles and a GCP bootstrap/deployment script.
- Architecture, deployment, research-agent, and implementation-plan documents.

Not implemented:

- Authentication or authorization.
- Token-aware context selection, conversation summaries, or context inspection.
- Embedding calls.
- Memory extraction, retrieval, consolidation, contradiction handling, or forgetting.
- Search-provider calls, evidence extraction, entity resolution, ranking, or domain agents.
- Pub/Sub publishing or task processing beyond a worker acknowledgement endpoint.

The research, context, memory, evidence, ranking, evaluation, and domain
packages are placeholders; `entities` currently contains chat records.
See the [implementation guide](phase-1-implementation-guide.md) for delivered
code and the [verification record](releases/phase-1-vertical-slice.md) for
dated evidence. The [verification closeout plan](phase-1-verification-plan.md)
outlines the remaining work.

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
instances. Chat uses Firestore; Pub/Sub is provisioned but chat publishes no
jobs and the worker only acknowledges delivery. See [GCP deployment](gcp-deployment.md)
for the topology, provisioning script, quota notes, and security boundary.

## Architectural invariants

These rules must hold as features are added:

1. **The LLM is replaceable.** Provider-specific code stays inside `llm` and adapter modules.
2. **Memory and external evidence are different data classes.** Memory represents durable, attributable user knowledge; evidence represents an observation from an external source at a point in time.
3. **Freshness is explicit.** Evidence has source, observation time, expiry or freshness policy, and entity links. Never treat old price, availability, or opening-hours data as permanent fact.
4. **Conclusions are not facts.** Recommendations must preserve the evidence and reasoning that support them rather than becoming unqualified memory.
5. **Hard constraints precede preferences.** Filter on requirements such as budget, dates, location, availability, or dimensions before applying soft preference ranking.
6. **Memory may guide investigation.** It can influence query planning and ranking, but must not override current constraints or fresh evidence.
7. **Domain modules remain thin.** Travel and shopping add schemas, source adapters, constraints, features, and presentation rules; they reuse the shared research, memory, evidence, entity, ranking, and evaluation layers.
8. **Experiments require evaluation.** Experimental memory or ranking behavior stays isolated until it has a baseline comparison and measured result.

## Implementation order

Follow [implementation plan](implementation-plan.md) in sequence. Phase 0–1
code paths are delivered; use the [Phase 0–1 plan](phase-1-implementation-plan.md)
and [implementation guide](phase-1-implementation-guide.md) to assess acceptance.
The immediate target is closing the remaining Phase 1 verification gaps:

1. Verify Firestore Emulator persistence across an API restart.
2. Add deterministic automated client-disconnect integration coverage.
3. Run the opt-in Gemini smoke test and credentialed GCP deployment checklist
   when the required environment is available.
4. Record results, revision, and remaining gaps without storing secrets or chats.

The next feature phase, once explicitly advanced, is the
[Phase 2 context-window plan](phase-2-implementation-plan.md).

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

- Embedding-model choice when memory work begins. Chat already uses the Google
  Gen AI SDK with runtime model selection; see [ADR 0001](decisions/0001-llm-provider-boundary.md).
- Authentication approach for personal use and the point at which it becomes mandatory.
- Future Firestore schema migrations, backups, export, and deletion behavior.
  Phase 1 collections, owner scoping, and indexes are implemented; see the
  [API contract](api-contract.md) and [ADR 0002](decisions/0002-firestore-native-persistence.md).
- Search providers and their data, pricing, and attribution requirements.
- Travel and shopping providers, only when those domain phases begin.
- Operational safeguards: budgets, usage alerts, logging retention, backups, export, and deletion behavior.

## How to start a new session

1. Follow the root [agent instructions](../AGENTS.md), then read this brief,
   [architecture](architecture.md), [implementation guide](phase-1-implementation-guide.md),
   and the plan for the active task. Read [GCP deployment](gcp-deployment.md)
   when working on infrastructure.
2. Default to Phase 1 verification unless the user explicitly advances the phase.
3. Preserve the architectural invariants above.
4. Implement the smallest testable vertical slice of the current phase, update tests and docs, and do not expand into a later phase without a user decision.
