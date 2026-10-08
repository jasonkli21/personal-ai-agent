# Target architecture

Status: target for future Chapter 2 work. The Phase 10 Postgres/DynamoDB
runtime wiring is implemented locally; see [current state](../current-state.md)
for code status and unverified acceptance gates.

## 1. Pre-Phase-10 repository baseline (historical)

When this target was prepared, the implementation was Firestore-based. P10.6
later changed normal API/worker runtime wiring and removed Firestore runtime
dependencies; no real data migration or cloud cutover is claimed. This section
preserves the pre-P10 baseline for context rather than describing current code.

Completed next-scope Phases 1–2 add application/workspace identity and an application registry on top of the existing system.

## 2. Target logical architecture

```text
Domain apps / standalone UI
          |
          v
Application Integration Contract
 scope / manifest / typed providers / policy
 optional host / federation / mutation capabilities
          |
          v
Policy -> Context planner -> authorized context providers
          |                       |
          |                       +--> domain-owned APIs
          |                       +--> Postgres memory/profile/research
          |                       +--> DynamoDB conversation/runtime
          v
AI capability runtime freezes permitted source/policy facts
          |
          +--> search/research through search adapters
          |
          +--> Personal AI endpoint registry + non-disclosing hard admission
                 |
                 v
              provisional Personal AI semantic selection
              pluggable RoutingStrategy (no provider calls)
                 |
                 v
              endpoint-specific context assembly + admitted counter
                 |
                 v
              revalidate policy/profile + reserve all quota buckets
                 |
                 v
              final ExecutionPlan -> Personal AI inference gateway
                 |
                 v
              LiteLLM Python SDK (implemented in Phase 17R) -> selected endpoint
              Gemini / Groq / Cloudflare initially;
              OpenRouter as a later provider family

                 STRICT_FREE: eligible automatic endpoint profiles
                 EXPLICIT_BYOK: explicit user-billed lane (future)
                 CHATGPT_PLAN: separate explicit subscription lane
                   via local/user-controlled bridge
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

The [Phase 10 storage contract](phase-10-storage-ownership-and-access-patterns.md) fixes record-level ownership and scoped references. Research transaction groups and knowledge-effect receipts stay Postgres-owned even when execution jobs/timelines are DynamoDB-owned. P10.6 implemented the local runtime ownership split; target-engine, cloud, migration-source, and recovery acceptance are tracked in the [Phase 10 verification plan](phase-10-migration-cutover-and-verification-plan.md). The remaining context/provider architecture in this document is a future target, not a claim that those layers are implemented.

Endpoint fit is established only after provisional selection by assembling/counting with that endpoint's serializer and admitted counter. A remote counter or summary call is a separately authorized operation; denial means zero context disclosure. Final policy/source revalidation and atomic quota reservation precede generation dispatch. Any bounded reselection creates a linked decision and recomputes preparation under the same or narrower still-authorized source set and request deadline; if a revoked source is required by task policy, abort. See the shared [endpoint-specific preparation lifecycle](03-free-tier-inference-and-routing.md#endpoint-specific-preparation-and-dispatch).

## 4. Request envelope

Conceptually carries authenticated owner plus `application_id`, optional `workspace_id`, conversation/request identity, bounded capabilities, and bounded non-authoritative client context. Owner authority is server-derived; application/workspace labels do not replace authentication/membership checks.

## 5. Application registry

Maps application identity to supported context providers, tools/actions, policies, memory namespace, sensitivity defaults, cross-app declarations, and optional budget hints. Registration advertises capability; it grants no permission by itself.

### Application Integration Contract

The **Application Integration Contract** is the evolving logical typed interface through which independently authoritative applications integrate with Personal AI. It composes existing scope and registry contracts; it need not become one class, package, SDK, or plugin framework. Travel, Shopping, Finance, and Health are initial reference integrations, not a closed set of application types.

| Phase | Contract contribution |
| --- | --- |
| 1 (implemented) | Authenticated `RequestScope` with application/workspace identity. |
| 2 (implemented) | `ApplicationDefinition`, workspace semantics, and capability registration metadata. |
| 11 (future) | First runtime integration seam: scope + definition + registered typed `ContextProvider` capabilities. |
| 15 (partially implemented) | Typed application/provider/operation/field policy, sensitivity declarations, and local pre-retrieval/model-disclosure enforcement. End-to-end revocation through derived context and immutable Postgres policy/source references remain open. |
| 25.4 (future) | Optional shared sidecar/host launch and action hooks. |
| 30 (future) | Optional scoped export/federation declarations and authorization dependencies. |
| 31 (future) | Optional versioned typed mutation capabilities. |
| 36 (future) | Complete evaluation/conformance fixtures. |

Shared orchestration consumes registered capabilities instead of branching on application names. Domain providers, adapters, policies, validators, APIs, and registration own application-specific behavior. A domain implementation may repair a demonstrated shared abstraction deficiency, but the repair must remain compatible with synthetic applications.

Domain -> Personal AI supplies bounded typed context; Personal AI -> domain supplies typed proposals; the domain authorizes, validates, writes, and returns authoritative post-state. Personal AI may own conversations, AI memory, research/evidence, routing/evaluation metadata, policy/control records, proposals, and AI artifacts. It must not become the canonical store for trips/bookings, shopping projects/products, financial records, or Health records.

Reference integrations progressively test broad workspace/entity/booking-versus-evidence context (Travel), constraints and saved/rejected project state (Shopping), narrow sensitive read-only context with semantic labels (Finance), and flexible field-sensitive records with bounded time series (Health). Phase 36 validates a synthetic fifth app against the completed contract, rather than introducing extensibility then.

## 6. Context providers and source classes

Providers hide domain storage details and return bounded typed records with owner/app/workspace scope, source identity/version, provenance, authority, sensitivity, timestamps, and predictable failures.

Normalize this envelope, entity references, permission dependencies, and freshness/expiry; preserve domain-typed payloads. Trips, shopping projects, portfolios, and Health profiles do not become one universal untyped domain-data schema.

Source classes remain explicit: global profile, domain profile/current/history, AI memory, conversation, external research, tool result, and client context. Source class affects trust, freshness, policy, priority, and downstream sensitivity.

## 7. Context planner and builder

Planner decides **what information to retrieve**, beginning with deterministic rules. Builder assembles system/security instructions, application policy, bounded global/domain context, memory, conversation, research/evidence, and tool state while enforcing token/source budgets, recency, authority, sensitivity, and provenance.

The builder emits a safe actual-build manifest. Reconstruction of historical context from current state is explicitly labelled as estimated.

## 8. Policy boundary

Before retrieval: authenticate/authorize owner/app/workspace, provider/field/cross-app access, sensitivity, and operation class.

Before model/auxiliary disclosure: verify provider privacy/data policy, strict-free eligibility when applicable, and capability/context fit. Explicit ChatGPT selection does not bypass these checks.

Typed application policy/capability configuration narrows disclosure and sensitivity without separate planner, builder, inference, or sidecar forks. The Phase 15 local contract implements server-owned provider/operation/field rules and passes effective sensitivity to the internal inference boundary; immutable policy-version references and revocation through all derived-context surfaces remain open. Registration still grants no permission; neither explicit BYOK nor same-owner cross-app access waives authorization.

Before mutation: require a typed proposal, domain validation, exact user confirmation, idempotency, and authoritative post-state.

## 9. Provider runtime

Personal AI's neutral inference/embedding contracts remain the application-facing boundary for generation, streaming, structured generation, token/counting semantics, embeddings, usage, provider/execution identity, latency/status/error information, sensitivity/inference context, cancellation, and embedding-space identity. LiteLLM types do not escape the Personal AI inference gateway; application, domain, and context code do not call LiteLLM directly.

The first transport integration, [Phase 17R](personal-ai-next-scope-detailed-implementation-plans/plans/phase-17r-implementation-plan.md), is implemented locally with the LiteLLM Python SDK inside the existing runtime. Phase 17's Gemini/Groq/Cloudflare adapters remain reference/parity evidence. Live provider compatibility and account/tier/privacy gates remain unverified. A separate LiteLLM Proxy/Gateway is not initial scope.

Personal AI owns endpoint profiles, hard admission/privacy policy, semantic routing, execution/cost-mode permission, quota accounting, evaluation, cascades, and later adaptive strategies. The router applies deterministic hard filters before a project-owned `RoutingStrategy`; the strategy produces an explainable provisional selection without provider calls. Personal AI then assembles/counts endpoint-specific input, revalidates policy and profile facts, reserves all applicable quota buckets, and finalizes an `ExecutionPlan`. LiteLLM mechanically executes that selected endpoint. LiteLLM Router, cross-provider/model fallback, and load balancing must not silently make semantic decisions. Phase 17R configures zero implicit SDK/provider retries; a later explicitly accounted same-endpoint retry requires Phase 19 attempt admission and cannot change provider/model, account/credential scope, cost mode, or consent.

The primary routable unit is a versioned execution endpoint profile, not provider order or a LiteLLM catalog entry. Model, provider, deployment/endpoint, credential source/scope, account/project/tier, execution mode, cost/billing class, capability, and privacy eligibility are distinct facts. Endpoint profiles contain safe references and metadata, never credential secrets. `STRICT_FREE`, `EXPLICIT_BYOK`, and `CHATGPT_PLAN` remain separate. Unknown cost is not free; strict-free exhaustion never selects paid/BYOK or subscription capacity.

Gemini, Groq, and Cloudflare are initial reference endpoint families, not privileged identities. A LiteLLM-supported provider normally adds endpoint/configuration/profile/evaluation without new transport code; retain a narrow provider-specific shim only for a demonstrated LiteLLM compatibility gap. OpenRouter is a possible later provider family, not a Phase 17R or Phase 18–24 live requirement. A specific OpenRouter model can be a normal endpoint profile. An OpenRouter-managed `auto`/`free` router is a future composite/virtual endpoint whose requested virtual identity and actual upstream identity are retained separately. Before disclosure, every possible upstream must satisfy enforceable cost, data-policy, capability, context, and quality bounds; unknown membership excludes the composite for requests it cannot safely attest. Unknown response identity cannot claim model-specific measured quality.

Routing decision and invocation observations follow the shared [Routing Observation Contract](03-free-tier-inference-and-routing.md#routing-observation-contract). Phase 21 introduces its strategy and `ExecutionPlan` seams; Phases 19–24 add joinable operational facts; Phase 35 is the first phase that experiments with learned/adaptive strategies.

ChatGPT plan is a separate explicit lane using a local/user-controlled credential runtime and shared context package. It never silently becomes automatic fallback or API-key billing.

### Task, validator, and evaluation extension seams

Task identity is distinct from typed requirements: structured output, context/output capacity and count confidence, sensitivity/privacy, citation behavior, required quality profile/floor, deterministic validator references, and bounded retry/escalation permission. Generic routing filters registered endpoint facts for execution/cost mode, privacy, capability, endpoint-specific count support, context fit, quota-bucket membership, quality floor, and cooldown/exhaustion before any preference strategy. A required measured floor rejects missing, stale, insufficiently covered, or below-floor evidence; only tasks explicitly allowing unmeasured baseline operation may use configured priorities without numeric quality. Names are configuration/trace identity, not provider- or task-name branches in generic control flow. A new domain task that fits existing requirements can register policy and validators without router edits; genuinely new requirements extend the shared contract with conformance coverage.

Registered deterministic `TaskValidator` capabilities may cover schema, citations, required fields, hard constraints, exact source spans, and domain-specific itinerary or shopping checks. Tasks reference validator IDs/versions through typed configuration; generic cascades execute them without domain branches. Cascades remain bounded and free-only, with unchanged source/sensitivity constraints.

Evaluation operates over registered eligible endpoint profiles and task fixtures/profiles. Quality identity includes provider, endpoint/model, serializer/configuration, task/profile, policy version, and tested revision (plus counter/seed where applicable), so evidence is invalidated when relevant configuration changes. Initial live evaluation remains Gemini/Groq/Cloudflare; a synthetic additional provider tests harness extension without a fourth live integration or fabricated quality evidence. Strict-free evaluation prohibits paid/unknown-cost endpoints.

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

## 11. Other semantic seams and deferred abstractions

Generalize when upcoming phases persist policy, routing decisions, evaluation identities, or runtime state against a seam. Defer speculative frameworks when replacement remains local and only one implementation needs them.

- **Search/research:** evolve the existing `SearchAdapter` boundary with search and applicable lookup/fetch capabilities, safe usage metadata, source-rights metadata, and explicit failure semantics. Brave is an initial adapter, not the definition of research. Keep source policy, provenance, freshness, bounded retrieval, and zero-overflow admission; search and model providers retain separate contracts. Phase 19 handles accounting/admission and Phase 33 evaluates retrieval extensions; no extra live search provider is required to prove the seam.
- **Embedding spaces:** identify provider, model, dimensions, normalization, task semantics, and version. A future migration creates a new space identity with explicit re-embedding/re-index and resource acceptance; incompatible vectors are never mixed. Preserve current Gemini compatibility and original vector values until separately authorized migration.
- **Memory experiments:** keep repository, retriever, ranker, extractor, and lifecycle-policy seams where justified by current code. Preserve strategy/version, embedding-space, provenance, lifecycle, and retrieval/ranking metadata needed for evaluated comparisons; Phase 34 remains retrieval optimization, not a speculative memory-plugin framework.
- **Tools/actions:** eventual typed capabilities carry operation ID/version, input/output schema, read/write class, sensitivity, authorization, provenance, and idempotency where needed. Phase 31 and actual app use cases shape the interface; generic model orchestration must not branch on tool names.

Keep intentional Postgres/pgvector, DynamoDB, GCS, and Cloud Run roles behind existing semantic contracts. Do not add arbitrary database/object-store/compute portability, dynamic plugins/provider marketplaces, automatic paid fallback or budgeted BYOK, a hosted user-key vault, a new embedding migration, or a general tools ecosystem. Extract a shared client SDK only later if real integrations demonstrate meaningful repetition. These are future planning boundaries, not claims of implemented capabilities.
