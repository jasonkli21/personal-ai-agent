# Phase 23 implementation evidence — Quota-aware routing

Date: 2026-10-09
Tested revision: `3459a2e-working-tree-ae2489486cfc`
Status: Internal routing strategy, P19 snapshot integration, linked-reselection coverage, and deterministic synthetic evaluation implemented locally. Workflow routing and external acceptance remain gated.

## Delivered boundary

- Extended the existing `RoutingDecisionService`, `RoutingStrategy`, endpoint registry, and Phase 19 accounting seam. No parallel quota ledger or dispatch path was added.
- Added an operation-specific, locked Phase 19 snapshot of applicable shared quota buckets and endpoint health. The route transaction reads the current endpoint-profile snapshot and live bucket windows together. Shared bucket IDs remain canonical across endpoint or credential identities.
- Added `QuotaAwareDeterministicStrategy` with qualified remaining-send scarcity, known reset relief, explicit unknown-capacity uncertainty penalty, degraded-health penalty, and the existing optional reliability signal. Existing `DeterministicScoringStrategy` identity and behavior remain available for historical replay and deterministic rollback.
- Added schema-4 bounded decision facts for operation, quota state, health/cooldown, candidate eligibility, strategy ranking, and reason. Unknown remaining capacity and reset horizon remain null. At most 128 unique bucket facts are accepted; the existing 64 KiB decision limit is also enforced, and an oversized record becomes an explicit persisted no-route outcome rather than losing all routing state or truncating facts. Shared-bucket conflicts fail closed.
- Reused Phase 19 atomic all-bucket reservation, attempt identity, single-use dispatch claim, no-send denial behavior, and Phase 21 linked reselection with inherited exclusions and unchanged admission checks.
- Added four paired synthetic scenarios. The current fixture report passes every configured gate: quality delta `-0.016`, no availability increase, `+6 ms` mean latency per demand, one protected send equivalent preserved, zero uncertain dispatches, no quality-floor or hard-filter violations, and conserved capacity. Exhausting strict-free capacity returns unavailable despite an explicit BYOK fixture endpoint.
- Added `make quota-scarcity-eval`. No database migration or root README change was required: live quota ownership remains in the already-established Phase 19 ledger, and no user-visible provider-selection behavior changed.

## Verification performed

| Check | Result |
| --- | --- |
| `PATH=backend/.venv/bin:$PATH make backend-test` | **Passed:** 1,066 passed, 72 skipped, one existing Starlette/httpx deprecation warning. The opt-in Postgres integration cases, including P23's persisted snapshot/reselection case, were skipped. |
| `PATH=backend/.venv/bin:$PATH make backend-lint` / `.venv/bin/ruff check .` | **Passed:** all Ruff checks passed after the final implementation change. |
| `PATH=backend/.venv/bin:$PATH make backend-build` | **Passed:** source distribution and wheel built; the P23 JSON fixture is present in both artifacts. |
| `PATH=backend/.venv/bin:$PATH make quota-scarcity-eval` | **Passed:** all seven gates passed; quality delta `-0.016`, unavailable delta `0`, latency increase `6 ms/demand`, one protected send equivalent saved, zero uncertain dispatches. |
| `PATH=/Users/jasonkli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:/Users/jasonkli/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback:$PATH make frontend-test frontend-lint frontend-typecheck frontend-build` | **Passed:** 98 tests; lint, both TypeScript checks, and production build passed. Build reports the existing missing Next.js ESLint plugin warning; Vite also reports its CJS API deprecation. |
| Backend type check | No backend mypy/pyright/ty target is configured in the Makefile or backend project configuration. |
| Updated Markdown local links | **Passed:** all local path targets in the nine updated documents exist. |
| `git diff --check` | **Passed** after the implementation and documentation edits. |

The host shell does not expose `node` on its default `PATH`; the initial frontend command stopped before starting Vitest. Rerunning with the desktop's bundled Node.js and pnpm paths completed all frontend checks. `PERSISTENCE_TEST_POSTGRES_DSN` is unset, so no real PostgreSQL test database was used.

## Architecture audit

- P19 remains canonical for mutable quota windows, reservations, health, and physical outcomes; the P21 decision stores only the bounded facts used for replay.
- Authorization, static eligibility, privacy/capability/cost mode, quality floors, and known exhaustion precede strategy input. P19 rechecks and atomically reserves all buckets before a physical send.
- The scorer receives stable bucket identities and compatible per-operation send equivalents, not provider/app branches, secrets, account objects, or raw request content. Unknown values remain explicit.
- Old P21 strategy identity remains replayable. Phase 24 can consume the typed operation, linked decisions, and P19 attempt contract without adding cascade state to generic routing.
- The target PostgreSQL migration/concurrency behavior and the Phase 15 workflow boundary are separate from local synthetic evidence.

## Remaining verification and review attention

- No configured isolated PostgreSQL DSN or Docker-backed test database was used. The new P23 Postgres integration test is skipped locally when the DSN is unset; real locking, concurrent capacity loss, JSONB replay, and migration behavior are unverified.
- No live Gemini, Groq, Cloudflare, BYOK, account/tier/privacy, cloud, deployment, or production-security checks were performed. Application workflows remain Gemini-only pending Phase 15 membership and end-to-end revocation acceptance.
- Independent review should pay particular attention to Postgres lock ordering under concurrent decisions/reservations, operation-to-bucket mapping for shared windows, behavior at reset/freshness boundaries, the overflow outcome and 64 KiB decision ceiling, and calibration of synthetic promotion thresholds against a future trusted evaluation source.

## Scope and README closeout

No root README edit was required: the phase adds an internal router strategy and evaluation command, while user-visible request workflows and provider support remain unchanged and Gemini-only. No plan deviation was required. A new database migration was unnecessary because the canonical P21 decision already stores bounded versioned JSON facts; P19 retains live ledger ownership. Automatic workflow integration remains withheld under the existing Phase 15 authorization/revocation prerequisite.
