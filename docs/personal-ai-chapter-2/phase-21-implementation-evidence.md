# Phase 21 implementation evidence — deterministic task-aware routing

**Date:** 2026-10-08 (America/Los_Angeles).

**Tested revision:** working tree based on `a79ba90` (`Implement Phase 21 deterministic routing foundation`). Runtime/config/test SHA-256: `8545c6789cfe0bfd858e022330fd00f9b44257c90ead2463566ba01a1567fc5f`.

The digest covers sorted unique Git tracked/non-ignored file paths under `backend/src`, `backend/tests`, `frontend/src`, `frontend/tests`, plus `backend/pyproject.toml`, `backend/uv.lock`, `.github/workflows/quality.yml` and `Makefile`. For each file it hashes its UTF-8 relative path, a NUL byte, then the binary SHA-256 of its contents. Markdown documentation is excluded.

## Delivered local boundary

| Package | Delivered behavior |
| --- | --- |
| P21.0 task/strategy/plan contracts | `routing/phase21.py` defines the known task taxonomy, typed requirements and quality policy, freshness-bounded runtime/quality/signal facts, safe request metadata, strategy input/result identities, endpoint-specific preparation, quota reservation references, explicit provisional/ready plans, and bounded observation/event records. `RoutingStrategy` is replaceable; the deterministic baseline ranks by configured priority and opted-in fresh evidence with a stable profile-ID/version tie break. |
| P21.1 admission/finalization | `RoutingDecisionService` applies Phase 18 profile admission and current runtime, quality-floor, authorization/credential, health/cooldown, and exhaustion filters before strategy input. Rejected profiles and priorities cannot be selected by a strategy. Finalization reloads canonical facts, checks preparation/revalidation order and fit, count confidence/schema where required, fresh dispatch facts, source authorization, current profile, and only quota buckets for the explicit physical operation. A ready plan requires a Phase 19 attempt proof bound to owner/scope, request/run, decision, endpoint/version, send number, operation and exact bucket rows. The service has no provider client and returns a ready plan only after its lifecycle event is durable. |
| P21.2 observation/replay | `persistence/postgres_routing_observations.py` and migrations `020_routing_decisions.sql` plus `021_routing_lifecycle_integrity.sql` store scoped immutable decision facts and append-only lifecycle events. Event publication checks the canonical trail under a row lock, enforces transitions and event-ID idempotency, and atomically links parent reselections and consumes root-scoped reselection/auxiliary-call budgets. Reselection preserves or tightens requirements, inherits all exclusions and the immutable root deadline, and proves source-set narrowing using bounded per-source hashes. Replay compares the recomputed strategy outcome with the recorded result. Records retain request/run/time/invocation/attempt/evaluation lookup, owner deletion fencing, and 90-day-bounded replay. Explicit overflow records are incomplete/no-route and are not silently truncated. Owner export inventory includes these canonical rows; scheduled maintenance purges expired observations. |
| Tests and packaging | `tests/test_routing_phase21.py` covers chat, research synthesis, and structured proposal task profiles through the shared service, admission-before-strategy, freshness and quality filters, replay mismatch, overflow, fit/revocation/reservation checks, requirement and source narrowing, inherited deadlines/exclusions, root auxiliary budgets and event idempotency. `tests/persistence/test_routing_decisions.py` adds opt-in real-Postgres scope, owner-fence, expiration/purge and concurrency cases for event publication, reselection and auxiliary-call budgets. The Phase 19 persistence suite checks routing proof against canonical attempt and bucket rows. These are included in the existing Postgres CI step. The built wheel contains both routing migrations 020 and 021. |

The phase plan requires Phase 15's authoritative membership and end-to-end revocation acceptance before connecting request workflows to automatic endpoint selection. That prerequisite remains open. The implementation therefore delivers the reusable routing and persistence core without wiring chat, research, proposals, or other actual workflows to it. Current app workflows remain Gemini-only; actual producing-endpoint attribution, shared builder integration, and Phase 19 invocation/reservation integration are not claimed. This follows the plan's stated work ordering and is a material remaining Phase 21 acceptance gate.

The repository-root `README.md` was reviewed. No README edit was needed because this local internal foundation does not change user-visible runtime capability, setup, supported providers, or deployment status.

## Verification

Environment: local macOS, existing backend Python 3.11.15 virtual environment and pinned dependencies. No provider or cloud calls were made.

| Command/check | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q tests/test_routing_phase21.py tests/persistence/test_routing_decisions.py tests/persistence/test_provider_usage_accounting.py` (run from `backend/`) | **Passed: 35 tests; skipped 19 opt-in Postgres tests** without `PERSISTENCE_TEST_POSTGRES_DSN`. |
| `.venv/bin/python -m pytest -q` (run from `backend/`) | **Passed: 1,006 tests, 52 skipped.** One existing Starlette/httpx deprecation warning. |
| `.venv/bin/ruff check .` (run from `backend/`) | **Passed.** |
| `UV_CACHE_DIR=/tmp/personal-ai-phase21-review-uv-cache uv build --no-build-isolation` (run from `backend/`) | **Passed:** source distribution and wheel built. Wheel contents include all Phase 21 Python modules and migrations `020_routing_decisions.sql` and `021_routing_lifecycle_integrity.sql`. |
| `git diff --check` | **Passed.** |
| Documentation links/content review | **Passed:** Phase 21 delivery and acceptance status were checked against code, plan, tests, and the Phase 15 integration gate. |
| Frontend tests/lint/typecheck/build | **Not run:** this review changes no frontend files or UI behavior. |

The offline tests use synthetic profiles and fake Postgres behavior. They establish local contracts only.

## Open acceptance and verification gates

- Phase 15 authoritative membership and end-to-end revocation through derived context remain incomplete. Automatic workflow selection and actual turn attribution remain gated; app workflows are Gemini-only.
- Migrations 020–021 were packaged but not applied. No real Postgres/DynamoDB engine or migration race/integration test was run locally. Docker and the configured persistence integration DSNs were not exercised.
- Five opt-in Phase 21 real-Postgres cases and the Phase 19 reservation-proof integration case are part of the CI persistence command; they were skipped locally without `PERSISTENCE_TEST_POSTGRES_DSN`, and no CI run is claimed here.
- No live provider, account/tier, privacy/data-use, quota/billing, cloud IAM, or deployed behavior was checked. Strict-free attestations, reservation controls, and the current fake runtime facts do not establish live eligibility.
- Linked reselection and lifecycle logic are tested offline. Crash reconciliation across canonical P decisions, Phase 19 reservations/attempts, and future D turn attribution remains unverified and depends on later workflow integration.
- No dedicated backend type-check target is defined in the repository's Makefile; Ruff, tests, and package build are the applicable local backend checks.

Phase 21's **local deterministic routing foundation is delivered**. Full phase acceptance remains open at the explicit Phase 15 prerequisite and external persistence/provider/workflow gates. See the [guide](phase-21-implementation-guide.md) and [current state](../current-state.md).
