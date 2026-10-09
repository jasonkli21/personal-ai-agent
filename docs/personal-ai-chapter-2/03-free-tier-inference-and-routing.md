# Free-tier inference and routing

## Principles

The project optimizes for a fully hosted strict-$0 AI system without requiring local AI hardware. Model/search quota is expected to be the near-term throughput limiter, but durable storage and cloud resource use accumulate over time and are tracked separately.

This is the Chapter 2 routing contract. Strict-free/free-first is the default automatic execution goal; optional explicit user-funded capacity is additive. Phases 21–23 provide a local deterministic routing core with quota-aware ranking and paired synthetic evaluation, but request workflows remain Gemini-only until the Phase 15 membership and end-to-end revocation prerequisite is complete. See [current state](../current-state.md), the [Phase 21 evidence](phase-21-implementation-evidence.md), and [Phase 23 evidence](phase-23-implementation-evidence.md) for delivered behavior and gates.

## Provider boundary

The intended sequence is:

```text
16  Personal AI neutral inference and embedding contracts
17  completed Gemini/Groq/Cloudflare reference adapters
17R completed locally: LiteLLM execution-substrate reconciliation
18  phase-local implementation complete; integration/prerequisite acceptance open
19  usage/quota ledger and invocation observations
21  deterministic semantic routing and RoutingStrategy baseline — local core implemented
22  task-profile x endpoint-profile quality evidence
23  deterministic scarcity-aware strategy and frozen P19 quota snapshots — local core implemented
24  bounded Personal AI cascades and deterministic validation
35  adaptive strategy experiments
```

Phase 17 established contract behavior and provider edge cases; Phase 17R implemented the LiteLLM transport migration behind those contracts. Personal AI's neutral contracts remain the application-facing boundary for generation, streaming, structured generation, count confidence, embeddings, usage, provider/execution identity, latency/status/errors, sensitivity/inference context, cancellation, and embedding-space identity. LiteLLM-specific types stay inside the Personal AI inference gateway. Context, domain, and application code must not call LiteLLM directly. Local implementation evidence does not establish live provider compatibility or account/tier/privacy eligibility.

The implemented transport uses the LiteLLM Python SDK inside the existing runtime. A separately deployed LiteLLM Proxy/Gateway is not initial scope. Personal AI owns semantic routing, hard admission, privacy, execution/cost modes, task quality, quota policy, cascades, and later adaptive strategies. LiteLLM normalizes provider transport for an already-selected endpoint. LiteLLM Router, cross-provider fallback, and load balancing must not silently change the selected semantic endpoint. Phase 17R disables implicit SDK/provider/HTTP retries; a later explicit bounded retry may repeat only the same endpoint after Phase 19 gives each physical send its own attempt identity and admission/reservation. No retry may change provider/model, credential scope, cost mode, or consent. Phase 18's registry is implemented as an admission foundation but is not yet wired into request-workflow provider selection.

The request/execution boundary is:

```text
Task + context + policy
        |
        v
Personal AI endpoint registry and hard admission
        |
        v
provisional endpoint selection -> endpoint-specific assembly/count
        |
        v
policy/source/profile revalidation -> atomic quota reservation
        |
        v
final ExecutionPlan -> Personal AI inference gateway -> LiteLLM SDK -> selected endpoint
```

The Phase 21–23 strategy only makes a provisional choice among hard-eligible endpoints. Phase 23 adds typed P19 quota-window, reset, and health facts to the frozen decision and deterministically ranks scarcity after all existing hard filters. It does not establish context fit or authorize dispatch. The implemented `RoutingDecisionService` and `ExecutionPlan` types enforce the local decision/preparation boundary. Request workflows remain disconnected while the explicit Phase 15 membership and end-to-end revocation prerequisite is open. Once integration is authorized, the orchestrator completes endpoint-specific preparation, revalidates policy and source permissions, reserves applicable quota, and finalizes one selected endpoint plan before the gateway sends.

Gemini, Groq, and Cloudflare are initial reference endpoint families, not privileged identities or a closed universe. A LiteLLM-supported provider normally adds endpoint/configuration/profile/evaluation without new provider transport code. A narrow provider-specific shim remains only for a demonstrated LiteLLM compatibility gap. OpenRouter is a possible later provider family through endpoint profiles, credential/account/cost metadata, privacy eligibility, evaluation, and quota handling; it is not a Phase 17R or Phase 18–24 live-provider requirement.

For a future OpenRouter integration, a specific model endpoint can be represented as a normal endpoint profile. An OpenRouter-managed `auto` or `free` route is a composite/virtual endpoint: retain the requested virtual endpoint and the actual selected model/upstream provider when known. Before any context is disclosed, enforceable cost/execution mode, data policy, capability, and context/output bounds must hold for every possible upstream. A required quality floor may be established either by a proven per-upstream minimum across the full possible set or by a versioned composite-level quality profile measured for the exact upstream-set and selection-policy version. Unknown membership or any missing hard safety bound excludes the composite for requests that require it. A response identity never retroactively authorizes disclosure or substitutes for pre-dispatch quality evidence. Any membership or selection-policy change invalidates the composite quality profile. Future integration acceptance includes unknown/disallowed upstreams denied before disclosure, composite-level quality evidence bound to its exact membership/policy version, and response identity that cannot grant retroactive permission. These routes remain outside the initial quality matrix and primary Personal AI semantic router.

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

Quota authority is a separate identity from endpoint attribution and credentials. Each endpoint profile references every authoritative quota bucket it may consume, using stable bucket IDs, scope, unit/window, and source/confidence. Multiple endpoints or rotated credentials may share a bucket while retaining distinct endpoint/account/credential attribution. A credential rotation under the same quota authority does not create capacity; independently scoped free and paid accounts never borrow capacity. A dispatch reserves all applicable buckets atomically under bounded concurrency, or it does not dispatch. Unknown bucket relationships exclude the profile from automatic strict-free admission unless a verified conservative shared bucket resolves the relationship. Provider/account facts define bucket membership; router names do not.

A separately authorized first BYOK implementation may resolve a local environment reference, deployment secret reference, or user-controlled runtime. Hosted user-secret management requires a separate security/product decision. Automatic capped spending (`BUDGETED_BYOK`), paid overflow, invoices/monthly billing/cost dashboards, and a hosted API-key vault remain deferred. These API credential options do not relax the stricter ChatGPT credential exclusions.

## Strict-free eligibility

Hard admission is deterministic and precedes every strategy:

1. enabled/configured endpoint and usable credential/account;
2. verified zero-cost eligibility for that endpoint/account/tier and requested execution mode;
3. provider data/privacy eligibility for effective sensitivity;
4. task capability, required endpoint-specific counter/confidence/schema compatibility, and declared context/output limits;
5. known cooldown/exhaustion and quota-bucket constraints;
6. if the task requires a measured quality floor, fresh, sufficiently covered evidence meets that floor;
7. only then a `RoutingStrategy` may rank/select among eligible endpoints using deterministic priority, measured quality, or later scarcity inputs.

Execution mode and cost/selection permission filter candidates before strategy input. Automatic candidates exclude BYOK and ChatGPT-plan profiles even when provider/model names match a free profile. Hard admission is never pluggable or bypassable. The strategy cannot call providers, mutate orchestration state, own secrets, widen eligibility, or change modes.

Unknown eligibility does not justify a potentially billable path. Unknown quota remains unknown rather than fake precision.

## Endpoint-specific preparation and dispatch

Context fit and count evidence belong to a particular endpoint serializer, counter, and context/output limit. The request orchestrator, not a strategy, coordinates this bounded lifecycle:

1. Authorize the request and freeze the permitted source identities/versions, effective sensitivity, and policy/grant versions.
2. Apply non-disclosing hard filters using registered endpoint, account, privacy, capability, count-compatibility, quality-floor, and known quota facts. No counter or provider call occurs in this step.
3. Select a provisional eligible endpoint with the `RoutingStrategy`; the selection does not claim that the final input fits.
4. Persist the bounded provisional decision and candidate facts in Postgres with a `preparing` outcome before any external counter, summary, or generation call. If this write fails, make no external call.
5. Assemble and count for that endpoint. A remote counter or summary call is a separately admitted external operation with its own endpoint, disclosure, cost, quota, attempt identity, and deadline checks. A denied or incompatible remote counter receives zero input. If the prepared input exceeds the endpoint's limits, do not generate on it.
6. Revalidate the frozen policy, source permissions, and endpoint profile immediately before reserving and dispatching generation. If a source was revoked, remove it only when task policy explicitly permits narrowing; otherwise abort. If preparation, reservation, or revalidation fails, bounded reselection creates a linked decision/plan before any new external call and recomputes endpoint-specific assembly/count evidence from the same or narrower still-authorized source set.

Every summary, counter, preparation, reservation, and reselection shares the request deadline and a finite auxiliary-call/attempt budget. Reassembly may narrow the already authorized source set only under explicit policy; it never silently widens sources or claims that differently truncated inputs are identical. The execution handoff retains the exact prepared input in request scope plus a bounded identity for its sources, serializer, and count; routing observations contain metadata only, never raw text. Endpoint-specific counters and summary generation cannot be invoked by a strategy.

## Model bottleneck vs. storage

Model/search quotas are resettable flow constraints; database/object storage is cumulative stock. Phase 10 therefore chooses storage primarily by data model/access pattern while still exploiting complementary free tiers:

- DynamoDB for high-volume operational timeline state;
- Postgres/pgvector for query-rich durable knowledge;
- GCS for large artifacts later.

The architecture does not add providers or clouds solely to maximize theoretical quotas. New backends remain behind interfaces and are activated incrementally.

## ChatGPT plan lane

Phases 25.1–25.4 add explicit user-controlled ChatGPT-plan execution through a local/user-controlled credential bridge. It is not part of automatic strict-free candidate sets and never silently falls back in either direction. Context/policy rules are identical to automatic inference.

## Routing strategy and execution plan

Phase 21 introduced a project-owned `RoutingStrategy`; Phase 23 extends it with `QuotaAwareDeterministicStrategy`, which consumes only candidates that passed static, authorization, runtime, and quality admission. Its immutable feature view contains one bounded P19 shared-state fact per bucket and candidate-specific per-dispatch reservation requirements. It converts each bucket to equivalent sends using that candidate's requirement, never compares incompatible raw units, ignores zero-unit requirements, and applies explicit uncertainty and degraded-health penalties. The P19 batch snapshot locks the full bucket union in canonical order before locking endpoint health. Schema-5 decisions bind the strategy ref, composed dependencies, implementation digest, effective-preference digest, and tie-break version; schema-4 reservation facts remain readable for historical replay. The synthetic paired evaluator reports those identities and requires scenario-level as well as aggregate gates; it does not change live application wiring or supply production-provider evidence. Phase 35 can add interchangeable learned strategies without rewriting orchestration or provider transport.

The strategy returns a bounded, explainable provisional result: selected eligible endpoint, optional ranked eligible candidates/scores, strategy ID/version, and reason. Personal AI assembles/counts for that endpoint, revalidates policy/source/profile, reserves quota, and then finalizes an `ExecutionPlan` containing task/profile identity, selected endpoint, advisory `reselection_candidate_refs`, execution mode, required capabilities, endpoint-specific prepared-input/count identity and fit, validator/escalation permission, physical-attempt/time/token/auxiliary-call/quota bounds, registry/policy versions, decision ID, strategy identity/version, and reason. These references are not executable fallbacks. Selecting another endpoint requires a linked decision, recomputed endpoint-specific preparation/count, revalidation, reservation, and a new final plan. The execution layer carries out only the final selected endpoint through the Personal AI inference gateway. Provider/model names are profile and provenance data, never generic fallback order.

## Routing observation contract

Operational phases record stable semantic facts; Phase 35 derives adaptive features from them later. Routing observations are bounded, versioned, privacy-safe, and joinable across decisions and outcomes. They must contain enough context to replay the known decision inputs and compare strategies, without retaining raw prompts or embeddings solely for future routing experiments.

The canonical record is a scoped, compact Postgres observation with schema version `routing-decision-v1`; DynamoDB turn/runtime records keep only its ID and actual producing-endpoint attribution. Read by `routing_decision_id` only after owner/application/workspace authorization; bounded list/join paths use that same scope and indexed request/run, invocation, and evaluation IDs. Include observations and their dependencies in export/deletion inventory. A decision observation is advisory history, not an admission grant. Versioned endpoint/policy records and Phase 19 reservations/settlements remain authoritative controls.

Each successful or rejected/no-route decision records every considered candidate and bounded rejection reason before dispatch. Limit a decision to 32 candidates and 64 KiB encoded; Phase 18 rejects an active automatic profile set above the candidate cap. If an invalid/legacy set still exceeds either bound at runtime, do not select or dispatch. A quota-count overflow or 64 KiB decision overflow records a bounded terminal no-route reason; the detailed candidate/quota snapshot is intentionally omitted, and replay returns unavailable for that record. Record pre-dispatch failures and link any later endpoint reselection or cascade selection to its parent decision. A physical retry of the identical endpoint plan reuses its routing decision and has a distinct physical attempt identity. Re-selection to another endpoint requires a new decision ID.

The shared record contract includes, where each phase has the fact:

- stable `routing_decision_id` and `invocation_id`, task/profile identity and version, routing policy version, strategy ID/version, request/run correlation, and retry/cascade lineage;
- observation schema version, decision lifecycle/completeness state, parent/previous decision ID, logical operation/root invocation ID, and physical attempt IDs;
- bounded request characteristics such as prepared input/context size, count/estimate plus confidence/source, source count where relevant, required capabilities, structured-output/citation/validator requirements, sensitivity class, requested execution mode, and output bounds;
- the candidate endpoint/profile IDs and versions seen at decision time, eligibility or rejection and reasons, selected endpoint, strategy ranking/score/reason, and the registry/policy versions;
- exact quality evidence/profile versions and latency/reliability inputs used by the strategy;
- required task-quality floor, evidence freshness/coverage, and the exact score/eligibility facts used;
- a bounded decision-time quota/scarcity snapshot with every consumed bucket ID, unit/window, reset and time-to-reset when known, source/confidence/freshness, shared consumed/reserved/remaining amounts, and candidate-specific per-dispatch reservation requirements; unknown values remain unknown;
- actual invocation latency, usage/count confidence, status/error, normalized retries and outcomes from Phase 19;
- task-specific evaluation/quality evidence and its version from Phase 22;
- validator ID/version, result, escalation reason, attempt lineage, and final accepted attempt from Phase 24;
- bounded retention and explicit privacy-safe summaries, with forward-compatible optional fields rather than an unbounded blob.

Store the exact strategy ID/version, implementation digest, configuration digest, composed dependency refs, and tie-break version used. Phase 21's deterministic baseline resolves equal scores by stable `endpoint_profile_id`, then `profile_version`, in ascending lexical order; later strategies record their own deterministic tie-break contract. Mutable references alone are insufficient when policy, registry, quality evidence, or quota state may change. Store decision-time facts inline or retain immutable/versioned references for the same replay horizon; snapshot every bounded input needed to reconstruct what the strategy knew. Default replay retention is 90 days from decision time, shortened by owner deletion, source-rights expiry, or an earlier dependency expiry. Set `replay_until` explicitly; mandatory inputs remain resolvable through that time, or the record is marked incomplete. After expiry/deletion, return unavailable instead of reconstructing from current state. Replay reruns the recorded strategy/configuration where available or compares alternate strategies offline; it does not require raw sensitive prompts or promise counterfactual provider outputs for endpoints that never ran. Do not introduce feature vectors, a feature store, reward functions, or learned policy in Phases 19–24.

Create the compact decision observation before provider dispatch. If its required write or an authoritative reservation fails, do not dispatch. Reconcile decision, reservation, attempt, and DynamoDB turn references by stable IDs; unresolved cross-store publication is marked incomplete/unknown and is not repaired from current registry state. Unknown outcomes keep the original reservation and attempt identity until safely reconciled. Optional Phase 20 verbose artifacts can supplement this record but are never its only copy. Cross-owner reads are denied; deletion removes or makes unavailable the scoped observation and any dependent replay inputs.

## Evaluation discipline

Measured project-specific quality profiles precede quality-aware/scarcity/cascade promotion. Skipped live providers have no measured score. Model judges may supplement deterministic/schema/provenance/hard-constraint scoring but are not the sole evaluator.

The harness consumes registered eligible endpoint profiles and task fixtures/profiles; initial live comparison stays Gemini/Groq/Cloudflare. Quality is task-profile x endpoint-profile evidence, not one universal model score. Quality evidence identifies provider, endpoint/profile and version, model, account/config where material, serializer/runtime, task/profile and version, policy version, and revision, with explicit coverage and invalidation. When quality affects routing, the decision observation captures the exact evidence version used. Strict-free evaluations cannot invoke paid or unknown-cost profiles.

Task identity is separate from requirements, so new tasks that fit existing capability/sensitivity/context/citation/quality/validator requirements register policy without router branching. A required quality floor is a hard eligibility filter: missing, stale, insufficiently covered, or below-floor evidence rejects the endpoint before every strategy. An explicitly unmeasured baseline task may use configured priorities without invented scores. Phase 22 owns evidence coverage/freshness policy. Phase 24 executes registered deterministic validators within finite free-only cascades. Phase 19 attribution distinguishes endpoint/profile version, account/credential scope, cost, app/workspace/task, physical attempts, usage/buckets, status, and latency without secrets or billing-system scope. Phase 23 consumes typed request/token/neuron/other-unit buckets with window/reset/source/confidence and captures decision-time scarcity facts; unknown quota remains unknown and never opens BYOK overflow. Phase 35 is the first adaptive-routing phase: RouteLLM-style routing, classifiers, bandits, or other rankers are optional interchangeable strategies behind the Phase 21 seam, evaluated offline/shadow against deterministic baselines. See [target extension seams](02-target-architecture.md#task-validator-and-evaluation-extension-seams) for task/validator details.
