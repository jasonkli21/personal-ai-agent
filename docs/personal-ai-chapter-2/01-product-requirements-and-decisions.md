# Product requirements and durable decisions

Status: integrated next-scope plan, regenerated 2026-10-06; extensibility clarified 2026-10-07. Future requirements below do not establish delivery; see [current state](../current-state.md).

## Product goal

Personal AI is an open-ended shared AI substrate for standalone use and independently authoritative applications. Travel, Shopping, Finance, and Health are initial reference integrations. It should remain useful on strict-$0 hosted resources/models, preserve domain authority, support attributable personal memory and research, and evolve as the free cloud/model landscape changes without requiring user-owned AI hardware.

The architecture should be **heterogeneous-capable but incrementally activated**: abstractions may support multiple free providers/resources over time, while each implementation phase introduces only complexity justified by product, capacity, reliability, or learning value.

## Existing foundation

The repository already has conversation/chat, source-attributed memory, research/evidence/decision/domain seams, partial owner authentication, deterministic context/research safeguards, and evaluation infrastructure. Next-scope Phases 1–2 added application/workspace identity and the application registry/manifest model. Phase 10 runtime wiring uses Postgres/pgvector and DynamoDB locally and retires Firestore; real-engine, live cloud/IAM, strict-$0, source/no-source, and recovery acceptance remain open as recorded in [current state](../current-state.md) and [P10.6 evidence](phase-10-p10.6-implementation-evidence.md).

Phase 10 changes persistence; it does not reset this foundation. Phase 11 is the next planned boundary and remains unimplemented.

## Product requirements

### Shared application context

- Every request has owner/application/workspace scope.
- Domain applications remain authoritative for their own state.
- Personal AI retrieves bounded typed context through providers rather than directly querying domain databases.
- Cross-app context is deny-by-default and later requires explicit revocable policy/grants.
- Global Personal-AI preferences are bounded and distinct from domain profiles and inferred memory.
- The [Application Integration Contract](02-target-architecture.md#application-integration-contract) evolves through existing phases; domain capabilities extend registration rather than application-name branches in shared orchestration. Normalize context metadata while preserving domain-typed schemas.

### Context, provenance, and policy

- Context source class, authority, sensitivity, timestamps, and source references remain explicit.
- Context planning is deterministic first; LLM-assisted planning is a measured later experiment.
- Unauthorized data is not fetched first and filtered later.
- Effective sensitivity is monotonic and controls auxiliary as well as primary model disclosure.
- Developer inspection is bounded/redacted and distinguishes actual-build manifests from estimates.

### Strict-$0 hosted inference

- Gemini, Groq, and Cloudflare are initial reference inference adapters for eligible automatic free capacity; future adapters extend neutral contracts through profiles, tests, preflight, evaluation, and configuration.
- Provider/model profiles describe capabilities, privacy/data policy, account/tier eligibility, and quota facts independently of routing.
- Paid/unknown-eligibility paths never silently enter strict-free candidates.
- Quota usage is measured before quota-aware routing is introduced.
- Routing, cascades, and later adaptive experiments always preserve hard privacy/capability/free constraints.
- Strict-free/free-first remains the default automatic execution policy. Optional BYOK API capacity is user-billed and explicit-only initially; free exhaustion never crosses into paid capacity. ChatGPT subscription execution is a separate explicit lane and does not imply OpenAI API capacity.
- Provider, endpoint/model, credential source/reference, account/project/tier, cost class, and selection eligibility remain distinct; profiles never hold secrets. See [execution modes](03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes).
- Routing consumes endpoint facts and task requirements; tasks attach registered deterministic validators. Evaluation profiles extend by endpoint/task configuration and versioned evidence rather than a fixed provider list.

### ChatGPT plan integration

- ChatGPT plan use is an explicit user-controlled lane, not automatic strict-free fallback.
- Reusable ChatGPT credentials live only in protected user-controlled/local runtime storage.
- Browser/cloud services never receive reusable ChatGPT tokens.
- Context sent to ChatGPT uses the same planner/provider/policy/builder pipeline.
- Completed turns preserve safe provider/model attribution.
- Sidecar Copy is broadly allowed; Insert is non-authoritative only; Apply requires the typed mutation framework and domain validation/confirmation.

### Persistence and artifacts

After Phase 10:

- DynamoDB is canonical for operational timeline state with stable key/range access patterns.
- Neon Postgres + pgvector is canonical for relational/query-rich knowledge, memory, provenance, lifecycle, control metadata, and vector retrieval.
- GCS is introduced later for bulky immutable artifact bodies.
- Local Postgres + pgvector and DynamoDB Local are first-class development/test targets.
- Every durable record class has exactly one canonical store.
- Cross-store workflows are idempotent/recoverable; no distributed transaction or permanent dual-write architecture is assumed.
- Firestore is migrated and retired from normal runtime after a bounded rollback window.

### Domain authority and mutation

- Travel, Shopping, Finance, and Health state stays authoritative in those applications.
- Generic model output cannot directly mutate authoritative domain state.
- Typed mutation proposals carry target, version, rationale/source provenance, validation/confirmation state, and idempotency.
- Domain validation and explicit user confirmation precede AI-assisted authoritative writes.
- Provider/model identity is provenance, never mutation authority.

## Strict-$0 requirement

Zero-dollar operation is a product constraint across the whole deployed system, not only model calls. Operational verification must include model/search quotas, Cloud Run/GCS/Artifact Registry/Secret Manager, Neon compute/storage/connections, DynamoDB capacity/storage/indexes, and cross-cloud network usage. Free-tier facts are operational metadata, not hard-coded application constants.

## README accuracy requirement

Each implementation phase reviews the root README and updates it only when user/developer-visible facts change. Phase 10 must update architecture/tech-stack/setup/deployment sections after the migration is actually complete. Historical evidence and ADRs are not rewritten to imply future architecture existed earlier.

## Non-goals

- using every free provider/service immediately;
- making Personal AI authoritative for domain databases;
- hiding unverified cloud/provider gates behind a “passed” status;
- accumulating duplicate canonical state for convenience;
- broad multi-cloud infrastructure beyond justified components;
- paid fallback in strict-$0 mode.
- automatic budgeted BYOK, hosted user API-key vaults, dynamic plugins/provider marketplaces, premature shared client SDKs, arbitrary storage/compute portability, new embedding migrations, or a general tool ecosystem.

Use the [target architecture](02-target-architecture.md#11-other-semantic-seams-and-deferred-abstractions) for the detailed generalization rule. Storage/runtime roles remain intentionally concrete; these clarifications add no major phase and remove no existing normative requirement.
