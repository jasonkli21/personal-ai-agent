# Phase 11 implementation plan — Provider usage accounting and quota ledger

Reconciled on 2026-10-05 against `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`. This is **next-scope** numbering, distinct from existing repository Phases 1–9. Read the [source roadmap](../../05-phased-implementation-plan.md), [comprehensive Phase 0 review](../../09-phase-0-reconciliation.md) and [shared execution contract](../execution-contract.md) first. This plan preserves product scope and defines future implementation; it does not claim delivery.

## Scope boundary

**Goal:** Measure capacity before optimizing it.

### Normative commitments from the integrated roadmap

- Record provider/model/task per invocation.
- Capture token usage where available.
- Record latency/success/429/5xx/retries.
- Add health/cooldown.
- Add quota/reset state with confidence/source.
- Expose compact developer summaries.

### Phase acceptance criteria

- Every normalized invocation is attributable.
- Unknown quota state remains unknown.

### Explicitly out of scope

- scarcity-aware route selection
- billing aggregation beyond project needs
- ChatGPT-plan opaque usage handling
- unbounded telemetry retention

## Current state and reuse

HTTP estimated reservations, iterative run ledgers and shared lookup throttles are partial reusable patterns. Full per-operation accounting/quota ledger is missing.

Verified existing backend seams (paths exist at the reviewed revision):

- `backend/src/personal_ai/auth/safeguards.py`
- `backend/src/personal_ai/auth/owner_data.py`
- `backend/src/personal_ai/agents/research/iterative_contracts.py`
- `backend/src/personal_ai/agents/research/iterative_repositories.py`
- `backend/src/personal_ai/agents/research/iterative_service.py`
- `backend/src/personal_ai/llm/client.py`
- `backend/src/personal_ai/search/contracts.py`
- `backend/src/personal_ai/domains/providers.py`

Frontend integration, where needed, extends `frontend/src/lib/api.ts`, `frontend/src/lib/conversation-proxy.ts`, `frontend/src/lib/sse.ts`, `frontend/src/features/chat/chat-state.ts` and adjacent feature/UI components. Infrastructure extends `infrastructure/gcp/deploy.sh`, `firestore.indexes.json`, `Makefile` and `.github/workflows/quality.yml` only when required. Named target types in this plan are **future contracts**; choose their exact file/class placement beside these seams during implementation. Do not create fictitious files or parallel services merely to match a diagram.

## Prerequisites and work ordering

Required phases: 10. Each must deliver the contracts this plan consumes; a similarly named existing phase is not a substitute. Recommended numerical order is recorded in the roadmap. Within this plan, work packages run in order; each consumes prior packages' delivered contracts, then closes verification below.

## Phase-specific invariants

- Accounting failures should not silently change inference semantics; define which failures are advisory versus admission-blocking.
- Store safe metadata only—no prompts/responses/secrets by default.
- The ledger must support exact/derived/configured/unknown confidence states.

## Work packages

### P11.0 — Invocation lifecycle and scope

**Depends on:** required phases above.

Add one bounded invocation/reservation identity per external operation: generation, counting, summaries, extraction, embedding, worker model work, search and lookup. Carry owner/app/workspace/task plus opaque provider account/project/tier scope. Reuse durable transaction/fence patterns. Reserve before dispatch; settle confirmed usage or conservatively retain unknown-outcome reservation. Correlation does not replace idempotency, and uncertainty never authorizes implicit retries.

**Acceptance:** All external operation families reserve once before dispatch and settle known/unknown outcomes safely.

### P11.1 — Quota windows and health

**Depends on:** P11.0.

Represent unit/window/reset/source/confidence separately for each quota bucket; do not mix requests/day with tokens/minute or Cloudflare neurons. Account-level quota is shared across users/apps; track attributable local usage separately and conservative unobserved external use. Record latency, success, 429/5xx/retries, cooldown and exact/derived/configured/unknown observations. Basic search admission/zero-overflow checks belong here; Brave requires verified prepaid/no-auto-reload/no-paid-balance configuration and source rights, with postpaid overflow excluded. Scarcity scoring waits for Phase 15.

**Acceptance:** Shared-account windows and header units/reset confidence remain distinct under concurrent owner usage.

### P11.2 — Bounded persistence and developer summary

**Depends on:** P11.1.

Store compact safe metadata, bounded rollups and retention/cleanup through repository protocols/fakes. Extend account inventory/export/deletion rules, documenting legally/operationally retained tombstones separately. Replace reliance on unconditionally enabled paid Firestore TTL when strict-free is active as part of implementation. Developer summaries never expose prompts, secrets or fabricated remaining quota. Account deletion/lifecycle closure remains an existing Phase 9 release obligation.

**Acceptance:** Safe summaries, bounded retention and account inventory work without paid TTL reliance in strict-free mode.

## Requirement coverage

The commitments above remain normative. This mapping assigns every commitment to the concrete packages; verification covers all packages and acceptance criteria.

| Requirement | Work packages |
| --- | --- |
| R11.1: Record provider/model/task per invocation. | P11.0 |
| R11.2: Capture token usage where available. | P11.0 |
| R11.3: Record latency/success/429/5xx/retries. | P11.1 |
| R11.4: Add health/cooldown. | P11.1 |
| R11.5: Add quota/reset state with confidence/source. | P11.1 |
| R11.6: Expose compact developer summaries. | P11.2 |

## Targeted verification and closeout

Test concurrent reservations across owners/apps sharing an account, window resets, header-unit parsing, unknown settlements, cancelled/timeout calls, counts/search/embeddings included, durable cooldown and bounded cleanup.

Run `make backend-test` and `make backend-lint` for backend changes. Run `make frontend-test`, `make frontend-lint` and `make frontend-typecheck` when frontend/proxy/UI contracts change. Activate the backend venv and use the README's pinned Node/pnpm/uv setup; bare shell `python` is not assumed to exist. Run builds only for dependency/build changes, and `bash -n infrastructure/gcp/deploy.sh` for deployment script edits. Finish with `git diff --check`.

New routing/storage/bridge evaluation runners are **future artifacts**: add an actual documented command during the implementing phase before claiming it ran. Use deterministic fakes and synthetic fixtures; missing credentials cannot block or weaken offline tests.

**External checks:** Actual headers, model billing/free limits and shared account consumption are opt-in; application estimates do not prove provider quota or GCP spend.

Record actual files/interfaces, tested revision/configuration, command results, disabled gates and unresolved external checks in an implementation guide/release evidence. Follow the shared execution contract for failure, isolation, retention and scope preservation. Completion requires every normative commitment and package locally verified; external gates may remain pending only with the affected live capability unavailable. Do not describe a skipped check as passed.
