# Free-tier inference and routing

## Principles

The project optimizes for a fully hosted strict-$0 AI system without requiring local AI hardware. Model/search quota is expected to be the near-term throughput limiter, but durable storage and cloud resource use accumulate over time and are tracked separately.

This is future Chapter 2 planning. Strict-free/free-first is the default automatic execution goal; optional explicit user-funded capacity is additive. See [current state](../current-state.md) for implemented behavior.

## Provider boundary

Phase 16 establishes neutral generation/streaming/structured-output/counting/embedding seams. Phase 17 adds concrete Gemini/Groq/Cloudflare adapters. Phase 18 describes model/account capability/free/privacy facts. Phase 19 measures usage/quota. Phase 21 adds deterministic task routing, Phase 22 measures quality, Phase 23 adds quota-aware scarcity, Phase 24 adds bounded cascades, and Phase 35 later explores adaptive routing only in shadow/offline first.

Provider SDK types never leak into context/domain logic. Current quotas/model availability are not application constants.

Gemini, Groq, and Cloudflare are reference adapters, not privileged provider identities or a closed universe. Additional providers normally add an adapter, endpoint profile, contract tests, compatibility/preflight, evaluation evidence, and configuration. Phase 17 still implements only those three; Phase 16 tests the seam with a synthetic provider. No dynamic discovery or marketplace is required.

## Execution identity and cost modes

Provider identity describes protocol/adapter ownership; endpoint/model identifies the callable configuration. Credential reference/source and ownership class describe how capacity is accessed; opaque provider account/project/tier identifies whose quota, privacy terms, and billing apply. Cost class and automatic/explicit eligibility are independent policy facts. One provider/model may be used with a deployment free credential or a user's paid credential; identity alone implies neither free eligibility nor routing permission.

| Execution mode | Capacity/cost classification | Selection boundary |
| --- | --- | --- |
| `STRICT_FREE` | Account-specific `VERIFIED_FREE` capacity. | Default automatic lane after all hard admission checks. |
| `EXPLICIT_BYOK` | User-supplied API capacity, normally `USER_BILLED`. | Explicit-only initially; never scarcity fallback. |
| `CHATGPT_PLAN` | `SUBSCRIPTION` capacity via the supported user-controlled bridge. | Explicit separate lane; subscription access is not OpenAI API usage. |

`UNKNOWN` cost never counts as verified free. Free exhaustion returns an explicit unavailable/exhausted outcome; it cannot silently select a user-billed key, switch execution modes, or imply consent to spend. All lanes retain authorization, sensitivity, provider privacy, capability, and context limits.

Phase 18 profiles represent provider/endpoint identity, capabilities/limits, credential runtime/source/ownership references, account/project/tier, cost and billing-owner/class metadata, automatic/explicit eligibility, privacy/data-use restrictions, typed quota windows/units/source/confidence, and version/freshness. Profiles contain no credential secrets. BYOK-compatible metadata is representable here; live BYOK execution is not added to Phases 16–24 by this reconciliation.

A separately authorized first BYOK implementation may resolve a local environment reference, deployment secret reference, or user-controlled runtime. Hosted user-secret management requires a separate security/product decision. Automatic capped spending (`BUDGETED_BYOK`), paid overflow, invoices/monthly billing/cost dashboards, and a hosted API-key vault remain deferred. These API credential options do not relax the stricter ChatGPT credential exclusions.

## Strict-free eligibility

Hard admission precedes scoring:

1. enabled/configured account/model;
2. verified zero-cost eligibility for that account/tier;
3. provider data/privacy eligibility for effective sensitivity;
4. task capability and context/output limits;
5. known cooldown/exhaustion constraints;
6. only then deterministic routing priorities/quality/scarcity.

Execution mode and cost/selection permission filter candidates before these priorities. Automatic candidates exclude BYOK and ChatGPT-plan profiles even when provider/model names match a free profile.

Unknown eligibility does not justify a potentially billable path. Unknown quota remains unknown rather than fake precision.

## Model bottleneck vs. storage

Model/search quotas are resettable flow constraints; database/object storage is cumulative stock. Phase 10 therefore chooses storage primarily by data model/access pattern while still exploiting complementary free tiers:

- DynamoDB for high-volume operational timeline state;
- Postgres/pgvector for query-rich durable knowledge;
- GCS for large artifacts later.

The architecture does not add providers or clouds solely to maximize theoretical quotas. New backends remain behind interfaces and are activated incrementally.

## ChatGPT plan lane

Phases 25.1–25.4 add explicit user-controlled ChatGPT-plan execution through a local/user-controlled credential bridge. It is not part of automatic strict-free candidate sets and never silently falls back in either direction. Context/policy rules are identical to automatic inference.

## Evaluation discipline

Measured project-specific quality profiles precede quality-aware/scarcity/cascade promotion. Skipped live providers have no measured score. Model judges may supplement deterministic/schema/provenance/hard-constraint scoring but are not the sole evaluator.

The harness consumes registered eligible endpoint profiles and task fixtures/profiles; initial live comparison stays Gemini/Groq/Cloudflare. Quality evidence identifies provider, endpoint/model, serializer/configuration, task/profile, policy version, and revision, with explicit coverage and invalidation. Strict-free evaluations cannot invoke paid or unknown-cost profiles.

Task identity is separate from requirements, so new tasks that fit existing capability/sensitivity/context/citation/quality/validator requirements register policy without router branching. Phase 24 executes registered deterministic validators within finite free-only cascades. Phase 19 attribution distinguishes endpoint, account/credential scope, cost, app/workspace/task, usage/buckets, status, and latency without secrets or billing-system scope. Phase 23 consumes typed request/token/neuron/other-unit buckets with window/reset/source/confidence; unknown quota remains unknown and never opens BYOK overflow. See [target extension seams](02-target-architecture.md#task-validator-and-evaluation-extension-seams) for contract details.
