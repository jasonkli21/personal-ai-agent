# Phase 9 implementation plan — Concrete provider adapters: Gemini, Groq, Cloudflare

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

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

## Current state and reuse

Gemini SDK adapters are implemented and need neutral migration. Groq and Cloudflare adapters are genuinely missing. LiteLLM is optional, not a required new dependency.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/llm/gemini.py`
- `backend/src/personal_ai/llm/context.py`
- `backend/src/personal_ai/llm/memory.py`
- `backend/src/personal_ai/llm/errors.py`
- `backend/src/personal_ai/llm/fake.py`
- `backend/src/personal_ai/api/dependencies.py`
- `backend/src/personal_ai/settings.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 8. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Capture usage/rate-limit metadata when provided, but do not build selection policy yet.
- Cloudflare models requiring Workers Paid are ineligible in strict-free configuration.
- Real-provider checks are opt-in and must not be represented as passed when credentials/network are unavailable.

## Work packages

### P9.0 — Gemini compatibility adapter

**Depends on:** required phases above.

Reuse existing Gemini generation/count/summary/extraction/embedding implementations behind Phase 8 contracts. Retain zero implicit retry and cancellation cleanup; normalize 429, auth/config, timeout, unavailable, malformed and incomplete results with safe metadata. Keep current vector space and task-schema validation unchanged.

**Acceptance:** Gemini regressions and neutral error/terminal contracts pass without changing embeddings.

### P9.1 — Groq and Cloudflare adapters

**Depends on:** P9.0.

Add generation/structured-output operations actually needed by tasks, with supported capability declarations. Normalize each provider serializer/stream terminal behavior, limits, usage and safe rate headers below llm. Add deterministic adapters/fake transports. Native SDK/HTTP adapters or LiteLLM are implementation choices justified by contract fit, not framework adoption; no router, quality scores, quota selection or cascades.

**Acceptance:** Groq and Cloudflare fake transports satisfy supported operations and reject unsupported fields.

### P9.2 — Disabled configuration and preflight

**Depends on:** P9.1.

All new live paths default off. Require model/account free-tier and privacy compatibility checks before opt-in dispatch, even before Phase 10 centralizes registry policy. Cloudflare paid-only models are excluded. Record deployed TTL incompatibility and other paid GCP features before any strict-$0 enablement; do not claim existing deployment is compliant. Missing credentials/provider environment skips external checks only.

**Acceptance:** New live providers remain disabled until independent eligible-account/privacy/preflight checks are recorded.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R9.1: Migrate Gemini generation and structured memory extraction behind the neutral backend while preserving Gemini embeddings. | P9.0 |
| R9.2: Add Groq backend support for the minimal generation operations needed by actual tasks, with fake/contract tests and rate-limit/usage-header capture. | P9.1 |
| R9.3: Add Cloudflare Workers AI backend support for the minimal generation operations needed by actual tasks, with fake/contract tests. | P9.1 |
| R9.4: Verify strict-free configuration only against currently eligible account/tier models. | P9.2 |
| R9.5: Use LiteLLM internally where it reduces duplication or native adapters where cleaner; keep provider-specific details below the boundary. | P9.1 |
| R9.6: Do not add benchmarking, quota-aware selection, cascades, or generalized provider discovery in this phase. | P9.2 |

## Targeted verification and closeout

Contract fixtures for all three adapters cover unsupported request fields, structured failures, 429/5xx, stream interruption, cancellation cleanup, unknown usage and provider-type confinement; no test uses a paid endpoint.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

Affected existing evaluation targets: `make context-eval`, `make memory-eval`, `make research-eval`, `make itinerary-proposal-eval`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Run separate synthetic Gemini/Groq/Cloudflare compatibility checks only against explicitly eligible configured accounts. Model access, data use and strict-free account settings remain unverified until run.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
