# Free-tier inference and routing

## Principles

The project optimizes for a fully hosted strict-$0 AI system without requiring local AI hardware. Model/search quota is expected to be the near-term throughput limiter, but durable storage and cloud resource use accumulate over time and are tracked separately.

This is future Chapter 2 planning. Strict-free/free-first is the default automatic execution goal; optional explicit user-funded capacity is additive. See [current state](../current-state.md) for implemented behavior.

## Provider boundary

The intended sequence is:

```text
16  Personal AI neutral inference and embedding contracts
17  completed Gemini/Groq/Cloudflare reference adapters
17R planned LiteLLM execution-substrate reconciliation
18  endpoint registry and strict-free admission
19  usage/quota ledger and invocation observations
21  deterministic semantic routing and RoutingStrategy baseline
22  task-profile x endpoint-profile quality evidence
23  deterministic scarcity-aware strategy inputs
24  bounded Personal AI cascades and deterministic validation
35  adaptive strategy experiments
```

Phase 17 established contract behavior and provider edge cases; Phase 17R plans a migration behind those contracts. Personal AI's neutral contracts remain the application-facing boundary for generation, streaming, structured generation, count confidence, embeddings, usage, provider/execution identity, latency/status/errors, sensitivity/inference context, cancellation, and embedding-space identity. LiteLLM-specific types stay inside the Personal AI inference gateway. Context, domain, and application code must not call LiteLLM directly.

The planned first integration uses the LiteLLM Python SDK inside the existing runtime. A separately deployed LiteLLM Proxy/Gateway is not initial scope. Personal AI owns semantic routing, hard admission, privacy, execution/cost modes, task quality, quota policy, cascades, and later adaptive strategies. LiteLLM normalizes provider transport for an already-selected endpoint. LiteLLM Router, cross-provider fallback, and load balancing must not silently change the selected semantic endpoint. A bounded safe retry may repeat only that same endpoint and cannot change provider/model, credential scope, cost mode, or consent.

The contract boundary is:

```text
Task + context + policy
        |
        v
Personal AI endpoint registry and hard admission
        |
        v
Personal AI semantic router -> pluggable RoutingStrategy
        |
        v
ExecutionPlan
        |
        v
Personal AI inference gateway -> LiteLLM SDK -> selected endpoint
```

Gemini, Groq, and Cloudflare are initial reference endpoint families, not privileged identities or a closed universe. A LiteLLM-supported provider normally adds endpoint/configuration/profile/evaluation without new provider transport code. A narrow provider-specific shim remains only for a demonstrated LiteLLM compatibility gap. OpenRouter is a possible later provider family through endpoint profiles, credential/account/cost metadata, privacy eligibility, evaluation, and quota handling; it is not a Phase 17R or Phase 18–24 live-provider requirement.

For a future OpenRouter integration, a specific model endpoint can be represented as a normal endpoint profile. An OpenRouter-managed `auto` or `free` route is a composite/virtual endpoint: retain the requested virtual endpoint and, where available, the actual selected model and upstream provider. These virtual routes are not part of the initial quality matrix or primary Personal AI semantic router.

Current quotas/model availability are operational facts, not application constants. No dynamic discovery or provider marketplace is required.

## Execution identity and cost modes

Model, provider, and execution endpoint are distinct. A model is the logical/underlying model or family. A provider identifies the access, commercial, or transport service (for example Gemini API, Groq, Cloudflare, and later OpenRouter). An execution endpoint profile is the primary routable/admission unit: the callable provider + model + deployment/endpoint + account/project/tier + safe credential source/scope + execution mode + relevant serializer/runtime characteristics. Credential/account identity determines whose quota, privacy terms, and billing apply. Cost class and automatic/explicit eligibility are independent policy facts. One provider/model may be exposed through a verified-free deployment credential, a user-paid credential, another account/tier, or a future aggregator; identity alone implies neither free eligibility nor routing permission. The Personal AI registry is not a mirror of LiteLLM's model catalog, and profiles never store credential secrets.

| Execution mode | Capacity/cost classification | Selection boundary |
| --- | --- | --- |
| `STRICT_FREE` | Account-specific `VERIFIED_FREE` capacity. | Default automatic lane after all hard admission checks. |
| `EXPLICIT_BYOK` | User-supplied API capacity, normally `USER_BILLED`. | Explicit-only initially; never scarcity fallback. |
| `CHATGPT_PLAN` | `SUBSCRIPTION` capacity via the supported user-controlled bridge. | Explicit separate lane; subscription access is not OpenAI API usage. |

`UNKNOWN` cost never counts as verified free. Free exhaustion returns an explicit unavailable/exhausted outcome; it cannot silently select a user-billed key, switch execution modes, or imply consent to spend. All lanes retain authorization, sensitivity, provider privacy, capability, and context limits.

Phase 18 endpoint profiles represent model and provider identities separately, plus endpoint/deployment, capabilities/limits, credential runtime/source/ownership references, account/project/tier, cost and billing-owner/class metadata, execution mode and automatic/explicit eligibility, privacy/data-use restrictions, typed quota windows/units/source/confidence, and version/freshness. BYOK-compatible metadata is representable here; live BYOK execution is not added to Phases 16–24 by this reconciliation.

A separately authorized first BYOK implementation may resolve a local environment reference, deployment secret reference, or user-controlled runtime. Hosted user-secret management requires a separate security/product decision. Automatic capped spending (`BUDGETED_BYOK`), paid overflow, invoices/monthly billing/cost dashboards, and a hosted API-key vault remain deferred. These API credential options do not relax the stricter ChatGPT credential exclusions.

## Strict-free eligibility

Hard admission is deterministic and precedes every strategy:

1. enabled/configured endpoint and usable credential/account;
2. verified zero-cost eligibility for that endpoint/account/tier and requested execution mode;
3. provider data/privacy eligibility for effective sensitivity;
4. task capability and context/output limits;
5. known cooldown/exhaustion constraints;
6. only then a `RoutingStrategy` may rank/select among eligible endpoints using deterministic priority, measured quality, or later scarcity inputs.

Execution mode and cost/selection permission filter candidates before strategy input. Automatic candidates exclude BYOK and ChatGPT-plan profiles even when provider/model names match a free profile. Hard admission is never pluggable or bypassable. The strategy cannot call providers, mutate orchestration state, own secrets, widen eligibility, or change modes.

Unknown eligibility does not justify a potentially billable path. Unknown quota remains unknown rather than fake precision.

## Model bottleneck vs. storage

Model/search quotas are resettable flow constraints; database/object storage is cumulative stock. Phase 10 therefore chooses storage primarily by data model/access pattern while still exploiting complementary free tiers:

- DynamoDB for high-volume operational timeline state;
- Postgres/pgvector for query-rich durable knowledge;
- GCS for large artifacts later.

The architecture does not add providers or clouds solely to maximize theoretical quotas. New backends remain behind interfaces and are activated incrementally.

## ChatGPT plan lane

Phases 25.1–25.4 add explicit user-controlled ChatGPT-plan execution through a local/user-controlled credential bridge. It is not part of automatic strict-free candidate sets and never silently falls back in either direction. Context/policy rules are identical to automatic inference.

## Routing strategy and execution plan

Phase 21 introduces a project-owned `RoutingStrategy` (or equivalent) that consumes a versioned task/profile, the eligible endpoint profiles and versions, decision-time policy context, quality evidence, latency/reliability inputs when used, and quota/scarcity inputs when available. The Phase 21 deterministic scorer is the baseline implementation of this seam, not the architecture embedded in request orchestration. Phase 23 may enrich that baseline or add another deterministic strategy. Phase 35 can add interchangeable learned strategies without rewriting orchestration or provider transport.

The strategy returns a bounded, explainable result: selected eligible endpoint, optional ranked eligible candidates/scores, strategy ID/version, and reason. Personal AI then creates an `ExecutionPlan` containing task/profile identity, selected endpoint, permitted alternatives, execution mode, required capabilities, validator/escalation permission, attempt/time/token bounds, registry/policy versions, decision ID, strategy identity/version, and reason. The execution layer carries out that plan through the Personal AI inference gateway. Provider/model names are profile and provenance data, never generic fallback order.

## Routing observation contract

Operational phases record stable semantic facts; Phase 35 derives adaptive features from them later. Routing observations are bounded, versioned, privacy-safe, and joinable across decisions and outcomes. They must contain enough context to replay the known decision inputs and compare strategies, without retaining raw prompts or embeddings solely for future routing experiments.

The shared record contract includes, where each phase has the fact:

- stable `routing_decision_id` and `invocation_id`, task/profile identity and version, routing policy version, strategy ID/version, request/run correlation, and retry/cascade lineage;
- bounded request characteristics such as prepared input/context size, count/estimate plus confidence/source, source count where relevant, required capabilities, structured-output/citation/validator requirements, sensitivity class, requested execution mode, and output bounds;
- the candidate endpoint/profile IDs and versions seen at decision time, eligibility or rejection and reasons, selected endpoint, strategy ranking/score/reason, and the registry/policy versions;
- exact quality evidence/profile versions and latency/reliability inputs used by the strategy;
- a bounded decision-time quota/scarcity snapshot or immutable observation once Phase 23 supplies it; unknown values remain unknown;
- actual invocation latency, usage/count confidence, status/error, normalized retries and outcomes from Phase 19;
- task-specific evaluation/quality evidence and its version from Phase 22;
- validator ID/version, result, escalation reason, attempt lineage, and final accepted attempt from Phase 24;
- bounded retention and explicit privacy-safe summaries, with forward-compatible optional fields rather than an unbounded blob.

Mutable references alone are insufficient when the referenced policy, registry, quality evidence, or quota state may change. Store immutable/versioned evidence references or bounded decision-time snapshots required to reconstruct what the strategy knew. Replay means reconstructing the bounded decision context and rerunning deterministic logic or comparing alternate strategies offline; it does not require raw sensitive prompts or promise counterfactual provider outputs for endpoints that were never executed. Do not introduce feature vectors, a feature store, reward functions, or learned policy in Phases 19–24.

## Evaluation discipline

Measured project-specific quality profiles precede quality-aware/scarcity/cascade promotion. Skipped live providers have no measured score. Model judges may supplement deterministic/schema/provenance/hard-constraint scoring but are not the sole evaluator.

The harness consumes registered eligible endpoint profiles and task fixtures/profiles; initial live comparison stays Gemini/Groq/Cloudflare. Quality is task-profile x endpoint-profile evidence, not one universal model score. Quality evidence identifies provider, endpoint/profile and version, model, account/config where material, serializer/runtime, task/profile and version, policy version, and revision, with explicit coverage and invalidation. When quality affects routing, the decision observation captures the exact evidence version used. Strict-free evaluations cannot invoke paid or unknown-cost profiles.

Task identity is separate from requirements, so new tasks that fit existing capability/sensitivity/context/citation/quality/validator requirements register policy without router branching. Phase 24 executes registered deterministic validators within finite free-only cascades. Phase 19 attribution distinguishes endpoint/profile version, account/credential scope, cost, app/workspace/task, usage/buckets, status, and latency without secrets or billing-system scope. Phase 23 consumes typed request/token/neuron/other-unit buckets with window/reset/source/confidence and captures decision-time scarcity facts; unknown quota remains unknown and never opens BYOK overflow. Phase 35 is the first adaptive-routing phase: RouteLLM-style routing, classifiers, bandits, or other rankers are optional interchangeable strategies behind the Phase 21 seam, evaluated offline/shadow against deterministic baselines. See [target extension seams](02-target-architecture.md#task-validator-and-evaluation-extension-seams) for task/validator details.
