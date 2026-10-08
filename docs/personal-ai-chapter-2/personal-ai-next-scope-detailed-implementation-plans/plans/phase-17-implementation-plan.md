# Phase 17 implementation plan — Concrete provider adapters: Gemini, Groq, Cloudflare

Renumbered on 2026-10-06 from former next-scope Phase 9. Phase 17 is completed locally; see the [Phase 17 evidence](../../phase-17-implementation-evidence.md) and [current state](../../../current-state.md). This plan preserves the original scope, work packages, invariants, and acceptance criteria rather than rewriting its implementation history. Read the source roadmap, Phase 10 persistence plan, and shared execution contract for the active future boundary.

## Scope boundary

**Goal:** Prove the provider boundary against the three explicitly planned providers without adding routing policy.

### Normative commitments from the integrated roadmap

- Migrate Gemini generation and structured memory extraction behind the neutral backend while preserving Gemini embeddings.
- Add Groq backend support for the minimal generation operations needed by actual tasks, with fake/contract tests and rate-limit/usage-header capture.
- Add Cloudflare Workers AI backend support for the minimal generation operations needed by actual tasks, with fake/contract tests.
- Verify strict-free configuration only against currently eligible account/tier models.
- Use LiteLLM internally where it reduces duplication or native adapters where cleaner; keep provider-specific details below the boundary.
- Do not add benchmarking, quota-aware selection, cascades, or generalized provider discovery in this phase.

### Phase acceptance criteria

- Gemini, Groq, and Cloudflare satisfy neutral contracts offline; opt-in compatibility checks are independently required before each live enablement.
- Strict-free tests never require paid provider paths.
- No provider-specific types leak into context/domain logic.

### Explicitly out of scope

- cross-provider quality benchmarking
- quota-aware router
- cascades
- provider discovery marketplace

## Baseline observed before Phase 17 implementation (historical)

At planning time, Gemini SDK adapters existed and needed neutral migration; Groq and Cloudflare adapters were missing. LiteLLM was optional in that plan. The implementation that completed Phase 17 used the Phase 16 neutral contracts and did not make LiteLLM the transport layer; the later LiteLLM decision is recorded separately in [ADR 0022](../../../decisions/0022-litellm-inference-transport-boundary.md).

Verified existing backend seams include the current `personal_ai.llm`, dependency/settings, context, memory, and provider boundary modules. Infrastructure changes must build on the Postgres/DynamoDB/GCS ownership established by Phase 10; do not reintroduce Firestore as a canonical runtime store.

## Prerequisites and work ordering

Required phase: 16 (former Phase 8). Phase 10 is also a standing persistence prerequisite for all post-migration phases. Each must deliver the contracts this plan consumes. Within this plan, work packages run in order.

## Phase-specific invariants

- Capture usage/rate-limit metadata when provided, but do not build selection policy yet.
- Cloudflare models requiring Workers Paid are ineligible in strict-free configuration.
- Real-provider checks are opt-in and must not be represented as passed when credentials/network are unavailable.
- Gemini/Groq/Cloudflare are reference adapters validating the [neutral seam](../../02-target-architecture.md#9-provider-runtime), not privileged identities. Concrete scope remains these three; OpenAI, Anthropic, and other future live adapters are not added here.

## Post-completion reconciliation

The Gemini, Groq, and Cloudflare adapters remain reference and parity evidence for the neutral contracts. Their edge cases, defensive invariants, and contract tests are migration criteria for the planned [Phase 17R](phase-17r-implementation-plan.md). Phase 17R may move provider transport normalization to the LiteLLM Python SDK only after parity is demonstrated; retain a provider-specific compatibility shim only for a demonstrated LiteLLM gap. This reconciliation does not invalidate Phase 17 or imply that LiteLLM was used during its implementation.

## Work packages

### P17.0 — Gemini compatibility adapter

Reuse existing Gemini generation/count/summary/extraction/embedding implementations behind Phase 16 contracts. Retain zero implicit retry and cancellation cleanup; normalize 429, auth/config, timeout, unavailable, malformed and incomplete results with safe metadata. Keep current vector-space and task-schema validation semantics; persisted memory vectors now use the Postgres/pgvector persistence boundary established by Phase 10.

**Acceptance:** Gemini regressions and neutral error/terminal contracts pass without unintended embedding-space changes.

### P17.1 — Groq and Cloudflare adapters

Add generation/structured-output operations actually needed by tasks, with supported capability declarations. Normalize each provider serializer/stream terminal behavior, limits, usage and safe rate headers below `llm`. Add deterministic adapters/fake transports. Native SDK/HTTP adapters or LiteLLM are implementation choices justified by contract fit, not framework adoption; no router, quality scores, quota selection or cascades.

**Acceptance:** Groq and Cloudflare fake transports satisfy supported operations and reject unsupported fields.

### P17.2 — Disabled configuration and preflight

All new live paths default off. Require model/account free-tier and privacy compatibility checks before opt-in dispatch, even before Phase 18 centralizes registry policy. Cloudflare paid-only models are excluded. Record strict-$0 deployment incompatibilities before enablement. Missing credentials/provider environment skips external checks only.

**Acceptance:** New live providers remain disabled until independent eligible-account/privacy/preflight checks are recorded.

Document the same adapter/profile/contract-test/preflight/evaluation/configuration path for a future provider. Configuration and safe trace identity may contain provider names; higher-level context/domain/routing control flow must not require them. Phase 16 synthetic conformance remains the extension check, not a fourth live adapter.

## Requirement coverage

| Requirement | Work packages |
| --- | --- |
| R17.1: Migrate Gemini generation and structured memory extraction behind the neutral backend while preserving embedding compatibility. | P17.0 |
| R17.2: Add Groq backend support with fake/contract tests and rate-limit/usage-header capture. | P17.1 |
| R17.3: Add Cloudflare Workers AI backend support with fake/contract tests. | P17.1 |
| R17.4: Verify strict-free configuration only against currently eligible account/tier models. | P17.2 |
| R17.5: Keep provider-specific details below the boundary; LiteLLM is optional. | P17.1 |
| R17.6: Do not add benchmarking, quota-aware selection, cascades, or generalized discovery. | P17.2 |

## README maintenance

Review the repository-root `README.md` before closing this phase. Update it only if this phase changes the truth of user-visible provider support, prerequisites, configuration, architecture, tech stack, setup, deployment, or current capability status. Do not add implementation-detail churn. If no README-visible fact changes, record that no README edit was required.

## Targeted verification and closeout

Contract fixtures for all three adapters cover unsupported request fields, structured failures, 429/5xx, stream interruption, cancellation cleanup, unknown usage and provider-type confinement; no test uses a paid endpoint. Run the applicable backend/frontend test, lint, typecheck, and build commands and finish with `git diff --check`.

Affected existing evaluation targets include context, memory, research and itinerary-proposal evaluation. New routing/storage/bridge runners remain future artifacts until their implementing phase documents an actual command. External compatibility checks are opt-in and skipped checks remain unverified, not passed.
