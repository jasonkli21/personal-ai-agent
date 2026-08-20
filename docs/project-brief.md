# Project brief and session handoff

Read this document before making implementation decisions. It carries the product intent and guardrails that sit behind the architecture and implementation plan.

## Purpose

This is a **personal learning and research project**, not an attempt to host or reproduce a frontier model. The goal is to learn the systems around an LLM—streaming chat, persistence, context management, retrieval, memory, search, evidence, ranking, and evaluation—and eventually use the system to experiment with AI memory architectures.

The end state is one reusable personal research platform with chat, memory, and evidence-grounded search. Travel and shopping are the first domain modules, not separate applications.

## Current state

This repository is a scaffold, not a working assistant.

Implemented only:

- Python/FastAPI and Next.js project structure.
- Minimal API and worker health endpoints.
- Web-to-API health check at `/api/health`.
- Dockerfiles and a GCP bootstrap/deployment script.
- Architecture, deployment, research-agent, and implementation-plan documents.

Not implemented:

- Authentication or authorization.
- Conversation/message persistence.
- Firestore reads or writes.
- LLM or embedding calls.
- Streaming chat.
- Memory extraction, retrieval, consolidation, contradiction handling, or forgetting.
- Search-provider calls, evidence extraction, entity resolution, ranking, or domain agents.
- Pub/Sub publishing or task processing beyond a worker acknowledgement endpoint.

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

Cloud Run is used request-based with zero minimum instances in the scaffold. Firestore and Pub/Sub are provisioned early, but are not yet used by application behavior. See [GCP deployment](gcp-deployment.md) for the runnable topology, provisioning script, current quota notes, and security boundary.

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

Follow [implementation plan](implementation-plan.md) in sequence. The immediate target is **Phase 1 only**; use the [Phase 0–1 implementation plan](phase-1-implementation-plan.md) as its task-level backlog:

1. Persist conversations and messages.
2. Add FastAPI conversation and streaming-response endpoints.
3. Add a minimal chat UI with conversation history.
4. Add one LLM-provider adapter, configuration, timeout, and retry behavior.
5. Support regenerate and edit/retry message flows.

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

- Exact Gemini SDK, model, and embedding-model choices.
- Authentication approach for personal use and the point at which it becomes mandatory.
- Firestore collection structure, document ownership, indexes, and schema-versioning approach.
- Whether local development starts with Firestore Emulator, a local adapter, or a dedicated development GCP project.
- Search providers and their data, pricing, and attribution requirements.
- Travel and shopping providers, only when those domain phases begin.
- Operational safeguards: budgets, usage alerts, logging retention, backups, export, and deletion behavior.

## How to start a new session

1. Read this brief, then [architecture](architecture.md), [implementation plan](implementation-plan.md), and [GCP deployment](gcp-deployment.md).
2. Confirm the active implementation phase; default to Phase 1 unless the user explicitly advances it.
3. Preserve the architectural invariants above.
4. Implement the smallest testable vertical slice of the current phase, update tests and docs, and do not expand into a later phase without a user decision.
