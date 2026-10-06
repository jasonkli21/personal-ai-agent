# Target architecture

Status: target after Phase 10 unless explicitly marked current

## 1. Current repository baseline before Phase 10

The current implementation is still Firestore-based. This document distinguishes that factual baseline from the target so planning does not make the root README or historical evidence prematurely claim the migration is complete.

Completed next-scope Phases 1–2 add application/workspace identity and an application registry on top of the existing system.

## 2. Target logical architecture

```text
Domain apps / standalone UI
          |
          v
Request scope + application registry
          |
          v
Policy -> Context planner -> Context providers -> Context builder
          |                                  |
          |                                  +--> domain-owned APIs
          |                                  +--> Postgres memory/profile/research
          |                                  +--> DynamoDB conversation/runtime
          v
Provider-neutral inference runtime
          |
          +--> automatic strict-free providers
          |      Gemini / Groq / Cloudflare
          |
          +--> explicit ChatGPT plan lane
                 local/user-controlled bridge
```

## 3. Target data plane after Phase 10

```text
                         Personal AI Runtime
                                |
          +---------------------+---------------------+
          |                     |                     |
          v                     v                     v
      DynamoDB              Neon Postgres             GCS
 operational timeline       + pgvector          artifact bodies
          |                     |                     |
 conversations/messages      global profile          raw evals
 summaries/runtime events    memory + vectors        verbose traces
 checkpoints/idempotency     provenance/lifecycle   exports/replay
                             research/decisions
                             compact metadata
```

Rules:

1. DynamoDB is authoritative for operational timeline state assigned by Phase 10.
2. Postgres is authoritative for query-rich/interpreted state and semantic/vector memory.
3. GCS is authoritative only for artifact bodies introduced by Phase 20.
4. No authoritative domain-app state is copied into these stores as a substitute for the domain API.
5. No durable record class is canonical in two stores.
6. No cross-store atomic transaction is assumed; projections/retries are idempotent and recoverable.
7. Local Postgres/pgvector and DynamoDB Local implement the same repository contracts used by cloud deployments.
8. Firestore is a migration/rollback source, not target architecture.

## 4. Request envelope

Conceptually carries authenticated owner plus `application_id`, optional `workspace_id`, conversation/request identity, bounded capabilities, and bounded non-authoritative client context. Owner authority is server-derived; application/workspace labels do not replace authentication/membership checks.

## 5. Application registry

Maps application identity to supported context providers, tools/actions, policies, memory namespace, sensitivity defaults, cross-app declarations, and optional budget hints. Registration advertises capability; it grants no permission by itself.

## 6. Context providers and source classes

Providers hide domain storage details and return bounded typed records with owner/app/workspace scope, source identity/version, provenance, authority, sensitivity, timestamps, and predictable failures.

Source classes remain explicit: global profile, domain profile/current/history, AI memory, conversation, external research, tool result, and client context. Source class affects trust, freshness, policy, priority, and downstream sensitivity.

## 7. Context planner and builder

Planner decides **what information to retrieve**, beginning with deterministic rules. Builder assembles system/security instructions, application policy, bounded global/domain context, memory, conversation, research/evidence, and tool state while enforcing token/source budgets, recency, authority, sensitivity, and provenance.

The builder emits a safe actual-build manifest. Reconstruction of historical context from current state is explicitly labelled as estimated.

## 8. Policy boundary

Before retrieval: authenticate/authorize owner/app/workspace, provider/field/cross-app access, sensitivity, and operation class.

Before model/auxiliary disclosure: verify provider privacy/data policy, strict-free eligibility when applicable, and capability/context fit. Explicit ChatGPT selection does not bypass these checks.

Before mutation: require a typed proposal, domain validation, exact user confirmation, idempotency, and authoritative post-state.

## 9. Provider runtime

Provider SDKs remain below neutral inference/embedding contracts. Automatic routing applies hard strict-free/privacy/capability filters before deterministic priorities, then later measured quota/cascade/adaptive optimization.

ChatGPT plan is a separate explicit lane using a local/user-controlled credential runtime and shared context package. It never silently becomes automatic fallback or API-key billing.

## 10. Local/cloud topology

```text
LOCAL                              CLOUD
FastAPI                            Cloud Run
 |                                  |
 +-> Postgres + pgvector             +-> Neon Postgres + pgvector
 +-> DynamoDB Local                  +-> AWS DynamoDB
 +-> fake/local ArtifactStore        +-> private GCS (Phase 20+)
```

AWS scope in Phase 10 is deliberately narrow: IAM needed for DynamoDB plus DynamoDB itself. Lambda/API Gateway/SQS/EventBridge/etc. are not introduced merely because DynamoDB exists.
