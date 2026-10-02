# Current State and Near-Term Scope

Status: reconciled handoff  
Date: 2026-10-02

## 1. Confirmed baseline from supplied repository docs

Implemented locally:

- FastAPI + Next.js project structure.
- Conversation creation/list/reopen.
- Firestore repositories plus deterministic local fakes.
- Provider-neutral LLM boundary and Gemini streaming adapter.
- SSE chat responses.
- Append-only branchable message history.
- Regenerate and edit/retry.
- Provider-authoritative context budgeting.
- Branch-safe working summaries.
- Development-only context inspection.
- Source-grounded memory extraction.
- Gemini embeddings and Firestore vector retrieval.
- Experimental scoring/consolidation/contradiction/forgetting lifecycle.
- Private worker for bounded Phase 4 memory jobs using authenticated Pub/Sub push.
- Offline backend/frontend tests and CI.
- Cloud Run/GCP deployment bootstrap.

Still incomplete or deliberately absent:

- real end-user authentication/authorization,
- user-facing memory management,
- broad inferred memory consolidation,
- domain agents,
- full domain applications,
- generalized scheduled maintenance,
- sensitive-data-ready deployment.

External verification gaps also remain for credentialed Firestore/Gemini/deployed behavior.

## 2. Phase 5 status

ADR 0011 is accepted and says Phase 5 was explicitly authorized.

Its accepted shape is intentionally constrained:

```text
standalone opt-in research request
  -> bounded typed queries
  -> Brave search snippets only
  -> bounded observations/evidence
  -> source-grounded selection
  -> citation from persisted source metadata
```

Important constraints:

- research is independent from chat/memory flows;
- request execution is owned by the request/SSE connection;
- there is no implicit retry after process loss;
- full publisher pages/raw search responses are not retained;
- redirects and publisher page fetches are forbidden;
- broader free-form synthesis remains deferred;
- larger asynchronous investigations remain deferred.

Unless implementation/release evidence exists elsewhere in the live repository, treat this as an authorized/accepted design, not proof of completed implementation.

## 3. Near-term priority

Do not pivot from the current roadmap into building travel/shopping/health applications yet.

Recommended immediate ordering:

1. reconcile stale handoff docs around Phase 5 authorization;
2. close important external verification gaps for delivered Phase 1–4 behavior;
3. implement/verify the accepted bounded Phase 5 research slice if not already complete;
4. evaluate the research evidence contracts before expanding to Phase 6;
5. keep domain app integration as a design constraint, not an implementation prerequisite.

## 4. No new generic platform framework

Do not add now solely for long-term extensibility:

- app manifests,
- generic plugin registries,
- cross-repo SDKs,
- generic action-approval engines,
- multi-cloud runtime,
- universal blob storage,
- health-specific schemas,
- broad event ingestion,
- generalized workflow engines.

These should be introduced only when a concrete phase/app requires them.

## 5. Preserve current accepted boundaries

### LLM boundary

Continue to keep provider-specific generation/counting/embedding behavior inside the LLM layer.

### Repository boundaries

Continue to keep Firestore details out of application services and API routes.

### SSE

Keep SSE for browser-facing streaming.

### Pub/Sub

Use Pub/Sub only for durable asynchronous work that needs it. It should not enter ordinary token streaming.

### Context

Keep the shared context assembler as the only prompt path. New memory/evidence/domain context must fit through its explicit budget/provenance rules rather than creating parallel prompt assembly.

### Evidence

Preserve source, observation/freshness metadata, and selected evidence. Do not turn model conclusions into durable facts.

### Hard constraints

Application/deterministic code enforces requirements such as price limits, dates, dimensions, availability, or location. Model reasoning/ranking operates after those filters.
