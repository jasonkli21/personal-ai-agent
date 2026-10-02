# Reconciliation Summary

Status: proposed documentation update  
Date: 2026-10-02

## Purpose

The earlier design discussion was written as though `personal-ai-system` were still at the pre-v1 planning stage. The repository has progressed beyond that point.

This document records what should change in the earlier long-term notes so they align with the current codebase and accepted ADRs.

## 1. Current implementation wins over the earlier v1 sketch

The earlier sketch described a future v1 with:

- basic chat,
- Firestore,
- SSE,
- a Gemini provider,
- no memory,
- no Pub/Sub,
- no research.

That is now obsolete as a description of the repository.

The current repo has already implemented locally:

- persistent branchable chat,
- regenerate/edit-and-retry,
- provider-authoritative context budgeting,
- branch-safe working summaries,
- read-only context inspection,
- source-grounded memory extraction and vector retrieval,
- experimental memory scoring/lifecycle/consolidation/forgetting,
- a private Pub/Sub-triggered worker for bounded lifecycle jobs.

Therefore these capabilities are the baseline to preserve, not future v1 scope.

## 2. Phase 5 status must be stated carefully

The supplied docs contain a handoff mismatch:

- the project brief still frames Phase 4 verification as active and says not to advance to Phase 5 without explicit instruction;
- ADR 0011 states that Phase 5 was explicitly authorized and defines the accepted bounded research design.

Reconciled interpretation:

> Phases 1–4 are implemented locally. Phase 5 has been explicitly authorized and has an accepted design decision. Do not claim that Phase 5 is implemented unless code/release evidence in the live repository confirms it.

Codex should update stale handoff wording before using it to decide the next task.

## 3. Pub/Sub is no longer a pure future/non-goal

The earlier discussion correctly said Pub/Sub is unnecessary for streaming chat tokens.

That remains true.

However, Pub/Sub is now part of the Phase 4 architecture:

- lifecycle jobs are persisted before notification,
- a private worker receives authenticated Pub/Sub push,
- processing uses fenced leases and bounded recovery.

The correct rule is now:

> SSE is the synchronous browser streaming path. Pub/Sub is reserved for durable asynchronous work with a demonstrated need.

Do not remove Pub/Sub merely to match the old v1 sketch.

## 4. Firestore is more deeply integrated than the earlier portability sketch implied

The repository already uses Firestore behind repository boundaries, which is good for portability.

However, simple memory also uses Firestore cosine KNN and model/dimension-prefiltered vector search. An eventual DynamoDB move therefore has two separate concerns:

1. canonical durable records;
2. vector retrieval/indexing.

A future migration must not assume that replacing a document repository automatically replaces Firestore vector search.

## 5. Cloud Storage should be a reserved extension point, not a current dependency

The earlier plan added Cloud Storage as though it were part of v1.

The current repo does not need it in the core request path.

Phase 5's accepted bounded research design explicitly avoids storing full publisher pages or raw provider responses. Therefore no blob store is required merely for research snippets/evidence.

Cloud Storage becomes justified when a real feature requires durable blobs, for example:

- uploaded PDFs,
- email attachments,
- user images,
- exported research artifacts,
- domain-app documents.

Add a `BlobStore` boundary when that requirement becomes concrete.

## 6. Model upgrades should use the existing runtime boundary

The repo already did the important architectural work:

- Gemini is behind an internal LLM client protocol;
- `AI_MODEL` is runtime configuration;
- context ceilings are application configuration rather than inferred from a hard-coded provider model.

As of 2026-10-02, Gemini 3.8 Flash is a newer stable Flash generation model than the deployment example's `gemini-2.5-flash`.

Reconciled recommendation:

- do not hard-code `gemini-3.8-flash` into application code;
- test it through the existing `AI_MODEL` configuration;
- verify context/output assumptions and provider-quality checks before making it the deployment default.

Embedding changes are more disruptive. The accepted Phase 3 design currently uses `gemini-embedding-001`, 768 dimensions, and Firestore vector indexes. A move to Gemini Embedding 2 should be a separate migration/ADR with explicit compatibility, re-embedding, and index strategy.

## 7. Domain modules and separate rich applications can coexist

The repository currently says travel and shopping are domain modules on one reusable platform.

The newer product vision says travel, shopping, and health should have substantial specialized UIs and may live in separate repositories.

These are compatible if the boundary is:

```text
personal-ai-system
  shared research/memory/model/evidence/tool capabilities
  optional domain intelligence modules
        ^
        |
        | stable API/client contract
        |
travel-app / shopping-app / health-app
  rich UI
  authoritative domain state
  deterministic domain business rules
```

The shared system may understand domain schemas and ranking logic without owning every domain application's state or UI.

## 8. Health remains long-term only

The current public bootstrap has no end-user authentication and is explicitly unsuitable for sensitive personal data.

Therefore health should remain a future consumer of the platform, not a near-term implementation phase.

Before real health data is supported, require at minimum:

- authenticated user identity,
- authorization and scoped access,
- deliberate model/provider data-use policy,
- secure upload/blob handling if documents are supported,
- audit/deletion/export rules,
- stronger separation between authoritative health records and AI-derived observations.

## 9. Do not build a generic app/plugin framework yet

The earlier platform vision proposed manifests, generic schemas, tool registries, app-scoped memory, and SDKs.

Those are plausible end-state abstractions but should remain deferred.

Build them only after at least one rich external application creates repeated integration requirements.

The current Phase 5/6/7 roadmap should remain the source of pressure for those abstractions rather than designing them speculatively.
