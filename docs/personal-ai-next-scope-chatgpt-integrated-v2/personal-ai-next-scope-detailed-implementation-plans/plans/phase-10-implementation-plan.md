# Phase 10 implementation plan — Provider/model registry and strict-free eligibility

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Describe endpoint capability/privacy/free eligibility independently of routing.

### Normative commitments from the integrated roadmap

- Define model profile schema.
- Represent enabled/strict-free flags.
- Represent capabilities and context/output limits.
- Represent provider data-policy metadata.
- Represent quota/reset metadata.
- Add initial profiles for configured Gemini free-tier, Groq Free-plan, and Cloudflare Workers Free models.
- Add strict-free admission guard.

### Phase acceptance criteria

- Paid/ineligible endpoints cannot enter strict-free candidate sets.
- Unknown data policy can conservatively exclude sensitive use.
- Current quota numbers are not application constants.

### Explicitly out of scope

- routing scores
- provider benchmarking
- automatic quota scarcity policy
- paid fallback

## Current state and reuse

AI_MODEL and fixed Gemini budgets are configuration; no provider/model registry or strict-free eligibility guard currently exists.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/llm/client.py`
- `backend/src/personal_ai/api/dependencies.py`
- `backend/src/personal_ai/settings.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 7, 9. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Volatile pricing/quota/model availability is not hard-coded into business logic.
- Eligibility is model/account-specific, not provider-wide.
- Registry describes facts; the router in Phase 13 owns selection policy.

## Work packages

### P10.0 — Versioned capability profiles

**Depends on:** required phases above.

Add neutral endpoint profiles for enabled state, provider/model/serializer/counter, supported tasks/stream/structured/tools/vision as implemented, context/output limits, embedding compatibility, credential runtime/selection mode, account-tier identity, privacy/data-use, quota units/windows/reset provenance and fact freshness. Quotas/model lists remain configuration/operational observations, not hard-coded business constants.

**Acceptance:** Profiles encode versions, capabilities, count/embedding compatibility and account-scoped facts without secrets.

### P10.1 — Strict-free admission

**Depends on:** P10.0.

Filter by model AND account/tier and by required sensitivity/capability before dispatch. Verified zero-cost eligible Gemini/Groq/Workers Free paths only; unknown eligibility or possible automatic paid overflow denies. Unknown quota remains unknown but cannot justify a billable path. No credentials in profile IDs. Embeddings/count/search auxiliaries receive independent eligibility admission.

**Acceptance:** Paid/unknown-eligibility and sensitivity-ineligible paths cannot enter candidates or dispatch.

### P10.2 — Profile lifecycle and candidate API

**Depends on:** P10.1.

Seed only configured verified profiles, explicitly marking unavailable or unverified ones. Removing/updating profiles invalidates stale candidates; freeze registry version per invocation and recheck eligibility at dispatch. Registry returns candidate facts, not scores. No ChatGPT candidate appears in automatic sets; its explicit-only metadata is extended in 17.2.

**Acceptance:** Profile removal invalidates candidates, and registry lookup does not introduce routing scores.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R10.1: Define model profile schema. | P10.0 |
| R10.2: Represent enabled/strict-free flags. | P10.0 |
| R10.3: Represent capabilities and context/output limits. | P10.0 |
| R10.4: Represent provider data-policy metadata. | P10.0 |
| R10.5: Represent quota/reset metadata. | P10.0 |
| R10.6: Add initial profiles for configured Gemini free-tier, Groq Free-plan, and Cloudflare Workers Free models. | P10.2 |
| R10.7: Add strict-free admission guard. | P10.1 |

## Targeted verification and closeout

Test model/account mismatch, paid Cloudflare/Gemini paths, expired/unknown privacy facts, unsupported capabilities, profile removal and deterministic candidate exclusion; no paid fallback.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Account dashboards and current provider tier/data-use rules require recorded verification before enablement.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
