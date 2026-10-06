# Project brief and session handoff

Read this document before making implementation decisions. It carries the product intent and guardrails that sit behind the architecture and implementation plan.

## Purpose

This is a **personal learning and research project**, not an attempt to host or reproduce a frontier model. The goal is to learn the systems around an LLM—streaming chat, persistence, context management, retrieval, memory, search, evidence, ranking, and evaluation—and eventually use the system to experiment with AI memory architectures.

The end state is one reusable AI/research substrate with chat, memory, and evidence-grounded search. Travel and shopping may add shared AI-side domain modules here; future rich applications may live in separate repositories and own authoritative domain state, business rules, and UI.

## Current state

Phase 1–4 chat, context and memory, Phase 5 bounded research, Phase 6
evidence-backed decision support, Phase 7 travel/shopping comparison modules,
and Phase 8 bounded iterative research are implemented locally. Phases 6–8
were explicitly authorized; decision, domain, and iterative gates remain
disabled by default. Offline checks use synthetic evidence and fakes. Real
Firestore, Gemini, provider-rights, and deployed GCP behavior still need
verification.
See the Phase 5 [reviewed plan](phase-5-implementation-plan.md),
[guide](phase-5-implementation-guide.md) and
[release evidence](releases/phase-5-source-grounded-research.md).
See the Phase 7 [implementation plan](phase-7-implementation-plan.md),
[guide](phase-7-implementation-guide.md), and
[release evidence](releases/phase-7-travel-shopping.md) for the bounded provider
scope and verification gaps.
See the Phase 8 [implementation plan](phase-8-implementation-plan.md),
[guide](phase-8-implementation-guide.md), and
[release evidence](releases/phase-8-iterative-research.md) for state, budgets,
recovery, evaluation, and remaining verification gaps.
Phase 9 authentication and operational safeguards are implemented locally in
part; its acceptance criteria remain incomplete. See the
[Phase 9 plan](phase-9-implementation-plan.md),
[evidence](phase-9-implementation-evidence.md), and
[repository review](repository-review-2026-10-03.md).
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
- Versioned travel and shopping modules that reuse shared evidence, identity,
  constraints, ranking, and decision snapshots; bounded Nominatim place lookup
  and exact-barcode Open Food Facts catalog lookup remain independently gated.
- Ten synthetic travel/shopping fixtures, domain-specific feature evaluation,
  attributable comparison views, and a gated browser workbench.
- Versioned, owner-scoped bounded research runs, deterministic sufficiency/gap
  assessment, validated follow-up templates, resource ledgers, safe progress,
  cancellation/recovery, and 18 paired Phase 5/8 synthetic evaluations.
- Decision creation and inspection gates default off. Local/test `local`
  ownership remains a development boundary; deployed requests require verified
  Google identity and private API invocation.
- Partial Phase 9 Google OIDC, owner mappings, safe request telemetry, durable
  request counters, request-level usage estimates, service-token verification,
  bounded account export and deletion-request audit records.
- Offline backend/frontend tests, lint/type checks, and GitHub Actions CI.
- Dockerfiles and a GCP bootstrap/deployment script.
- Architecture, deployment, research-agent, and implementation-plan documents.

Not implemented:

- User-facing memory management, broad inferred consolidation or contradiction adjudication.
- General scheduled maintenance; Phase 4 provides explicit bounded jobs and recovery.
- Physical owner-data deletion and deletion-aware restore.
- Full legacy owner migration, provider usage accounting, and operational
  release promotion gates. Phase 9 has local authentication, request limits,
  scheduled-maintenance plumbing and account workflows, but remains incomplete.

Research/search/evidence implement the bounded Phase 5 pipeline; Phase 6 adds
shared evidence-backed decision support and Phase 7 adds thin travel/shopping
extensions.
`memory` implements gated extraction, durable provenance, vector retrieval and inspection.
`context` and `evaluation` now implement conversation budgeting and synthetic
quality checks; `entities` contains both chat records and canonical research
entities.
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
- Do not treat the local implementation as ready for real personal data. The private API deployment and Google OIDC boundary still require staged verification, provider-data review, and operational release checks.
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
verification gaps remain open. Phases 7 and 8 are implemented locally; their
provider, emulator, and deployment checks remain open. Follow their guides and
release records. Phase 9 is partially implemented locally. Preserve its remaining acceptance
gaps; do not expand into new operational/product behavior without explicit direction.

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
- Acceptance of the implemented Google OIDC boundary in staging/production; see [ADR 0018](decisions/0018-personal-oidc-authentication.md).
- Future Firestore schema migrations, backups, export, and deletion behavior.
  Phase 1 collections, owner scoping, and indexes are implemented; see the
  [API contract](api-contract.md) and [ADR 0002](decisions/0002-firestore-native-persistence.md).
- Additional search providers and their data, pricing, and attribution requirements. Phase 5's gated Brave snippet adapter and storage-rights policy are implemented locally.
- Additional travel and shopping providers, after separate policy review and
  attribution/retention decisions.
- Operational safeguards: budgets, usage alerts, logging retention, backups, export, and deletion behavior.

## How to start a new session

1. Follow the root [agent instructions](../AGENTS.md), then read this brief,
   [architecture](architecture.md), [implementation guide](phase-1-implementation-guide.md),
   and the plan for the active task. Read [GCP deployment](gcp-deployment.md)
   when working on infrastructure.
2. Use the Phase 5–8 guides and release records for delivered behavior and remaining verification gaps. Consult the Phase 9 plan/evidence for partial operational implementation; do not infer production readiness.
3. Preserve the architectural invariants above.
4. Once a phase is authorized, implement its smallest testable vertical slice, update tests and docs, and do not expand into a later phase without a user decision.

## Reconciled next-scope handoff — 2026-10-05

The [comprehensive Phase 0 reconciliation](personal-ai-next-scope-chatgpt-integrated-v2/09-phase-0-reconciliation.md) verifies the additive application/context, provider/routing, Firestore/GCS and ChatGPT/domain handoff against revision `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. Its next-scope Phases 0–28 are separate from the existing implementation history. Next-scope Phase 1 application/workspace identity is implemented and verified locally; see its [implementation guide](personal-ai-next-scope-chatgpt-integrated-v2/phase-1-implementation-guide.md) and [evidence](personal-ai-next-scope-chatgpt-integrated-v2/phase-1-implementation-evidence-2026-10-05.md). Workspace membership, live Firestore indexes, deployed IAM/proxy behavior, and existing Phase 9 physical deletion and owner migration remain unverified or open. The target is incremental and preserves domain authority, source-attributed memory/evidence, strict-free and privacy boundaries.
