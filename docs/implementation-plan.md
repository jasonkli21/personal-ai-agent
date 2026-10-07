# Original repository implementation plan

> Historical sequencing and scope for the original repository Phases 0–9.
> It contains phase-era status and provider/storage notes; it is not the living
> status source or the active Chapter 2 roadmap. See [current state](current-state.md),
> the [documentation router](README.md), and the [Chapter 2 plan index](personal-ai-chapter-2/personal-ai-next-scope-detailed-implementation-plans/README.md).

This plan builds a usable personal chat system first, then progressively turns it into a memory and research-agent platform. Each phase should be evaluated before the next one adds complexity.

For task-level dependencies, requirements, and acceptance criteria, see the
[Phase 0–1 implementation plan](phase-1-implementation-plan.md) and the
[Phase 2 implementation plan](phase-2-implementation-plan.md).


## Phase 0 — Define the learning baseline

1. Write short architecture decisions: initial LLM provider, storage choice, deployment target, and privacy boundaries.
2. Define the initial data vocabulary: users, conversations, messages, memories, research sessions, evidence, and entities.
3. Add local development setup, formatting, tests, and continuous integration.
4. Create a small set of evaluation conversations before building advanced behavior.

**Outcome:** a reproducible project foundation and a way to measure progress.

## Phase 1 — Build the basic chat system

1. Implement conversation and message persistence.
2. Create FastAPI endpoints for conversations and streamed responses.
3. Add a minimal Next.js chat interface with conversation history.
4. Implement an LLM provider adapter and error/retry handling.
5. Support regenerate and edit/retry flows.

**Outcome:** a usable personal chat application with no long-term memory.

## Phase 2 — Add context-window management

For the Phase 2 task backlog, dependencies, requirements, and acceptance
criteria, see [Phase 2 implementation plan](phase-2-implementation-plan.md).

1. Define a context-assembly interface.
2. Add token-aware recent-message selection.
3. Add conversation summaries once a thread becomes large.
4. Expose a development-only context-inspection view.
5. Evaluate answer quality as conversations grow.

**Outcome:** conversations remain coherent without sending all history every time.

## Phase 3 — Add simple long-term memory

Implemented locally with gates disabled by default. See the
[task plan](phase-3-implementation-plan.md), [guide](phase-3-implementation-guide.md),
and [release evidence](releases/phase-3-simple-memory.md). Credentialed verification
remains pending. Phase 4 was explicitly authorized on 2026-10-02.

1. Define memory types: preference, episodic observation, semantic summary, and explicit user correction.
2. Extract candidate memories from conversations.
3. Store memory with provenance, confidence, timestamps, and embeddings.
4. Retrieve relevant memories for a new query.
5. Inject retrieved memory through the context layer.
6. Build tests for relevance, contradiction, temporal change, and non-retrieval of irrelevant facts.

**Outcome:** the system remembers useful personal context across conversations.

## Phase 4 — Make memory experimental

Implemented locally on 2026-10-02 after explicit authorization and plan review.
See the [guide](phase-4-implementation-guide.md) and
[release record](releases/phase-4-experimental-memory.md). Follow the
[Phase 4 task plan](phase-4-implementation-plan.md), including its reviewed
execution contracts. Existing external verification gaps remain open.

1. Implement memory scoring: semantic similarity, importance, recency, frequency, and confidence.
2. Add consolidation jobs that turn related episodes into general preferences.
3. Add contradiction handling and supersession.
4. Add forgetting and decay policies.
5. Compare fixed retrieval, scored retrieval, and consolidated-memory approaches using the evaluation suite.

**Outcome:** memory becomes a researchable subsystem rather than generic RAG.

## Phase 5 — Build the reusable search platform

Implemented locally after explicit authorization on 2026-10-02, behind default-off
gates. The [reviewed task plan](phase-5-implementation-plan.md),
[guide](phase-5-implementation-guide.md) and
[release record](releases/phase-5-source-grounded-research.md) document the bounded
snippet/excerpt scope and remaining external checks.

1. Define research-session, search-query, evidence, and source-adapter contracts.
2. Implement a basic web-search adapter.
3. Add evidence extraction, source attribution, timestamps, TTLs, and deduplication.
4. Add a query-planning interface and a simple single-pass research flow.
5. Add evidence selection and reranking before synthesis.
6. Generate answers with evidence links and clear uncertainty.

**Outcome:** the assistant can conduct fresh, source-grounded research without confusing it with long-term memory.

## Phase 6 — Add entities, constraints, and ranking

Implemented locally after explicit authorization on 2026-10-02. The
[Phase 6 task plan](phase-6-implementation-plan.md), [guide](phase-6-implementation-guide.md),
[ADR 0012](decisions/0012-evidence-grounded-decision-support.md), and
[release record](releases/phase-6-decision-support.md) document contracts,
policy behavior, offline results, and remaining external verification gaps.
Evidence-backed research entities remain separate from authoritative
domain-application state; a Phase 5 session is optional when another validated
evidence source supplies a decision.

1. Define canonical entities and entity-resolution interfaces.
2. Implement deterministic hard constraints, such as budget, date, availability, dimensions, or location.
3. Implement explainable soft ranking.
4. Use memory-derived preferences only after hard constraints are satisfied.
5. Add evaluation cases for stale data, conflicting sources, duplicate entities, and invalid recommendations.

**Outcome:** research turns into structured decision support instead of a generic web summary.

## Phase 7 — Build travel and shopping agents

Implemented locally on 2026-10-02. See the [Phase 7 implementation guide](phase-7-implementation-guide.md),
[provider ADRs](decisions/0013-nominatim-travel-place-source.md),
[synthetic evaluation](releases/phase-7-travel-shopping.md), and the detailed
[Phase 7 task plan](phase-7-implementation-plan.md). Provider, emulator, and
deployed checks remain open.

This phase validates thin AI-side travel and shopping modules with synthetic
data. It does not require rich applications to live in this repository. Future
separate applications may own itineraries, bookings, purchases, business rules,
and specialized UI while consuming the shared research and decision contracts.

1. Implement shared travel research models for places, neighborhoods, hotels, flights, restaurants, and evidence-backed itinerary proposals.
2. Add travel source adapters incrementally, beginning with general web search and structured place data.
3. Implement travel-specific constraints and ranking features.
4. Implement the shopping domain: products, offers, merchants, specifications, and reviews.
5. Add shopping-specific source adapters, constraints, and ranking features.
6. Build bounded reference views for evidence, comparisons, filters, and recommendation rationale; rich domain-application UI remains app-owned.

**Outcome:** two practical domain agents validate that the shared platform is reusable.

## Phase 8 — Add iterative research behavior

Implemented locally under explicit authorization. See the [Phase 8 task
plan](phase-8-implementation-plan.md), [guide](phase-8-implementation-guide.md),
[accepted state/budget ADRs](decisions/0016-bounded-iterative-research.md),
and [release evidence](releases/phase-8-iterative-research.md). The Phase 8
evidence records checks from that implementation period; current persistence
verification is tracked in [current state](current-state.md).

1. Make the research agent assess whether evidence is sufficient.
2. Identify missing facts, conflicts, stale evidence, or weak entity matches.
3. Generate focused follow-up searches.
4. Stop based on a configurable evidence-quality budget.
5. Stream research progress to the frontend.
6. Evaluate single-pass versus iterative research on the same scenarios.

**Outcome:** the system can investigate a question in multiple steps instead of only performing search → answer.

## Phase 9 — Harden and deploy

Authentication and private-data controls must move earlier if any earlier
phase or external application begins using real emails, bookings, receipts,
uploads, or other private records. The phase number is not a waiver of that
prerequisite. Local/test `local` ownership is unauthenticated; deployed code
requires Google OIDC and private API IAM. Phase 9 is partially implemented, with
open acceptance criteria in its [task plan](phase-9-implementation-plan.md) and
[evidence](phase-9-implementation-evidence.md).

1. Add authentication appropriate for personal use.
2. Add secrets management, observability, rate limits, and cost safeguards.
3. Deploy the API and UI, initially with a simple serverless architecture.
4. Add scheduled maintenance for memory consolidation and evidence expiry.
5. Create backups, export tools, and data-deletion controls.
6. Track evaluation results and regressions for every experimental change.

**Outcome:** a private, maintainable personal AI system that can support real experiments.

## Chapter 2 roadmap

Chapter 2 is a separate next-scope plan, not an extension of this original
phase numbering. See the [Chapter 2 overview](personal-ai-chapter-2/README.md),
[numbering map](personal-ai-chapter-2/NUMBERING-MAP.md), and [current state](current-state.md).
